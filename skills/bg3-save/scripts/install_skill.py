#!/usr/bin/env python3
"""Link this Skill into Codex without maintaining a second copy of its code."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def inspect_installation(target: Path, source: Path) -> dict:
    required = ["SKILL.md", "scripts/bg3save.py", "references/cli.md",
                "references/editing.md", "references/sources.md", "agents/openai.yaml"]
    missing = [name for name in required if not (target / name).is_file()]
    same_source = target.resolve() == source.resolve() if target.exists() else False
    return {"skill": "bg3-save", "source": str(source), "installation": str(target),
            "shared_source": same_source, "missing": missing,
            "discoverable_on_next_skill_refresh": same_source and not missing,
            "status": "safe" if same_source and not missing else "unsupported"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path,
                        help="Defaults to CODEX_HOME or ~/.codex.")
    parser.add_argument("--check", action="store_true", help="Validate without changing files.")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run the installed wrapper's capabilities command after validation.")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    codex_home = args.codex_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    target = codex_home.expanduser().absolute() / "skills" / "bg3-save"
    if not (source / "SKILL.md").is_file():
        parser.error("The source Skill must contain SKILL.md.")
    if not args.check:
        if os.path.lexists(target):
            if target.resolve() != source.resolve():
                print(json.dumps({"status": "unsupported", "error":
                      "The target already exists and points elsewhere; it was left unchanged.",
                      "installation": str(target)}, ensure_ascii=False))
                return 2
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                # Directory junctions do not require administrator/developer-mode privileges.
                # Reject cmd expansion/control characters rather than constructing unsafe text.
                for value in (target, source):
                    if any(character in str(value) for character in '%!&|<>^"\r\n'):
                        parser.error("Use source and target paths without cmd metacharacters on Windows.")
                result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J",
                                         str(target), str(source)], capture_output=True, text=True)
                if result.returncode:
                    print(json.dumps({"status": "unsupported", "error": result.stderr.strip(),
                                      "installation": str(target)}, ensure_ascii=False))
                    return result.returncode
            else:
                target.symlink_to(source, target_is_directory=True)
    report = inspect_installation(target, source)
    if args.smoke_test and report["status"] == "safe":
        smoke_env = dict(os.environ, PYTHONUTF8="1")
        smoke = subprocess.run([sys.executable, str(target / "scripts" / "bg3save.py"),
                                "capabilities", "--json"], capture_output=True, text=True,
                                encoding="utf-8", env=smoke_env)
        report["smoke_test"] = {"exit_code": smoke.returncode}
        if smoke.returncode:
            report["smoke_test"]["stderr"] = smoke.stderr.strip()
            report["status"] = "unsupported"
        else:
            try:
                report["smoke_test"]["result"] = json.loads(smoke.stdout)
            except json.JSONDecodeError:
                report["smoke_test"]["stdout"] = smoke.stdout.strip()
                report["status"] = "unsupported"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "safe" else 2


if __name__ == "__main__":
    raise SystemExit(main())
