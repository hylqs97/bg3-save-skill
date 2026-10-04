from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .backend import Backend
from .errors import SaveError
from .model import entity_uuid
from . import service


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SaveError("invalid_arguments", message)


def make_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Structured JSON (also the default)", default=argparse.SUPPRESS)
    common.add_argument("--divine", default=argparse.SUPPRESS, help="Pinned LSLib Divine executable")
    common.add_argument("--bridge", default=argparse.SUPPRESS, help="Compiled LSLib bridge DLL")
    parser = Parser(prog="bg3save", description="Conservative BG3 save inspection and semantic editing", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    sub.add_parser("capabilities", parents=[common])
    find = sub.add_parser("find", parents=[common])
    find.add_argument("--root", type=Path)
    find.add_argument("--latest", action="store_true")
    for name in ("inspect", "party", "character", "flags", "quests", "missed-content", "verify"):
        command = sub.add_parser(name, parents=[common])
        command.add_argument("save", type=Path)
        if name == "character":
            command.add_argument("character")
        if name == "inspect":
            command.add_argument("--full", action="store_true", help="Include all typed Story database rows (large/private)")
        if name == "flags":
            command.add_argument("--limit", type=int, default=500)
        if name in ("quests", "missed-content"):
            command.add_argument("--offline", action="store_true")
    diff = sub.add_parser("diff", parents=[common])
    diff.add_argument("first", type=Path)
    diff.add_argument("second", type=Path)
    modify = sub.add_parser("modify", parents=[common])
    mods = modify.add_subparsers(dest="operation", required=True, parser_class=Parser)
    for name in ("set-hotbar-lock", "set-flag", "unset-flag", "restore-integrity-marker", "set-gold", "add-item", "remove-item", "set-approval", "repair"):
        command = mods.add_parser(name, parents=[common])
        command.add_argument("save", type=Path)
        if name not in ("repair", "restore-integrity-marker"):
            command.add_argument("value")
        command.add_argument("--slot", type=int, default=1)
        command.add_argument("--output", type=Path)
        command.add_argument("--backup-dir", type=Path)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--allow-experimental", action="store_true")
    rollback = sub.add_parser("rollback", parents=[common])
    rollback.add_argument("manifest", type=Path)
    rollback.add_argument("--output", type=Path, required=True)
    return parser


def run(args):
    if args.command == "capabilities":
        return service.capabilities()
    if args.command == "find":
        return service.find_saves(args.root, latest=args.latest)
    backend = Backend(getattr(args, "divine", None), getattr(args, "bridge", None))
    if args.command == "verify":
        return service.verify(args.save, backend)
    if args.command == "rollback":
        return service.rollback(args.manifest, args.output, backend)
    if args.command == "diff":
        return service.diff_snapshots(service.inspect(args.first, backend), service.inspect(args.second, backend))
    if args.command == "modify":
        value = getattr(args, "value", None)
        if args.operation == "set-hotbar-lock":
            if value.lower() not in ("true", "false"):
                raise SaveError("invalid_value", "Use true or false")
            value = value.lower() == "true"
        return service.modify(args.save, args.output, args.operation, value, slot=args.slot,
                              dry_run=args.dry_run, allow_experimental=args.allow_experimental,
                              backup_dir=args.backup_dir, backend=backend)
    snapshot = service.inspect(args.save, backend)
    if args.command == "inspect":
        return snapshot if args.full else service.public_snapshot(snapshot)
    if args.command == "party":
        return {"schema_version": 1, "capability": "SUPPORTED", "party": snapshot["party"],
                "players": snapshot["players"], "approval": snapshot["approval"], "romance": snapshot["romance"],
                "warnings": snapshot["warnings"]}
    if args.command == "character":
        query = args.character.casefold()
        matching = [char for char in snapshot["characters"]
                    if query in ((char.get("origin") or "").casefold(), (char.get("id") or "").casefold())
                    or (char.get("id") and entity_uuid(query) == entity_uuid(char["id"]))]
        if len(matching) != 1:
            raise SaveError("character_not_found_or_ambiguous", "Use an exact Origin or persisted character ID from party")
        char = matching[0]
        return {"schema_version": 1, "capability": "SUPPORTED", "character": char,
                "approval": [r for r in snapshot["approval"] if char["id"] and entity_uuid(char["id"]) in (entity_uuid(r["character"]), entity_uuid(r["toward"]))],
                "romance": {name: [r for r in fact["rows"] if char["id"] and entity_uuid(char["id"]) in [entity_uuid(v) for v in r]] for name, fact in snapshot["romance"].items()},
                "warnings": snapshot["warnings"]}
    if args.command == "flags":
        if args.limit < 0:
            raise SaveError("invalid_limit", "Limit must be nonnegative")
        return {"schema_version": 1, "capability": "SUPPORTED", "flags": snapshot["flags"][:args.limit],
                "total": len(snapshot["flags"]), "truncated": len(snapshot["flags"]) > args.limit,
                "warnings": snapshot["warnings"]}
    if args.command in ("quests", "missed-content"):
        from .content import analyze_content
        report = analyze_content(snapshot, online=not args.offline)
        report["save"] = snapshot["save"]
        report["journal"] = snapshot["journal"]
        return report
    raise SaveError("unknown_command", args.command)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = run(make_parser().parse_args(argv))
    except SaveError as error:
        print(json.dumps(error.as_json(), ensure_ascii=False, indent=2))
        return 2
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps(SaveError("operation_failed", str(error)).as_json(), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
