"""Synthetic quest scenarios. No copyrighted game save or private state fixture."""
from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from email.message import Message
from unittest.mock import patch

from bg3save.content import analyze_content, load_rules
from bg3save.wiki import WikiClient, citation, page_text, validate_url


class _Sources:
    def __init__(self, *, current=True, missing_url=None):
        self.online = current
        self.current = current
        self.missing_url = missing_url

    def retrieve_many(self, urls):
        # Construct synthetic page text from rule anchors, not copied wiki prose.
        markers = {}
        for rule in load_rules()["rules"]:
            for source in rule["sources"]:
                markers.setdefault(source["url"], set()).update(source["markers"])
        return {url: {"url": url, "resolved_url": url, "retrieved_at": "2026-10-04T00:00:00+00:00",
                      "sha256": "a" * 64, "page_revision": "synthetic",
                      "freshness": "live" if self.current else "offline_no_cache",
                      "network_checked_this_run": self.current,
                      "text": " | ".join(markers[url]) if self.current and url != self.missing_url else ""}
                for url in set(urls)}


def report(snapshot, **kwargs):
    return analyze_content(snapshot, wiki_client=kwargs.pop("wiki_client", _Sources()), **kwargs)


def quest(result, quest_id):
    return next(item for item in result["quests"] if item["id"] == quest_id)


