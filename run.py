"""Entry point for the v2 pipeline."""
import logging
import sys

import uvicorn
from config import settings

_DEBUG_BANNER = """
================================================================================
  SWARMA DEBUG TRACES
  • Terminal (python run.py): copy lines starting with "SWARMA |"
  • Browser: DevTools → Console → filter "SWARMA:fe"
================================================================================
"""


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("swarma.trace").setLevel(logging.INFO)
    print(_DEBUG_BANNER, flush=True)

    settings.ensure_dirs()
    uvicorn.run(
        "backend.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
