#!/usr/bin/env python3
"""Fail if a requirement is not pinned in the lock that is supposed to cover it.

The deploy installs `requirements.lock` with `--require-hashes`, and CI installs
`requirements-dev.lock` the same way. Neither reads `requirements.txt`. That is
the point — a range resolves to something different every day — but it means a
package added to `requirements.txt` without regenerating the lock is simply
never installed, and the first anybody hears of it is an ImportError on a
facility's server halfway through a deploy.

This only checks that every named requirement appears pinned. It deliberately
does not re-resolve against PyPI: that would turn "somebody published a new
version this morning" into a red build nobody can make green.

Run from `backend/`:

    python ../.github/scripts/check_locks.py

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# A requirement line: name, optional [extras], then the version bound.
REQUIREMENT = re.compile(r"^([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?:[<>=~!].*)?$")

# A pin in the lock: name==version, with the hashes on the lines after it. The
# extras come along — pip-compile writes `psycopg[binary]==3.3.4` — and are
# dropped here, because the name is what has to match.
PINNED = re.compile(r"^([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==")


def normalise(name: str) -> str:
    """PyPI treats `-`, `_` and `.` as the same character, and ignores case."""
    return re.sub(r"[-_.]+", "-", name).lower()


def named_requirements(path: Path) -> set[str]:
    found = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):  # -r other.txt, -c constraints
            continue
        match = REQUIREMENT.match(line)
        if match:
            found.add(normalise(match.group(1)))
    return found


def pinned_packages(path: Path) -> set[str]:
    return {
        normalise(match.group(1))
        for line in path.read_text().splitlines()
        if (match := PINNED.match(line.strip()))
    }


def main() -> int:
    here = Path(__file__).resolve().parent.parent.parent / "backend"
    pairs = [
        (here / "requirements.txt", here / "requirements.lock"),
        (here / "requirements-dev.txt", here / "requirements-dev.lock"),
    ]

    failed = False
    for source, lock in pairs:
        if not lock.exists():
            print(f"MISSING: {lock.name} does not exist", file=sys.stderr)
            failed = True
            continue

        # requirements-dev.txt starts with `-r requirements.txt`, so the dev
        # lock has to cover both files.
        wanted = named_requirements(source)
        if source.name == "requirements-dev.txt":
            wanted |= named_requirements(here / "requirements.txt")

        missing = sorted(wanted - pinned_packages(lock))
        if missing:
            failed = True
            print(f"{lock.name} does not pin: {', '.join(missing)}", file=sys.stderr)
        else:
            print(f"{lock.name} covers every requirement in {source.name}")

    if failed:
        print(
            "\nRegenerate the locks — the command is in the header of "
            "backend/requirements.txt.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