class ContentEvidenceTests(unittest.TestCase):
    def test_absence_is_not_completion_or_permanent_loss(self):
        first_act = report({"act": 1, "flags": [], "journal": []})
        self.assertEqual(quest(first_act, "investigate_beach")["status"], "possibly_available")
        later_act = report({"act": 3, "flags": [], "journal": []})
        self.assertEqual(quest(later_act, "investigate_beach")["status"], "unknown")
        self.assertNotIn("completed", later_act["summary"])
        self.assertNotIn("missed", later_act["summary"])

    def test_successful_journal_branch_is_completed(self):
        result = report({"act": 1, "journal": [{"id": "DEN_SnakeCourt", "steps": ["KidFreed", "ParentThankful"], "objective_id": "DEN_SnakeCourt_COMPLETION"}]})
        arabella = quest(result, "save_arabella")
        self.assertEqual((arabella["status"], arabella["confidence"]), ("completed", "high"))
        self.assertEqual(arabella["evidence"][0]["kind"], "journal_step")
        self.assertTrue(arabella["sources"][0]["supports_rule_markers"])

    def test_closed_journal_is_not_success(self):
        result = report({"act": 1, "journal": [{"id": "DEN_Conflict", "objective_id": "DEN_Conflict_COMPLETION", "steps": [], "disabled": True}]})
        self.assertEqual(quest(result, "save_refugees")["status"], "resolved")
        self.assertEqual(quest(result, "save_refugees")["confidence"], "low")

    def test_patch8_kagha_journal_alias_successful_fight_is_resolved(self):
        result = report({"act": 1, "journal": [{"id": "DEN_Conflict_SUB_Ritual",
                         "unlocked": True, "disabled": True,
                         "objective_id": "DEN_Conflict_SUB_Ritual_COMPLETION",
                         "steps": ["FoundNote", "FoundLetterAfterNote", "FightGood", "RitualStopped", "FightEndedGood"]}]})
        item = quest(result, "investigate_kagha")
        self.assertEqual((item["status"], item["confidence"]), ("completed", "high"))
        self.assertEqual(item["evidence"][0]["value"], "FightEndedGood")

    def test_patch8_kagha_note_alone_is_active_investigation(self):
        result = report({"act": 1, "journal": [{"id": "DEN_Conflict_SUB_Ritual",
                         "unlocked": True, "disabled": False, "steps": ["FoundNote"]}]})
        self.assertEqual(quest(result, "investigate_kagha")["status"], "in_progress")

    def test_beach_already_met_mol_hint_does_not_prove_terminal_success(self):
        result = report({"act": 1, "journal": [{"id": "DEN_HarpyMeal", "unlocked": True,
                         "disabled": True, "objective_id": "DEN_HarpyMeal_COMPLETION",
                         "steps": ["DefeatedHarpies", "ToldDragonLair_MetMol", "MolGone"]}]})
        self.assertEqual(quest(result, "investigate_beach")["status"], "resolved")

    def test_beach_harpies_defeated_alone_does_not_prove_mol_followup(self):
        result = report({"act": 1, "journal": [{"id": "DEN_HarpyMeal", "unlocked": True,
                         "disabled": False, "steps": ["DefeatedHarpies"]}]})
        self.assertEqual(quest(result, "investigate_beach")["status"], "in_progress")

    def test_rescued_arabella_with_active_parent_objective_is_not_full_completion(self):
        result = report({"act": 1, "journal": [{"id": "DEN_SnakeCourt", "unlocked": True,
                         "objective_id": "DEN_SnakeCourt_ReturnParents", "steps": ["KidFreed"]}]})
        self.assertEqual(quest(result, "save_arabella")["status"], "in_progress")

    def test_florrick_fire_stage_does_not_wait_for_whole_grand_duke_quest(self):
        result = report({"act": 1, "journal": [{"id": "PLA_GrandDukeRescue", "unlocked": True,
                         "objective_id": "PLA_GrandDukeRescue_SearchGrandDuke", "steps": ["FreedCounsellor"]}]})
        self.assertEqual(quest(result, "waukeen_florrick")["status"], "completed")
        self.assertEqual(quest(result, "grand_duke")["status"], "in_progress")

    def test_positive_failed_branch_is_not_completed(self):
        result = report({"act": 1, "journal": [{"id": "PLA_StuckHalfElf", "steps": ["Dead"], "disabled": True}]})
        self.assertEqual(quest(result, "trapped_man")["status"], "missed")

    def test_positive_flag_can_include_uuid_suffix_and_scope(self):
        result = report({"act": 1, "flags": [{"name": "DEN_HarpyMeal_State_VictimDead_50cfd9b3-bf92-e441-e166-1466dcf1e185", "scope": "npc", "uuid": "50cfd9b3-bf92-e441-e166-1466dcf1e185"}]})
        item = quest(result, "investigate_beach")
        self.assertEqual(item["status"], "missed")
        self.assertEqual(item["evidence"][0]["value"]["scope"], "npc")

    def test_registered_flags_never_count_as_positive_set(self):
        result = report({"act": 1, "registered_flags": [{"name": "DEN_HarpyMeal_State_VictimDead"}], "flags": [{"name": "DEN_HarpyMeal_State_VictimDead", "set": False}]})
        self.assertEqual(quest(result, "investigate_beach")["status"], "possibly_available")

    def test_unknown_act_never_infers_cutoff(self):
        result = report({"region": "UnrecognizedModRegion", "journal": []})
        self.assertEqual(quest(result, "investigate_beach")["status"], "unknown")
        self.assertTrue(any("act is unknown" in warning for warning in result["warnings"]))

    def test_active_quest_after_real_act_deadline_has_cutoff_evidence(self):
        result = report({"act": 3, "journal": [{"id": "FOR_IncompleteMasterwork", "unlocked": True, "steps": ["FindPlansBeforeJournal"]}]})
        item = quest(result, "masterwork_weapon")
        self.assertEqual(item["status"], "missed")
        self.assertEqual({e["kind"] for e in item["evidence"]}, {"act", "journal"})

    def test_mountain_pass_is_not_act_two_inference(self):
        # The transition is within Act One; no flag-free permanent failure claim.
        result = report({"act": 1, "region": "CRE_Main_A", "journal": []})
        self.assertEqual(quest(result, "save_refugees")["status"], "unknown")
        self.assertIn("Mountain Pass", " ".join(quest(result, "save_refugees")["cautions"]))

    def test_same_act_region_transition_changes_active_rescue_advice(self):
        snapshot = {"act": 1, "region": "WLD_Main_A", "journal": [{"id": "DEN_Conflict", "unlocked": True, "steps": ["MetZevlor"]}]}
        before = quest(report(snapshot), "save_refugees")
        after = quest(report({**snapshot, "region": "CRE_Main_A"}), "save_refugees")
        self.assertEqual(before["status"], "in_progress")
        self.assertEqual(after["status"], "unknown")
        self.assertEqual(after["confidence"], "low")
        self.assertTrue(any(item["kind"] == "region_cutoff" for item in after["evidence"]))
        self.assertIn("do not assume", after["next_action"])

    def test_conflicting_branch_evidence_requires_review(self):
        result = report({"act": 1, "journal": [{"id": "DEN_HarpyMeal", "steps": ["ChildSaved", "ChildDead"]}]})
        item = quest(result, "investigate_beach")
        self.assertEqual((item["status"], item["confidence"]), ("unknown", "low"))

    def test_hag_mercy_and_repaired_alive_masks_do_not_claim_liberation(self):
        result = report({"act": 1, "flags": [{"name": "HAG_Hag_State_HagGivenMercy", "scope": "global"}],
                         "characters": [{"id": "S_HAG_Hag_MaskedVictim1_synthetic", "dead": False}],
                         "story": {"databases": {"DB_PermaDefeated": {"rows": [["S_HAG_Hag_MaskedVictim1_synthetic"]]}}}})
        item = quest(result, "ethel_mask_victims")
        self.assertEqual(item["status"], "blocked")
        self.assertEqual(len(item["sources"]), 2)
        self.assertTrue(all(source["supports_rule_markers"] for source in item["sources"]))

    def test_actual_dead_record_is_distinct_from_defeat_history(self):
        result = report({"act": 1, "story": {"databases": {"DB_Dead": {"columns": ["CHARACTERGUID"], "rows": [["S_HAG_Hag_MaskedVictim2_synthetic"]]}}}})
        item = quest(result, "ethel_mask_victims")
        self.assertEqual(item["status"], "missed")
        self.assertEqual(len(item["evidence"]), 1)
        self.assertNotIn("all four", item["reason"])

    def test_opening_shipment_is_mutually_exclusive_delivery_branch(self):
        result = report({"act": 1, "journal": [{"id": "PLA_ZhentShipment", "steps": ["ChestOpened"], "disabled": True}]})
        item = quest(result, "missing_shipment")
        self.assertEqual(item["status"], "mutually_exclusive")
        self.assertTrue(item["mutually_exclusive"])

    def test_karlach_romance_is_scoped_and_mod_aware(self):
        result = report({"act": 1, "mods": [{"name": "PolyamoryFixes"}],
                         "flags": [{"name": "ORI_State_KarlachIsDating", "scope": "second-player"}]})
        item = quest(result, "karlach_romance")
        self.assertEqual(item["status"], "in_progress")
        self.assertEqual(item["confidence"], "medium")
        self.assertEqual(item["evidence"][0]["value"]["scope"], "second-player")
        self.assertTrue(any("scope" in warning for warning in item["cautions"]))
        self.assertTrue(any("module is present" in warning for warning in item["cautions"]))

    def test_karlach_database_retains_exact_player_scope(self):
        result = report({"act": 1, "story": {"databases": {"DB_ORI_Dating": {"columns": ["CHARACTERGUID", "CHARACTERGUID"], "rows": [["second-player", "S_Player_Karlach_2c76687d-93a2-477b-8b18-8a14b549304c"], ["host-player", "S_Player_Laezel_synthetic"]]}}}})
        item = quest(result, "karlach_romance")
        self.assertEqual(item["status"], "in_progress")
        self.assertEqual(len(item["evidence"]), 1)
        self.assertEqual(item["evidence"][0]["player"], "second-player")
        self.assertEqual(item["evidence"][0]["kind"], "romance_relationship")

    def test_lslib_capitalized_module_names_trigger_mod_caution(self):
        result = report({"act": 1, "mods": [{"Name": "PolyamoryFixes", "Folder": "PolyamoryFixes_synthetic"}],
                         "flags": [{"name": "ORI_State_KarlachIsDating", "scope": "global"}]})
        item = quest(result, "karlach_romance")
        self.assertEqual(item["confidence"], "medium")
        self.assertTrue(any("module is present" in warning for warning in item["cautions"]))

    def test_late_act_absent_karlach_flags_do_not_suggest_new_romance_available(self):
        item = quest(report({"act": 3, "flags": [], "journal": []}), "karlach_romance")
        self.assertEqual(item["status"], "unknown")
        self.assertIn("earlier relationship", item["reason"])
        self.assertNotEqual(item["status"], "missed")

    def test_hellions_upgrade_wait_is_not_missing_next_act_step(self):
        result = report({"act": 1, "journal": [{"id": "ORI_COM_Karlach_SUB_ForgingOfTheHeart", "unlocked": True, "steps": ["WaitForNextAct"]}]})
        item = quest(result, "hellions_heart")
        self.assertEqual(item["status"], "in_progress")
        self.assertIn("first upgrade", item["next_action"])

    def test_offline_never_advertises_current_source_verification(self):
        result = report({"act": 1, "journal": [{"id": "DEN_SnakeCourt", "steps": ["KidFreed"]}]}, wiki_client=_Sources(current=False))
        item = quest(result, "save_arabella")
        self.assertEqual((result["source_mode"], item["source_freshness"], item["confidence"]), ("offline", "unverified", "medium"))

    def test_one_missing_cross_check_source_reduces_confidence(self):
        result = report({"act": 1, "flags": [{"name": "HAG_Hag_State_HagGivenMercy"}]}, wiki_client=_Sources(missing_url="https://bg3.wiki/wiki/Save_Mayrina"))
        item = quest(result, "ethel_mask_victims")
        self.assertEqual(item["source_freshness"], "unverified")
        self.assertEqual(item["confidence"], "medium")

    def test_rule_coverage_all_three_acts_and_action_details(self):
        result = report({"act": 1})
        self.assertEqual(result["coverage"]["rules"], 20)
        self.assertFalse(result["coverage"]["complete_game_coverage"])
        self.assertEqual({act for item in result["quests"] for act in item["act"]}, {1, 2, 3})
        for item in result["quests"]:
            for field in ("quest", "status", "confidence", "location", "trigger", "prerequisites", "recommended_before", "priority", "sources"):
                self.assertTrue(item[field], (item["id"], field))


