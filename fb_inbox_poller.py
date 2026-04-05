"""Facebook Marketplace inbox poller — Browser-Use agents that monitor
FB Messenger for new buyer messages and auto-reply via Gemini.

One agent per listed item. Each agent:
  1. Navigates to the FB Marketplace selling inbox
  2. Polls for new messages every ~3 seconds
  3. When a new message is detected, generates a reply via Gemini
  4. Types the reply directly into the FB Messenger input
  5. Emits events so the frontend Concierge page shows live activity

Designed for a 90-second window while the Concierge page is open.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback

from browser_use import Agent, BrowserProfile, BrowserSession

from config import settings
from contracts import AgentEvent
import backend.streaming as streaming

logger = logging.getLogger("swarmsell.fb_poller")

try:
    from backend.debug_trace import swarma_line
except ImportError:
    def swarma_line(component, event, **fields):
        logger.info("SWARMA | %s | %s | %s", component, event,
                     " | ".join(f"{k}={v}" for k, v in fields.items()))


POLL_INTERVAL_S = 3.0
MAX_CONCIERGE_DURATION_S = 90.0

# JS to extract the latest messages from FB Marketplace selling inbox.
# Runs on the /marketplace/you/selling page or inbox conversation page.
FB_INBOX_CHECK_JS = r"""
(() => {
    // Try to find unread message indicators or new message elements
    const results = { messages: [], has_new: false };

    // Strategy 1: Look for unread badges/dots in the selling inbox
    const badges = document.querySelectorAll('[aria-label*="unread"], [aria-label*="new message"], .x1n2onr6');
    if (badges.length > 0) {
        results.has_new = true;
    }

    // Strategy 2: Look for conversation rows with message previews
    const rows = document.querySelectorAll('[role="row"], [role="listitem"], [data-testid*="message"]');
    for (const row of rows) {
        const text = row.textContent?.trim().slice(0, 200) || '';
        if (text.length > 5) {
            results.messages.push(text);
        }
    }

    // Strategy 3: If we're inside a conversation, grab the last few messages
    const msgBubbles = document.querySelectorAll('[dir="auto"]');
    const chatMsgs = [];
    const seen = new Set();
    for (let i = Math.max(0, msgBubbles.length - 10); i < msgBubbles.length; i++) {
        const t = msgBubbles[i].textContent?.trim();
        if (t && t.length > 2 && t.length < 500 && !seen.has(t)) {
            seen.add(t);
            chatMsgs.push(t);
        }
    }
    if (chatMsgs.length > 0) {
        results.chat_messages = chatMsgs;
    }

    // Strategy 4: Find the message input box to confirm we're in a conversation
    const input = document.querySelector('[aria-label*="message"], [aria-label*="Message"], [contenteditable="true"][role="textbox"]');
    results.has_input = !!input;

    return JSON.stringify(results);
})()
"""

REPLY_SYSTEM_PROMPT = """You are a friendly marketplace seller responding to a buyer on Facebook Marketplace.
Keep replies short (1-2 sentences), natural, and helpful.
If they ask about price, be firm but friendly.
If they ask about condition, be honest and positive.
If they want to buy, express enthusiasm and suggest next steps.
If they lowball, politely counter with a fair price.
Never be rude. Never reveal minimum price. Be conversational like a real person texting.
Return ONLY the reply text, nothing else."""


def _make_llm():
    if settings.use_chat_browser_use or settings.browser_use_api_key:
        from browser_use import ChatBrowserUse
        return ChatBrowserUse()
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
        )
        llm.provider = "google"
        return llm
    except Exception:
        from browser_use import ChatBrowserUse
        return ChatBrowserUse()


GEMINI_TIMEOUT_S = 8.0  # Hard cap so we never block a poll cycle too long


async def _generate_reply(buyer_message: str, item_name: str, price: float) -> str:
    """Generate a seller reply via Gemini. Falls back to a canned response."""
    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = f"""{REPLY_SYSTEM_PROMPT}

Item: {item_name}
Listed price: ${price:.0f}
Buyer said: {buyer_message}

