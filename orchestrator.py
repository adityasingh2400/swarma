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
import time
import traceback

from browser_use import Agent, Browser, BrowserProfile

from config import settings
from contracts import AgentEvent, AgentState, Playbook, RouteDecision
from extraction import make_research_tools
from models.item_card import ItemCard
from models.listing_package import ListingPackage
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
    if settings.use_chat_browser_use:
        from browser_use import ChatBrowserUse
        swarma_line("orchestrator", "llm_init", backend="ChatBrowserUse")
        return ChatBrowserUse()
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
        )
        swarma_line("orchestrator", "llm_init", backend="gemini-2.0-flash")
        return llm
    except Exception as exc:
        swarma_line("orchestrator", "llm_init_fallback", error=str(exc), fallback="ChatBrowserUse")
        logger.warning("Gemini LLM init failed, falling back to ChatBrowserUse: %s", exc)
        from browser_use import ChatBrowserUse
        return ChatBrowserUse()


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
                     step_prehook=None) -> Agent:
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

        agent = Agent(
            task=task_str,
            llm=_make_llm(),
            browser_profile=profile,
            flash_mode=True,
            max_actions_per_step=4,
            max_steps=5 if phase == "research" else 30,
            use_vision=use_vision,
            initial_actions=initial_actions,
            tools=tools,
            register_new_step_callback=cb,
        )
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

            try:
                agent_box: list[Agent | None] = [None]
                sc_started = [False]

                async def _screencast_on_first_step(state, model_output, step):
                    if sc_started[0]:
                        return
                    sc_started[0] = True
                    try:
                        page = await agent_box[0].browser_session.get_current_page()
                        await streaming.start_screencast(agent_id, page)
                        swarma_line("agent", "screencast_started", agent_id=agent_id,
                                    url=getattr(page, "url", "unknown"))
                    except Exception as sc_err:
                        swarma_line("agent", "screencast_start_failed", agent_id=agent_id,
                                    error=str(sc_err))

                agent = self._build_agent(
                    agent_id, task_str, profile,
                    initial_actions=initial_actions,
                    use_vision=use_vision,
                    platform=playbook.platform,
                    phase=phase,
                    step_prehook=_screencast_on_first_step,
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
                    retry_agent = self._build_agent(
                        agent_id, task_str, profile,
                        initial_actions=initial_actions,
                        use_vision=use_vision,
                    )
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

    async def start_pipeline(self, job_id: str, items: list[ItemCard]) -> None:
        """Full pipeline: research → route decision → listing."""
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

        # Phase 1: Research — all items, all platforms, concurrently
        research_tasks = [
            self.run_agent(item, pb, "research")
            for item in items
            for pb in playbooks
        ]
        swarma_line("pipeline", "research_phase_start", job_id=job_id,
                    agents_n=len(research_tasks))

        all_results = await asyncio.gather(*research_tasks, return_exceptions=True)

        successes = sum(1 for r in all_results if not isinstance(r, BaseException))
        failures = sum(1 for r in all_results if isinstance(r, BaseException))
        swarma_line("pipeline", "research_phase_complete", job_id=job_id,
                    successes=successes, failures=failures)

        # Phase 2: Route decision + Phase 3: Listing — per item
        for i, item in enumerate(items):
            item_results = all_results[i * num_playbooks: (i + 1) * num_playbooks]

            parsed: dict[str, dict] = {}
            for pb, result in zip(playbooks, item_results):
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
                continue

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

            item.listing_package = ListingPackage(
                item_id=item.item_id,
                job_id=job_id,
                platforms=decision.platforms,
                prices=decision.prices,
                research=parsed,
            )

            listing_tasks = [
                self.run_agent(item, get_playbook(platform), "listing")
                for platform in decision.platforms
                if platform in PLAYBOOKS
            ]
            if listing_tasks:
                swarma_line("pipeline", "listing_phase_start", job_id=job_id,
                            item=item.name_guess, agents_n=len(listing_tasks),
                            platforms=decision.platforms)
                await asyncio.gather(*listing_tasks, return_exceptions=True)
                swarma_line("pipeline", "listing_phase_complete", job_id=job_id,
                            item=item.name_guess)

        swarma_line("pipeline", "complete", job_id=job_id)
