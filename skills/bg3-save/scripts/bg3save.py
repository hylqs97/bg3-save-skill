#!/usr/bin/env python3
"""Run the shared CLI from an editable checkout or an installed bg3save package."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import runpy
import sys


def main() -> None:
    # resolve() follows the Skill's junction/symlink: one source of truth.
    script = Path(__file__).resolve()
    repository = script.parents[3]
    # This file shares the package name; never import the wrapper as bg3save.
    sys.path[:] = [entry for entry in sys.path if Path(entry).resolve() != script.parent]
    source = repository / "src"
    if (source / "bg3save").is_dir():
        sys.path.insert(0, str(source))
    if importlib.util.find_spec("bg3save") is None:
        print(json.dumps({"status": "unsupported", "error": {
            "code": "cli_not_installed", "message":
            "Install the bg3-save-skill Python package or link this Skill from the full repository."
        }}), file=sys.stderr)
        raise SystemExit(2)
    runpy.run_module("bg3save", run_name="__main__")


if __name__ == "__main__":
    main()
