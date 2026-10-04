# Safe editing and rollback

## Capability boundary

Use `capabilities --json` and the actual save's version before selecting an edit. The verified baseline is BG3 product version **4.1.1.7631656** (Patch 8 lineage) with Story/Osiris **1.15**, using the tested LSLib backend. The internal Script Extender engine identifier `4.69.95.0` is not the BG3 product version.

All current save-edit operations are **EXPERIMENTAL** and require `--allow-experimental`. Hotbar editing changes the `HotbarLocked` boolean in a selected player/client slot's save metadata. Its small scope makes an automated preservation check practical, but does not establish the game's use of that value. An actual false-field output loaded without the save warning; its subsequent native save contained true. The cause is unknown, and no successful UI effect or persistent hotbar change is claimed. It must not be represented as a gold, inventory or quest writer.

Ordinary writes additionally require single-part package LSPK 18, flags and priority both zero, a valid canonical native archive checksum, `Sanity = true`, and matching SaveInfo/metadata game-version evidence. A physical-order MD5 match alone is insufficient. The original LSF revision and metadata format are retained by template-based conversion, and production repacking preserves the original archive layout. If an input has already been marked `Sanity = false`, the ordinary writer refuses it; do not bypass that refusal with raw edits or by disabling game integrity checks.

`set-flag` and `unset-flag` are **experimental**, require `--allow-experimental`, and are not generic quest repairs. They write only `DB_GlobalFlag`, not object flags or opaque entity state. A story flag can be coupled to databases, journal steps, NPC components, event callbacks and relationships. Missing coupled state must remain a documented uncertainty.

Gold, item add/remove, approval, NPC resurrection, relationship repair, arbitrary ECS writes and “complete every quest” are **unsupported** in this MVP. Do not bypass this by editing raw resources or running an improvised debugger workflow.

## Experimental marker restoration

`modify restore-integrity-marker` is an explicit recovery operation, not an ordinary edit and not a generic damaged-save repair. A previously invalid repack can leave a failed marker in a later container with a correct checksum. That possibility must be supported by diagnostics; a game warning alone does not establish the cause.

The CLI requires `--allow-experimental`, a false original marker, supported version/header, a correct canonical checksum, exactly one boolean `MetaData/Sanity` field, and successful parsing of every LSF member. Dry-run reports these checks and the false-to-true plan. Execution changes only that field, preserves other metadata and all other payload bytes, backs up the source, template repacks, verifies and diffs to a new output.

```console
bg3save modify restore-integrity-marker save.lsv --output recovered.lsv --allow-experimental --dry-run --json
bg3save modify restore-integrity-marker save.lsv --output recovered.lsv --allow-experimental --json
```

The result remains **EXPERIMENTAL** with `game_load_validated: false`: the CLI does not perform a runtime check. Successful LSF parsing does not prove that opaque ECS components are semantically intact. A separately observed, warning-free game reload is required before reporting recovery success. A read-only analysis request does not authorize this write.

One diagnosed private case completed that external acceptance check on 2026-10-04: the exact generated copy loaded without the warning, a native re-save retained a true marker and valid checksums, key party/story summaries were compared, and subsequent continued-play verification passed. This establishes the tested repair, not a general corruption-repair guarantee. For each new source, diagnose and inspect afresh rather than treating that result as proof that all false markers may be cleared.

## Write sequence

1. Read the exact source and inspect its version, relevant field, and existing value. Check that it is not being written by the running game/cloud client.
2. Generate the semantic plan with `--dry-run`. Present the actual before/after field and capability. No output/backup should be created by dry-run.
3. Execute the user's authorized semantic operation, with the required experimental opt-in, to a distinct, new output path. The CLI must automatically back up the original, record hashes and a manifest, preserve untouched members, repack, and verify the result.
4. Inspect `diff` and the writer's validation. The change must be confined to the plan. A failure, unexpected difference, unsupported version or missing field is not success; retain the original and explain the failure.
5. Return the output path, backup/manifest, changed value and verification level. If an actual game reload is authorized and possible, perform it and report the observed result separately.

Do not alter the source in place. Do not load another campaign silently. Do not repeat a write just because monitoring timed out: inspect the existing output, manifest and process state first.

## Rollback

Use the emitted manifest:

```console
bg3save rollback /path/to/manifest.json --output /path/to/restored.lsv --json
```

Rollback verifies the backup's hash and creates a restored copy. It does not delete the original, silently overwrite a newer player save, remove cloud copies or rewrite a live game. If a user wants the restored copy made active, determine the target campaign/save slot and preserve any newer data before performing an authorized placement.

When rolling back marker restoration, the exact original can have `Sanity = false`. The result then reports byte restoration separately from `verification.valid: false` and a warning about the retained game warning. Do not clear the original marker during rollback or describe it as a fully verified playable save.

## Explain uncertainty

Distinguish these outcomes:

- A plan is available, but no modification was executed.
- A write and structural round-trip verification passed.
- A corresponding output was actually loaded in BG3.
- A gameplay outcome was observed after loading.

The latter two cannot be inferred from the first two. A flag that round-trips correctly may still be the wrong semantic repair for a quest.

If BG3 displays the modified/corrupted-save warning, report runtime acceptance as failed even if the user can continue loading. Preserve the source and investigate the actual output; do not present a structural `verify` result as evidence that the warning was resolved.
