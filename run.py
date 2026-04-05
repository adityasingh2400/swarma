"""Entry point for the v2 pipeline."""
import uvicorn
from config import settings


def main():
    settings.ensure_dirs()
    uvicorn.run(
        "server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    main()
