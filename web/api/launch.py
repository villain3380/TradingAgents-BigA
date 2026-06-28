"""Entry point for the ``tradingagents-web`` command: run the FastAPI server."""

import uvicorn


def main() -> None:
    uvicorn.run("web.api.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
