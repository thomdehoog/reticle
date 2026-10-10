"""``python -m app.importer`` — see :mod:`app.importer.cli`."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
