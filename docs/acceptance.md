# MVP acceptance evidence

This maps the requested sixteen acceptance items to reproducible evidence. A parser fixture is synthetic and not playable; private game saves and audit outputs remain outside the public repository. The installed revision's `capabilities --json` controls operation support.

| # | Requirement | Authoritative evidence |
|---|---|---|
| 1 | Find and open a BG3 `.lsv` | `bg3save find --latest --json`; real private-save inspection and synthetic fixture `test_real_unpack_parse_and_inspect` |
| 2 | Unpack and parse basic data | Opt-in real LSLib tests in `tests/test_backend.py`, LSPK 18/LSF/Osiris parsing; [backend version evidence](dependencies.md#current-verification-evidence) |
| 3 | Structured summary | JSON `inspect`, `party`, `character`; fixture assertions in backend/service tests; unknown fields retain null/unsupported status |
| 4 | Identify some Quest/Story flags | Typed global/object flags and journal steps, with source IDs; successful/failure/closed/absent evidence tests in `tests/test_content.py` |
| 5 | Source-backed possible-missed report | Twenty curated rules, wiki retrieval/provenance and confidence tests; [independent Skill scenarios](skill-forward-test.md); `missed-content SAVE --json` |
| 6 | At least one verified safe modification or repair | One diagnosed `modify restore-integrity-marker SAVE --output NEW --allow-experimental --json` recovery: exact output, minimal marker-only diff, backup/rollback, warning-free BG3 load, then native re-save with a true marker and valid checksums; see the case evidence below |
| 7 | Automatic backup before writes | `test_experimental_metadata_edit_preserves_payloads_and_has_verified_backup`; modification result and hashed backup manifest |
| 8 | Dry-run | `test_dry_run_creates_no_output_manifest_or_backup`; real CLI `--dry-run` report has `written: false` |
| 9 | Diff | `diff ORIGINAL CHANGED --json`; typed Story row-order test and minimal changed-member assertions |
| 10 | Verify | `verify SAVE --json`; actual LSLib extraction/resource/Story parse; automatic `game_load_validated: false`, with actual game reloads recorded separately |
| 11 | Automated tests | `python -m unittest discover -s tests -v`; `BG3SAVE_INTEGRATION=1` enables actual external-backend tests; ordinary CI matrix in `.github/workflows/ci.yml` |
| 12 | Full README | [README.md](../README.md): purpose, versions, capabilities, unsupported fields, CLI/Skill installation, examples, backup, sources, risks and architecture |
| 13 | Actual Skill | [SKILL.md](../skills/bg3-save/SKILL.md), references, generated UI metadata and runnable wrapper; frontmatter and behavior checks |
| 14 | Commit | `git log -1 --format=%H` and `git status --short` on the delivered checkout |
| 15 | Public repository and push when allowed | GitHub repository visibility/API plus `git ls-remote origin refs/heads/main` compared with local commit |
| 16 | Local Skill installation and smoke test | `install_skill.py --check --smoke-test`: shared source, required files, installed wrapper JSON, discovery-refresh note |

## Verification scope

The full external-backend suite validates an actual LSLib serialization cycle, rather than mocking binary parsing. Transaction tests establish that all untouched members remain byte-identical, metadata differs only at the planned field, Story semantics stay unchanged, backups match the original, and rollback reproduces the original bytes. Unknown versions and missing slots are rejected before mutation. These checks do not establish a hotbar UI effect.

The initial independent Skill review passed frontmatter, command routing, unsupported-gold refusal, bounded Mountain Pass recommendations, same-Act region cutoff reasoning, actual capitalized module metadata and linked-installation preservation checks. See [the review record](skill-forward-test.md).

The complete local suite was subsequently recorded on **2026-10-04** as **98 tests, no skips**, with actual LSLib integration enabled and a private native save supplied for the optional template/checksum regression checks. This proves the checks covered by that suite; it does not prove game acceptance, publication or the final real local installation.

Final private-save editing/reload, public GitHub state and the user's real local installation must be verified directly at delivery. Unit tests, synthetic fixtures, a temporary install directory, and a plausible repository URL cannot substitute for those final checks. An actual in-game reload does not make experimental flags or unsupported ECS writers safe.

## Delivery gates

A modified/corrupted-save warning is a failed runtime acceptance check, even if the game permits continuing. A successful structural `verify` result must not be used to dismiss that warning. Preserve the source, examine the original resource/container formats and checksums, fix the writer, and repeat the real reload. Do not turn off the game's `Sanity` check, suppress the warning, or weaken the acceptance requirement.

The explicit `restore-integrity-marker` recovery operation is **EXPERIMENTAL**: a canonical checksum match, successful parsing of every LSF member, a unique false marker, minimal metadata diff, untouched payloads and a verified backup are necessary preflight/transaction evidence. They do not establish gameplay acceptance by themselves. The diagnosed case below additionally passed actual warning-free loading and native re-save checks, supplying item 6's safe-repair example without promoting every marker repair to safe. Rollback deliberately restores the false original marker and returns a verification warning with exact byte identity.

Hotbar metadata writing is **EXPERIMENTAL**. A false-field output loaded without the warning, but the subsequent native save contained true; the cause is not established. That proves container acceptance for the tested output, not the requested UI state or persistence. This feature does not supply item 6's successful semantic-repair evidence, and its UI acceptance requirement has not been waived.

Commit/push and the real local installation are separate final gates. Check the exact published `main` commit and repository visibility, then run the installed wrapper from the actual Codex Skill path. A temporary test installation proves the installer behavior but does not satisfy item 16.

## Observed delivery state on 2026-10-04

- The public repository is [hylqs97/bg3-save-skill](https://github.com/hylqs97/bg3-save-skill). GitHub confirmed public visibility, and the published `main` matched the local commit when checked.
- The source revision `a3b9696a900946ad4246091fae8f8da9697ca9b3` passed [all four CI jobs](https://github.com/hylqs97/bg3-save-skill/actions/runs/37191443634): Windows and Ubuntu, each with Python 3.11 and 3.13. This is a historical published-revision result; check the delivered revision's own run. External-backend/private-save tests are covered by the separate 98-test local run above.
- The actual local Codex installation resolves to the checkout's Skill directory, with no independent parser copy. The installed wrapper passed both `capabilities` and a private candidate's structural `verify`; the latter correctly retained `game_load_validated: false`.
- The running Codex session's available-skills catalog now lists `bg3-save`, and its installed `SKILL.md` was read from that catalog path. This supplies actual discovery evidence in addition to the filesystem/smoke checks.
- The diagnosed integrity-marker recovery passed the actual-load gate described below. Hotbar UI effect/persistence remains unverified and is classified experimental. Neither CI success nor catalog discovery substitutes for those runtime checks.

## Diagnosed integrity-marker recovery case

Observed on **2026-10-04**, using private local saves kept outside this repository:

1. The exact source had a false native `Sanity` marker despite valid canonical and physical archive checksums. Earlier invalid repacks supplied a diagnostic basis for an inherited failed marker; this was not a repair selected from a warning alone.
2. The semantic CLI checked the supported product/container version, unique boolean field, and every LSF member. Dry-run produced the false-to-true plan; execution backed up the original and changed only the marker in `meta.lsf`. Other payloads and Story facts were unchanged. Rollback reproduced the original bytes and its false marker.
3. The generated output and the distinct staged game copy were matched by SHA-256. The player explicitly distinguished the original slot, which still warned, from the repaired slot, which loaded without the warning. Continuing past a warning was not counted as acceptance.
4. The running game then created a native save from the repaired session. Its marker was true and both native checksum calculations passed. Party identity, classes, experience, journal, approval, dating, camp-event and mod summaries were checked against the source; observed ordinary world progression was kept separate from the offline edit.
5. The player continued the same campaign and reported no error for a later native save. That save's session identity matched the source, its marker remained true, and the CLI verification passed.

This is one implemented and verified safe repair under the demonstrated conditions. The general operation remains **EXPERIMENTAL**: checksums, LSF parsing and one successful campaign reload do not certify every opaque ECS component or every other save. The automatic CLI/manifest field remains `game_load_validated: false`, because these runtime checks were observed separately from the CLI. No player save, account path, save hash or runtime screenshot is published here.
