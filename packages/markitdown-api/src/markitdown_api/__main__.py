from markitdown_api.app import app
import uvicorn


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run a MarkItDown API server")
    default_host = "127.0.0.1"
    parser.add_argument(
        "--host",
        default=default_host,
        help=f"Host to bind to (default: {default_host})",
    )
    default_port = 3002
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Port to listen on (default: {default_port})",
    )
    args = parser.parse_args()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
