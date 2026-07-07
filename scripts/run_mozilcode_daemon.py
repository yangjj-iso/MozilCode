from __future__ import annotations

import argparse

from mozilcode.daemon.server import run_daemon


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local MozilCode daemon.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7800)
    parser.add_argument("--work-dir", default=None)
    args = parser.parse_args()
    run_daemon(host=args.host, port=args.port, work_dir=args.work_dir)


if __name__ == "__main__":
    main()
