"""Orchestrator — semaphore pool over Browser-Use Cloud agents.
Manages agent lifecycle, concurrency, event emission, and retry.
Person 3's server.py imports this and calls start_pipeline().

Speed optimizations:
  - initial_actions: pre-navigate to target URL WITHOUT an LLM call
  - use_vision=False: skip screenshots in LLM context (saves 0.8s/step)
  - flash_mode=True: skip thinking/evaluation
  - max_actions_per_step=4: batch more actions per LLM round-trip
  - Task strings assume agent is ALREADY on the page (initial_actions handled nav)

Visual feed:
  - register_new_step_callback: fires after every step with screenshot + agent state
  - Screenshots pushed as agent:screenshot events for Person 3 to stream via WebSocket
"""
from __future__ import annotations

import asyncio
import logging
import platform
import time
import traceback

from browser_use import Agent, Browser, BrowserProfile
from browser_use.browser.session import BrowserSession

from config import settings
from contracts import AgentEvent, AgentState, Playbook, RouteDecision
from extraction import make_research_tools, get_extraction_js
from models.item_card import ItemCard
from models.listing_package import ListingPackage, ListingImage
from route_decision import route_decision
import backend.streaming as streaming

logger = logging.getLogger("swarmsell.orchestrator")

try:
    from backend.debug_trace import swarma_line
except ImportError:
    def swarma_line(component, event, **fields):
        logger.info("SWARMA | %s | %s | %s", component, event,
                     " | ".join(f"{k}={v}" for k, v in fields.items()))


# ---------------------------------------------------------------------------
# macOS: suppress Chrome window focus-stealing
# ---------------------------------------------------------------------------

_IS_MACOS = platform.system() == "Darwin"

# A PERSISTENT AppleScript that runs in a tight loop for the lifetime of the
# pipeline.  Whenever Chrome becomes the frontmost app it:
#   1. Hides Chrome via System Events  (instant, no window flash)
#   2. Re-activates the app the user was actually using
# Detects the user's current app on first run so it works regardless of IDE.
# SELF-TERMINATING: checks if parent Python process is still alive every loop.
# If the terminal is closed or the server is killed, this exits automatically.
_FOCUS_GUARD_SCRIPT_TEMPLATE = '''\
set parentPID to "{pid}"

-- Detect whatever app the user is actually using right now
tell application "System Events"
    set targetApp to name of first application process whose frontmost is true
end tell
if targetApp is "osascript" then set targetApp to "Finder"

repeat
    delay 0.1
    try
        -- Exit immediately if parent process is dead (terminal closed, server killed)
        set exitCode to (do shell script "kill -0 " & parentPID & " 2>/dev/null; echo $?")
        if exitCode is not "0" then exit repeat

        tell application "System Events"
            set currentFront to name of first application process whose frontmost is true

            if currentFront is not "Google Chrome" and currentFront is not "Chromium" and currentFront is not "osascript" then
                set targetApp to currentFront
            end if

            if currentFront is "Google Chrome" or currentFront is "Chromium" then
                tell process currentFront
                    set visible to false
                end tell
                tell application targetApp to activate
            end if
        end tell
    end try
end repeat
'''

_focus_guard_proc: asyncio.subprocess.Process | None = None


async def _start_focus_guard():
    """Launch the persistent focus-guard AppleScript."""
    global _focus_guard_proc
    if not _IS_MACOS:
        return
    if _focus_guard_proc is not None:
        return
    try:
        import os
        script = _FOCUS_GUARD_SCRIPT_TEMPLATE.format(pid=os.getpid())
        _focus_guard_proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        swarma_line("focus_guard", "started",
                     pid=_focus_guard_proc.pid, parent_pid=os.getpid())
    except Exception as exc:
        swarma_line("focus_guard", "start_failed", error=str(exc))
        _focus_guard_proc = None


