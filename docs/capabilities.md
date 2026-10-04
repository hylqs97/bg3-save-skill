# Capability contract

The CLI's `capabilities --json` is authoritative for the installed revision. Documentation describes the current MVP, not a promise that every future save format behaves the same way.

| Tier | Meaning | Current examples |
|---|---|---|
| `SUPPORTED` / `safe` | Implemented deterministic operation with automatic validation and stated format limits | Structured metadata/party/Story queries; output-only hotbar-lock change; backup, dry-run, diff, verify, rollback |
| `EXPERIMENTAL` / `experimental` | Implemented with a real uncertainty that the caller must explicitly opt into | Setting or removing one Story flag; restoring a persisted integrity marker; selected quest/romance interpretations |
| `UNSUPPORTED` / `unsupported` | No reliable implementation or insufficient evidence for this save | Gold/item/approval writes, arbitrary ECS edits, generic quest repair, complete missed-content certification |

An operation's tier does not imply that every individual field can be read. Optional/unknown fields are emitted as unknown with their reasons. A query may be supported while a gameplay inference derived from its evidence is experimental.

## Fields and boundaries

- Metadata, region/Act evidence, save version, mod manifest and party summaries can be queried when present.
- Companion/character summaries expose the values recoverable from save resources, including level, class and experience when available. Optional physical/inventory/approval fields are not fabricated.
- Story flags and journal records are inspectable with raw identifiers and evidence. Typed `DB_ApprovalRating` and `DB_ORI_Dating`/`DB_ORI_Partnered` facts are readable when present. Interpreting selected facts as a full romance state remains experimental; absence is not proof of zero approval or an absent relationship.
- Quest analysis covers the bundled catalog. `unknown` and `possibly_available` are valid outcomes, not parse failures. A deadline beyond the current Act requires supporting task-state evidence before `missed` is reported.
- The safe writer changes the selected client/player slot's `HotbarLocked` metadata boolean only. It does not change HP, quests, items, relationships or character progression. Game-menu save naming is not treated as a reliably editable metadata field.
- Experimental flag writers alter a narrowly specified global Story flag (`DB_GlobalFlag`) through LSLib and are gated by `--allow-experimental`. They do not write object flags or synchronize ECS/triggers and cannot promise to repair the other state a quest expects.
- `restore-integrity-marker` is a separate **EXPERIMENTAL** recovery operation, also requiring `--allow-experimental`. It changes a unique boolean `MetaData/Sanity` from false to true only after a canonical checksum match and parsing every LSF member. It preserves all other metadata fields and all other payload bytes. It does not repair opaque ECS corruption and has no automatic or currently proven runtime acceptance.
- Gold, item addition/removal, approval, resurrection and generic quest-repair writers are unsupported. The Skill still handles those requests by collecting evidence and explaining the supported boundary.

## Unsupported format behavior

The parser reports version/resource/Story limitations instead of silently falling back to byte searching. Unknown formats may permit metadata queries while refusing writes. Malformed containers, unsafe output paths and unsupported semantic operations must fail without overwriting the original.

The ordinary writer requires single-part LSPK 18 with flags and priority both zero, a valid native container checksum, `Sanity = true`, and matching SaveInfo/metadata evidence for product version `4.1.1.7631656`. An already failed sanity check is not silently cleared. Explicit marker restoration requires the same format/version gates and additionally a false marker, a unique boolean field and complete LSF parse checks. Original LSF revision and metadata format are retained by template-based conversion; production repacking retains the original archive layout.

Checksum validation uses the native canonical full-path ordering, not only the diagnostic physical-order hash. Neither checksum equality nor readable LSF data proves that opaque campaign state is semantically valid.

## Verification levels

`verify` checks the properties it reports: extraction, resource parsing, expected members and other implemented structural checks. A write's diff and payload checks establish scope. Neither is an automatic proof that BG3 has loaded the output. In-game reload validation is reported only when actually performed.

A game warning about a modified or corrupted save fails the runtime acceptance gate. Continuing past the warning is not equivalent to a clean reload. See [the delivery gates](acceptance.md#delivery-gates).

Rollback reproduces original bytes, including a failed original sanity marker. For that case it returns a successful byte restoration with `verification.valid: false` and a warning, rather than claiming the original save passes full verification.
