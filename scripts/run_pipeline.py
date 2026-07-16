#!/usr/bin/env python3
"""Thin CLI wrapper — delegates to newsroom.pipeline.runner (authoritative)."""

import os
import sys

# allow host runs without installed package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from newsroom.pipeline.runner import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
