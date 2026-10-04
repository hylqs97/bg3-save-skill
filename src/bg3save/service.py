from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET

from .backend import Backend, cache_root, sha256
from .errors import SaveError
from .model import UUID_SUFFIX, attrs, parse_snapshot, read_xml

SAFE_WRITE_VERSIONS = {"4.1.1.7631656"}


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def capabilities() -> dict:
    return {"schema_version": 1, "capability": "SUPPORTED", "operations": {
        "find": "SUPPORTED", "inspect": "SUPPORTED", "party": "SUPPORTED", "character": "SUPPORTED",
        "flags": "SUPPORTED", "approval-story-facts": "SUPPORTED", "romance-story-facts": "SUPPORTED",
        "quests": "EXPERIMENTAL", "missed-content": "EXPERIMENTAL", "diff": "SUPPORTED",
        "verify": "SUPPORTED", "set-hotbar-lock": "SUPPORTED", "set-flag": "EXPERIMENTAL",
        "unset-flag": "EXPERIMENTAL", "rollback": "SUPPORTED", "set-gold": "UNSUPPORTED",
        "restore-integrity-marker": "EXPERIMENTAL",
        "add-item": "UNSUPPORTED", "remove-item": "UNSUPPORTED", "set-approval": "UNSUPPORTED",
        "repair": "UNSUPPORTED"},
        "safe_write_versions": sorted(SAFE_WRITE_VERSIONS), "package_write_versions": [18],
        "limits": ["SUPPORTED write is a narrow client UI state, not arbitrary ECS editing.",
                   "verify checks structure and typed facts; actual in-game load is a separate test.",
                   "Quest analysis covers curated rules only; absent evidence remains uncertain."]}


def find_saves(root: Path | None = None, *, latest=False) -> dict:
    if root is None:
        # The documented Windows game profile lives outside the packaged app's
        # virtualized LOCALAPPDATA. Prefer the actual user profile directory.
        root = Path.home() / "AppData/Local/Larian Studios/Baldur's Gate 3/PlayerProfiles"
    if not root.is_dir():
        raise SaveError("save_directory_missing", "Save directory not found; provide --root")
    saves = [{"path": str(path.resolve()), "size": path.stat().st_size, "modified": path.stat().st_mtime}
             for path in root.rglob("*.lsv") if path.is_file()]
    saves.sort(key=lambda s: (s["modified"], s["path"]), reverse=True)
    return {"schema_version": 1, "capability": "SUPPORTED", "root": str(root),
            "saves": saves[:1] if latest else saves}


@contextmanager
def opened_save(path: Path, backend: Backend):
    path = path.expanduser().resolve()
    before_hash = sha256(path) if path.is_file() else None
    with tempfile.TemporaryDirectory(prefix="bg3save-") as temporary:
        work = Path(temporary)
        unpacked = work / "unpacked"
        package = backend.unpack(path, unpacked)
        if not (unpacked / "meta.lsf").is_file() or not (unpacked / "Globals.lsf").is_file():
            raise SaveError("missing_save_members", "Expected meta.lsf and Globals.lsf")
        meta_xml, globals_xml = work / "meta.lsx", work / "globals.lsx"
        backend.convert(unpacked / "meta.lsf", meta_xml)
        backend.convert(unpacked / "Globals.lsf", globals_xml)
        story_path = unpacked / "StorySave.bin"
        story = backend.read_story(story_path, work / "story.json") if story_path.is_file() else None
        snapshot = parse_snapshot(unpacked, meta_xml, globals_xml, story)
        snapshot["archive"] = {"version": package["version"],
                               "header_md5": package.get("header_md5"),
                               "checksum_valid": package.get("canonical_checksum_valid"),
                               "physical_checksum_valid": package.get("checksum_valid"),
                               "flags": package.get("flags"), "priority": package.get("priority"), "members": [
            {"name": entry["name"], "size": entry["size"],
             "sha256": sha256(unpacked / entry["name"].replace("\\", "/"))} for entry in package["entries"]]}
        if sha256(path) != before_hash:
            raise SaveError("source_changed", "Source changed during inspection; retry after saving finishes")
        snapshot["save"] = {"path": str(path), "sha256": before_hash, "bytes": path.stat().st_size}
        snapshot["story"]["semantic_sha256"] = digest_json(canonical_databases(snapshot["story"]["databases"]))
        yield {"snapshot": snapshot, "directory": unpacked, "meta_xml": meta_xml,
               "globals_xml": globals_xml, "work": work, "package": package}


