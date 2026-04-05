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
import base64
import logging
import time

from browser_use import Agent, Browser, BrowserProfile

from config import settings
from contracts import AgentEvent, AgentState, Playbook, RouteDecision
from extraction import make_research_tools
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from route_decision import route_decision

logger = logging.getLogger(__name__)

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
        return ChatBrowserUse()
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.gemini_api_key,
        )
    except Exception:
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

        # Exposed for Person 3
        self.agents: dict[str, Agent] = {}
        self.agent_states: dict[str, AgentState] = {}

        # Auth profiles
        self.profiles: dict[str, str | None] = settings.storage_state_map

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
        """Creates a per-step callback that emits screenshots + agent thoughts.
        This is how Person 3/4 see what each agent is doing visually."""
        def callback(state, model_output, step: int):
            # Push screenshot as event (base64 JPEG)
            screenshot = getattr(state, "screenshot", None)
            if screenshot:
                self._emit(AgentEvent(
                    type="agent:screenshot",
                    agent_id=agent_id,
                    data={
                        "step": step,
                        "screenshot_b64": screenshot,  # base64 encoded
                        "url": getattr(state, "url", ""),
                    },
                ))

            # Push agent's current thinking as status update
            thoughts = {}
            if model_output and hasattr(model_output, "current_state"):
                cs = model_output.current_state
                thoughts = {
                    "memory": getattr(cs, "memory", ""),
                    "next_goal": getattr(cs, "next_goal", ""),
                }
            actions = []
            if model_output and hasattr(model_output, "action"):
                actions = [
                    a.model_dump(exclude_unset=True)
                    for a in model_output.action
                ]

            self._emit(AgentEvent(
                type="agent:status",
                agent_id=agent_id,
                data={
                    "status": "running",
                    "step": step,
                    "thoughts": thoughts,
                    "actions": actions,
                    "url": getattr(state, "url", ""),
                },
            ))

        return callback

    def _build_agent(self, agent_id: str, task_str: str, profile: BrowserProfile,
                     initial_actions: list[dict] | None = None,
                     use_vision: bool | str = False,
                     platform: str = "",
                     phase: str = "") -> Agent:
        """Build an Agent with all speed + visual optimizations."""
        # Research agents get custom JS extraction tools (replaces slow LLM extract)
        tools = make_research_tools(platform) if phase == "research" else None

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
            register_new_step_callback=self._make_step_callback(agent_id),
        )
        return agent

    # --- Agent execution ---

    async def run_agent(
        self, item: ItemCard, playbook: Playbook, phase: str
    ):
        async with self.sem:
            agent_id = f"{playbook.platform}-{phase}-{item.item_id}"
            now = time.time()

            # Register state
            self.agent_states[agent_id] = AgentState(
                agent_id=agent_id,
                item_id=item.item_id,
                platform=playbook.platform,
                phase=phase,
                status="running",
                task=f"{phase} {playbook.platform} for {item.name_guess}",
                started_at=now,
            )

            # Emit spawn
            self._emit(AgentEvent(
                type="agent:spawn", agent_id=agent_id,
                data={"platform": playbook.platform, "phase": phase,
                      "item_id": item.item_id, "task": self.agent_states[agent_id].task},
            ))

            # Build task string + initial_actions from playbook
            if phase == "research":
                task_str, initial_actions = playbook.research_task(item)
            else:
                task_str, initial_actions = playbook.listing_task(item, item.listing_package)

            profile = self._make_profile(playbook.platform)

            # Listing phase needs vision (to see forms), research doesn't
            use_vision: bool | str = "auto" if phase == "listing" else False

            try:
                agent = self._build_agent(
                    agent_id, task_str, profile,
                    initial_actions=initial_actions,
                    use_vision=use_vision,
                    platform=playbook.platform,
                    phase=phase,
                )
                self.agents[agent_id] = agent

                history = await agent.run()

                # Emit result
                final = history.final_result() if history.is_done() else None
                self._emit(AgentEvent(
                    type="agent:result", agent_id=agent_id,
                    data={"final_result": final},
                ))

                duration = time.time() - now
                self._update_state(agent_id, status="complete", completed_at=time.time())
                self._emit(AgentEvent(
                    type="agent:complete", agent_id=agent_id,
                    data={"duration_s": duration},
                ))

                logger.info(f"Agent {agent_id} completed in {duration:.1f}s")
                return history

            except Exception as first_err:
                logger.warning(f"Agent {agent_id} failed: {first_err}, retrying...")
                self._update_state(agent_id, status="retrying")
                self._emit(AgentEvent(
                    type="agent:status", agent_id=agent_id,
                    data={"status": "retrying", "error": str(first_err)},
                ))
                self.agents.pop(agent_id, None)

                await asyncio.sleep(3)

                try:
                    retry_agent = self._build_agent(
                        agent_id, task_str, profile,
                        initial_actions=initial_actions,
                        use_vision=use_vision,
                    )
                    self.agents[agent_id] = retry_agent

                    history = await retry_agent.run()

                    duration = time.time() - now
                    self._update_state(agent_id, status="complete", completed_at=time.time())
                    self._emit(AgentEvent(
                        type="agent:complete", agent_id=agent_id,
                        data={"duration_s": duration, "retried": True},
                    ))
                    logger.info(f"Agent {agent_id} completed on retry in {duration:.1f}s")
                    return history

                except Exception as retry_err:
                    self._update_state(agent_id, status="blocked", error=str(retry_err))
                    self._emit(AgentEvent(
                        type="agent:error", agent_id=agent_id,
                        data={"error": str(retry_err), "status": "blocked"},
                    ))
                    logger.error(f"Agent {agent_id} blocked after retry: {retry_err}")
                    raise

                finally:
                    self.agents.pop(agent_id, None)

            finally:
                self.agents.pop(agent_id, None)

    # --- Pipeline ---

    async def start_pipeline(self, job_id: str, items: list[ItemCard]) -> None:
        """Full pipeline: research → route decision → listing. Called by Person 3."""
        playbooks = get_all_playbooks()
        num_playbooks = len(playbooks)

        if not playbooks:
            logger.warning("No playbooks registered. Skipping pipeline.")
            return

        logger.info(
            f"Starting pipeline for job {job_id}: {len(items)} items, "
            f"{num_playbooks} playbooks, {len(items) * num_playbooks} research agents"
        )

        # Phase 1: Research — all items, all platforms, concurrently
        research_tasks = [
            self.run_agent(item, pb, "research")
            for item in items
            for pb in playbooks
        ]
        all_results = await asyncio.gather(*research_tasks, return_exceptions=True)

        # Phase 2: Route decision + Phase 3: Listing — per item
        for i, item in enumerate(items):
            item_results = all_results[i * num_playbooks: (i + 1) * num_playbooks]

            parsed: dict[str, dict] = {}
            for pb, result in zip(playbooks, item_results):
                if isinstance(result, BaseException):
                    logger.warning(f"Research failed for {pb.platform}/{item.item_id}: {result}")
                    continue
                try:
                    parsed[pb.platform] = pb.parse_research(result.final_result())
                except Exception as e:
                    logger.warning(f"Parse failed for {pb.platform}/{item.item_id}: {e}")

            if not parsed:
                logger.warning(f"No research results for item {item.item_id}, skipping listing")
                continue

            decision: RouteDecision = route_decision(item, parsed)

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
            logger.info(
                f"Route decision for {item.name_guess}: "
                f"{', '.join(decision.platforms)} "
                f"(scores: {decision.scores})"
            )

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
                await asyncio.gather(*listing_tasks, return_exceptions=True)