async def _stop_focus_guard():
    """Kill the persistent focus-guard AppleScript."""
    global _focus_guard_proc
    if _focus_guard_proc is None:
        return
    try:
        _focus_guard_proc.terminate()
        await asyncio.wait_for(_focus_guard_proc.wait(), timeout=3)
        swarma_line("focus_guard", "stopped")
    except Exception:
        try:
            _focus_guard_proc.kill()
        except Exception:
            pass
    _focus_guard_proc = None


def _kill_focus_guard_sync():
    """Synchronous kill — used by atexit and signal handlers.

    This is the nuclear option: if the async cleanup didn't run
    (server killed, crash, Ctrl+C), this ensures the osascript
    process is dead. Also kills any orphaned osascript processes
    matching our script pattern.
    """
    global _focus_guard_proc
    import os
    import signal as _sig
    import subprocess

    if _focus_guard_proc is not None:
        try:
            os.kill(_focus_guard_proc.pid, _sig.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        _focus_guard_proc = None

    if _IS_MACOS:
        try:
            subprocess.run(
                ["pkill", "-f", "osascript.*set parentPID"],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass


import atexit
import signal as _sig2

atexit.register(_kill_focus_guard_sync)

# Also kill on SIGHUP (terminal close) and SIGTERM (kill command)
def _signal_cleanup(signum, frame):
    _kill_focus_guard_sync()
    raise SystemExit(128 + signum)

for _s in (getattr(_sig2, "SIGHUP", None), _sig2.SIGTERM):
    if _s is not None:
        try:
            _sig2.signal(_s, _signal_cleanup)
        except (OSError, ValueError):
            pass  # can't set handler in non-main thread

# ---------------------------------------------------------------------------
# Playbook registry — Person 2 registers these at import time
# ---------------------------------------------------------------------------

PLAYBOOKS: dict[str, Playbook] = {}


def register_playbook(playbook: Playbook) -> None:
    PLAYBOOKS[playbook.platform] = playbook


def get_all_playbooks() -> list[Playbook]:
    return list(PLAYBOOKS.values())


def get_playbook(platform: str) -> Playbook:
    return PLAYBOOKS[platform]


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _make_llm():
    # Browser-Use 0.12+ checks llm.provider — ChatGoogleGenerativeAI lacks it.
    # Use ChatBrowserUse when BROWSER_USE_API_KEY is set (preferred for agents).
    if settings.use_chat_browser_use or settings.browser_use_api_key:
        from browser_use import ChatBrowserUse
        swarma_line("orchestrator", "llm_init", backend="ChatBrowserUse")
        return ChatBrowserUse()
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
        )
        llm.provider = "google"
        swarma_line("orchestrator", "llm_init", backend="gemini-2.0-flash")
        return llm
    except Exception as exc:
        swarma_line("orchestrator", "llm_init_fallback", error=str(exc), fallback="ChatBrowserUse")
        logger.warning("Gemini LLM init failed, falling back to ChatBrowserUse: %s", exc)
        from browser_use import ChatBrowserUse
        return ChatBrowserUse()


# ---------------------------------------------------------------------------
# Listing detail generation — fills the ListingPackage before agents run
# ---------------------------------------------------------------------------

def _collect_listing_images(item: ItemCard) -> list[ListingImage]:
    """Get this item's listing images from the per-item directory on disk.

    server.py saves each item's hero frames to data/listing-images/{item_id}/
    during the pipeline. Each item gets ONLY its own frames — no shared fallbacks.
    """
    from pathlib import Path

    images: list[ListingImage] = []

    if item.listing_image_paths:
        for i, p in enumerate(item.listing_image_paths[:6]):
            if Path(p).exists():
                role = "hero" if i == 0 else "secondary"
                images.append(ListingImage(path=p, role=role))

    if not images:
        item_dir = Path(settings.listing_images_dir) / item.item_id
        if item_dir.exists():
            jpgs = sorted(item_dir.glob("*.jpg"))
            for i, p in enumerate(jpgs[:6]):
                role = "hero" if i == 0 else "secondary"
                images.append(ListingImage(path=str(p.resolve()), role=role))

    if not images:
        swarma_line("pipeline", "no_images_for_item",
                    item=item.name_guess, item_id=item.item_id)

    return images


def _build_listing_package(
    item: ItemCard,
    decision: RouteDecision,
    research: dict[str, dict],
    job_id: str,
) -> ListingPackage:
    """Generate a complete ListingPackage from item + research data.

    Uses the item card's specs, condition, and research prices to produce
    title, description, price strategy, and image list — everything the
    listing playbooks need to fill marketplace forms.
    """
    specs = item.likely_specs or {}
    brand = specs.get("brand", "")
    model = specs.get("model", "")
    color = specs.get("color", "")
    storage = specs.get("storage", "")

    title = item.name_guess
    if len(title) < 20:
        extras = [v for k, v in specs.items()
                  if k not in ("brand", "model") and v
                  and "_" not in str(v)]
        title = f"{title} {' '.join(extras[:2])}".strip()

    condition_label = item.condition_label
    defects = item.all_defects
    if defects:
        defect_lines = [f"- {d.description}" for d in defects[:5]]
        defects_disclosure = "Known issues:\n" + "\n".join(defect_lines)
    else:
        defects_disclosure = "No visible defects."

    desc_parts = [
        title,
        f"Condition: {condition_label}.",
    ]
    if defects:
        desc_parts.append(defects_disclosure)
    spec_line = ", ".join(f"{k}: {v}" for k, v in specs.items() if v)
    if spec_line:
        desc_parts.append(f"Specs: {spec_line}")
    desc_parts.append("Ships quickly. Message with questions!")
    description = "\n\n".join(desc_parts)

    research_prices = [
        data.get("avg_sold_price", 0.0)
        for data in research.values()
        if data.get("avg_sold_price", 0) > 0
    ]
    if research_prices:
        avg_market = sum(research_prices) / len(research_prices)
        price_strategy = round(avg_market * 0.95)
        price_min = round(min(research_prices) * 0.85)
        price_max = round(max(research_prices) * 1.05)
    else:
        price_strategy = 0.0
        price_min = 0.0
        price_max = 0.0

    images = _collect_listing_images(item)

    swarma_line("pipeline", "listing_package_detail",
                item_id=item.item_id, item_name=item.name_guess,
                title=title, price=price_strategy,
                images_n=len(images),
                image_paths=[img.path for img in images],
                condition=condition_label,
                specs_keys=list(specs.keys()))

    return ListingPackage(
        item_id=item.item_id,
        job_id=job_id,
        title=title,
        description=description,
        specs=specs,
        condition_summary=condition_label,
        defects_disclosure=defects_disclosure,
        price_strategy=price_strategy,
        price_min=price_min,
        price_max=price_max,
        images=images,
        platforms=decision.platforms,
        prices=decision.prices,
        research=research,
    )


_LISTING_PLATFORMS = {"facebook"}


def _should_list_on_platform(item: ItemCard, platform: str) -> bool:
    """Gate check: only Facebook is allowed for listing. All others are research-only."""
    if platform not in _LISTING_PLATFORMS:
        swarma_line("pipeline", "skip_listing",
                    item=item.name_guess, platform=platform,
                    reason="listing restricted to " + ", ".join(_LISTING_PLATFORMS))
        return False
    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    def __init__(self, max_concurrent: int | None = None):
        limit = max_concurrent or settings.max_concurrent_agents
        self.sem = asyncio.Semaphore(limit)
        self.events: asyncio.Queue[AgentEvent] = asyncio.Queue()

        self.agents: dict[str, Agent] = {}
        self.agent_states: dict[str, AgentState] = {}

        self._research_gate: asyncio.Event = asyncio.Event()
        self._pending_items: list[ItemCard] = []
        self._pending_job_id: str | None = None
        self._preloaded_sessions: dict[str, BrowserSession] = {}

        self.profiles: dict[str, str | None] = settings.storage_state_map
        swarma_line("orchestrator", "init", max_concurrent=limit,
                    profiles={k: ("loaded" if v else "missing") for k, v in self.profiles.items()})

    # --- Interface for Person 3 ---

    def get_agent_instance(self, agent_id: str) -> Agent | None:
        """Returns the Agent instance for a running agent, or None."""
        return self.agents.get(agent_id)

    def get_active_agents(self) -> list[AgentState]:
        """Returns current state of all agents for REST endpoint."""
        return list(self.agent_states.values())

    # --- Internal helpers ---

    def _make_profile(self, platform: str) -> BrowserProfile:
        storage = self.profiles.get(platform)
        return BrowserProfile(
            storage_state=storage,
            minimum_wait_page_load_time=0.1,
            wait_between_actions=0.1,
            headless=False,
            # Keep agent windows small and off-screen so they don't cover the
            # user's main Chrome window.  CDP + screencast work regardless of
            # on-screen visibility, so agents are unaffected.
            window_size={"width": 800, "height": 600},
            window_position={"width": 3000, "height": 3000},
        )

    def _emit(self, event: AgentEvent) -> None:
        self.events.put_nowait(event)

    def _update_state(self, agent_id: str, **kwargs) -> None:
        if agent_id in self.agent_states:
            for k, v in kwargs.items():
                setattr(self.agent_states[agent_id], k, v)

    def _make_step_callback(self, agent_id: str):
        """Creates a per-step callback that emits screenshots + agent thoughts."""
        def callback(state, model_output, step: int):
            url = getattr(state, "url", "")
            screenshot = getattr(state, "screenshot", None)

            thoughts = {}
            if model_output and hasattr(model_output, "current_state"):
                cs = model_output.current_state
                thoughts = {
                    "memory": getattr(cs, "memory", ""),
                    "next_goal": getattr(cs, "next_goal", ""),
                }
            actions = []
            action_names = []
            if model_output and hasattr(model_output, "action"):
                actions = [a.model_dump(exclude_unset=True) for a in model_output.action]
                action_names = [list(a.keys())[0] if a else "?" for a in actions]

            swarma_line("agent.step", "callback",
                        agent_id=agent_id, step=step, url=url,
                        has_screenshot=bool(screenshot),
                        actions=action_names,
                        next_goal=thoughts.get("next_goal", "")[:120])

            if screenshot:
                self._emit(AgentEvent(
                    type="agent:screenshot",
                    agent_id=agent_id,
                    data={"step": step, "screenshot_b64": screenshot, "url": url},
                ))

            self._emit(AgentEvent(
                type="agent:status",
                agent_id=agent_id,
                data={
                    "status": "running", "step": step,
                    "thoughts": thoughts, "actions": actions, "url": url,
                },
            ))

        return callback

    def _build_agent(self, agent_id: str, task_str: str, profile: BrowserProfile,
                     initial_actions: list[dict] | None = None,
                     use_vision: bool | str = False,
                     platform: str = "",
                     phase: str = "",
                     step_prehook=None,
                     file_paths: list[str] | None = None,
                     browser_session: BrowserSession | None = None) -> Agent:
        """Build an Agent with all speed + visual optimizations."""
        tools = make_research_tools(platform) if phase == "research" else None
        base_cb = self._make_step_callback(agent_id)

        if step_prehook is not None:
            async def _combined_cb(state, model_output, step):
                await step_prehook(state, model_output, step)
                base_cb(state, model_output, step)
            cb = _combined_cb
        else:
            cb = base_cb

        kwargs = dict(
            task=task_str,
            llm=_make_llm(),
            flash_mode=True,
            max_actions_per_step=4,
            max_steps=5 if phase == "research" else 30,
            use_vision=use_vision,
            initial_actions=initial_actions,
            tools=tools,
            register_new_step_callback=cb,
        )
        if browser_session is not None:
            kwargs["browser_session"] = browser_session
        else:
            kwargs["browser_profile"] = profile
        if file_paths:
            kwargs["available_file_paths"] = file_paths

        agent = Agent(**kwargs)
        return agent

    # --- Agent execution ---

    async def run_agent(
        self, item: ItemCard, playbook: Playbook, phase: str
    ):
        async with self.sem:
            agent_id = f"{playbook.platform}-{phase}-{item.item_id}"
            now = time.time()

            swarma_line("agent", "spawn", agent_id=agent_id, platform=playbook.platform,
                        phase=phase, item=item.name_guess, item_id=item.item_id)

            self.agent_states[agent_id] = AgentState(
                agent_id=agent_id,
                item_id=item.item_id,
                platform=playbook.platform,
                phase=phase,
                status="running",
                task=f"{phase} {playbook.platform} for {item.name_guess}",
                started_at=now,
            )

            self._emit(AgentEvent(
                type="agent:spawn", agent_id=agent_id,
                data={"platform": playbook.platform, "phase": phase,
                      "item_id": item.item_id, "task": self.agent_states[agent_id].task},
            ))

            if phase == "research":
                task_str, initial_actions = playbook.research_task(item)
            else:
                task_str, initial_actions = playbook.listing_task(item, item.listing_package)

            swarma_line("agent", "task_built", agent_id=agent_id,
                        task_len=len(task_str),
                        initial_actions_n=len(initial_actions) if initial_actions else 0,
                        task_preview=task_str[:150])

            profile = self._make_profile(playbook.platform)
            use_vision: bool | str = "auto" if phase == "listing" else False

            file_paths: list[str] | None = None
            if phase == "listing" and item.listing_package:
                pkg = item.listing_package
                from pathlib import Path as _P
                file_paths = [img.path for img in (pkg.images or []) if img.path and _P(img.path).exists()]
                swarma_line("agent", "listing_file_paths",
                            agent_id=agent_id, item=item.name_guess,
                            requested=[img.path for img in (pkg.images or [])],
                            valid=file_paths,
                            title=pkg.title[:80],
                            price=pkg.price_strategy)

            try:
                agent_box: list[Agent | None] = [None]
                sc_started = [False]

                preloaded = self._preloaded_sessions.pop(agent_id, None)

                async def _screencast_on_first_step(state, model_output, step):
                    if sc_started[0]:
                        return
                    sc_started[0] = True
                    try:
                        page = await agent_box[0].browser_session.get_current_page()
                        await streaming.start_screencast(agent_id, page, agent_box[0].browser_session)
                        swarma_line("agent", "screencast_started", agent_id=agent_id,
                                    url=getattr(page, "url", "unknown"))
                    except Exception as sc_err:
                        swarma_line("agent", "screencast_start_failed", agent_id=agent_id,
                                    error=str(sc_err))

                if preloaded:
                    sc_started[0] = True
                    swarma_line("agent", "using_preloaded_session", agent_id=agent_id)

                agent = self._build_agent(
                    agent_id, task_str, profile,
                    initial_actions=None if preloaded else initial_actions,
                    use_vision=use_vision,
                    platform=playbook.platform,
                    phase=phase,
                    step_prehook=None if preloaded else _screencast_on_first_step,
                    file_paths=file_paths,
                    browser_session=preloaded,
                )
                agent_box[0] = agent
                self.agents[agent_id] = agent

                swarma_line("agent", "run_start", agent_id=agent_id,
                            max_steps=5 if phase == "research" else 30,
                            use_vision=use_vision, flash_mode=True)

                history = await agent.run()

                final = history.final_result() if history.is_done() else None
                duration = time.time() - now

                swarma_line("agent", "run_complete", agent_id=agent_id,
                            duration_s=round(duration, 1),
                            is_done=history.is_done(),
                            result_len=len(str(final)) if final else 0,
                            result_preview=str(final)[:200] if final else "null")

                self._emit(AgentEvent(
                    type="agent:result", agent_id=agent_id,
                    data={"final_result": final},
                ))

                self._update_state(agent_id, status="complete", completed_at=time.time())
                self._emit(AgentEvent(
                    type="agent:complete", agent_id=agent_id,
                    data={"duration_s": duration},
                ))

                logger.info("Agent %s completed in %.1fs", agent_id, duration)
                return history

            except Exception as first_err:
                swarma_line("agent", "run_failed", agent_id=agent_id,
                            error=str(first_err), error_type=type(first_err).__name__,
                            traceback=traceback.format_exc()[-500:])
                logger.warning("Agent %s failed: %s, retrying...", agent_id, first_err)

                self._update_state(agent_id, status="retrying")
                self._emit(AgentEvent(
                    type="agent:status", agent_id=agent_id,
                    data={"status": "retrying", "error": str(first_err)},
                ))
                self.agents.pop(agent_id, None)

                await asyncio.sleep(3)

                try:
                    swarma_line("agent", "retry_start", agent_id=agent_id)

                    retry_box: list[Agent | None] = [None]
                    retry_sc_started = [False]

                    async def _retry_screencast_hook(state, model_output, step):
                        """Start screencast on the first step of the retry agent."""
                        if retry_sc_started[0]:
                            return
                        retry_sc_started[0] = True
                        try:
                            if retry_box[0] and retry_box[0].browser_session:
                                page = await retry_box[0].browser_session.get_current_page()
                                await streaming.start_screencast(agent_id, page, retry_box[0].browser_session)
                                swarma_line("agent", "retry_screencast_started", agent_id=agent_id)
                        except Exception:
                            pass

                    retry_agent = self._build_agent(
                        agent_id, task_str, profile,
                        initial_actions=initial_actions,
                        use_vision=use_vision,
                        platform=playbook.platform,
                        phase=phase,
                        file_paths=file_paths,
                        step_prehook=_retry_screencast_hook,
                    )
                    retry_box[0] = retry_agent
                    self.agents[agent_id] = retry_agent

                    history = await retry_agent.run()

                    duration = time.time() - now
                    swarma_line("agent", "retry_complete", agent_id=agent_id,
                                duration_s=round(duration, 1))

                    self._update_state(agent_id, status="complete", completed_at=time.time())
                    self._emit(AgentEvent(
                        type="agent:complete", agent_id=agent_id,
                        data={"duration_s": duration, "retried": True},
                    ))
                    logger.info("Agent %s completed on retry in %.1fs", agent_id, duration)
                    return history

                except Exception as retry_err:
                    swarma_line("agent", "retry_failed_blocked", agent_id=agent_id,
                                error=str(retry_err), error_type=type(retry_err).__name__,
                                traceback=traceback.format_exc()[-500:])
                    self._update_state(agent_id, status="blocked", error=str(retry_err))
                    self._emit(AgentEvent(
                        type="agent:error", agent_id=agent_id,
                        data={"error": str(retry_err), "status": "blocked"},
                    ))
                    logger.error("Agent %s blocked after retry: %s", agent_id, retry_err)
                    raise

                finally:
                    self.agents.pop(agent_id, None)

            finally:
                self.agents.pop(agent_id, None)
                try:
                    await streaming.stop_screencast(agent_id)
                    swarma_line("agent", "screencast_stopped", agent_id=agent_id)
                except Exception as sc_err:
                    swarma_line("agent", "screencast_stop_failed", agent_id=agent_id, error=str(sc_err))

    # --- Pipeline ---

    def release_research(self):
        """No-op — kept for API compat. Research starts automatically after preload."""
        pass

    async def start_pipeline(self, job_id: str, items: list[ItemCard]) -> None:
        """Full pipeline: advertise → preload browsers → research → listing.

        After intake, browsers are pre-launched and navigated to target URLs.
        Research begins automatically once preload finishes. The frontend
        auto-advances to the Research page when the first CDP frame arrives.
        """
        playbooks = get_all_playbooks()
        num_playbooks = len(playbooks)

        if not playbooks:
            swarma_line("pipeline", "no_playbooks", job_id=job_id)
            logger.warning("No playbooks registered. Skipping pipeline.")
            return

        swarma_line("pipeline", "start", job_id=job_id,
                    items_n=len(items), playbooks_n=num_playbooks,
                    total_research_agents=len(items) * num_playbooks,
                    playbook_platforms=[pb.platform for pb in playbooks],
                    item_names=[i.name_guess for i in items])

        self._pending_items = items
        self._pending_job_id = job_id

        # ── 1. Advertise: emit agent:spawn "ready" ──
        agent_plan: list[tuple[ItemCard, Playbook, str]] = []
        for item in items:
            for pb in playbooks:
                agent_id = f"{pb.platform}-research-{item.item_id}"
                agent_plan.append((item, pb, agent_id))
                self.agent_states[agent_id] = AgentState(
                    agent_id=agent_id,
                    item_id=item.item_id,
                    platform=pb.platform,
                    phase="research",
                    status="ready",
                    task=f"research {pb.platform} for {item.name_guess}",
                    started_at=None,
                )
                self._emit(AgentEvent(
                    type="agent:spawn", agent_id=agent_id,
                    data={
                        "platform": pb.platform, "phase": "research",
                        "item_id": item.item_id,
                        "task": self.agent_states[agent_id].task,
                        "status": "ready",
                    },
                ))

        swarma_line("pipeline", "agents_advertised", job_id=job_id,
                    agents_n=len(agent_plan))

        # ── 2. Preload: launch browsers & navigate to target URLs ──
        await _start_focus_guard()

        preloaded_sessions = self._preloaded_sessions

        async def _preload_one(item: ItemCard, pb: Playbook, agent_id: str):
            """Launch one browser, navigate to target URL, start screencast."""
            session = None
            try:
                profile = self._make_profile(pb.platform)
                session = BrowserSession(browser_profile=profile)
                await session.start()

                task_str, initial_actions = pb.research_task(item)
                nav_url = None
                if initial_actions:
                    for act in initial_actions:
                        if isinstance(act, dict) and "navigate" in act:
                            nav_url = act["navigate"].get("url") or act["navigate"]
                            break
                        if isinstance(act, dict) and "go_to_url" in act:
                            nav_url = act["go_to_url"].get("url") or act["go_to_url"]
                            break

                if nav_url:
                    await session.navigate_to(nav_url)

                page = await session.get_current_page()
                if page:
                    await streaming.start_screencast(agent_id, page, session)

                    # Run extraction JS during preload so agent starts with data
                    extract_js = get_extraction_js(pb.platform)
                    if extract_js:
                        try:
                            await asyncio.sleep(2)  # let DOM settle after navigation
                            await page.evaluate(extract_js)
                            swarma_line("preload", "extraction_done",
                                        agent_id=agent_id, platform=pb.platform)
                        except Exception as js_err:
                            swarma_line("preload", "extraction_failed",
                                        agent_id=agent_id, error=str(js_err))

                preloaded_sessions[agent_id] = session
                self._update_state(agent_id, status="preloaded")
                self._emit(AgentEvent(
                    type="agent:status", agent_id=agent_id,
                    data={"status": "preloaded"},
                ))
                swarma_line("preload", "done", agent_id=agent_id, url=nav_url or "none")
            except Exception as exc:
                swarma_line("preload", "failed", agent_id=agent_id, error=str(exc))
                self._update_state(agent_id, status="preload_failed")
                self._emit(AgentEvent(
                    type="agent:error", agent_id=agent_id,
                    data={"error": f"Preload failed: {exc}", "status": "preload_failed"},
                ))
                if session:
                    try:
                        await session.close()
                    except Exception:
                        pass

        preload_tasks = [
            _preload_one(item, pb, aid) for item, pb, aid in agent_plan
        ]
        await asyncio.gather(*preload_tasks, return_exceptions=True)

        swarma_line("pipeline", "preload_complete", job_id=job_id,
                    preloaded=len(preloaded_sessions))

        try:
            # Run each item's full lifecycle concurrently:
            # research → route decision → listing, all in parallel across items
            async def _run_item_pipeline(item: ItemCard):
                """Complete pipeline for one item — research, decide, list."""
                # Research: all platforms concurrently for this item
                item_research = [
                    self.run_agent(item, pb, "research")
                    for pb in playbooks
                ]
                results = await asyncio.gather(*item_research, return_exceptions=True)

                parsed: dict[str, dict] = {}
                for pb, result in zip(playbooks, results):
                    if isinstance(result, BaseException):
                        swarma_line("pipeline", "research_result_error", job_id=job_id,
                                    platform=pb.platform, item=item.name_guess,
                                    error=str(result))
                        continue
                    try:
                        parsed[pb.platform] = pb.parse_research(result.final_result())
                        swarma_line("pipeline", "research_parsed", job_id=job_id,
                                    platform=pb.platform, item=item.name_guess,
                                    result_keys=list(parsed[pb.platform].keys()))
                    except Exception as e:
                        swarma_line("pipeline", "research_parse_failed", job_id=job_id,
                                    platform=pb.platform, item=item.name_guess,
                                    error=str(e))

                if not parsed:
                    swarma_line("pipeline", "no_research_results_skip_listing",
                                job_id=job_id, item=item.name_guess)
                    self._emit(AgentEvent(
                        type="agent:error",
                        agent_id=f"research-{item.item_id}",
                        data={
                            "item_id": item.item_id,
                            "error": "All research agents failed — no pricing data available",
                            "status": "blocked",
                        },
                    ))
                    return

                decision: RouteDecision = route_decision(item, parsed)

                swarma_line("pipeline", "route_decision", job_id=job_id,
                            item=item.name_guess,
                            platforms=decision.platforms,
                            prices=decision.prices,
                            scores=decision.scores)

                self._emit(AgentEvent(
                    type="decision:made",
                    agent_id=f"decision-{item.item_id}",
                    data={
                        "item_id": item.item_id,
                        "platforms": decision.platforms,
                        "prices": decision.prices,
                        "scores": decision.scores,
                    },
                ))

                listing_pkg = _build_listing_package(item, decision, parsed, job_id)
                item.listing_package = listing_pkg

                swarma_line("pipeline", "listing_package_built", job_id=job_id,
                            item=item.name_guess,
                            item_id=item.item_id,
                            title=listing_pkg.title[:80],
                            images_n=len(listing_pkg.images),
                            image_paths=[img.path for img in listing_pkg.images],
                            price=listing_pkg.price_strategy,
                            condition=listing_pkg.condition_summary)

                if listing_pkg.price_strategy <= 0:
                    swarma_line("pipeline", "skip_listing_zero_price",
                                job_id=job_id, item=item.name_guess,
                                reason="price_strategy is 0 — all research failed or returned no prices")
                    self._emit(AgentEvent(
                        type="agent:error",
                        agent_id=f"listing-{item.item_id}",
                        data={
                            "item_id": item.item_id,
                            "error": "Cannot list: no valid price from research",
                            "status": "blocked",
                        },
                    ))
                    return

                listing_tasks = [
                    self.run_agent(item, get_playbook(platform), "listing")
                    for platform in decision.platforms
                    if platform in PLAYBOOKS
                    and _should_list_on_platform(item, platform)
                ]
                if listing_tasks:
                    swarma_line("pipeline", "listing_phase_start", job_id=job_id,
                                item=item.name_guess, agents_n=len(listing_tasks),
                                platforms=decision.platforms)
                    await asyncio.gather(*listing_tasks, return_exceptions=True)
                    swarma_line("pipeline", "listing_phase_complete", job_id=job_id,
                                item=item.name_guess)

            # Launch all items concurrently
            swarma_line("pipeline", "all_items_concurrent_start", job_id=job_id,
                        items_n=len(items))
            await asyncio.gather(
                *[_run_item_pipeline(item) for item in items],
                return_exceptions=True,
            )

            swarma_line("pipeline", "complete", job_id=job_id)

        finally:
            # Clean up any preloaded sessions that were never consumed by agents
            for aid, sess in list(self._preloaded_sessions.items()):
                try:
                    await sess.close()
                    swarma_line("pipeline", "cleanup_preloaded", agent_id=aid)
                except Exception:
                    pass
            self._preloaded_sessions.clear()
            await _stop_focus_guard()
