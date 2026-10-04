"""Deterministic, source-attributed analysis of a bounded set of BG3 content.

This is deliberately an evidence engine, not a claim of complete game coverage.
Missing flags and journal records are never evidence of completion or failure.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any

from .wiki import WikiClient, citation, utc_now


LIMITATIONS = [
    "Curated coverage only: twenty quest/event rules, not a complete BG3 checklist.",
    "A missing journal entry or flag is not proof of a task being unstarted, completed or permanently lost.",
    "QuestDisabled/COMPLETION can mean failure, automatic closure or success; explicit branch evidence is required.",
    "Historical story flags may survive resurrection or mods; contradictory observations require manual review.",
    "Actor death records are not inferred from DB_PermaDefeated, which can retain combat history after resurrection.",
    "Vanilla wiki conditions can differ under mods and game hotfixes. Verify unusual routes in the game.",
    "The analyzer does not infer elapsed rests from missing counters or assign a romance to a player without scope evidence.",
]


def load_rules() -> dict[str, Any]:
    return json.loads(resources.files("bg3save").joinpath("data/quests.json").read_text(encoding="utf-8"))


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("Name") or value.get("value") or value.get("id") or "")
    return str(value or "")


def _flag_name(value: str) -> str:
    # Symbol names can be followed by UUIDs in Osiris string identifiers.
    return re.sub(r"_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "", value, flags=re.I).casefold()


def _true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.casefold() in {"true", "1"})


def _act(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("value", value.get("act"))
    if isinstance(value, int) and not isinstance(value, bool) and value in {1, 2, 3}:
        return value
    if isinstance(value, str):
        folded = value.casefold().strip()
        for number, word in ((1, "one"), (2, "two"), (3, "three")):
            if folded in {str(number), f"act {number}", f"act {word}", f"act_{number}"}:
                return number
    return None


def _journal(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records = snapshot.get("journal", [])
    if isinstance(records, dict):
        return [{"id": key, **item} for key, items in records.items()
                for item in (items if isinstance(items, list) else [items]) if isinstance(item, dict)]
    return [item for item in records if isinstance(item, dict)]


class _EvidenceIndex:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.act = _act(snapshot.get("act"))
        self.region = _name(snapshot.get("region", ""))
        self.flags: dict[str, list[dict[str, Any]]] = {}
        for index, item in enumerate(snapshot.get("flags", [])):
            # Only normalized positive-set flags from the parser, never a flag catalog.
            if isinstance(item, dict) and item.get("set") is False:
                continue
            key = _flag_name(_name(item))
            self.flags.setdefault(key, []).append({"kind": "flag", "path": f"flags[{index}]", "value": deepcopy(item)})
        self.journal = _journal(snapshot)
        story = snapshot.get("story", {})
        self.databases = story.get("databases", snapshot.get("databases", {})) if isinstance(story, dict) else {}

    def named_flags(self, names: list[str]) -> list[dict[str, Any]]:
        return [item for name in names for item in self.flags.get(_flag_name(name), [])]

    def records(self, rule: dict[str, Any]) -> list[dict[str, Any]]:
        aliases = {name.casefold() for name in rule.get("journal_ids", [])}
        result = []
        for index, item in enumerate(self.journal):
            identity = str(item.get("id", item.get("quest_id", item.get("quest", ""))))
            if identity.casefold() in aliases:
                result.append({"kind": "journal", "path": f"journal[{index}]", "value": item})
        return result

    def steps(self, records: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
        wanted = {name.casefold() for name in names}
        result = []
        for record in records:
            item = record["value"]
            for step in item.get("steps", item.get("unlocked_steps", [])):
                label = _name(step)
                if label.casefold() in wanted:
                    result.append({"kind": "journal_step", "path": record["path"] + ".steps",
                                   "quest_id": item.get("id", item.get("quest_id")), "value": label})
        return result

    def dead_npcs(self, patterns: list[str]) -> list[dict[str, Any]]:
        result = []
        for db_name, database in self.databases.items():
            if db_name.split("(")[0] != "DB_Dead":
                continue
            rows = database.get("rows", []) if isinstance(database, dict) else []
            for index, row in enumerate(rows):
                cells = row.values() if isinstance(row, dict) else row if isinstance(row, (list, tuple)) else [row]
                for cell in cells:
                    label = _name(cell)
                    if any(label.startswith(pattern) for pattern in patterns):
                        result.append({"kind": "npc_death", "path": f"story.databases.{db_name}.rows[{index}]", "value": label})
        for index, character in enumerate(self.snapshot.get("characters", [])):
            if not isinstance(character, dict):
                continue
            label = _name(character.get("story_id", character.get("id", character)))
            if character.get("dead", character.get("is_dead")) is True and any(label.startswith(pattern) for pattern in patterns):
                result.append({"kind": "npc_death", "path": f"characters[{index}].dead", "value": label})
        return result

    def relationships(self, database_name: str, companion_symbol: str, companion_uuid: str) -> list[dict[str, Any]]:
        result = []
        for db_name, database in self.databases.items():
            if db_name.split("(")[0] != database_name or not isinstance(database, dict):
                continue
            for index, row in enumerate(database.get("rows", [])):
                cells = list(row.values()) if isinstance(row, dict) else list(row) if isinstance(row, (list, tuple)) else []
                if len(cells) >= 2 and (companion_symbol.casefold() in _name(cells[1]).casefold() or _name(cells[1]).casefold() == companion_uuid.casefold()):
                    result.append({"kind": "romance_relationship", "path": f"story.databases.{db_name}.rows[{index}]",
                                   "player": _name(cells[0]), "companion": _name(cells[1]), "value": deepcopy(row)})
        return result

    @staticmethod
    def active(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [record for record in records if
                _true(record["value"].get("unlocked", record["value"].get("QuestUnlocked")))
                and not _true(record["value"].get("disabled", record["value"].get("QuestDisabled")))
                and "completion" not in str(record["value"].get("objective_id", record["value"].get("ObjectiveID", ""))).casefold()]

    @staticmethod
    def closed(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [record for record in records if
                _true(record["value"].get("disabled", record["value"].get("QuestDisabled")))
                or _true(record["value"].get("completed"))
                or "completion" in str(record["value"].get("objective_id", record["value"].get("ObjectiveID", ""))).casefold()]


def _deduplicate(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in evidence:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _special(rule: dict[str, Any], index: _EvidenceIndex) -> tuple[str, str, list[dict[str, Any]], list[str]] | None:
    if rule.get("special") == "masked_victims":
        deaths = index.dead_npcs(["S_HAG_Hag_MaskedVictim"])
        spared = index.named_flags(rule.get("blocked_flags", []))
        if deaths:
            return "missed", "Victim death is recorded; the ordinary survivor dialogue is unavailable for those actors.", deaths + spared, ["The count and identities of recorded dead victims appear in evidence; no claim is made that all four died."]
        if spared:
            return "blocked", "Ethel's mercy outcome is recorded. Under the vanilla route, keeping her alive does not liberate the masks.", spared, ["Revived/neutral actors can coexist with this story outcome. Survival is not proof of complete liberation."]
    if rule.get("special") == "karlach_romance":
        partnered_rows = index.relationships("DB_ORI_Partnered", "S_Player_Karlach_", "2c76687d-93a2-477b-8b18-8a14b549304c")
        dating_rows = index.relationships("DB_ORI_Dating", "S_Player_Karlach_", "2c76687d-93a2-477b-8b18-8a14b549304c")
        partnered = index.named_flags(rule.get("partnered_flags", []))
        dating = index.named_flags(rule.get("dating_flags", []))
        ended = index.named_flags(rule.get("ended_flags", []))
        if partnered_rows:
            return "in_progress", "An explicit player-to-Karlach partnership database row is observed; later scenes still require separate evidence.", partnered_rows + partnered, ["The relationship evidence retains the player and companion identifiers rather than assigning it to an assumed host."]
        if dating_rows:
            return "in_progress", "An explicit player-to-Karlach dating database row is observed; later engine and relationship stages are not proved.", dating_rows + dating, ["The relationship evidence retains the player and companion identifiers rather than assigning it to an assumed host."]
        if partnered:
            return "in_progress", "A Karlach partnership flag is observed; it does not prove later romance scenes are complete.", partnered, ["Read flag scope/player identity before assigning this relationship to a specific player."]
        if dating:
            return "in_progress", "A Karlach dating flag is observed; later engine and romance stages still need separate evidence.", dating, ["Read flag scope/player identity before assigning this relationship to a specific player."]
        if ended:
            return "unknown", "A historical Karlach partnership flag is observed, without a confirmed current relationship stage.", ended, ["WasPartnered is historical and is not used alone as a definitive current breakup verdict."]
        if index.act in {2, 3}:
            return "unknown", "No current Karlach relationship stage is established. The ordinary initiation is in Act One, while later progression depends on an earlier relationship.", [{"kind": "act", "path": "act", "value": index.act}], ["Missing romance records cannot prove a permanent loss, but do not imply a new vanilla romance can be initiated in this act."]
    return None


def _evaluate(rule: dict[str, Any], index: _EvidenceIndex) -> dict[str, Any]:
    records = index.records(rule)
    completed = index.steps(records, rule.get("complete_steps", [])) + index.named_flags(rule.get("complete_flags", []))
    failed = index.steps(records, rule.get("failed_steps", [])) + index.named_flags(rule.get("failed_flags", [])) + index.dead_npcs(rule.get("dead_npc_patterns", []))
    branches = index.steps(records, rule.get("branch_steps", []))
    active, closed = index.active(records), index.closed(records)
    cautions = list(rule.get("cautions", []))
    confidence = "medium"
    special = _special(rule, index)
    if completed and failed:
        status, reason, evidence = "unknown", "Successful and adverse evidence coexist; inspect the exact branch and chronology.", completed + failed
        cautions.append("Contradictory evidence is not resolved by assuming one flag overrides another.")
        confidence = "low"
    elif completed and active and rule.get("completion_scope") != "stage":
        status, reason, evidence = "in_progress", "A successful sub-objective is observed, while the journal still explicitly lists an active objective.", completed + active
        confidence = "high"
        cautions.append("Do not treat a rescued NPC or obtained reward alone as completion of every remaining quest step.")
    elif completed:
        status, reason, evidence = "completed", "A recognized successful/resolved branch step or flag is explicitly present.", completed
        confidence = "high"
    elif failed:
        status, reason, evidence = "missed", "A recognized failure branch or relevant NPC death is explicitly present.", failed
        confidence = "high"
    elif special:
        status, reason, evidence, extra = special
        cautions.extend(extra)
        confidence = "high" if status != "unknown" else "low"
    elif branches:
        status, reason, evidence = "mutually_exclusive", "An observed branch choice closes the alternative listed below.", branches
        confidence = "high"
    elif closed:
        status, reason, evidence = "resolved", "The journal is closed, but no curated step proves whether it succeeded, failed or auto-resolved.", closed
        confidence = "low"
    elif index.act is not None and index.act < min(rule["acts"]):
        status, reason, evidence = "not_yet_available", "The save is in an earlier act than this content's ordinary trigger.", [{"kind": "act", "path": "act", "value": index.act}]
    elif index.act is not None and index.act > rule.get("deadline_after_act", 99):
        if active:
            status, reason, evidence = "missed", "The save has passed the documented last act for an explicitly active, unresolved quest.", active + [{"kind": "act", "path": "act", "value": index.act}]
        else:
            status, reason, evidence = "unknown", "The ordinary deadline is past, but missing completion records cannot prove the content was missed.", [{"kind": "act", "path": "act", "value": index.act}]
            confidence = "low"
    elif index.region in rule.get("region_deadlines", []):
        status, reason, evidence = "unknown", "The current map proves a documented story-transition boundary has been crossed, but the exact earlier branch outcome is not established.", records + [{"kind": "region_cutoff", "path": "region", "value": index.region}]
        confidence = "low"
        cautions.append("Mountain Pass remains Act One while advancing this encounter. Check its saved terminal outcome; the original rescue/investigation route may no longer be available.")
    elif active:
        status, reason, evidence = "in_progress", "The journal contains an explicitly active objective.", active
        confidence = "high"
    elif records:
        status, reason, evidence = "unknown", "Journal evidence is present, but does not establish an active or terminal state.", records
        confidence = "low"
    elif index.act in rule["acts"]:
        status, reason, evidence = "possibly_available", "The act fits the ordinary route. Missing records do not prove the quest is unstarted or all prerequisites still hold.", [{"kind": "act", "path": "act", "value": index.act}]
        confidence = "low"
    else:
        status, reason, evidence = "unknown", "Insufficient reliable save evidence to determine availability or outcome.", []
        confidence = "low"
    waiting = index.steps(records, rule.get("waiting_steps", []))
    next_action = rule["trigger"]
    if waiting and index.act == 1:
        next_action = "The first upgrade is recorded; continue to Act Two and return to Dammon for the next stage."
        cautions.append("Observed WaitForNextAct is a progression gate, not a missed step.")
        evidence.extend(waiting)
    if status in {"completed", "resolved", "missed", "blocked", "mutually_exclusive"}:
        next_action = "Review the observed outcome and the cited branch conditions before attempting any repair."
    if any(item["kind"] == "region_cutoff" for item in evidence):
        next_action = "Inspect the saved grove/fire outcome and linked transition conditions before returning; do not assume the original encounter remains available."
    return {
        "id": rule["id"], "quest": rule["quest"], "quest_zh": rule.get("quest_zh"),
        "status": status, "reason": reason, "confidence": confidence, "evidence": _deduplicate(evidence),
        "act": rule["acts"], "location": rule["location"], "npc": rule["npc"], "trigger": rule["trigger"],
        "prerequisites": rule["prerequisites"], "missable": rule.get("missable", False),
        "recommended_before": rule["recommended_before"], "priority": rule["priority"],
        "mutually_exclusive": rule.get("mutually_exclusive", []), "next_action": next_action,
        "cautions": cautions, "sources": [], "capability": "EXPERIMENTAL",
    }


def analyze_content(snapshot: dict[str, Any], *, online: bool = True,
                    cache_dir: str | Path | None = None, wiki_client: WikiClient | None = None,
                    rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Combine positive save evidence with curated rules and current source checks."""
    database = rules or load_rules()
    index = _EvidenceIndex(snapshot)
    client = wiki_client or WikiClient(cache_dir, online=online)
    urls = [source["url"] for rule in database["rules"] for source in rule["sources"]]
    downloaded = client.retrieve_many(urls)
    results = []
    warnings = []
    mods = snapshot.get("mods", snapshot.get("modules", []))
    modified_romance = any("polyamory" in _name(mod).casefold() or "romance" in _name(mod).casefold() for mod in mods)
    for rule in database["rules"]:
        result = _evaluate(rule, index)
        result["sources"] = [citation(downloaded[source["url"]], source.get("markers", []), database["reviewed_at"]) for source in rule["sources"]]
        checked = all(source["freshness"] in {"live", "cached_recent"} and source["supports_rule_markers"] for source in result["sources"])
        result["source_freshness"] = "checked" if checked else "unverified"
        if not checked:
            if result["confidence"] == "high":
                result["confidence"] = "medium"
            result["cautions"].append("The external rules were not verified against fresh source text in this run; consult the attributed page before treating a gameplay inference as definitive.")
        if modified_romance and rule["id"] == "karlach_romance":
            result["cautions"].append("A romance/polyamory module is present in the save; vanilla relationship restrictions may not apply.")
            if result["confidence"] == "high":
                result["confidence"] = "medium"
        results.append(result)
    unverified = sum(result["source_freshness"] != "checked" for result in results)
    if unverified:
        warnings.append(f"{unverified} rules have unverified/stale/offline source text; confidence is reduced where applicable.")
    if index.act is None:
        warnings.append("Current act is unknown; no act-based availability or permanent cutoff is inferred.")
    return {
        "schema_version": 1, "capability": "EXPERIMENTAL", "generated_at": utc_now(),
        "coverage": {"rules": len(results), "complete_game_coverage": False, "rules_reviewed_at": database["reviewed_at"]},
        "source_mode": "online" if client.online else "offline", "act": index.act, "region": index.region,
        "summary": dict(Counter(result["status"] for result in results)), "quests": results,
        "possible_missed_content": [result for result in results if result["status"] in {"possibly_available", "in_progress", "missed", "blocked", "mutually_exclusive", "unknown"}],
        "warnings": warnings, "limitations": LIMITATIONS,
    }


analyze_quests = analyze_content