Your reply:"""

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=[prompt],
            ),
            timeout=GEMINI_TIMEOUT_S,
        )
        reply = response.text.strip().strip('"').strip("'")
        if reply:
            return reply
    except asyncio.TimeoutError:
        swarma_line("fb_poller", "gemini_reply_timeout", timeout_s=GEMINI_TIMEOUT_S)
    except Exception as exc:
        swarma_line("fb_poller", "gemini_reply_failed", error=str(exc))

    # Canned fallbacks — always return something
    if any(w in buyer_message.lower() for w in ["price", "lower", "deal", "discount"]):
        return f"Thanks for your interest! I'm asking ${price:.0f} which is already a great deal. Let me know if that works for you!"
    if any(w in buyer_message.lower() for w in ["available", "still"]):
        return "Yes it's still available! Are you interested?"
    if any(w in buyer_message.lower() for w in ["condition", "damage", "scratch"]):
        return "It's in great condition, just as shown in the photos. Happy to send more pics if you'd like!"
    return "Thanks for reaching out! Let me know if you have any questions."


class FBInboxPoller:
    """Manages one Browser-Use agent per item that polls FB Marketplace inbox."""

    def __init__(self, broadcast_fn=None):
        self._broadcast_fn = broadcast_fn
        self._tasks: dict[str, asyncio.Task] = {}
        self._sessions: dict[str, BrowserSession] = {}
        self._running = False
        self._start_time: float = 0
        self._known_messages: dict[str, set[str]] = {}
        self._global_replied: set[str] = set()
        self._job_id: str = ""

    def _emit(self, event: AgentEvent):
        if self._broadcast_fn and self._job_id:
            event_dict = {"type": event.type, "data": event.data}
            if event.agent_id:
                event_dict["data"]["agent_id"] = event.agent_id
                event_dict["data"]["agentId"] = event.agent_id
            asyncio.ensure_future(self._broadcast_fn(self._job_id, event_dict))

    async def start(self, job_id: str, items: list[dict]):
        """Launch one polling agent per item. Each gets its own browser.

        items: list of dicts with keys: item_id, name, price
        """
        if self._running:
            swarma_line("fb_poller", "already_running")
            return

        self._running = True
        self._start_time = time.time()
        self._job_id = job_id
        swarma_line("fb_poller", "start", job_id=job_id, items_n=len(items))

        self._emit(AgentEvent(
            type="concierge:started",
            agent_id="fb-poller-control",
            data={"job_id": job_id, "items": len(items)},
        ))

        for item in items:
            item_id = item["item_id"]
            agent_id = f"fb-concierge-{item_id[:8]}"
            self._known_messages[agent_id] = set()
            task = asyncio.create_task(
                self._poll_loop(job_id, agent_id, item)
            )
            self._tasks[agent_id] = task
            swarma_line("fb_poller", "agent_launched", agent_id=agent_id,
                        item=item.get("name", "?"))

    async def stop(self):
        """Cancel all polling agents and close browsers."""
        if not self._running:
            return
        self._running = False
        swarma_line("fb_poller", "stopping", agents_n=len(self._tasks))

        for agent_id, task in self._tasks.items():
            task.cancel()

        for agent_id, task in self._tasks.items():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=3)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        for agent_id, session in self._sessions.items():
            try:
                await session.close()
            except Exception:
                pass
            try:
                await streaming.stop_screencast(agent_id)
            except Exception:
                pass

        self._tasks.clear()
        self._sessions.clear()
        self._known_messages.clear()
        self._global_replied.clear()

        self._emit(AgentEvent(
            type="concierge:stopped",
            agent_id="fb-poller-control",
            data={},
        ))
        swarma_line("fb_poller", "stopped")

    def is_running(self) -> bool:
        return self._running

    def _time_remaining(self) -> float:
        return max(0, MAX_CONCIERGE_DURATION_S - (time.time() - self._start_time))

    async def _poll_loop(self, job_id: str, agent_id: str, item: dict):
        """Core polling loop for one item's FB inbox conversations."""
        item_id = item["item_id"]
        item_name = item.get("name", "Item")
        item_price = float(item.get("price", 0))

        self._emit(AgentEvent(
            type="agent:spawn",
            agent_id=agent_id,
            data={
                "platform": "facebook", "phase": "concierge",
                "item_id": item_id, "task": f"Monitoring FB inbox for {item_name}",
                "status": "running",
            },
        ))

        profile = BrowserProfile(
            storage_state=settings.storage_state_map.get("facebook"),
            minimum_wait_page_load_time=0.1,
            wait_between_actions=0.1,
            headless=False,
        )

        session: BrowserSession | None = None
        poll_count = 0

        try:
            session = BrowserSession(browser_profile=profile)
            await session.start()
            self._sessions[agent_id] = session

            page = await session.get_current_page()
            await streaming.start_screencast(agent_id, page, session)
            swarma_line("fb_poller", "screencast_started", agent_id=agent_id)

            # Navigate to FB Marketplace selling inbox
            inbox_url = "https://www.facebook.com/marketplace/you/selling"
            await session.navigate_to(inbox_url)
            await asyncio.sleep(3)

            swarma_line("fb_poller", "inbox_loaded", agent_id=agent_id)
            self._emit(AgentEvent(
                type="agent:status",
                agent_id=agent_id,
                data={"status": "polling", "detail": "Watching for buyer messages..."},
            ))

            while self._running and self._time_remaining() > 0:
                poll_count += 1
                try:
                    await self._poll_once(session, agent_id, item_name, item_price, job_id, item_id, poll_count)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    swarma_line("fb_poller", "poll_error", agent_id=agent_id,
                                poll=poll_count, error=str(exc))

                # Sleep only as long as we have time left (don't overshoot)
                sleep_s = min(POLL_INTERVAL_S, self._time_remaining())
                if sleep_s > 0:
                    await asyncio.sleep(sleep_s)

            swarma_line("fb_poller", "loop_ended", agent_id=agent_id,
                        reason="timeout" if self._time_remaining() <= 0 else "stopped",
                        polls=poll_count)

        except asyncio.CancelledError:
            swarma_line("fb_poller", "cancelled", agent_id=agent_id, polls=poll_count)
        except Exception as exc:
            swarma_line("fb_poller", "agent_crashed", agent_id=agent_id,
                        error=str(exc), traceback=traceback.format_exc()[-400:])
            self._emit(AgentEvent(
                type="agent:error",
                agent_id=agent_id,
                data={"error": str(exc)},
            ))
        finally:
            try:
                await streaming.stop_screencast(agent_id)
            except Exception:
                pass
            if session:
                try:
                    await session.close()
                except Exception:
                    pass
                self._sessions.pop(agent_id, None)

            self._emit(AgentEvent(
                type="agent:complete",
                agent_id=agent_id,
                data={"polls": poll_count, "phase": "concierge"},
            ))

    async def _poll_once(
        self, session: BrowserSession, agent_id: str,
        item_name: str, item_price: float, job_id: str, item_id: str,
        poll_count: int,
    ):
        """Single poll iteration: check inbox, detect new messages, reply if needed."""
        page = await session.get_current_page()
        if not page:
            return

        # Run inbox check JS
        try:
            raw = await page.evaluate(FB_INBOX_CHECK_JS)
        except Exception:
            # Page might have navigated, try to go back to inbox
            await session.navigate_to("https://www.facebook.com/marketplace/you/selling")
            await asyncio.sleep(2)
            return

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {}

        chat_msgs = data.get("chat_messages", [])
        has_input = data.get("has_input", False)
        has_new = data.get("has_new", False)

        if poll_count <= 2 or poll_count % 10 == 0:
            swarma_line("fb_poller", "poll_result", agent_id=agent_id,
                        poll=poll_count, chat_n=len(chat_msgs),
                        has_input=has_input, has_new=has_new)

        # If we're in a conversation and see messages we haven't processed
        known = self._known_messages.get(agent_id, set())

        if has_input and chat_msgs:
            last_msg = chat_msgs[-1]
            msg_key = last_msg[:100]

            if msg_key not in known:
                known.add(msg_key)

                # Cross-agent dedup: all agents share the same FB inbox page,
                # so if another agent already handled this message, skip it.
                if msg_key in self._global_replied:
                    swarma_line("fb_poller", "dedup_skip", agent_id=agent_id,
                                message=last_msg[:80])
                    return

                swarma_line("fb_poller", "new_message_detected", agent_id=agent_id,
                            message=last_msg[:120], item=item_name)

                self._emit(AgentEvent(
                    type="concierge:message_received",
                    agent_id=agent_id,
                    data={
                        "item_id": item_id,
                        "buyer_message": last_msg[:300],
                        "platform": "facebook",
                    },
                ))

                # Also push to backend thread store via the internal API
                await self._update_thread_store(
                    job_id, item_id, "buyer", last_msg
                )

                # Guard: don't start a reply if <5s remain — Gemini + typing
                # takes ~3-9s, and cancellation mid-type can leave partial text
                # in the FB input box.
                remaining = self._time_remaining()
                if remaining < 5.0:
                    swarma_line("fb_poller", "reply_skipped_timeout",
                                agent_id=agent_id, remaining_s=round(remaining, 1))
                    return

                # Mark globally BEFORE generating so parallel agents don't race
                self._global_replied.add(msg_key)

                # Generate and send reply
                self._emit(AgentEvent(
                    type="agent:status",
                    agent_id=agent_id,
                    data={"status": "replying", "detail": f"Generating reply to: {last_msg[:60]}..."},
                ))

                reply = await _generate_reply(last_msg, item_name, item_price)
                swarma_line("fb_poller", "reply_generated", agent_id=agent_id,
                            reply=reply[:120])

                # Type the reply into the FB message input
                typed = await self._type_reply(page, reply)

                if typed:
                    known.add(reply[:100])
                    self._global_replied.add(reply[:100])
                    swarma_line("fb_poller", "reply_sent", agent_id=agent_id)

                    self._emit(AgentEvent(
                        type="concierge:reply_sent",
                        agent_id=agent_id,
                        data={
                            "item_id": item_id,
                            "reply": reply,
                            "buyer_message": last_msg[:300],
                            "platform": "facebook",
                        },
                    ))

                    await self._update_thread_store(
                        job_id, item_id, "seller", reply
                    )
                else:
                    swarma_line("fb_poller", "reply_type_failed", agent_id=agent_id)

                self._emit(AgentEvent(
                    type="agent:status",
                    agent_id=agent_id,
                    data={"status": "polling", "detail": "Watching for buyer messages..."},
                ))

        elif has_new and not has_input:
            # We see unread indicators but aren't in a conversation yet.
            # Try clicking the first unread conversation.
            try:
                clicked = await page.evaluate("""
                (() => {
                    const links = document.querySelectorAll('a[href*="/marketplace/"], [role="row"], [role="listitem"]');
                    for (const link of links) {
                        const badge = link.querySelector('[aria-label*="unread"], .x1n2onr6');
                        if (badge) {
                            link.click();
                            return true;
                        }
                    }
                    // Just click the first conversation if any exist
                    const first = document.querySelector('a[href*="/marketplace/t/"]');
                    if (first) { first.click(); return true; }
                    return false;
                })()
                """)
                if clicked:
                    await asyncio.sleep(2)
                    swarma_line("fb_poller", "clicked_conversation", agent_id=agent_id)
            except Exception:
                pass

    async def _type_reply(self, page, reply: str) -> bool:
        """Type a reply into the FB Messenger input and send it."""
        try:
            # Find the message input
            typed = await page.evaluate(f"""
            (() => {{
                // Strategy 1: contenteditable textbox
                const box = document.querySelector('[contenteditable="true"][role="textbox"]');
                if (box) {{
                    box.focus();
                    box.textContent = '';
                    document.execCommand('insertText', false, {repr(reply)});
                    return 'found_textbox';
                }}
                // Strategy 2: aria-label message input
                const input = document.querySelector('[aria-label*="message" i], [aria-label*="Message" i]');
                if (input) {{
                    input.focus();
                    if (input.contentEditable === 'true') {{
                        document.execCommand('insertText', false, {repr(reply)});
                    }} else {{
                        const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeSet.call(input, {repr(reply)});
                        input.dispatchEvent(new Event('input', {{bubbles: true}}));
                    }}
                    return 'found_input';
                }}
                return 'no_input_found';
            }})()
            """)

            if typed == 'no_input_found':
                return False

            await asyncio.sleep(0.3)

            # Press Enter to send
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.5)
            return True

        except Exception as exc:
            swarma_line("fb_poller", "type_reply_error", error=str(exc))
            return False

    async def _update_thread_store(self, job_id: str, item_id: str, sender: str, text: str):
        """Push message to the backend's in-memory thread store so the
        ConciergePage's LiveConversation component picks it up on its next poll."""
        try:
            from backend.models.conversation import ChatMessage, ConversationThread
            from datetime import datetime

            # Import the server's thread store directly (same process)
            import backend.server as srv

            thread_id = f"fb-live-{item_id}"
            thread = srv._threads.get(thread_id)
            if not thread:
                thread = ConversationThread(
                    thread_id=thread_id,
                    item_id=item_id,
                    job_id=job_id,
                    platform="facebook",
                    buyer_handle="FB Buyer",
                )
                srv._threads[thread_id] = thread

            thread.messages.append(ChatMessage(
                sender=sender,
                text=text,
                timestamp=datetime.utcnow(),
            ))

            # Broadcast update to WS clients
            await srv.ws_manager.broadcast_event(job_id, {
                "type": "thread_updated",
                "data": thread.model_dump(mode="json"),
            })
        except Exception as exc:
            swarma_line("fb_poller", "thread_store_update_failed", error=str(exc))
