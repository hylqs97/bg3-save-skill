"""Mutation acceptance tests use invented saves and the real LSLib backend."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bg3save.backend import Backend, sha256
from bg3save.cli import main
from bg3save.errors import SaveError
from bg3save import service

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("test_service_fixture", ROOT / "fixtures/generate.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class PublicApiTests(unittest.TestCase):
    def test_capabilities_are_explicit_and_do_not_claim_ecs_writes(self):
        capabilities = service.capabilities()
        self.assertEqual(capabilities["operations"]["set-gold"], "UNSUPPORTED")
        self.assertEqual(capabilities["operations"]["set-hotbar-lock"], "SUPPORTED")
        self.assertEqual(capabilities["operations"]["set-flag"], "EXPERIMENTAL")

    def test_unsupported_edit_rejected_without_reading_or_writing_save(self):
        for operation in ("set-gold", "add-item", "remove-item", "set-approval", "repair"):
            with self.subTest(operation=operation), self.assertRaises(SaveError) as caught:
                service.modify(Path("does-not-exist.lsv"), None, operation)
            self.assertEqual(caught.exception.code, "unsupported_operation")

    def test_cli_json_capabilities_and_argument_error(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["capabilities", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["schema_version"], 1)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--invalid-option"]), 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "invalid_arguments")

    def test_find_latest_uses_real_mtimes_across_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, new = root / "Old.lsv", root / "Public/Story/Latest.lsv"
            new.parent.mkdir(parents=True)
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            os.utime(old, (100, 100))
            os.utime(new, (200, 200))
            self.assertEqual(service.find_saves(root, latest=True)["saves"][0]["path"], str(new.resolve()))

    def test_diff_compares_story_facts_without_incidental_row_order(self):
        left = {"story": {"databases": {"DB": {"columns": ["INTEGER"], "rows": [[1], [2]]}}}}
        right = {"story": {"databases": {"DB": {"columns": ["INTEGER"], "rows": [[2], [1]]}}}}
        self.assertTrue(service.diff_snapshots(left, right)["equal_extracted_semantics"])
        right["story"]["databases"]["DB"]["rows"].append([3])
        self.assertEqual(service.diff_snapshots(left, right)["story_changes"][0]["database"], "DB")

    def test_skill_wrapper_resolves_repo_and_installer_paths(self):
        wrapper = ROOT / "skills/bg3-save/scripts/bg3save.py"
        report = subprocess.run([sys.executable, str(wrapper), "capabilities", "--json"], capture_output=True, encoding="utf-8")
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(json.loads(report.stdout)["operations"]["repair"], "UNSUPPORTED")

    def test_installer_links_one_source_and_smoke_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            installer = ROOT / "skills/bg3-save/scripts/install_skill.py"
            result = subprocess.run([sys.executable, str(installer), "--codex-home", str(home), "--smoke-test"],
                                    capture_output=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["shared_source"])
            self.assertTrue(payload["discoverable_on_next_skill_refresh"])
            self.assertEqual(payload["smoke_test"]["exit_code"], 0)
            target = home / "skills/bg3-save"
            self.assertEqual(target.resolve(), (ROOT / "skills/bg3-save").resolve())
            # Remove the link, never recurse into the shared repository directory.
            if os.name == "nt":
                target.rmdir()
            else:
                target.unlink()


@unittest.skipUnless(os.environ.get("BG3SAVE_INTEGRATION") == "1", "Enable actual LSLib integration explicitly")
class SaveMutationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bg3save-semantic-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = Backend()
        self.source = self.root / "original.lsv"
        fixture.generate_save(self.source, self.backend)
        self.original_hash = sha256(self.source)

    def modify(self, name="modified.lsv", operation="set-hotbar-lock", value=False, **kwargs):
        return service.modify(self.source, self.root / name, operation, value,
                              backend=self.backend, backup_dir=self.root / "backups", **kwargs)

    def test_dry_run_creates_no_output_manifest_or_backup(self):
        report = self.modify(dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["written"])
        self.assertEqual(report["plan"]["before"], True)
        self.assertEqual(report["plan"]["after"], False)
        self.assertEqual([p.name for p in self.root.iterdir()], ["original.lsv"])
        self.assertEqual(sha256(self.source), self.original_hash)

    def test_safe_edit_preserves_all_unmodified_payloads_and_has_verified_backup(self):
        before = service.inspect(self.source, self.backend)
        report = self.modify()
        after = service.inspect(Path(report["output"]), self.backend)
        self.assertTrue(report["original_unchanged"])
        self.assertEqual(sha256(Path(report["backup"])), self.original_hash)
        self.assertEqual(after["clients"][0]["HotbarLocked"], "False")
        self.assertEqual(report["diff"]["changed_archive_members"], ["meta.lsf"])
        self.assertEqual(before["story"]["semantic_sha256"], after["story"]["semantic_sha256"])
        self.assertEqual(before["journal"], after["journal"])
        self.assertEqual(before["party"], after["party"])
        self.assertTrue(service.verify(Path(report["output"]), self.backend)["structural_valid"])
        self.assertFalse(report["verification"]["game_load_validated"])

    def test_rollback_restores_exact_original_without_overwrite(self):
        report = self.modify()
        restored = self.root / "restored.lsv"
        rollback = service.rollback(Path(report["manifest"]), restored, self.backend)
        self.assertTrue(rollback["byte_identical_to_original"])
        self.assertEqual(sha256(restored), self.original_hash)
        with self.assertRaises(SaveError):
            service.rollback(Path(report["manifest"]), restored, self.backend)

    def test_tampered_backup_cannot_be_used_for_rollback(self):
        report = self.modify()
        Path(report["backup"]).write_bytes(b"damaged")
        with self.assertRaises(SaveError) as caught:
            service.rollback(Path(report["manifest"]), self.root / "rollback.lsv", self.backend)
        self.assertEqual(caught.exception.code, "backup_tampered")
        self.assertFalse((self.root / "rollback.lsv").exists())

    def test_write_never_overwrites_original_or_existing_output(self):
        for output in (self.source, self.root / "existing.lsv"):
            output.touch(exist_ok=True)
            expected = sha256(output)
            with self.assertRaises(SaveError):
                service.modify(self.source, output, "set-hotbar-lock", False, backend=self.backend)
            self.assertEqual(sha256(output), expected)

    def test_experimental_writes_require_explicit_opt_in(self):
        with self.assertRaises(SaveError) as caught:
            self.modify(operation="unset-flag", value="00000000-0000-0000-0000-000000000001")
        self.assertEqual(caught.exception.code, "experimental_opt_in_required")
        self.assertFalse((self.root / "backups").exists())

    def test_known_global_flag_write_and_restore_are_experimental(self):
        original = service.inspect(self.source, self.backend)
        flag = original["flags"][0]["uuid"]
        removed = self.modify(operation="unset-flag", value=flag, allow_experimental=True)
        state = service.inspect(Path(removed["output"]), self.backend)
        self.assertEqual(state["flags"], [])
        self.assertEqual(removed["capability"], "EXPERIMENTAL")
        self.assertEqual(removed["diff"]["changed_archive_members"], ["StorySave.bin"])
        self.assertEqual(state["clients"], original["clients"])
        restored = service.modify(Path(removed["output"]), self.root / "flag-restored.lsv", "set-flag", flag,
                                  allow_experimental=True, backend=self.backend, backup_dir=self.root / "backups")
        state = service.inspect(Path(restored["output"]), self.backend)
        self.assertEqual(state["flags"], original["flags"])

    def test_unknown_flag_is_refused_even_with_experimental_opt_in(self):
        with self.assertRaises(SaveError) as caught:
            self.modify(operation="set-flag", value="00000000-0000-0000-0000-000000000999", allow_experimental=True)
        self.assertEqual(caught.exception.code, "unknown_or_ambiguous_flag")
        self.assertFalse((self.root / "backups").exists())

    def test_unverified_game_version_is_refused_before_backup(self):
        with service.opened_save(self.source, self.backend) as handle:
            info = handle["directory"] / "SaveInfo.json"
            data = json.loads(info.read_text())
            data["Game Version"] = "9.9.9.9"
            info.write_text(json.dumps(data))
            unknown = self.root / "unknown.lsv"
            self.backend.repack(handle["directory"], unknown, 18)
        with self.assertRaises(SaveError) as caught:
            service.modify(unknown, self.root / "no-write.lsv", "set-hotbar-lock", False,
                           backend=self.backend, backup_dir=self.root / "backups")
        self.assertEqual(caught.exception.code, "unsupported_game_version")
        self.assertFalse((self.root / "backups").exists())

    def test_missing_client_slot_is_refused_before_backup(self):
        with self.assertRaises(SaveError) as caught:
            self.modify(slot=99)
        self.assertEqual(caught.exception.code, "ambiguous_client")
        self.assertFalse((self.root / "backups").exists())

    def test_native_sanity_failure_is_not_silently_repaired(self):
        from xml.etree import ElementTree as ET
        with service.opened_save(self.source, self.backend) as handle:
            tree = ET.parse(handle["meta_xml"])
            tree.find(".//attribute[@id='Sanity']").set("value", "False")
            changed_xml = handle["work"] / "not-sane.lsx"
            changed_binary = handle["work"] / "not-sane.lsf"
            tree.write(changed_xml, encoding="utf-8", xml_declaration=True)
            self.backend.convert(changed_xml, changed_binary, template=handle["directory"] / "meta.lsf")
            (handle["directory"] / "meta.lsf").write_bytes(changed_binary.read_bytes())
            not_sane = self.root / "not-sane.lsv"
            self.backend.repack(handle["directory"], not_sane, 18)
        for action in (lambda: service.verify(not_sane, self.backend),
                       lambda: service.modify(not_sane, self.root / "no-output.lsv", "set-hotbar-lock", False,
                                              backend=self.backend, backup_dir=self.root / "backups")):
            with self.assertRaises(SaveError) as caught:
                action()
            self.assertEqual(caught.exception.code, "save_sanity_failed")
        self.assertFalse((self.root / "backups").exists())
        self.assertFalse((self.root / "no-output.lsv").exists())

    def test_explicit_marker_restore_is_minimal_and_rollback_preserves_the_old_marker(self):
        from xml.etree import ElementTree as ET
        with service.opened_save(self.source, self.backend) as handle:
            tree = ET.parse(handle["meta_xml"])
            tree.find(".//attribute[@id='Sanity']").set("value", "False")
            xml = handle["work"] / "marker-false.lsx"
            binary = handle["work"] / "marker-false.lsf"
            tree.write(xml, encoding="utf-8", xml_declaration=True)
            self.backend.convert(xml, binary, template=handle["directory"] / "meta.lsf")
            (handle["directory"] / "meta.lsf").write_bytes(binary.read_bytes())
            original = self.root / "native-false-marker.lsv"
            self.backend.repack(handle["directory"], original, 18)
        digest = sha256(original)
        with self.assertRaises(SaveError) as caught:
            service.modify(original, None, "restore-integrity-marker", dry_run=True, backend=self.backend)
        self.assertEqual(caught.exception.code, "experimental_opt_in_required")
        output = self.root / "marker-restored.lsv"
        dry = service.modify(original, output, "restore-integrity-marker", dry_run=True,
                             allow_experimental=True, backend=self.backend)
        self.assertEqual(dry["plan"]["before"], False)
        self.assertEqual(dry["plan"]["after"], True)
        self.assertFalse(output.exists())
        result = service.modify(original, output, "restore-integrity-marker", allow_experimental=True,
                                backend=self.backend, backup_dir=self.root / "marker-backups")
        self.assertEqual(result["capability"], "EXPERIMENTAL")
        self.assertEqual(result["diff"]["changed_archive_members"], ["meta.lsf"])
        self.assertEqual([r["field"] for r in result["diff"]["changes"]], ["metadata"])
        self.assertEqual(result["diff"]["story_changes"], [])
        self.assertTrue(service.verify(output, self.backend)["valid"])
        self.assertEqual(sha256(original), digest)
        restored = self.root / "original-marker-restored.lsv"
        rollback = service.rollback(Path(result["manifest"]), restored, self.backend)
        self.assertTrue(rollback["byte_identical_to_original"])
        self.assertFalse(rollback["verification"]["valid"])
        self.assertEqual(service.inspect(restored, self.backend)["metadata"]["Sanity"], "False")

    def test_marker_restore_is_not_a_generic_bad_resource_repair(self):
        from xml.etree import ElementTree as ET
        with service.opened_save(self.source, self.backend) as handle:
            tree = ET.parse(handle["meta_xml"])
            tree.find(".//attribute[@id='Sanity']").set("value", "False")
            xml, binary = handle["work"] / "bad-marker.lsx", handle["work"] / "bad-marker.lsf"
            tree.write(xml, encoding="utf-8", xml_declaration=True)
            self.backend.convert(xml, binary, template=handle["directory"] / "meta.lsf")
            (handle["directory"] / "meta.lsf").write_bytes(binary.read_bytes())
            broken = handle["directory"] / "LevelCache/broken.lsf"
            broken.parent.mkdir()
            broken.write_bytes(b"not-an-LSF-resource")
            bad = self.root / "resource-invalid.lsv"
            self.backend.repack(handle["directory"], bad, 18)
        with self.assertRaises(SaveError):
            service.modify(bad, self.root / "not-created.lsv", "restore-integrity-marker",
                           allow_experimental=True, backend=self.backend, backup_dir=self.root / "marker-backups")
        self.assertFalse((self.root / "not-created.lsv").exists())
        self.assertFalse((self.root / "marker-backups").exists())


if __name__ == "__main__":
    unittest.main()
