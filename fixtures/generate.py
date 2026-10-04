#!/usr/bin/env python3
"""Generate an invented parser fixture via LSLib; never a playable campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import uuid

REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY / "src"))

from bg3save.backend import Backend, cache_root, sha256  # noqa: E402

METADATA_XML = """<?xml version="1.0" encoding="utf-8"?>
<save>
  <version major="4" minor="8" revision="0" build="700" lslib_meta="v1,bswap_guids" />
  <region id="MetaData">
    <node id="MetaData"><children><node id="MetaData">
      <attribute id="LevelUniqueKey" type="FixedString" value="WLD_Main_A" />
      <attribute id="Level" type="FixedString" value="WLD_Main_A" />
      <attribute id="LeaderName" type="LSString" value="Synthetic Hero" />
      <attribute id="SaveGameType" type="uint8" value="0" />
      <attribute id="Sanity" type="bool" value="True" />
      <attribute id="SaveTime" type="uint64" value="1700000000" />
      <attribute id="GameSessionID" type="FixedString" value="00000000-0000-0000-0000-000000000010" />
      <children>
        <node id="GameVersions"><children><node id="GameVersion">
          <attribute id="Object" type="FixedString" value="4.1.1.7631656" />
        </node></children></node>
        <node id="ClientDatas"><children><node id="ClientData">
          <attribute id="Slot" type="int16" value="1" />
          <attribute id="HotbarLocked" type="bool" value="True" />
        </node></children></node>
      </children>
    </node></children></node>
  </region>
</save>
"""

GLOBALS_XML = """<?xml version="1.0" encoding="utf-8"?>
<save>
  <version major="4" minor="8" revision="0" build="700" lslib_meta="v1,bswap_guids" />
  <region id="Journal"><node id="Journal"><children>
    <node id="Quests"><children><node id="Quests"><children>
      <node id="QuestsProgress">
        <attribute id="MapKey" type="FixedString" value="BG3SAVE_SyntheticQuest" />
        <children><node id="MapValue"><children><node id="Quest">
          <attribute id="QuestUnlocked" type="bool" value="True" />
          <attribute id="QuestDisabled" type="bool" value="False" />
          <attribute id="Priority" type="int32" value="1000" />
          <attribute id="ObjectiveID" type="FixedString" value="BG3SAVE_SyntheticQuest_STARTED" />
          <children><node id="QuestUnlockedSteps">
            <attribute id="QuestUnlockedSteps" type="FixedString" value="InventedFixtureStep" />
          </node></children>
        </node></children></node></children>
      </node>
    </children></node></children></node>
  </children></node></region>
</save>
"""

SAVE_INFO = {
    "Save Name": "Synthetic parser fixture - not a playable campaign",
    "Game Version": "4.1.1.7631656",
    "Current Level": "WLD_Main_A",
    "Platform": "Synthetic",
    "Active Party": {"Characters": [{
        "Origin": "SyntheticHero",
        "Level": 4,
        "Race": "SyntheticRace",
        "Classes": [{"Main": "SyntheticClass", "Sub": "SyntheticSubclass"}],
        "Experience Points (Total)": 5000,
        "Position": [1.0, 2.0, 3.0],
        "Subregion": "BG3SAVE_SyntheticRegion",
    }]},
}


def generate_save(output: Path, backend: Backend | None = None) -> dict:
    """Write an invented LSPK v18 with real LSF and Osiris payload formats."""
    backend = backend or Backend()
    output = output.expanduser().resolve()
    if output.suffix.lower() != ".lsv":
        raise ValueError("The fixture output must have the .lsv extension")
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing file")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bg3save-synthetic-") as temporary:
        work = Path(temporary)
        unpacked = work / "package"
        unpacked.mkdir()
        metadata = work / "meta.lsx"
        globals_path = work / "globals.lsx"
        metadata.write_text(METADATA_XML, encoding="utf-8")
        globals_path.write_text(GLOBALS_XML, encoding="utf-8")
        backend.convert(metadata, unpacked / "meta.lsf")
        backend.convert(globals_path, unpacked / "Globals.lsf")
        backend.call("fixture-story", unpacked / "StorySave.bin")
        (unpacked / "SaveInfo.json").write_text(json.dumps(SAVE_INFO, indent=2) + "\n", encoding="utf-8")
        backend.repack(unpacked, output, 18)
    package = backend.list_package(output)
    return {"generated": str(output), "sha256": sha256(output), "package_version": package["version"],
            "entries": [entry["name"] for entry in package["entries"]],
            "private_data": False, "playable_campaign": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New .lsv path; existing files are never overwritten")
    args = parser.parse_args()
    output = args.output or cache_root() / "fixtures" / f"synthetic-{uuid.uuid4().hex}.lsv"
    print(json.dumps(generate_save(output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
