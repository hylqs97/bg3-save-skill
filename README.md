# BG3 Save Skill

A local Agent Skill and deterministic CLI for **Baldur's Gate 3 save analysis**: inspect a `.lsv`, expose save evidence as JSON, identify possible missed content with bg3.wiki sources, and perform narrowly supported edits with backup and rollback.

The Agent interprets natural language; the CLI reads or edits explicit semantic fields through LSLib. Player saves stay on your machine. The project does **not** claim to detect every missed quest or safely rewrite arbitrary ECS/LSMF state.

## Current scope

| Capability | Status | What it means |
|---|---|---|
| Find, unpack, parse and verify `.lsv` | **SUPPORTED** | External LSLib handles binary containers/resources/Story; JSON output preserves limitations |
| Save metadata, region/Act evidence, version, mods and party summaries | **SUPPORTED** | Fields are exposed when present; unknown is not fabricated |
| Character level/class/XP, companion identities, Story flags and journal evidence | **SUPPORTED** | Readable summaries and raw evidence; optional unavailable fields stay unknown |
| Approval and dating/partner Story facts | **SUPPORTED when present** | Typed `DB_ApprovalRating` and `DB_ORI_*` records; not full ECS relationship state |
| Quest and possible missed-content analysis | **EXPERIMENTAL** | A curated catalog of 20 quest/event rules across Acts 1–3; explicit evidence, confidence, prerequisites and sources |
| Selected companion/romance interpretations | **EXPERIMENTAL** | Evidence from known story states; not an exhaustive relationship simulator |
| Set one player's saved hotbar-lock state | **SUPPORTED / safe** | Minimal `HotbarLocked` metadata change to a new output, with automatic backup/verify/diff |
| Set or unset a Story flag | **EXPERIMENTAL** | Requires explicit opt-in; does not repair all related quest/NPC state |
| Restore a persisted integrity marker | **EXPERIMENTAL** | Explicit recovery operation after canonical checksum and all LSF parse checks; not a general corruption repair or a verified game-load guarantee |
| Dry-run, backup, diff and rollback | **SUPPORTED** | Original is retained; manifest records what changed and where its backup is |
| Gold, item add/remove, approval, resurrection and generic quest-repair writes | **UNSUPPORTED** | No reliable semantic writer yet; the CLI refuses rather than patches opaque data |
| Complete inventory/gold/ECS extraction and all missed content | **UNSUPPORTED** | Modern components may be opaque; absence of extracted values proves nothing |

Use `bg3save capabilities --json` for the installed revision's authoritative capability status. See [detailed boundaries](docs/capabilities.md).

## Versions and requirements

