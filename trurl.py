#!/usr/bin/env python3
"""Run the bundled Trurl tools without installation."""
from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "skills" / "trurl" / "scripts" / "curation.py"),
        run_name="__main__",
    )

