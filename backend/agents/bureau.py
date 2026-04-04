from __future__ import annotations

from uagents import Bureau

from backend.agents.bundle_opportunity_agent import create_bundle_opportunity_agent
from backend.agents.concierge_agent import create_concierge_agent
from backend.agents.condition_fusion_agent import create_condition_fusion_agent
from backend.agents.intake_agent import create_intake_agent
from backend.agents.marketplace_resale_agent import create_marketplace_resale_agent
from backend.agents.repair_roi_advisor_agent import create_repair_roi_advisor_agent
from backend.agents.return_agent import create_return_agent
from backend.agents.route_decider_agent import create_route_decider_agent
from backend.agents.trade_in_agent import create_trade_in_agent
from backend.config import settings

intake_agent = create_intake_agent()
condition_fusion_agent = create_condition_fusion_agent()
return_agent = create_return_agent()
trade_in_agent = create_trade_in_agent()
marketplace_resale_agent = create_marketplace_resale_agent()
repair_roi_advisor_agent = create_repair_roi_advisor_agent()
bundle_opportunity_agent = create_bundle_opportunity_agent()
route_decider_agent = create_route_decider_agent()
concierge_agent = create_concierge_agent()

STAGE2_AGENTS = [
    return_agent,
    trade_in_agent,
    marketplace_resale_agent,
    repair_roi_advisor_agent,
    bundle_opportunity_agent,
]

ALL_AGENTS = [
    intake_agent,
    condition_fusion_agent,
    *STAGE2_AGENTS,
    route_decider_agent,
    concierge_agent,
]


def create_bureau() -> Bureau:
    bureau = Bureau(
        port=settings.bureau_port,
        endpoint=f"http://localhost:{settings.bureau_port}/submit",
    )
    for agent in ALL_AGENTS:
        bureau.add(agent)
    return bureau
