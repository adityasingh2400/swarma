"""Orchestrator — semaphore pool over Browser-Use Cloud agents.
Manages agent lifecycle, concurrency, event emission, and retry.
Person 3's server.py imports this and calls start_pipeline()."""
from __future__ import annotations

import asyncio
import logging
import time

from browser_use import Agent, Browser, BrowserProfile

from config import settings
from contracts import AgentEvent, AgentState, Playbook, RouteDecision
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
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=settings.gemini_api_key,
    )


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
        self.browsers: dict[str, Browser] = {}
        self.agent_states: dict[str, AgentState] = {}

        # Auth profiles
        self.profiles: dict[str, str | None] = settings.storage_state_map

    # --- Interface for Person 3 ---

    def get_browser(self, agent_id: str) -> Browser | None:
        """Returns the Browser instance for a running agent, or None."""
        return self.browsers.get(agent_id)

    def get_active_agents(self) -> list[AgentState]:
        """Returns current state of all agents for REST endpoint."""
        return list(self.agent_states.values())

    # --- Internal helpers ---

    def _make_browser(self, platform: str) -> Browser:
        storage = self.profiles.get(platform)
        profile = BrowserProfile(
            storage_state=storage,
            minimum_wait_page_load_time=0.1,
            wait_between_actions=0.1,
        )
        if settings.use_cloud:
            return Browser(profile, use_cloud=True)
        return Browser(profile)

    def _emit(self, event: AgentEvent) -> None:
        self.events.put_nowait(event)

    def _update_state(self, agent_id: str, **kwargs) -> None:
        if agent_id in self.agent_states:
            for k, v in kwargs.items():
                setattr(self.agent_states[agent_id], k, v)

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

            # Build task string
            if phase == "research":
                task_str = playbook.research_task(item)
            else:
                task_str = playbook.listing_task(item, item.listing_package)

            browser = self._make_browser(playbook.platform)
            self.browsers[agent_id] = browser

            try:
                agent = Agent(
                    task=task_str,
                    llm=_make_llm(),
                    browser=browser,
                    flash_mode=True,
                    max_actions_per_step=3,
                    max_steps=50,
                )
                self.agents[agent_id] = agent

                self._emit(AgentEvent(
                    type="agent:status", agent_id=agent_id,
                    data={"status": "running"},
                ))

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

                # Clean up failed browser
                try:
                    await browser.close()
                except Exception:
                    pass
                self.browsers.pop(agent_id, None)
                self.agents.pop(agent_id, None)

                # Retry with fresh browser + agent
                await asyncio.sleep(3)
                retry_browser = self._make_browser(playbook.platform)
                self.browsers[agent_id] = retry_browser

                try:
                    retry_agent = Agent(
                        task=task_str,
                        llm=_make_llm(),
                        browser=retry_browser,
                        flash_mode=True,
                        max_actions_per_step=3,
                        max_steps=50,
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
                    try:
                        await retry_browser.close()
                    except Exception:
                        pass
                    self.browsers.pop(agent_id, None)
                    self.agents.pop(agent_id, None)

            finally:
                # Clean up primary browser (if not already cleaned in retry path)
                if agent_id in self.browsers and self.browsers[agent_id] is browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    self.browsers.pop(agent_id, None)
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

            # Parse research results via playbooks
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

            # Route decision — pure function, no browser, fast
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

            # Build listing package from research + decision
            item.listing_package = ListingPackage(
                item_id=item.item_id,
                job_id=job_id,
                platforms=decision.platforms,
                prices=decision.prices,
                research=parsed,
            )

            # Phase 3: Listing — chosen platforms, concurrently
            listing_tasks = [
                self.run_agent(item, get_playbook(platform), "listing")
                for platform in decision.platforms
                if platform in PLAYBOOKS
            ]
            if listing_tasks:
                await asyncio.gather(*listing_tasks, return_exceptions=True)
