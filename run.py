#!/usr/bin/env python3
"""
ReRoute — main entry point.
Starts the Bureau (uAgents) and the FastAPI server concurrently.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
import time

import uvicorn

from backend.config import settings


def _tame_bureau_logs():
    """Keep useful warnings but suppress verbose gRPC tracebacks on retry."""
    logging.getLogger("grpc").setLevel(logging.ERROR)
    logging.getLogger("cosmpy").setLevel(logging.WARNING)


def run_bureau_thread():
    """Run the uAgents Bureau in a dedicated thread with its own event loop."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    _tame_bureau_logs()

    from backend.agents.bureau import create_bureau

    bureau = create_bureau()
    print(f"\n  [Bureau] Starting agent cluster on port {settings.bureau_port}...")
    print(f"  [Bureau] Agents: IntakeAgent, ConditionFusionAgent, ReturnAgent,")
    print(f"           TradeInAgent, MarketplaceResaleAgent, RepairROIAdvisorAgent,")
    print(f"           BundleOpportunityAgent, RouteDeciderAgent, ConciergeAgent")
    print(f"  [Bureau] Network: testnet | Concierge mailbox=True (Agentverse-connected)\n")

    try:
        bureau.run()
    except Exception as e:
        print(f"  [Bureau] Error: {e}")


def run_api_server():
    """Run the FastAPI server."""
    config = uvicorn.Config(
        "backend.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    return server


def main():
    settings.ensure_dirs()

    print(r"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     ██████╗ ███████╗██████╗  ██████╗ ██╗   ██╗████████╗███████╗║
    ║     ██╔══██╗██╔════╝██╔══██╗██╔═══██╗██║   ██║╚══██╔══╝██╔════╝║
    ║     ██████╔╝█████╗  ██████╔╝██║   ██║██║   ██║   ██║   █████╗  ║
    ║     ██╔══██╗██╔══╝  ██╔══██╗██║   ██║██║   ██║   ██║   ██╔══╝  ║
    ║     ██║  ██║███████╗██║  ██║╚██████╔╝╚██████╔╝   ██║   ███████╗║
    ║     ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝║
    ║                                                               ║
    ║     Record once. We handle the rest.                          ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)

    print(f"  [Config] Demo mode:    {settings.demo_mode}")
    print(f"  [Config] API server:   http://{settings.api_host}:{settings.api_port}")
    print(f"  [Config] Mac dashboard: http://localhost:{settings.api_port}")
    print(f"  [Config] Phone UI:     http://localhost:{settings.api_port}/phone/")
    print(f"  [Config] Bureau port:  {settings.bureau_port}")
    print()

    bureau_thread = threading.Thread(target=run_bureau_thread, daemon=True)
    bureau_thread.start()

    time.sleep(1)

    server = run_api_server()

    try:
        server.run()
    except KeyboardInterrupt:
        print("\n  [ReRoute] Shutting down...")
        sys.exit(0)


if __name__ == "__main__":
    main()
