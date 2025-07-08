from markitdown_api.app import app
import uvicorn


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run a MarkItDown API server")
    parser.add_argument(
        "--host", default=None, help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Port to listen on (default: 3002)"
    )
    args = parser.parse_args()

    uvicorn.run(
        app,
        host=args.host if args.host else "127.0.0.1",
        port=args.port if args.port else 3002,
    )


if __name__ == "__main__":
    main()
