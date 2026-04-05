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
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("swarma.trace").setLevel(logging.DEBUG)
    logging.getLogger("swarmsell.server").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
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
