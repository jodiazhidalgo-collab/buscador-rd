import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path("/app")
LOG_DIR = ROOT / "logs"
CLOUDFLARED_LOG = Path(os.getenv("CLOUDFLARED_LOG", str(LOG_DIR / "cloudflared" / "cloudflared.log")))
TUNNEL_TARGET = os.getenv("TUNNEL_TARGET", "http://btdigg-rd:9007")


def ensure_dirs():
    for path in [
        LOG_DIR / "cloudflared",
        LOG_DIR / "watcher",
        ROOT / "data" / "estado",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def start_processes():
    cloudflared_cmd = [
        "cloudflared",
        "tunnel",
        "--no-autoupdate",
        "--loglevel",
        "info",
        "--logfile",
        str(CLOUDFLARED_LOG),
        "--url",
        TUNNEL_TARGET,
    ]
    watcher_cmd = [sys.executable, "/app/watcher/watcher.py"]
    return [
        subprocess.Popen(cloudflared_cmd),
        subprocess.Popen(watcher_cmd),
    ]


def terminate(processes):
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if all(proc.poll() is not None for proc in processes):
            return
        time.sleep(0.2)
    for proc in processes:
        if proc.poll() is None:
            proc.kill()


def main():
    ensure_dirs()
    processes = start_processes()
    stopping = False

    def handle_signal(_signum, _frame):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        terminate(processes)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while not stopping:
        for proc in processes:
            code = proc.poll()
            if code is not None:
                terminate(processes)
                return code
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
