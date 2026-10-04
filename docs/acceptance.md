# MVP acceptance evidence

This maps the requested sixteen acceptance items to reproducible evidence. A parser fixture is synthetic and not playable; private game saves and audit outputs remain outside the public repository. The installed revision's `capabilities --json` controls operation support.

| # | Requirement | Authoritative evidence |
|---|---|---|
| 1 | Find and open a BG3 `.lsv` | `bg3save find --latest --json`; real private-save inspection and synthetic fixture `test_real_unpack_parse_and_inspect` |
| 2 | Unpack and parse basic data | Opt-in real LSLib tests in `tests/test_backend.py`, LSPK 18/LSF/Osiris parsing; [backend version evidence](dependencies.md#current-verification-evidence) |
| 3 | Structured summary | JSON `inspect`, `party`, `character`; fixture assertions in backend/service tests; unknown fields retain null/unsupported status |
| 4 | Identify some Quest/Story flags | Typed global/object flags and journal steps, with source IDs; successful/failure/closed/absent evidence tests in `tests/test_content.py` |
| 5 | Source-backed possible-missed report | Twenty curated rules, wiki retrieval/provenance and confidence tests; [independent Skill scenarios](skill-forward-test.md); `missed-content SAVE --json` |
| 6 | At least one verified safe modification | `modify set-hotbar-lock SAVE false --slot 1 --output NEW --json`; actual LSLib metadata/repack preservation test **and a matching BG3 reload without the modified/corrupted-save warning**, with the requested hotbar state observed |
| 7 | Automatic backup before writes | `test_safe_edit_preserves_all_unmodified_payloads_and_has_verified_backup`; modification result and hashed backup manifest |
| 8 | Dry-run | `test_dry_run_creates_no_output_manifest_or_backup`; real CLI `--dry-run` report has `written: false` |
| 9 | Diff | `diff ORIGINAL CHANGED --json`; typed Story row-order test and minimal changed-member assertions |
| 10 | Verify | `verify SAVE --json`; actual LSLib extraction/resource/Story parse; explicit `game_load_validated: false` unless a separate real reload occurred |
| 11 | Automated tests | `python -m unittest discover -s tests -v`; `BG3SAVE_INTEGRATION=1` enables actual external-backend tests; ordinary CI matrix in `.github/workflows/ci.yml` |
| 12 | Full README | [README.md](../README.md): purpose, versions, capabilities, unsupported fields, CLI/Skill installation, examples, backup, sources, risks and architecture |
| 13 | Actual Skill | [SKILL.md](../skills/bg3-save/SKILL.md), references, generated UI metadata and runnable wrapper; frontmatter and behavior checks |
| 14 | Commit | `git log -1 --format=%H` and `git status --short` on the delivered checkout |
| 15 | Public repository and push when allowed | GitHub repository visibility/API plus `git ls-remote origin refs/heads/main` compared with local commit |
| 16 | Local Skill installation and smoke test | `install_skill.py --check --smoke-test`: shared source, required files, installed wrapper JSON, discovery-refresh note |

## Verification scope

The full external-backend suite validates an actual LSLib serialization cycle, rather than mocking binary parsing. Safe-write tests establish that all untouched members remain byte-identical, metadata differs only at the planned field, Story semantics stay unchanged, backups match the original, and rollback reproduces the original bytes. Unknown versions and missing slots are rejected before mutation.

The initial independent Skill review passed frontmatter, command routing, unsupported-gold refusal, bounded Mountain Pass recommendations, same-Act region cutoff reasoning, actual capitalized module metadata and linked-installation preservation checks. See [the review record](skill-forward-test.md).

The complete local suite was subsequently recorded on **2026-10-04** as **94 tests, no skips**, with actual LSLib integration enabled and a private native save supplied for the optional template/checksum regression checks. This proves the checks covered by that suite; it does not prove game acceptance, publication or the final real local installation.

Final private-save editing/reload, public GitHub state and the user's real local installation must be verified directly at delivery. Unit tests, synthetic fixtures, a temporary install directory, and a plausible repository URL cannot substitute for those final checks. An actual in-game reload does not make experimental flags or unsupported ECS writers safe.

## Delivery gates

A modified/corrupted-save warning is a failed runtime acceptance check, even if the game permits continuing. A successful structural `verify` result must not be used to dismiss that warning. Preserve the source, examine the original resource/container formats and checksums, fix the writer, and repeat the real reload. Do not turn off the game's `Sanity` check, suppress the warning, or weaken the acceptance requirement.

The explicit `restore-integrity-marker` recovery operation is **EXPERIMENTAL**: a canonical checksum match, successful parsing of every LSF member, a unique false marker, minimal metadata diff, untouched payloads and a verified backup are necessary preflight/transaction evidence. They do not establish gameplay acceptance or replace item 6's supported-edit reload. Runtime verification for this recovery remains pending. Rollback deliberately restores the false original marker and returns a verification warning with exact byte identity.

Commit/push and the real local installation are separate final gates. Check the exact published `main` commit and repository visibility, then run the installed wrapper from the actual Codex Skill path. A temporary test installation proves the installer behavior but does not satisfy item 16.

## Observed delivery state on 2026-10-04

- The public repository is [hylqs97/bg3-save-skill](https://github.com/hylqs97/bg3-save-skill). GitHub confirmed public visibility, and the published `main` matched the local commit when checked.
- The source revision `a3b9696a900946ad4246091fae8f8da9697ca9b3` passed [all four CI jobs](https://github.com/hylqs97/bg3-save-skill/actions/runs/37191443634): Windows and Ubuntu, each with Python 3.11 and 3.13. External-backend/private-save tests are covered by the separate 94-test local run above.
- The actual local Codex installation resolves to the checkout's Skill directory, with no independent parser copy. The installed wrapper passed both `capabilities` and a private candidate's structural `verify`; the latter correctly retained `game_load_validated: false`.
- The running Codex session's available-skills catalog now lists `bg3-save`, and its installed `SKILL.md` was read from that catalog path. This supplies actual discovery evidence in addition to the filesystem/smoke checks.
- Supported hotbar-edit and experimental marker-restoration runtime acceptance are **still unverified**. The Windows desktop was locked and screen capture/input unavailable; neither a completed CI run nor catalog discovery satisfies the game-load gate. The MVP goal remains incomplete until that gate passes.