- Python **3.11+**; package runtime uses the standard library.
- External **Norbyte/LSLib 1.20.4** tools and the repository's .NET Story bridge; see [setup and license review](docs/dependencies.md).
- Read/round-trip baseline: BG3 product version **4.1.1.7631656**, Patch 8 lineage, Story/Osiris **1.15**. Save versions are read from actual metadata. `4.69.95.0` is an internal engine identifier, not the public game version.
- Ordinary writes require single-part LSPK **18**, package **flags = 0 / priority = 0**, a valid native archive checksum, and the native metadata **`Sanity = true`**. SaveInfo and metadata version evidence must agree with the verified product version. Other formats or failed checks are refused before mutation; inspection can still reveal useful evidence. The explicit experimental marker-restoration operation below has a separate, stricter preflight for a false marker.
- Resource writeback preserves the original LSF container revision and metadata format through an explicit original-resource template. Payloads outside the selected edit remain unchanged.
- Native checksum verification uses ordinal, case-insensitive full-path ordering. A physical-order MD5 match alone is insufficient. Production repacking uses the original archive template to preserve its layout, file-table order and compression flags; see [the checksum investigation](docs/dependencies.md#adapter-api).
- Initial external-backend verification is on Windows. Pure Python tests also run on Linux; this does not establish Linux/Wine compatibility of externally supplied LSLib executables.

This is an MVP. Structural validation and gameplay validation are separate. A successful parse/repack cannot on its own prove BG3 will load a changed save or that an experimental flag edit restores a quest.

A BG3 warning that a save was modified or corrupted is a failed runtime acceptance check, even when loading can continue. Ordinary edits do not clear a failed marker or disable game integrity checks. A save already marked `Sanity = false` is refused by the ordinary writer; the explicit experimental recovery operation below must not be confused with a routine edit.

## Install

Clone this repository, then install the CLI:

```console
git clone https://github.com/hylqs97/bg3-save-skill.git
cd bg3-save-skill
python -m pip install -e .
bg3save capabilities --json
```

LSLib is not bundled. With .NET SDK 8 or newer and a .NET 8 runtime installed, bootstrap the pinned official toolchain:

```console
python tools/bootstrap-lslib.py
```

An offline ZIP can be provided with `--archive /path/to/ExportTool-v1.20.4.zip`. The bootstrap verifies the pinned archive hash, builds the bridge and stores a toolchain manifest outside the repository. Follow [docs/dependencies.md](docs/dependencies.md) for paths, manual configuration and the license review. Set `BG3SAVE_DIVINE` and `BG3SAVE_BRIDGE`, or pass global `--divine PATH` and `--bridge PATH` options when using a different installation. Do not commit external binaries or personal saves.

### Install the Codex Skill

After the package/tests work:

```console
python skills/bg3-save/scripts/install_skill.py --smoke-test
```

The installer uses `$CODEX_HOME/skills/bg3-save` when `CODEX_HOME` is set, otherwise `~/.codex/skills/bg3-save`. It creates a Windows directory junction or a Unix symlink to `skills/bg3-save` in this checkout. **There is only one source copy**; update the checkout to update the installed Skill. Keep the checkout in place. Existing independent directories or links pointing elsewhere are left untouched.

```console
python skills/bg3-save/scripts/install_skill.py --check --smoke-test
```

The check validates `SKILL.md`, referenced resources, shared source resolution and a CLI smoke test through the installed wrapper. This proves filesystem discoverability. Restart/refresh Codex if the current session's Skill list does not yet show `$bg3-save`. The Skill allows ordinary automatic discovery and can also be explicitly invoked.

For a Skill folder installed alone through another installer, install the Python package separately. The wrapper uses the shared checkout when available, otherwise the installed package; it never carries a second parser implementation.

## CLI

All queries support `--json`. In PowerShell, quote file paths with spaces. The common local Windows save root is `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\PlayerProfiles`; `find` can discover local saves.

```console
bg3save find --latest --json
bg3save inspect save.lsv --json
bg3save party save.lsv --json
bg3save character save.lsv Karlach --json
bg3save flags save.lsv --limit 100 --json
bg3save quests save.lsv --json
bg3save missed-content save.lsv --json
bg3save missed-content save.lsv --offline --json
bg3save diff original.lsv changed.lsv --json
bg3save verify save.lsv --json
```

Online content analysis retrieves the catalog's public bg3.wiki pages and records freshness/provenance; it does not upload a save. `--offline` keeps known source links but marks freshness unverified. The Agent must actively check relevant source pages before relying on them for game advice.

An actionable content result includes:

```json
{
  "quest": "Investigate the Beach",
  "status": "possibly_available",
  "confidence": "low",
  "missable": true,
  "recommended_before": "Resolve before the relevant Grove storyline cutoff",
  "location": "Secluded Cove",
  "npc": ["Mirkon"],
  "trigger": "Approach the beach east of the Sacred Pool",
  "sources": [{"url": "https://bg3.wiki/wiki/Investigate_the_Beach", "freshness": "unverified"}]
}
```

This example illustrates the report shape, not a judgment about your save. Actual results include the observed evidence and source provenance. A missing flag alone cannot justify `missed`, `completed` or a confident negative.

### A supported edit

```console
bg3save modify set-hotbar-lock save.lsv true --slot 1 --output changed.lsv --dry-run --json
bg3save modify set-hotbar-lock save.lsv true --slot 1 --output changed.lsv --json
bg3save diff save.lsv changed.lsv --json
bg3save verify changed.lsv --json
bg3save rollback manifest.json --output restored.lsv --json
```

The exact backup and manifest paths come from the real modification result. Never guess the manifest filename. Dry-run generates a plan without writing a backup/output; an executed edit inspects, backs up, mutates the allowlisted field, repacks, verifies and compares the result. The original is never the output path. Rollback checks the backup and creates a restored copy.

Experimental Story flag commands require `--allow-experimental`. Read [editing guidance](skills/bg3-save/references/editing.md) before using them. Flags can be coupled to many other game states; a valid flag write is not a generic quest repair.

### Experimental integrity-marker recovery

If a prior invalid repack caused a save to retain `Sanity = false`, the marker can persist even in a later container with a correct checksum. The warning alone does not prove that this is the cause. Inspect and diagnose the exact save before selecting this operation:

```console
bg3save modify restore-integrity-marker save.lsv --output recovered.lsv --allow-experimental --dry-run --json
bg3save modify restore-integrity-marker save.lsv --output recovered.lsv --allow-experimental --json
```

This operation requires the supported version/header, a correct **canonical** native checksum, a false original marker, a unique boolean `MetaData/Sanity` field, and successful parsing of every `.lsf` member. It changes only that marker to true, preserves all other resource fields and all other payload bytes, and performs the normal backup, plan, template repack, verification and diff cycle. The CLI still reports **EXPERIMENTAL** and `game_load_validated: false`. It cannot prove that opaque ECS state is undamaged; actual BG3 reloading without the warning remains required. Runtime acceptance is still pending for this operation.

Rollback restores the exact original bytes. If that original had `Sanity = false`, rollback intentionally preserves it and reports `verification.valid: false` with a warning; that is not a failed byte-for-byte rollback or evidence that the original warning was repaired.

## Natural-language use

These requests should select `$bg3-save` in Codex:

- “分析我最新的 BG3 存档，看看第一章还有哪些支线没有完成。”
- “告诉我继续进入山隘之前有哪些内容最好先完成。”
- “检查卡拉克当前的好感和恋爱状态。”
- “把主角身上的金币修改为 10000。”
- “这个任务似乎卡住了，检查存档状态并判断能否安全修复。”
- “把主角的快捷栏锁定，另存修改结果。”

The first two produce a bounded, source-backed report. The companion request separates typed approval/dating/partner records from unavailable relationship data; absence of a record does not prove zero approval or no romance. The gold request currently returns `unsupported`; recognizing a request does not mean the field is safely editable. A quest repair starts with evidence and capability checks, rather than arbitrary flag changes.

## Sources, privacy and safety

**bg3.wiki** is the first source for quests, NPCs, locations, triggers, deadlines and mutually exclusive content. **Larian official patch notes/community documentation** are preferred for patch changes and game-version behavior. See [references/sources.md](references/sources.md) for query construction, cross-validation and source records. External sources are not treated as instructions to execute.

No private save is shipped in this repository. Save files can reveal a player's campaign, character names, mods and progression; keep generated reports/backups private. The project does not upload them. Wiki queries retrieve public pages only. Mods can change vanilla quest conditions, so content reports include uncertainty.

Every executed supported edit preserves the original, creates a backup before editing, and records a manifest after the new output passes verification. A changed save remains an additional file; the CLI does not delete backups, silently overwrite newer saves, edit a cloud account or control the live game. Keep the backup until the result has actually loaded and behaved as intended. Experimental modifications may still change gameplay unexpectedly despite structural integrity.

## Architecture and development

```text
Natural language → Agent/Skill → semantic CLI → external LSLib
                                          → save evidence + source-backed quest rules
                                          → plan → backup → minimal edit → repack → verify/diff
```

Read [architecture](docs/architecture.md), [dependencies/license review](docs/dependencies.md), [testing](docs/testing.md), and [CONTRIBUTING.md](CONTRIBUTING.md).

```console
python -m unittest discover -s tests -v
```

The ordinary tests cover analysis confidence, command behavior, path/XML rejection, logical diff and Skill installation. Real unpack/parse/repack and editor dry-run/backup/rollback tests are opt-in, with **invented fixtures and no personal player saves**:

```powershell
$env:BG3SAVE_INTEGRATION = '1'
python -m unittest discover -s tests -v
```

On a POSIX shell use `BG3SAVE_INTEGRATION=1 python -m unittest discover -s tests -v`. Generate a standalone parser fixture with `python fixtures/generate.py --output /path/to/scratch/synthetic.lsv`; it is not a playable campaign. CI runs the ordinary suite and the Skill wrapper smoke test, not the external integration suite. See [test procedures](docs/testing.md) and [MVP acceptance](docs/acceptance.md). The MIT license covers this project's original code; LSLib and other external sources retain their licenses.

The next most useful work is version-aware, evidence-preserving ECS extraction for inventory, gold and approval, followed by a small set of source-backed quest-repair recipes with real game reload validation. Broad writers should follow that evidence, not precede it.