def inspect(path: Path, backend: Backend | None = None) -> dict:
    with opened_save(path, backend or Backend()) as handle:
        return handle["snapshot"]


def public_snapshot(snapshot: dict) -> dict:
    result = dict(snapshot)
    result["story"] = {key: val for key, val in snapshot["story"].items() if key != "databases"}
    return result


def canonical_databases(databases: dict) -> dict:
    return {name: {"columns": db["columns"], "rows": sorted(db["rows"], key=lambda row: json.dumps(row, sort_keys=True))}
            for name, db in sorted(databases.items())}


def tree_state(node):
    return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
            tuple(tree_state(child) for child in node))


def file_map(directory: Path) -> dict:
    return {path.relative_to(directory).as_posix(): sha256(path)
            for path in directory.rglob("*") if path.is_file()}


def diff_snapshots(first: dict, second: dict) -> dict:
    keys = ("act", "region", "game_version", "save_name", "metadata", "clients", "mods",
            "party", "players", "flags", "journal", "approval", "romance", "npc_states")
    changes = [{"field": key, "before": first.get(key), "after": second.get(key)}
               for key in keys if first.get(key) != second.get(key)]
    db_changes = []
    a = canonical_databases(first.get("story", {}).get("databases", {}))
    b = canonical_databases(second.get("story", {}).get("databases", {}))
    for name in sorted(set(a) | set(b)):
        if a.get(name) != b.get(name):
            db_changes.append({"database": name, "before": a.get(name), "after": b.get(name)})
    members_a = {m["name"]: m["sha256"] for m in first.get("archive", {}).get("members", [])}
    members_b = {m["name"]: m["sha256"] for m in second.get("archive", {}).get("members", [])}
    byte_changes = [name for name in sorted(set(members_a) | set(members_b)) if members_a.get(name) != members_b.get(name)]
    return {"schema_version": 1, "capability": "SUPPORTED", "equal_extracted_semantics": not changes and not db_changes,
            "all_payloads_byte_identical": not byte_changes,
            "changes": changes, "story_changes": db_changes, "changed_archive_members": byte_changes,
            "warnings": ["Diff compares extracted fields and member bytes; opaque ECS semantics remain unknown."]}


def verify(path: Path, backend: Backend | None = None, *, allow_failed_sanity=False) -> dict:
    state = inspect(path, backend)
    if state["story"]["version"] is None:
        raise SaveError("missing_story", "StorySave.bin is required to verify a full BG3 campaign save")
    if state["archive"]["checksum_valid"] is not True:
        raise SaveError("archive_checksum_failed", "Native archive integrity checksum is invalid or unavailable")
    sane = state["metadata"].get("Sanity", "").lower() == "true"
    if not sane and not allow_failed_sanity:
        raise SaveError("save_sanity_failed", "Native Sanity flag is false or unavailable; full verification refused")
    checks = ["archive paths/sizes", "native archive integrity checksum", "LSLib archive extraction", "metadata resource parse",
              "globals resource parse", "journal extraction"]
    if state["story"]["version"]:
        checks.append("all typed Story databases parse")
    warnings = list(state["warnings"])
    if not sane:
        warnings.append("The original native Sanity flag is false; restoring these exact bytes retains its game warning.")
    return {"schema_version": 1, "capability": "SUPPORTED", "valid": sane, "structural_valid": True,
            "game_load_validated": False, "checks": checks, "save": state["save"],
            "archive_checksum_valid": state["archive"]["checksum_valid"],
            "game_version": state["game_version"], "warnings": warnings}


