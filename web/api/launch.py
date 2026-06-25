"""Entry point for the ``tradingagents-api`` command: run the FastAPI server."""

import uvicorn


def main() -> None:
    uvicorn.run("web.api.server:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
