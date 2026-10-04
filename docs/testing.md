# Testing

Run the normal suite without personal saves or external binaries:

```console
python -m pip install -e .
python -m unittest discover -s tests -v
python skills/bg3-save/scripts/bg3save.py capabilities --json
```

Committed fixtures must be small synthetic data or fixture-generation inputs. They must not contain a real player save, account metadata, character portraits, licensed game assets, or external executables. The ordinary suite exercises command parsing, structured output, content-rule confidence, path/XML rejection, unsupported operations, logical diff, and Skill installation. Real unpack/repack and the dry-run, backup/rollback and writer-preservation tests are explicitly skipped unless external integration is enabled.

CI runs that suite on Windows and Linux with Python 3.11 and 3.13. It does not download proprietary BG3 data, access a user's cloud saves, or enable game debugging. External-backend integration is opt-in, because LSLib is separately obtained and license-reviewed.

## Backend integration

Follow [dependency setup](dependencies.md), then enable tests against the actual LSLib backend. They generate invented LSPK/LSF/Osiris inputs rather than loading private player saves.

PowerShell:

```powershell
$env:BG3SAVE_INTEGRATION = '1'
python -m unittest discover -s tests -v
```

POSIX shell:

```sh
BG3SAVE_INTEGRATION=1 python -m unittest discover -s tests -v
```

To generate an individual parser fixture outside the checkout:

```console
python fixtures/generate.py --output /path/to/scratch/synthetic.lsv
bg3save inspect /path/to/scratch/synthetic.lsv --json
bg3save verify /path/to/scratch/synthetic.lsv --json
```

The generated `.lsv` is **not a playable BG3 campaign**, and must not be used as an in-game compatibility test. With no `--output`, the generator chooses a unique location in the private cache.

For a separate game-format acceptance check, use a private local `.lsv` that you own. Keep all output and backups outside the checkout. A complete integration run should establish:

1. The original SHA-256 and format/version evidence.
2. Package extraction and resource/Story parsing.
3. Structured `inspect`, `party`, `flags`, `quests`, `missed-content` and `verify` outputs.
4. A `modify set-hotbar-lock` dry-run with no output or backup mutation.
5. A real new-output hotbar-lock change with an unchanged original and a verified backup.
6. Successful parse/verify of the repacked save and a diff confined to the intended metadata change.
7. Rollback from the emitted manifest and byte identity of the restored copy and original.

For gameplay acceptance, load the new save in the matching BG3 version and confirm that it resumes and the selected player's hotbar lock matches the requested state. Record this as a separate result; a green unit suite and a successfully reparsed container cannot establish runtime acceptance.

The experimental `restore-integrity-marker` path needs separate tests for explicit opt-in, a false marker, canonical checksum and every-LSF parsing, a unique boolean field, dry-run without artifacts, a minimal metadata change and unchanged payloads. Rollback must recover the exact false-marker source and report `verification.valid: false` with a warning. A successful game reload for this recovery is a separate runtime result; it is not established by those tests and is currently pending.

## Skill installation smoke test

After all required tests pass:

```console
python skills/bg3-save/scripts/install_skill.py --smoke-test
python skills/bg3-save/scripts/install_skill.py --check --smoke-test
```

The installer validates the linked `SKILL.md`, referenced scripts, metadata and core references, resolves the installed link back to the repository, and executes `capabilities --json` through the installed wrapper. The report proves filesystem discoverability; a running Codex session may need a restart or Skill refresh before its catalog includes the new Skill.

The skill-creator validator can additionally check frontmatter and unfinished scaffolding when that built-in skill is available. It does not replace runnable smoke tests or an independent behavioral review.

On Windows, run that validator with `python -X utf8` if the interpreter's default text encoding is not UTF-8. The Skill contains Chinese example requests; an encoding error in the validator is not an invalid Skill frontmatter result.

The initial independent behavior checks are recorded in [skill-forward-test.md](skill-forward-test.md), including unsupported-gold handling, Mountain Pass uncertainty, actual mod metadata, command routing, and installation preservation.