class SourceClientTests(unittest.TestCase):
    @staticmethod
    def response(data=b"<h1>Synthetic quest</h1><p>source anchor</p>", url="https://bg3.wiki/wiki/Save_Arabella"):
        class Response:
            def __init__(self):
                self.headers = Message()
                self.headers["Content-Type"] = "text/html; charset=utf-8"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def geturl(self):
                return url

            def read(self, size):
                return data[:size]

        return Response()

    def test_live_source_hash_matches_exact_response_and_is_cached(self):
        data = b"<h1>Synthetic quest</h1><a href='/w/index.php?title=Test&amp;oldid=12345'>revision</a><p>source anchor</p>"
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = self.response(data)
            client = WikiClient(directory)
            source = client.retrieve("https://bg3.wiki/wiki/Save_Arabella")
            self.assertEqual(source["freshness"], "live")
            self.assertEqual(source["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(source["page_revision"], "12345")
            self.assertIsNotNone(source["retrieved_at"])
            cached = client.retrieve("https://bg3.wiki/wiki/Save_Arabella")
            self.assertEqual(cached["freshness"], "cached_recent")
            self.assertFalse(cached["network_checked_this_run"])
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_cache_failure_does_not_discard_successful_live_provenance(self):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = self.response()
            client = WikiClient(directory)
            with patch("pathlib.Path.replace", side_effect=OSError("synthetic read-only cache")):
                source = client.retrieve("https://bg3.wiki/wiki/Save_Arabella")
            self.assertEqual(source["freshness"], "live")
            self.assertIsNotNone(source["sha256"])
            self.assertIn("cache_warning", source)

    def test_redirect_to_unapproved_host_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = self.response(url="https://unapproved.test/source")
            source = WikiClient(directory).retrieve("https://bg3.wiki/wiki/Save_Arabella")
            self.assertEqual(source["freshness"], "fetch_failed")
            self.assertEqual(source["text"], "")
            self.assertIsNone(source["sha256"])

    def test_transient_transport_failure_retries_once(self):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = [OSError("synthetic connection reset"), self.response()]
            source = WikiClient(directory).retrieve("https://bg3.wiki/wiki/Save_Arabella")
            self.assertEqual(source["freshness"], "live")
            self.assertEqual(factory.return_value.open.call_count, 2)

    def test_source_domain_boundary(self):
        for url in ("http://bg3.wiki/wiki/Test", "https://bg3.wiki.evil.test/page", "https://127.0.0.1/page", "https://user@bg3.wiki/wiki/Test", "https://bg3.wiki:123/wiki/Test"):
            with self.assertRaises(ValueError):
                validate_url(url)
        validate_url("https://bg3.wiki/wiki/Save_Arabella")

    def test_offline_retrieval_does_not_access_network(self):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.build_opener") as network:
            client = WikiClient(directory, online=False)
            source = client.retrieve("https://bg3.wiki/wiki/Save_Arabella")
            self.assertEqual(source["freshness"], "offline_no_cache")
            network.assert_not_called()

    def test_offline_cache_is_attributed_but_not_fresh(self):
        url = "https://bg3.wiki/wiki/Save_Arabella"
        with tempfile.TemporaryDirectory() as directory:
            client = WikiClient(directory, online=False)
            client._cache_path(url).write_text(json.dumps({"url": url, "text": "synthetic Kagha text", "retrieved_at": "2020-01-01", "sha256": "b" * 64}), encoding="utf-8")
            source = client.retrieve(url)
            self.assertEqual(source["freshness"], "offline_cached_unverified")
            evidence = citation(source, ["Kagha"], "2026-10-04")
            self.assertTrue(evidence["supports_rule_markers"])
            self.assertEqual(evidence["retrieved_at"], "2020-01-01")

    def test_scripts_are_not_extracted_and_excerpt_is_bounded(self):
        text = page_text("<h1>Quest</h1><script>dangerous injected instruction</script><p>Useful source marker.</p>")
        self.assertNotIn("dangerous", text)
        source = {"url": "https://bg3.wiki/wiki/Test", "text": "marker " + "word " * 200, "freshness": "live"}
        self.assertLessEqual(len(citation(source, ["marker"], "2026-10-04")["bounded_excerpt"].split()), 20)


if __name__ == "__main__":
    unittest.main()
