"""Model/CLI regression scenarios built only from invented UUIDs and XML."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bg3save.cli import main
from bg3save.content import analyze_content
from bg3save.errors import SaveError
from bg3save.model import entity_uuid, known_bool, normalize_story, parse_snapshot, read_xml


PLAYER = "11111111-1111-4111-8111-111111111111"
COMPANION = "22222222-2222-4222-8222-222222222222"
OTHER_PLAYER = "33333333-3333-4333-8333-333333333333"
NPC = "44444444-4444-4444-8444-444444444444"
GLOBAL_FLAG = "55555555-5555-4555-8555-555555555555"
OBJECT_FLAG = "66666666-6666-4666-8666-666666666666"
REGISTERED_FLAG = "77777777-7777-4777-8777-777777777777"
NAMED_PLAYER = f"S_Player_Gale_{PLAYER}"
NAMED_COMPANION = f"S_Player_FixtureCompanion_{COMPANION}"
NAMED_OTHER_PLAYER = f"S_Player_FixtureOtherPlayer_{OTHER_PLAYER}"
NAMED_NPC = f"S_NPC_FixtureVendor_{NPC}"

META_XML = '''<?xml version="1.0" encoding="utf-8"?>
<save>
  <region id="MetaData"><node id="root"><children><node id="MetaData">
    <attribute id="Level" type="FixedString" value="WLD_Main_A" />
    <attribute id="SaveGameName" type="LSString" value="Invented fixture" />
    <children><node id="ModuleShortDesc">
      <attribute id="Name" type="LSString" value="PolyamoryFixes" />
      <attribute id="Folder" type="LSString" value="FixtureModule" />
    </node></children>
  </node></children></node></region>
</save>'''

JOURNAL_XML = '''<?xml version="1.0" encoding="utf-8"?>
<save><region id="Journal"><node id="root"><children>
  <node id="QuestsProgress">
    <attribute id="MapKey" type="FixedString" value="DEN_Conflict" />
    <children><node id="Quest">
      <attribute id="QuestUnlocked" type="bool" value="True" />
      <attribute id="QuestDisabled" type="bool" value="True" />
      <attribute id="ObjectiveID" type="FixedString" value="DEN_Conflict_FixtureObjective" />
      <children><node id="QuestUnlockedSteps">
        <attribute id="QuestUnlockedSteps" type="FixedString" value="FixtureObservedStep" />
      </node></children>
    </node></children>
  </node>
</children></node></region></save>'''


def exported_database(name, rows, *, arity=None, database_id=1):
    arity = arity if arity is not None else len(rows[0]) if rows else 1
    return {"name": name, "arity": arity, "id": database_id,
            "parameter_types": [{"name": "GUIDSTRING"} for _ in range(arity)],
            "facts": [{"columns": [{"value": value} for value in row]} for row in rows]}


def exported_story(databases):
    return {"osiris_version": "synthetic-1.15", "databases": databases,
            "database_count": len(databases), "fact_count": sum(len(d["facts"]) for d in databases)}


class ModelShapeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bg3-model-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.metadata = self.directory / "meta.lsx"
        self.globals = self.directory / "globals.lsx"
        self.metadata.write_text(META_XML, encoding="utf-8")
        self.globals.write_text(JOURNAL_XML, encoding="utf-8")
        info = {"Current Level": "WLD_Main_A", "Save Name": "Invented fixture",
                "Active Party": {"Characters": [{"Origin": "Gale", "Level": 4,
                  "Classes": [{"Class": "Wizard", "Level": 4}], "Race": "Human",
                  "Experience Points (Total)": 1234}]}}
        (self.directory / "SaveInfo.json").write_text(json.dumps(info), encoding="utf-8")

    def snapshot(self, databases=None):
        return parse_snapshot(self.directory, self.metadata, self.globals,
                              exported_story(databases or [exported_database("DB_Players", [[NAMED_PLAYER]])]))

    def test_journal_disabled_is_independent_of_completion_objective_suffix(self):
        snapshot = self.snapshot()
        journal = snapshot["journal"][0]
        self.assertTrue(journal["unlocked"])
        self.assertTrue(journal["disabled"])
        self.assertNotIn("COMPLETION", journal["objective_id"])
        self.assertEqual(journal["steps"], ["FixtureObservedStep"])
        self.assertEqual(journal["raw"]["QuestDisabled"], "True")
        report = analyze_content(snapshot, online=False, cache_dir=self.directory / "offline-cache")
        grove = next(q for q in report["quests"] if q["id"] == "save_refugees")
        self.assertEqual(grove["status"], "resolved")
        self.assertNotEqual(grove["status"], "completed")

    def test_flag_catalogs_are_retained_as_raw_facts_not_active_flags(self):
        databases = [
            exported_database("DB_Players", [[NAMED_PLAYER]]),
            exported_database("DB_GlobalFlag", [[f"FixtureObservedGlobal_{GLOBAL_FLAG}"]]),
            exported_database("DB_ObjectFlag", [[NAMED_PLAYER, f"FixtureObservedObject_{OBJECT_FLAG}"]]),
            exported_database("DB_Debug_ActFlag", [[1, f"FixtureRegisteredGlobal_{REGISTERED_FLAG}"]]),
            exported_database("DB_DeadStateFlag", [[NAMED_NPC, f"FixtureRegisteredDead_{REGISTERED_FLAG}"]]),
        ]
        snapshot = self.snapshot(databases)
        self.assertEqual({f["uuid"] for f in snapshot["flags"]}, {GLOBAL_FLAG, OBJECT_FLAG})
        self.assertEqual({f["scope"] for f in snapshot["flags"]}, {"global", "object"})
        self.assertNotIn(REGISTERED_FLAG, {f["uuid"] for f in snapshot["flags"]})
        self.assertIn("DB_Debug_ActFlag", snapshot["story"]["databases"])
        self.assertEqual(snapshot["npc_states"], [])
        object_flag = next(f for f in snapshot["flags"] if f["scope"] == "object")
        self.assertEqual(object_flag["owner"], NAMED_PLAYER)
        self.assertEqual(object_flag["source"], "DB_ObjectFlag")

    def test_missing_journal_booleans_remain_unknown_instead_of_false(self):
        missing = JOURNAL_XML.replace('<attribute id="QuestUnlocked" type="bool" value="True" />', "")
        missing = missing.replace('<attribute id="QuestDisabled" type="bool" value="True" />', "")
        self.globals.write_text(missing, encoding="utf-8")
        snapshot = self.snapshot()
        self.assertIsNone(snapshot["journal"][0]["unlocked"])
        self.assertIsNone(snapshot["journal"][0]["disabled"])
        report = analyze_content(snapshot, online=False, cache_dir=self.directory / "offline-cache")
        grove = next(q for q in report["quests"] if q["id"] == "save_refugees")
        self.assertEqual(grove["status"], "unknown")

    def test_boolean_unknown_and_false_are_distinct(self):
        self.assertIsNone(known_bool(None))
        self.assertIsNone(known_bool("FixtureUnexpectedValue"))
        self.assertIs(known_bool("False"), False)
        self.assertIs(known_bool("True"), True)

    def test_actor_references_do_not_claim_recruitment_or_full_stats(self):
        snapshot = self.snapshot([
            exported_database("DB_Players", [[NAMED_PLAYER]]),
            exported_database("DB_ApprovalRating", [[NAMED_COMPANION, NAMED_PLAYER, 17], [NAMED_NPC, NAMED_PLAYER, 5]]),
            exported_database("DB_ORI_Dating", [[PLAYER, NAMED_COMPANION]]),
        ])
        self.assertEqual(len(snapshot["party"]), 1)
        self.assertEqual(snapshot["party"][0]["origin"], "Gale")
        referenced = next(c for c in snapshot["characters"] if c["id"] == NAMED_COMPANION)
        for field in ("level", "classes", "race", "xp"):
            self.assertIsNone(referenced[field])
        self.assertIn("recruitment and current availability not inferred", referenced["state"])
        self.assertNotIn("recruited", referenced)
        self.assertNotIn("alive", referenced)
        self.assertNotIn(NAMED_NPC, {c["id"] for c in snapshot["characters"]})
        self.assertEqual(snapshot["inventory"]["capability"], "UNSUPPORTED")
        self.assertIsNone(snapshot["gold"]["value"])

    def test_named_and_bare_uuid_references_do_not_duplicate_active_party_character(self):
        snapshot = self.snapshot([
            exported_database("DB_Players", [[NAMED_PLAYER]]),
            exported_database("DB_ORI_Dating", [[PLAYER, NAMED_COMPANION], [NAMED_PLAYER.upper(), NAMED_OTHER_PLAYER]]),
        ])
        matches = [c for c in snapshot["characters"] if entity_uuid(c["id"]) == PLAYER]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["level"], 4)
        self.assertEqual(matches[0]["classes"], [{"Class": "Wizard", "Level": 4}])

    def test_nullable_story_references_do_not_fail_sorting_or_claim_recruitment(self):
        snapshot = self.snapshot([
            exported_database("DB_Players", [[NAMED_PLAYER], [None]]),
            exported_database("DB_ApprovalRating", [[NAMED_COMPANION, None, 9]]),
        ])
        referenced = next(c for c in snapshot["characters"] if c["id"] == NAMED_COMPANION)
        self.assertIsNone(referenced["level"])
        self.assertNotIn("recruited", referenced)

    def test_approval_direction_and_module_attribute_case_are_preserved(self):
        snapshot = self.snapshot([
            exported_database("DB_Players", [[NAMED_PLAYER]]),
            exported_database("DB_ApprovalRating", [[NAMED_COMPANION, NAMED_PLAYER, 27]]),
        ])
        self.assertEqual(snapshot["approval"][0]["character"], NAMED_COMPANION)
        self.assertEqual(snapshot["approval"][0]["toward"], NAMED_PLAYER)
        self.assertEqual(snapshot["approval"][0]["value"], 27)
        self.assertEqual(snapshot["mods"][0]["Name"], "PolyamoryFixes")
        self.assertEqual(snapshot["mods"][0]["Folder"], "FixtureModule")

    def test_current_death_database_does_not_mix_in_defeat_history(self):
        snapshot = self.snapshot([
            exported_database("DB_Players", [[NAMED_PLAYER]]),
            exported_database("DB_Dead", [[NAMED_NPC]]),
            exported_database("DB_PermaDefeated", [[NAMED_COMPANION]]),
        ])
        self.assertEqual(snapshot["npc_states"], [{"id": NAMED_NPC, "dead": True, "source": "DB_Dead"}])

    def test_unknown_modded_region_remains_unknown_act(self):
        (self.directory / "SaveInfo.json").write_text(json.dumps({"Current Level": "FixtureModdedLevel"}), encoding="utf-8")
        snapshot = self.snapshot()
        self.assertIsNone(snapshot["act"])
        self.assertEqual(snapshot["act_source"], "unknown")
        self.assertEqual(snapshot["region"], "FixtureModdedLevel")

    def test_missing_story_save_reports_unavailable_instead_of_zero_inventory(self):
        snapshot = parse_snapshot(self.directory, self.metadata, self.globals, None)
        self.assertEqual(snapshot["flags"], [])
        self.assertEqual(snapshot["romance"]["DB_ORI_Dating"]["rows"], [])
        self.assertTrue(any("StorySave.bin missing" in warning for warning in snapshot["warnings"]))
        self.assertIsNone(snapshot["gold"]["value"])

    def test_xml_external_entities_are_rejected(self):
        self.globals.write_text('<?xml version="1.0"?><!DOCTYPE save [<!ENTITY test SYSTEM "file:///fictional">]><save>&test;</save>', encoding="utf-8")
        with self.assertRaises(SaveError) as caught:
            read_xml(self.globals)
        self.assertEqual(caught.exception.code, "unsafe_xml")

    def test_overloaded_story_schemas_retain_both_sets_of_facts(self):
        result = normalize_story(exported_story([
            exported_database("DB_FixtureOverload", [[1]], database_id=1),
            exported_database("DB_FixtureOverload", [[2, 3]], database_id=2),
        ]))
        self.assertEqual(result["databases"]["DB_FixtureOverload"]["rows"], [[1]])
        self.assertEqual(result["databases"]["DB_FixtureOverload/2/2"]["rows"], [[2, 3]])

    def test_character_cli_matches_relationship_uuid_aliases_without_inverting_approval(self):
        snapshot = self.snapshot([
            exported_database("DB_Players", [[NAMED_PLAYER]]),
            exported_database("DB_ApprovalRating", [[NAMED_COMPANION, PLAYER, 33]]),
            exported_database("DB_ORI_Dating", [[PLAYER, NAMED_COMPANION], [NAMED_PLAYER.upper(), NAMED_OTHER_PLAYER], [OTHER_PLAYER, NAMED_COMPANION]]),
            exported_database("DB_ORI_Partnered", [[NAMED_PLAYER, NAMED_COMPANION]]),
        ])
        for query in ("Gale", NAMED_PLAYER, PLAYER):
            with self.subTest(query=query), patch("bg3save.cli.Backend"), patch("bg3save.cli.service.inspect", return_value=snapshot):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["character", "fictional.lsv", query, "--json"])
                payload = json.loads(output.getvalue())
                self.assertEqual(code, 0, payload)
                self.assertEqual(len(payload["romance"]["DB_ORI_Dating"]), 2)
                self.assertEqual(payload["romance"]["DB_ORI_Partnered"], [[NAMED_PLAYER, NAMED_COMPANION]])
                self.assertEqual(payload["approval"][0]["character"], NAMED_COMPANION)
                self.assertEqual(payload["approval"][0]["toward"], PLAYER)


if __name__ == "__main__":
    unittest.main()
