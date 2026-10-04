# Contributing

Use Python 3.11 or newer. Install the package in editable mode from a checkout:

```console
python -m pip install -e .
python -m unittest discover -s tests -v
```

Read [the architecture](docs/architecture.md), [capability boundaries](docs/capabilities.md), and [external-tool licenses](docs/dependencies.md) before changing a parser or editor. LSLib owns LSPK/LSF/LSMF mechanics; avoid an independent binary parser.

Keep deterministic save operations in `src/bg3save`, agent judgment in `skills/bg3-save`, and game knowledge in source-attributed quest rules. A new quest rule needs a current bg3.wiki source, explicit save predicates and exclusions, a confidence rationale, and cases covering both the positive result and uncertainty. Save evidence alone does not make a missing flag a proven missed quest.

For new semantic edits, document the format gate and affected fields; test dry-run, backup, original preservation, output repacking, diff, verify, and rollback. Do not promote a write to `SUPPORTED` until the complete cycle is demonstrated. A round-trip test cannot prove gameplay compatibility; record a real reload separately.

Do not commit personal `.lsv` files, screenshots, extracted private saves, account identifiers, mods, external binaries, or credentials. Use small generated fixtures and explicit opt-in local integration tests. See [testing](docs/testing.md). Test artifacts belong in temporary folders, not fixtures committed by accident.

Submit a focused pull request describing the behavior and validation. Include the supported game/LSLib versions for format changes, source links for quest knowledge, and limits of the evidence. This repository's MIT license covers its own code; external projects and wiki content retain their own licenses.
