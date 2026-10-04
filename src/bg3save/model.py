"""Extract only attributed evidence from LSLib-produced XML and typed facts."""
from __future__ import annotations

import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .errors import SaveError

UUID_SUFFIX = re.compile(r"(?P<uuid>[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})$")
ACT_REGIONS = {"WLD_Main_A": 1, "CRE_Main_A": 1, "UND_Main_A": 1, "SCL_Main_A": 2,
               "INT_Main_A": 3, "BGO_Main_A": 3, "CTY_Main_A": 3, "END_Main": 3}


def attrs(node) -> dict:
    return {a.get("id"): a.get("value", a.get("handle")) for a in node.findall("attribute")}


def known_bool(value):
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def read_xml(path: Path):
    try:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise SaveError("unsafe_xml", "Expected UTF-8 XML from LSLib") from error
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise SaveError("unsafe_xml", "External entities and DTDs are prohibited")
        return ET.fromstring(raw)
    except (ET.ParseError, OSError) as error:
        raise SaveError("invalid_resource", "Malformed LSLib XML resource", details=str(error)) from error


def flag_record(value, scope, *, owner=None):
    if not isinstance(value, str):
        return None
    match = UUID_SUFFIX.search(value)
    if not match:
        return None
    result = {"uuid": match["uuid"].lower(), "name": value[:match.start()].rstrip("_") or None,
              "value": value, "scope": scope, "source": f"DB_{scope.title()}Flag"}
    if owner is not None:
        result["owner"] = owner
    return result


def entity_uuid(value):
    match = UUID_SUFFIX.search(value) if isinstance(value, str) else None
    return match["uuid"].lower() if match else value


def normalize_story(export: dict) -> dict:
    databases = {}
    for db in export.get("databases", []):
        name = db["name"]
        record = {"columns": [p["name"] for p in db["parameter_types"]],
                  "rows": [[c["value"] for c in fact["columns"]] for fact in db["facts"]]}
        # Osiris can overload names. Retain separate schemas, never silently discard facts.
        key = name if name not in databases else f"{name}/{db['arity']}/{db['id']}"
        databases[key] = record
    return {"version": export.get("osiris_version"), "database_count": export.get("database_count"),
            "fact_count": export.get("fact_count"), "databases": databases}


def read_save_info(directory: Path) -> dict:
    path = directory / "SaveInfo.json"
    if not path.is_file():
        return {}
    try:
        info = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise SaveError("invalid_save_info", "Malformed SaveInfo.json") from error
    if not isinstance(info, dict):
        raise SaveError("invalid_save_info", "SaveInfo.json must contain an object")
    for field in ("Current Level", "Game Version", "Save Name"):
        if info.get(field) is not None and not isinstance(info[field], str):
            raise SaveError("invalid_save_info", f"SaveInfo.json/{field} must be a string or null")
    active_party = info.get("Active Party", {})
    if not isinstance(active_party, dict):
        raise SaveError("invalid_save_info", "SaveInfo.json/Active Party must be an object")
    characters = active_party.get("Characters", [])
    if not isinstance(characters, list) or any(not isinstance(c, dict) for c in characters):
        raise SaveError("invalid_save_info", "SaveInfo.json/Active Party/Characters must be a list of objects")
    for character in characters:
        if character.get("Origin") is not None and not isinstance(character["Origin"], str):
            raise SaveError("invalid_save_info", "SaveInfo.json character Origin must be a string or null")
        if "Classes" in character and not isinstance(character["Classes"], list):
            raise SaveError("invalid_save_info", "SaveInfo.json character Classes must be a list")
    return info