def resolve_flag(snapshot: dict, query: str) -> str:
    match = UUID_SUFFIX.fullmatch(query) or UUID_SUFFIX.search(query)
    if not match:
        raise SaveError("invalid_flag", "Provide a UUID or full persisted symbolic-name_UUID")
    flag_uuid = match["uuid"].lower()
    found = set()
    for db in snapshot["story"]["databases"].values():
        for row in db["rows"]:
            for kind, value in zip(db["columns"], row):
                if kind != "FLAG" or not isinstance(value, str):
                    continue
                suffix = UUID_SUFFIX.search(value)
                if suffix and suffix["uuid"].lower() == flag_uuid:
                    found.add(value)
    if len(found) != 1:
        raise SaveError("unknown_or_ambiguous_flag", "Flag must resolve uniquely in the save's typed FLAG catalog")
    return found.pop()


def _backup(source: Path, source_hash: str, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"{source.stem}-{uuid.uuid4().hex}.lsv"
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    if sha256(destination) != source_hash or sha256(source) != source_hash:
        raise SaveError("source_changed", "Source changed while backing up; mutation aborted")
    return destination


def _publish(source: Path, destination: Path):
    # Exclusive destination creation prevents a racing process from being overwritten.
    with source.open("rb") as incoming:
        outgoing = destination.open("xb")
        try:
            with outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def modify(source: Path, output: Path | None, operation: str, value=None, *, slot=1,
           dry_run=False, allow_experimental=False, backup_dir: Path | None = None,
           backend: Backend | None = None) -> dict:
    backend = backend or Backend()
    if operation not in ("set-hotbar-lock", "set-flag", "unset-flag", "restore-integrity-marker"):
        raise SaveError("unsupported_operation", f"{operation} cannot currently be safely written")
    flag_edit = operation in ("set-flag", "unset-flag")
    marker_edit = operation == "restore-integrity-marker"
    experimental = flag_edit or marker_edit
    if experimental and not allow_experimental:
        raise SaveError("experimental_opt_in_required", "This operation requires --allow-experimental; inspect its risks before executing",
                        status="EXPERIMENTAL")
    source = source.expanduser().resolve()
    output = output.expanduser().resolve() if output else None
    if not dry_run and output is None:
        raise SaveError("output_required", "Write a new .lsv using --output")
    if output is not None:
        if output == source or output.exists() or output.suffix.lower() != ".lsv":
            raise SaveError("unsafe_output", "Output must be a distinct, nonexistent .lsv")
        if Path(str(output) + ".manifest.json").exists():
            raise SaveError("output_exists", "Output manifest already exists")
    with opened_save(source, backend) as handle:
        before = handle["snapshot"]
        if before["story"]["version"] is None:
            raise SaveError("missing_story", "StorySave.bin is required before mutation")
        if before["archive"]["version"] != 18:
            raise SaveError("unsupported_package_version", "Only package version 18 is writable")
        if before["archive"]["checksum_valid"] is not True:
            raise SaveError("archive_checksum_failed", "Source native archive checksum is invalid; mutation refused")
        source_sanity = before["metadata"].get("Sanity", "").lower()
        if source_sanity != "true" and not (marker_edit and source_sanity == "false"):
            raise SaveError("save_sanity_failed", "Source was not marked sane by BG3; mutation refused without altering Sanity")
        if before["archive"]["flags"] != 0 or before["archive"]["priority"] != 0:
            raise SaveError("unsupported_package_header", "Writing requires the verified flags=0 and priority=0 header")
        if before["game_version"] not in SAFE_WRITE_VERSIONS:
            raise SaveError("unsupported_game_version", "Writes are restricted to locally verified versions",
                            details={"actual": before["game_version"], "supported": sorted(SAFE_WRITE_VERSIONS)})
        if before["game_versions"] and before["game_versions"][-1] != before["game_version"]:
            raise SaveError("version_evidence_conflict", "SaveInfo version disagrees with metadata; writing refused")
        xml = read_xml(handle["meta_xml"])
        deep_checks = []
        if marker_edit:
            if source_sanity != "false":
                raise SaveError("marker_repair_not_needed", "Native Sanity is already true")
            for resource in sorted(handle["directory"].rglob("*.lsf")):
                converted = handle["work"] / f"deep-resource-{len(deep_checks)}.lsx"
                backend.convert(resource, converted)
                deep_checks.append(resource.relative_to(handle["directory"]).as_posix())
            targets = xml.findall(".//region[@id='MetaData']/node/children/node/attribute[@id='Sanity']")
            if len(targets) != 1 or targets[0].get("type") != "bool":
                raise SaveError("unsupported_metadata_schema", "Expected exactly one native Sanity boolean")
            original, requested = False, True
            targets[0].set("value", "True")
            intended_member = "meta.lsf"
        elif not flag_edit:
            if not isinstance(value, bool):
                raise SaveError("invalid_value", "Hotbar lock must be true or false")
            clients = [node for node in xml.findall(".//node[@id='ClientData']") if attrs(node).get("Slot") == str(slot)]
            if len(clients) != 1:
                raise SaveError("ambiguous_client", "Expected exactly one client with that slot")
            target = clients[0].find("attribute[@id='HotbarLocked']")
            if target is None or target.get("type") != "bool" or target.get("value", "").lower() not in ("true", "false"):
                raise SaveError("unsupported_client_schema", "No supported HotbarLocked boolean")
            original = target.get("value").lower() == "true"
            requested = value
            target.set("value", "True" if value else "False")
            intended_member = "meta.lsf"
        else:
            requested = resolve_flag(before, str(value))
            original = requested in {flag["value"] for flag in before["flags"] if flag["scope"] == "global"}
            intended_member = "StorySave.bin"
        plan = {"operation": operation, "capability": "EXPERIMENTAL" if experimental else "SUPPORTED",
                "field": "DB_GlobalFlag" if flag_edit else "MetaData/Sanity" if marker_edit else "ClientData/HotbarLocked",
                "slot": None if experimental else slot, "before": original,
                "after": operation == "set-flag" if flag_edit else requested,
                "flag": requested if flag_edit else None, "member": intended_member,
                "source_sha256": before["save"]["sha256"], "output": str(output) if output else None,
                "backup_required": True,
                "deep_resource_checks": deep_checks,
                "risks": ["Restores only a persisted integrity marker after canonical checksum and LSF parsing; does not repair opaque ECS corruption. A game reload is still required."] if marker_edit else
                         ["Story DB writes do not execute quest events or synchronize ECS"] if flag_edit else []}
        if dry_run:
            return {"schema_version": 1, "capability": plan["capability"], "dry_run": True, "written": False, "plan": plan}
        backup = _backup(source, before["save"]["sha256"], backup_dir or cache_root().resolve() / "backups")
        directory = handle["directory"]
        before_files = file_map(directory)
        if flag_edit:
            written = handle["work"] / "edited-story.bin"
            backend.call("story-set-global-flag" if operation == "set-flag" else "story-unset-global-flag",
                         directory / "StorySave.bin", written, requested)
        else:
            edited_xml = handle["work"] / "edited-meta.lsx"
            ET.ElementTree(xml).write(edited_xml, encoding="utf-8", xml_declaration=True)
            written = handle["work"] / "edited-meta.lsf"
            backend.convert(edited_xml, written, template=directory / "meta.lsf")
            checked_xml = handle["work"] / "checked-meta.lsx"
            backend.convert(written, checked_xml)
            if tree_state(xml) != tree_state(read_xml(checked_xml)):
                raise SaveError("resource_roundtrip_mismatch", "LSLib conversion changed an unintended metadata field")
        shutil.copyfile(written, directory / intended_member)
        candidate = handle["work"] / "candidate.lsv"
        backend.repack(directory, candidate, before["archive"]["version"], template=source)
        with opened_save(candidate, backend) as after_handle:
            after = after_handle["snapshot"]
            if after["archive"]["checksum_valid"] is not True:
                raise SaveError("verification_failed", "Repacked native archive checksum does not match")
            after_files = file_map(after_handle["directory"])
            if set(after_files) != set(before_files):
                raise SaveError("verification_failed", "Archive membership changed")
            for member in before_files:
                if member != intended_member and before_files[member] != after_files[member]:
                    raise SaveError("verification_failed", f"Untouched member changed: {member}")
            if not flag_edit and tree_state(read_xml(after_handle["meta_xml"])) != tree_state(xml):
                raise SaveError("verification_failed", "Repacked metadata differs from the approved plan")
            differences = diff_snapshots(before, after)
            if not flag_edit and differences["story_changes"]:
                raise SaveError("verification_failed", "Story databases unexpectedly changed")
            if flag_edit:
                changed_dbs = {record["database"] for record in differences["story_changes"]}
                if not changed_dbs.issubset({"DB_GlobalFlag"}):
                    raise SaveError("verification_failed", "Unexpected Story database changes")
                enabled = requested in {f["value"] for f in after["flags"] if f["scope"] == "global"}
                if enabled != (operation == "set-flag"):
                    raise SaveError("verification_failed", "Requested flag state was not persisted")
        if sha256(source) != before["save"]["sha256"]:
            raise SaveError("source_changed", "Original changed before publication; retry on the newest save")
        output.parent.mkdir(parents=True, exist_ok=True)
        _publish(candidate, output)
        manifest_path = Path(str(output) + ".manifest.json")
        manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                    "source": str(source), "source_sha256": before["save"]["sha256"], "backup": str(backup),
                    "backup_sha256": sha256(backup), "output": str(output), "output_sha256": sha256(output),
                    "plan": plan, "diff": differences, "structural_valid": True,
                    "archive_checksum_valid": True, "game_load_validated": False}
        try:
            with manifest_path.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
        except OSError:
            output.unlink(missing_ok=True)
            raise
        return {"schema_version": 1, "capability": plan["capability"], "dry_run": False, "written": True,
                "output": str(output), "backup": str(backup), "manifest": str(manifest_path),
                "plan": plan, "diff": differences, "verification": {"structural_valid": True, "archive_checksum_valid": True, "game_load_validated": False},
                "original_unchanged": sha256(source) == before["save"]["sha256"]}


def rollback(manifest_path: Path, output: Path, backend: Backend | None = None) -> dict:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        backup = Path(manifest["backup"])
        expected = manifest["source_sha256"]
    except (OSError, ValueError, KeyError) as error:
        raise SaveError("invalid_manifest", "Invalid rollback manifest") from error
    output = output.expanduser().resolve()
    if output.exists() or output.suffix.lower() != ".lsv" or output == Path(manifest["source"]).resolve():
        raise SaveError("unsafe_output", "Rollback restores to a distinct, nonexistent .lsv")
    if not backup.is_file() or sha256(backup) != expected or manifest.get("backup_sha256") != expected:
        raise SaveError("backup_tampered", "Backup is missing or its digest differs")
    verification = verify(backup, backend, allow_failed_sanity=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    _publish(backup, output)
    if sha256(output) != expected:
        output.unlink(missing_ok=True)
        raise SaveError("backup_changed", "Backup changed during rollback; output was removed")
    return {"schema_version": 1, "capability": "SUPPORTED", "restored": True, "output": str(output),
            "sha256": sha256(output), "byte_identical_to_original": sha256(output) == expected, "verification": verification}
