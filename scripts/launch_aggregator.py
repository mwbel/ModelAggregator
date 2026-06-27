from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: launch_aggregator.py ROOT_DIR LOG_FILE HOST PORT", file=sys.stderr)
        return 2

    root_dir = Path(sys.argv[1]).resolve()
    log_file = Path(sys.argv[2]).resolve()
    host = sys.argv[3]
    port = sys.argv[4]

    env = os.environ.copy()
    env["AGGREGATOR_HOST"] = host
    env["AGGREGATOR_PORT"] = port

    log_file.parent.mkdir(parents=True, exist_ok=True)
    stdin = subprocess.DEVNULL
    stdout = open(log_file, "ab", buffering=0)

    process = subprocess.Popen(
        [sys.executable, "-m", "model_aggregator.server"],
        cwd=str(root_dir),
        env=env,
        stdin=stdin,
        stdout=stdout,
        stderr=stdout,
        start_new_session=True,
        close_fds=True,
    )
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
