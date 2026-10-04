"""Backend security checks and opt-in real LSLib integration fixtures."""

from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from bg3save.backend import Backend, MAX_UNPACKED_BYTES, sha256, validate_entries
from bg3save.errors import SaveError
from bg3save.cli import main
from bg3save.model import parse_snapshot, read_xml

REPOSITORY = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bg3save_test_fixture", REPOSITORY / "fixtures" / "generate.py")
_fixture = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixture)


class ArchiveValidationTests(unittest.TestCase):
    def test_malformed_toolchain_shapes_return_json_before_reading_a_save(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for value in ([], None, {"divine": []}, {"bridge": 42}):
                with self.subTest(value=value):
                    (root / "toolchain.json").write_text(json.dumps(value), encoding="utf-8")
                    output = io.StringIO()
                    with patch("bg3save.backend.cache_root", return_value=root), patch("bg3save.cli.service.inspect") as inspect, redirect_stdout(output):
                        code = main(["inspect", "nonexistent.lsv", "--json"])
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(output.getvalue())["error"]["code"], "invalid_toolchain_config")
                    inspect.assert_not_called()

    def test_normal_nested_member_paths(self):
        validate_entries([{"name": "meta.lsf", "size": 1}, {"name": "LevelCache/WLD_Main_A.lsf", "size": 5}])

    def test_path_traversal_and_absolute_paths_rejected(self):
        for path in ("../escape", "LevelCache/../../escape", "LevelCache\\..\\escape", "/absolute", "C:/absolute",
                     "C:\\absolute", "\\\\server\\share", "meta.lsf:stream", "foo//bar", "foo\x00bar"):
            with self.subTest(path=path):
                with self.assertRaises(SaveError) as caught:
                    validate_entries([{"name": path, "size": 1}])
                self.assertEqual(caught.exception.code, "unsafe_archive_path")

    def test_windows_aliases_and_dot_segments_rejected(self):
        for path in ("./meta.lsf", "LevelCache/./meta.lsf", "LevelCache/.. /escape", "meta.lsf.", "meta.lsf ",
                     "CON", "nul.txt", "LevelCache/LPT1.bin", "COM9.anything"):
            with self.subTest(path=path):
                with self.assertRaises(SaveError) as caught:
                    validate_entries([{"name": path, "size": 1}])
                self.assertEqual(caught.exception.code, "unsafe_archive_path")

    def test_case_colliding_members_rejected(self):
        with self.assertRaises(SaveError) as caught:
            validate_entries([{"name": "meta.lsf", "size": 1}, {"name": "META.LSF", "size": 1}])
        self.assertEqual(caught.exception.code, "duplicate_archive_path")

    def test_negative_size_and_expansion_budget_rejected(self):
        for size in (-1, "100", MAX_UNPACKED_BYTES + 1):
            with self.subTest(size=size), self.assertRaises(SaveError):
                validate_entries([{"name": "meta.lsf", "size": size}])

    def test_empty_archive_rejected(self):
        with self.assertRaises(SaveError):
            validate_entries([])

    def test_deleted_archive_member_rejected(self):
        with self.assertRaises(SaveError) as caught:
            validate_entries([{"name": "meta.lsf", "size": 1, "deleted": True}])
        self.assertEqual(caught.exception.code, "deleted_archive_member")

    def test_xml_external_entities_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsafe.lsx"
            path.write_text('<!DOCTYPE save [<!ENTITY x SYSTEM "file:///secret">]><save>&x;</save>', encoding="utf-8")
            with self.assertRaises(SaveError) as caught:
                read_xml(path)
            self.assertEqual(caught.exception.code, "unsafe_xml")

    def test_malformed_xml_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.lsx"
            path.write_text("<save><broken>", encoding="utf-8")
            with self.assertRaises(SaveError) as caught:
                read_xml(path)
            self.assertEqual(caught.exception.code, "invalid_resource")

    def test_utf16_internal_dtd_cannot_bypass_xml_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsafe-utf16.lsx"
            payload = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE save [<!ENTITY x "secret">]><save>&x;</save>'
            path.write_bytes(payload.encode("utf-16"))
            with self.assertRaises(SaveError):
                read_xml(path)


