"""Daemon 入口：python -m mozilcode.daemon。"""

from mozilcode.daemon.server import run_daemon

if __name__ == "__main__":
    run_daemon()
