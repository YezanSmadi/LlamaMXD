# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Run every check, each in its own process (they pin module globals), and summarise.

    python tests/run_all.py              compare against the goldens
    python tests/run_all.py --update     re-record them after an intended change
    python tests/run_all.py ui jobs      only the named checks

Exit code 0 only when everything passed."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = ["commands", "core", "ui", "render", "behaviour", "hover", "media", "jobs", "runners", "queue", "leaks",
          "orphans", "userdata"]


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or CHECKS
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    failed = []
    for name in names:
        print(f"[{name}]", flush=True)
        start = time.monotonic()
        proc = subprocess.run([sys.executable, os.path.join(HERE, f"check_{name}.py"), *flags], cwd=HERE, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(("  PASS", "  FAIL", "  KNOWN", "          "))]
        print("\n".join(lines))
        # Qt's own chatter on stderr is noise; a traceback is not.
        if "Traceback" in proc.stderr:
            print(proc.stderr[proc.stderr.index("Traceback"):])
        if proc.returncode != 0 or "Traceback" in proc.stderr or any(ln.startswith("  FAIL") for ln in lines) \
                or not lines:
            failed.append(name)
        print(f"  ({time.monotonic() - start:.0f}s)")
    print("\nALL PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