@unittest.skipUnless(os.environ.get("BG3SAVE_INTEGRATION") == "1", "Set BG3SAVE_INTEGRATION=1 after bootstrapping LSLib")
class RealBackendIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="bg3save-backend-test-")
        cls.directory = Path(cls.scratch.name)
        cls.backend = Backend()
        cls.save = cls.directory / "synthetic.lsv"
        cls.generated = _fixture.generate_save(cls.save, cls.backend)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def unpack(self, name):
        directory = self.directory / name
        package = self.backend.unpack(self.save, directory)
        return directory, package

    def test_real_unpack_parse_and_inspect(self):
        directory, package = self.unpack("inspect")
        self.assertEqual(package["version"], 18)
        self.assertTrue(package["checksum_valid"])
        self.assertTrue(package["canonical_checksum_valid"])
        self.assertNotEqual(package["header_md5"], "0" * 32)
        self.assertEqual({entry["name"] for entry in package["entries"]}, {"meta.lsf", "Globals.lsf", "SaveInfo.json", "StorySave.bin"})
        metadata = self.directory / "inspect-meta.lsx"
        globals_path = self.directory / "inspect-globals.lsx"
        self.backend.convert(directory / "meta.lsf", metadata)
        self.backend.convert(directory / "Globals.lsf", globals_path)
        story = self.backend.read_story(directory / "StorySave.bin", self.directory / "inspect-story.json")
        snapshot = parse_snapshot(directory, metadata, globals_path, story)
        self.assertEqual(snapshot["game_version"], "4.1.1.7631656")
        self.assertEqual(snapshot["act"], 1)
        self.assertEqual(snapshot["metadata"]["Sanity"], "True")
        self.assertEqual(snapshot["clients"][0]["HotbarLocked"], "True")
        self.assertEqual(snapshot["party"][0]["origin"], "SyntheticHero")
        self.assertEqual(snapshot["party"][0]["level"], 4)
        self.assertEqual(snapshot["flags"][0]["name"], "BG3SAVE_SyntheticFlag")
        self.assertEqual(snapshot["journal"][0]["steps"], ["InventedFixtureStep"])
        self.assertFalse(self.generated["private_data"])
        self.assertFalse(self.generated["playable_campaign"])

    def test_real_repack_preserves_every_member_byte(self):
        original, manifest = self.unpack("roundtrip-before")
        output = self.directory / "roundtrip.lsv"
        self.backend.repack(original, output, manifest["version"])
        restored = self.directory / "roundtrip-after"
        reread = self.backend.unpack(output, restored)
        self.assertTrue(reread["checksum_valid"])
        self.assertTrue(reread["canonical_checksum_valid"])
        self.assertEqual(reread["header_md5"], reread["computed_md5"])
        self.assertEqual(manifest["version"], reread["version"])
        self.assertEqual({entry["name"] for entry in manifest["entries"]}, {entry["name"] for entry in reread["entries"]})
        for entry in manifest["entries"]:
            self.assertEqual(sha256(original / entry["name"]), sha256(restored / entry["name"]), entry["name"])

    def test_repack_orders_nested_members_with_top_level_paths_for_native_hash(self):
        # The regression needs a nested LevelCache member: a flat synthetic save
        # cannot expose Packager's top-level-first traversal mistake.
        directory, _ = self.unpack("nested-native-hash")
        (directory / "LevelCache").mkdir()
        (directory / "LevelCache" / "InventedFixture.bin").write_bytes(b"Entirely invented nested test payload")
        output = self.directory / "nested-native-hash.lsv"
        report = self.backend.call("package-create", directory, output, 18)
        self.assertTrue(report["checksum_valid"])
        self.assertTrue(report["canonical_checksum_valid"])
        self.assertEqual(report["physical_order"], sorted(report["physical_order"], key=str.casefold))
        order = report["physical_order"]
        self.assertLess(order.index("LevelCache/InventedFixture.bin"), order.index("meta.lsf"))
        self.assertEqual(report["computed_md5"], report["computed_canonical_md5"])

    def test_template_repack_preserves_member_table_order_physical_order_and_compression(self):
        directory, before = self.unpack("template-before")
        output = self.directory / "template-copy.lsv"
        after = self.backend.call("package-create", directory, output, 18, "--template", self.save)
        self.assertEqual(before["header_md5"], after["header_md5"])
        self.assertEqual(before["physical_order"], after["physical_order"])
        self.assertEqual([e["name"] for e in before["entries"]], [e["name"] for e in after["entries"]])
        self.assertEqual([e["flags"] for e in before["entries"]], [e["flags"] for e in after["entries"]])
        self.assertEqual(before["flags"], after["flags"])
        self.assertEqual(before["priority"], after["priority"])
        restored = self.directory / "template-after"
        self.backend.unpack(output, restored)
        for entry in before["entries"]:
            self.assertEqual(sha256(directory / entry["name"]), sha256(restored / entry["name"]))

    def test_template_repack_rejects_missing_or_extra_members(self):
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                directory, _ = self.unpack("template-member-" + mutation)
                if mutation == "missing":
                    (directory / "SaveInfo.json").unlink()
                else:
                    (directory / "unexpected.txt").write_text("invented", encoding="utf-8")
                output = self.directory / ("template-invalid-" + mutation + ".lsv")
                with self.assertRaises(SaveError):
                    self.backend.call("package-create", directory, output, 18, "--template", self.save)
                self.assertFalse(output.exists())

    def test_real_lsf_conversion_preserves_all_nodes_and_attributes(self):
        directory, _ = self.unpack("resource-roundtrip")
        first = self.directory / "first-meta.lsx"
        rebuilt = self.directory / "rebuilt-meta.lsf"
        second = self.directory / "second-meta.lsx"
        self.backend.convert(directory / "meta.lsf", first)
        self.backend.call("resource-convert", first, rebuilt, "--template", directory / "meta.lsf")
        self.backend.convert(rebuilt, second)
        canonical = lambda element: (element.tag, sorted(element.attrib.items()), tuple(canonical(child) for child in element))
        self.assertEqual(canonical(ET.parse(first).getroot()), canonical(ET.parse(second).getroot()))

    def test_real_story_roundtrip_and_experimental_flag_add_remove(self):
        directory, _ = self.unpack("story-roundtrip")
        original = directory / "StorySave.bin"
        roundtrip = self.directory / "story-roundtrip.bin"
        verified = self.backend.call("story-roundtrip", original, roundtrip)
        self.assertTrue(verified["verified"])
        self.assertFalse(verified["game_load_validated"])
        added = self.directory / "story-added.bin"
        flag = "BG3SAVE_TestFlag_00000000-0000-0000-0000-000000000002"
        result = self.backend.call("story-set-global-flag", original, added, flag)
        self.assertEqual(result["capability"], "experimental")
        self.assertTrue(result["changed"])
        export = self.backend.read_story(added, self.directory / "story-added.json")
        facts = next(database["facts"] for database in export["databases"] if database["name"] == "DB_GlobalFlag")
        self.assertEqual(len(facts), 2)
        restored = self.directory / "story-restored.bin"
        removed = self.backend.call("story-unset-global-flag", added, restored, "00000000-0000-0000-0000-000000000002")
        self.assertTrue(removed["changed"])
        before = self.backend.read_story(original, self.directory / "story-original.json")
        after = self.backend.read_story(restored, self.directory / "story-restored.json")
        self.assertEqual(before, after)

    def test_malformed_lsv_rejected_by_actual_lslib(self):
        invalid = self.directory / "malformed.lsv"
        invalid.write_bytes(b"This is not an LSPK archive\x00\x00\x00\x00")
        with self.assertRaises(SaveError) as caught:
            self.backend.list_package(invalid)
        self.assertEqual(caught.exception.code, "backend_error")

    def test_malformed_story_rejected_by_actual_lslib(self):
        invalid = self.directory / "malformed-story.bin"
        invalid.write_bytes(b"This is not an Osiris save")
        with self.assertRaises(SaveError):
            self.backend.read_story(invalid, self.directory / "malformed-story.json")

    def test_real_unpack_refuses_nonempty_destination(self):
        destination = self.directory / "occupied"
        destination.mkdir()
        retained = destination / "keep.txt"
        retained.write_text("original", encoding="utf-8")
        with self.assertRaises(SaveError) as caught:
            self.backend.unpack(self.save, destination)
        self.assertEqual(caught.exception.code, "unsafe_destination")
        self.assertEqual(retained.read_text(encoding="utf-8"), "original")

    def test_real_repack_rejects_unverified_container_version(self):
        directory, _ = self.unpack("unsupported-package-version")
        with self.assertRaises(SaveError):
            self.backend.repack(directory, self.directory / "unsupported.lsv", 13)
        self.assertFalse((self.directory / "unsupported.lsv").exists())

    @unittest.skipUnless(os.environ.get("BG3SAVE_REAL_SAVE"), "Set BG3SAVE_REAL_SAVE to a private native .lsv; it is never copied into Git")
    def test_native_player_save_checksum_is_verified_in_physical_order(self):
        native = self.backend.list_package(Path(os.environ["BG3SAVE_REAL_SAVE"]))
        self.assertTrue(native["checksum_valid"])
        self.assertTrue(native["canonical_checksum_valid"])
        self.assertEqual(native["header_md5"], native["computed_md5"])
        self.assertEqual(native["header_md5"], native["computed_canonical_md5"])

    @unittest.skipUnless(os.environ.get("BG3SAVE_REAL_SAVE"), "Set BG3SAVE_REAL_SAVE to a private native .lsv; it is never copied into Git")
    def test_native_player_save_template_roundtrip_preserves_native_layout_and_every_payload(self):
        source = Path(os.environ["BG3SAVE_REAL_SAVE"])
        unpacked = self.directory / "native-template-before"
        before = self.backend.unpack(source, unpacked)
        output = self.directory / "native-template-copy.lsv"
        after = self.backend.call("package-create", unpacked, output, 18, "--template", source)
        self.assertTrue(after["checksum_valid"])
        self.assertTrue(after["canonical_checksum_valid"])
        self.assertEqual(before["header_md5"], after["header_md5"])
        self.assertEqual(before["physical_order"], after["physical_order"])
        self.assertEqual([(e["name"], e["flags"]) for e in before["entries"]],
                         [(e["name"], e["flags"]) for e in after["entries"]])
        restored = self.directory / "native-template-after"
        self.backend.unpack(output, restored)
        for entry in before["entries"]:
            self.assertEqual(sha256(unpacked / entry["name"]), sha256(restored / entry["name"]), entry["name"])

    def test_checksum_guard_detects_corrupted_header_without_suppressing_sanity(self):
        # Deliberately damaged synthetic fixture, never a mutation implementation.
        # Header corruption leaves compressed payloads intact, separating parsing
        # success from integrity success and reproducing the in-game warning class.
        corrupted = bytearray(self.save.read_bytes())
        corrupted[22] ^= 1
        path = self.directory / "bad-checksum.lsv"
        path.write_bytes(corrupted)
        report = self.backend.call("package-list", path)
        self.assertFalse(report["checksum_valid"])
        self.assertNotEqual(report["header_md5"], report["computed_md5"])


if __name__ == "__main__":
    unittest.main()
