from __future__ import annotations

import logging
import uuid
from datetime import datetime

from backend.models.conversation import ConversationThread, ChatMessage, BuyerSeriousness
from backend.services.gemini import GeminiService, GEMINI_MODEL
from backend.storage.store import store

logger = logging.getLogger(__name__)

REPLY_PROMPT = """You are a friendly but professional marketplace seller assistant.

Conversation history:
{history}

Current item listing price: ${price}
Buyer's current offer: ${offer}

Suggest a short, natural reply (1-3 sentences) that:
- Is warm but firm on price if the offer is too low
- Accepts if the offer is reasonable (within 15% of listing price)
- Provides relevant item details if asked
- Never reveals the minimum acceptable price

Return ONLY the suggested reply text, no quotes or labels."""


class UnifiedInboxSystem:
    def __init__(self, gemini: GeminiService | None = None) -> None:
        self.gemini = gemini or GeminiService()

    async def add_message(
        self,
        thread_id: str,
        sender: str,
        text: str,
        is_offer: bool = False,
        offer_amount: float | None = None,
    ) -> ConversationThread:
        thread = store.get_thread(thread_id)
        if not thread:
            thread = ConversationThread(thread_id=thread_id)

        msg = ChatMessage(
            sender=sender,
            text=text,
            timestamp=datetime.utcnow(),
            is_offer=is_offer,
            offer_amount=offer_amount,
        )
        thread.messages.append(msg)

        if is_offer and offer_amount is not None:
            thread.current_offer = offer_amount

        thread.seriousness_score = self._score_seriousness(thread)
        await store.add_thread(thread)
        return thread

    async def suggest_reply(self, thread: ConversationThread) -> str:
        if not thread.messages:
            return "Hi! Thanks for your interest. Let me know if you have any questions!"

        try:
            history = "\n".join(
                f"{m.sender}: {m.text}" for m in thread.messages[-10:]
            )

            listing = store.get_listing(thread.item_id)
            price = listing.price_strategy if listing else 0.0
            offer = thread.current_offer or 0.0

            prompt = REPLY_PROMPT.format(
                history=history,
                price=f"{price:.2f}",
                offer=f"{offer:.2f}" if offer else "none",
            )

            from backend.config import settings
            if settings.demo_mode and not settings.gemini_api_key:
                return self._mock_reply(thread)

            client = self.gemini._get_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[prompt],
            )
            reply = response.text.strip()
            thread.suggested_reply = reply
            await store.add_thread(thread)
            return reply

        except Exception:
            logger.exception("Reply suggestion failed for thread %s", thread.thread_id)
            return self._mock_reply(thread)

    async def rank_buyers(self, item_id: str) -> list[ConversationThread]:
        threads = store.get_threads_for_item(item_id)
        for thread in threads:
            thread.seriousness_score = self._score_seriousness(thread)
            await store.add_thread(thread)

        order = {BuyerSeriousness.HIGH: 0, BuyerSeriousness.MEDIUM: 1, BuyerSeriousness.LOW: 2, BuyerSeriousness.SPAM: 3}
        return sorted(threads, key=lambda t: order.get(t.seriousness_score, 99))

    def _score_seriousness(self, thread: ConversationThread) -> BuyerSeriousness:
        if not thread.messages:
            return BuyerSeriousness.LOW

        buyer_msgs = [m for m in thread.messages if m.sender == "buyer"]
        if not buyer_msgs:
            return BuyerSeriousness.LOW

        has_offer = any(m.is_offer for m in buyer_msgs)
        msg_count = len(buyer_msgs)
        total_text = " ".join(m.text.lower() for m in buyer_msgs)

        spam_signals = ["still available", "is this available", "dm me", "whatsapp"]
        if any(s in total_text for s in spam_signals) and msg_count <= 1:
            return BuyerSeriousness.SPAM

        if has_offer and msg_count >= 2:
            return BuyerSeriousness.HIGH

        if has_offer or msg_count >= 3:
            return BuyerSeriousness.MEDIUM

        return BuyerSeriousness.LOW

    @staticmethod
    def _mock_reply(thread: ConversationThread) -> str:
        if thread.current_offer:
            return f"Thanks for the offer of ${thread.current_offer:.2f}! Let me think about it and get back to you shortly."
        last = thread.messages[-1] if thread.messages else None
        if last and "condition" in last.text.lower():
            return "Great question! The item is in the condition described in the listing. Happy to send more photos if needed!"
        return "Thanks for reaching out! Let me know if you have any questions about the item."