def parse_snapshot(directory: Path, metadata_xml: Path, globals_xml: Path | None,
                   story_export: dict | None) -> dict:
    root = read_xml(metadata_xml)
    metadata_node = root.find(".//region[@id='MetaData']/node/children/node")
    if metadata_node is None:
        raise SaveError("missing_metadata", "No MetaData node found")
    metadata = attrs(metadata_node)
    info = read_save_info(directory)
    region = info.get("Current Level") or metadata.get("Level") or metadata.get("LevelUniqueKey")
    versions = [attrs(n).get("Object") for n in root.findall(".//node[@id='GameVersion']")]
    mods = [attrs(n) for n in root.findall(".//node[@id='ModuleShortDesc']")]
    clients = [attrs(n) for n in root.findall(".//node[@id='ClientData']")]
    story = normalize_story(story_export) if story_export else {"version": None, "databases": {}, "fact_count": 0, "database_count": 0}
    dbs = story["databases"]
    flags = []
    for row in dbs.get("DB_GlobalFlag", {}).get("rows", []):
        if len(row) == 1 and (flag := flag_record(row[0], "global")):
            flags.append(flag)
    for row in dbs.get("DB_ObjectFlag", {}).get("rows", []):
        if len(row) == 2 and (flag := flag_record(row[1], "object", owner=row[0])):
            flags.append(flag)
    players = [row[0] for row in dbs.get("DB_Players", {}).get("rows", []) if len(row) == 1]
    members = [row[0] for row in dbs.get("DB_PartyMembers", {}).get("rows", []) if len(row) == 1]
    party = []
    for character in info.get("Active Party", {}).get("Characters", []):
        origin = character.get("Origin")
        matching = [value for value in members + players if isinstance(value, str) and origin and
                    re.search(rf"(?:^|_){re.escape(origin)}(?:_|$)", value, re.IGNORECASE)]
        party.append({"origin": origin, "id": next(iter(dict.fromkeys(matching)), None),
                      "level": character.get("Level"), "classes": character.get("Classes", []),
                      "race": character.get("Race"), "xp": character.get("Experience Points (Total)"),
                      "position": character.get("Position"), "subregion": character.get("Subregion"),
                      "source": "SaveInfo.json/Active Party"})
    journal = []
    if globals_xml is not None:
        globals_root = read_xml(globals_xml)
        journal_node = globals_root.find("region[@id='Journal']")
        if journal_node is not None:
            for progress in journal_node.iter("node"):
                if progress.get("id") != "QuestsProgress":
                    continue
                for quest in progress.iter("node"):
                    if quest.get("id") == "Quest":
                        state = attrs(quest)
                        journal.append({"id": attrs(progress).get("MapKey"), "objective_id": state.get("ObjectiveID"),
                                        "unlocked": known_bool(state.get("QuestUnlocked")),
                                        "disabled": known_bool(state.get("QuestDisabled")),
                                        "steps": [attrs(n).get("QuestUnlockedSteps") for n in quest.iter("node") if n.get("id") == "QuestUnlockedSteps"],
                                        "raw": state, "source": "Globals.lsf/Journal"})
    approvals = [{"character": r[0], "toward": r[1], "value": r[2], "source": "DB_ApprovalRating", "capability": "SUPPORTED"}
                 for r in dbs.get("DB_ApprovalRating", {}).get("rows", []) if len(r) == 3]
    romance = {name: {"source": name, "rows": dbs.get(name, {}).get("rows", []),
                      "interpretation": "Persisted Story facts; mods can alter vanilla relationship logic"}
               for name in ("DB_ORI_Dating", "DB_ORI_Partnered", "DB_ORI_Partnered_Secondary")}
    characters = list(party)
    referenced = set(players + members)
    for record in approvals:
        referenced.update((record["character"], record["toward"]))
    for facts in romance.values():
        for row in facts["rows"]:
            referenced.update(value for value in row if isinstance(value, str))
    known = {entity_uuid(character["id"]) for character in characters if character["id"]}
    for value in sorted(v for v in referenced if isinstance(v, str)):
        if not isinstance(value, str) or entity_uuid(value) in known:
            continue
        match = re.fullmatch(r"S_Player_(.+)_([0-9a-fA-F-]{36})", value)
        if match:
            characters.append({"origin": match[1], "id": value, "level": None, "classes": None,
                               "race": None, "xp": None, "source": "persisted player/approval/romance reference",
                               "state": "referenced; recruitment and current availability not inferred"})
            known.add(entity_uuid(value))
    deaths = [{"id": row[0], "dead": True, "source": "DB_Dead"}
              for row in dbs.get("DB_Dead", {}).get("rows", []) if len(row) == 1]
    warnings = ["Inventory/gold and full ECS character state are not decoded; unknown values are not zero.",
                "A missing Story flag or DB_Dead fact does not prove an event never happened or an NPC is alive."]
    if story_export is None:
        warnings.append("StorySave.bin missing; Story-dependent findings are unavailable.")
    return {"schema_version": 1, "capability": "SUPPORTED", "region": region,
            "act": ACT_REGIONS.get(region), "act_source": "region mapping" if region in ACT_REGIONS else "unknown",
            "game_version": info.get("Game Version") or (versions[-1] if versions else None),
            "game_versions": versions, "save_name": info.get("Save Name"), "metadata": metadata,
            "clients": clients, "mods": mods, "party": party, "characters": characters,
            "players": players, "party_members": members, "flags": sorted(flags, key=lambda f: (f["scope"], f["value"], str(f.get("owner")))),
            "journal": sorted(journal, key=lambda q: q["id"] or ""), "approval": approvals,
            "romance": romance, "npc_states": deaths, "story": story,
            "inventory": {"capability": "UNSUPPORTED", "value": None},
            "gold": {"capability": "UNSUPPORTED", "value": None}, "warnings": warnings}
