# Dependency research and reproducible setup

The save parser reuses [Norbyte/LSLib](https://github.com/Norbyte/lslib), rather than implementing LSPK, LSF or Osiris binary formats again. Dependency binaries are downloaded to a user cache and are **not committed** to this repository. No real player saves are included.

## License and reuse decisions

| Project | Checked license | Decision |
|---|---|---|
| [LSLib v1.20.4](https://github.com/Norbyte/lslib/tree/v1.20.4) | [MIT, Copyright 2015 Norbyte](https://github.com/Norbyte/lslib/blob/v1.20.4/LICENSE) | Use the official release's Divine CLI and reference `LSLib.dll` in a small .NET adapter. Keep its full permission notice with the cached dependency. |
| [BG3 Script Extender](https://github.com/Norbyte/bg3se) | [MIT with Commons Clause v1.0](https://github.com/Norbyte/bg3se/blob/main/LICENSE) | Evaluated for native runtime repair. No BG3SE code or binaries are bundled or required by this offline MVP. Its license is **not plain MIT**; any later distribution/integration requires a fresh review. |

The Commons Clause restricts selling software whose value substantially derives from that dependency, including certain paid hosting/support services. This project does not infer an unrestricted commercial license from BG3SE's MIT paragraph.

The official ExportTool ZIP contains additional tools and native libraries with their own provenance. They are kept outside this repository; the project does not relicense or redistribute the entire ZIP as MIT. Only the save-related LSLib/Divine APIs are called. Game code, assets and proprietary/private saves must not be added to this repository.

## Install the pinned toolchain

Requirements: Python 3.11+, .NET SDK 8 or newer, and a .NET 8 runtime. Windows x64 is tested. Other operating systems remain experimental because upstream native compression libraries are platform dependent.

From the repository root:

```powershell
python tools/bootstrap-lslib.py
```

Offline installation with an already downloaded, unmodified official archive:

```powershell
python tools/bootstrap-lslib.py --archive C:\Downloads\ExportTool-v1.20.4.zip
```

The archive is pinned to:

- Release: [LSLib v1.20.4](https://github.com/Norbyte/lslib/releases/tag/v1.20.4)
- Asset: `ExportTool-v1.20.4.zip`
- SHA-256: `5e02368fb8acafda9b45acba37a3f3bf507fc3d65a083a159abbeab06337190e`
- Download: `https://github.com/Norbyte/lslib/releases/download/v1.20.4/ExportTool-v1.20.4.zip`

This digest was checked against the official GitHub release asset metadata and the local official ZIP. A hash mismatch fails closed. ZIP path traversal and symlinks are rejected before extraction.

By default, the manifest is `%LOCALAPPDATA%\bg3-save-skill\toolchain.json` on Windows, or `~/.cache/bg3-save-skill/toolchain.json` elsewhere. The cache is outside the Git repository. A packaged Codex app can virtualize `LOCALAPPDATA`; use the manifest path printed by the command instead of assuming a particular `C:\Users\...` directory.

`--cache-dir <directory>` chooses another cache. `--no-build` downloads/checks the dependency without building; inspection requiring the bridge will still need a subsequent normal bootstrap.

The manifest records `divine`, `bridge`, `lslib_dir`, version, checksum, source URL, and license notice path. The CLI's toolchain discovery reads this manifest. Rerun bootstrap after editing the C# adapter to rebuild it.

Manual adapter build, useful when reusing an existing official installation:

```powershell
dotnet build tools/lslib-bridge/Bg3Save.LSLibBridge.csproj -c Release `
  "-p:LSLibDir=C:\Tools\ExportTool\Packed\Tools" -o C:\Tools\bg3save-bridge
```

## Adapter API

All adapter outputs are JSON. Errors are JSON on stderr with exit code 2. Mutation output paths must not already exist and must differ from inputs. The Python CLI owns backup, transaction, dry-run, repack, verification and rollback policy; the adapter is an internal implementation detail.

```text
dotnet <bridge.dll> package-list <save.lsv>
dotnet <bridge.dll> package-create <unpacked-directory> <output.lsv> [18 [--template original.lsv]]
dotnet <bridge.dll> resource-convert <input.lsf-or-lsx> <output.lsf-or-lsx> [--template original.lsf]
dotnet <bridge.dll> story-read <StorySave.bin> [output.json]
dotnet <bridge.dll> story-roundtrip <StorySave.bin> <output.bin>
dotnet <bridge.dll> story-set-global-flag <StorySave.bin> <output.bin> <full-flag-name_UUID>
dotnet <bridge.dll> story-unset-global-flag <StorySave.bin> <output.bin> <full-flag-name_UUID-or-UUID>
dotnet <bridge.dll> fixture-story <output.bin>
```

`package-list` returns `{version, parts, header_md5, computed_md5, checksum_valid, computed_canonical_md5, canonical_checksum_valid, physical_order, flags, priority, entries: [{name, size, deleted, crc, flags, archive_part, offset_in_file}]}`. The Python layer validates member paths, duplicates, required entries and size budgets before running extraction. Repacking currently accepts only **LSPK v18** with `PackageBuildData.Hash = true`.

The native v18 checksum hashes the uncompressed members in **ordinal case-insensitive full-path order**, then increments each MD5 byte by one. Native physical write order follows that same order, but its file-table order can differ. `computed_md5` remains a physical-order diagnostic for compatibility; **its match alone is insufficient**. `computed_canonical_md5` and `canonical_checksum_valid` expose the separate native-order check. Both must match before a template is accepted. In particular, `LevelCache/...` must be sorted together with all top-level members, rather than appended after them.

Upstream `Packager.CreatePackage` traverses top-level files separately from subdirectories. Its writer hashes `Build.Files` in that traversal order for v18. An unchanged repack can therefore match its own physical-order hash while failing the native canonical-order hash. This defect was reproduced with prior repacks, while two native player saves matched both calculations. The adapter bypasses that traversal and explicitly constructs the canonical ordered file list. A flat test fixture would not detect this defect; the regression test includes nested members.

Production edits use `--template original.lsv`. The template preserves the original physical order, independent file-table order, per-member compression flags, package flags and priority. Only the verified single-part v18 save layout with package flags `0` and priority `0` is accepted. Missing/extra members, invalid checksums, deletion entries, symbolic links and junctions fail closed. Template compression uses the original method and level; the tested native saves use Zstd/default flags `35`. Repacking a generated fixture without a template uses zlib and canonical order. Upstream Divine also special-cases `.lsv` to zlib, but compression choice by itself does not fix wrong checksum order.

The template adapter uses LSLib's existing `PackageWriter.WriteFile`, padding, compression, archive-hash routine, header factory, structure serializer and compressed file-list serializer. It does **not** implement a second LSPK serializer. The pinned v1.20.4 header/file-entry types and file-list method are internal, so a small isolated reflection boundary calls those exact upstream serializers. If that API is missing, the operation fails; changing the dependency version requires rebuilding and rerunning the regression tests.

Disabling `Sanity` or suppressing the game's corruption warning is prohibited. A later native save can already carry `Sanity=False` after loading a previously invalid repack; a correct new container hash does not repair that inherited state. Such a source requires a separately justified, minimal repair and an actual game load test. Neither a checksum match nor successful structural parsing proves a campaign is semantically intact or that the game will load it without a warning.

`resource-convert --template original.lsf` keeps the original LSF container revision, game metadata and metadata format when writing back edited LSX. LSLib's `Resource` object does not retain the container revision, so the adapter reads only the fixed validated LSF signature/revision header; all actual resource parsing/writing is still performed by LSLib. For an LSF input, that input automatically supplies the template metadata.

`story-read` exports every database schema and typed fact, including GUID strings and numeric values. It does not translate facts into game conclusions. The Python/content analysis layer interprets selected records conservatively.

`story-roundtrip` verifies database schemas and typed facts after native StoryWriter/StoryReader roundtrip. This is structural evidence, not a guarantee that the game will accept all possible saves.

Global-flag operations are **EXPERIMENTAL**, even when their serialization roundtrip passes. They edit only `DB_GlobalFlag` facts, bypass game callbacks and do not synchronize ECS flags, quest journal state, cached character state or downstream quest consequences. They must not be advertised as a complete quest repair or NPC resurrection. GUID suffix matching prevents duplicate facts caused by different symbolic labels for the same UUID.

`fixture-story` constructs invented Osiris 1.15 data with one synthetic active global flag and a separate synthetic flag definition catalog. The parameter uses a proper `FLAG` alias of `GUIDSTRING`, matching real typed schemas. The definition catalog must not be interpreted as an active flag. It contains no game story scripts or private player data. Such a fixture is for parser tests; it is not a playable BG3 campaign save.

## Current verification evidence

The adapter was exercised against a private local BG3 save with product version **4.1.1.7631656**, Osiris **1.15**, LSPK **18**, and metadata LSF **7**. The save itself is not committed.

- Typed story export: 15,753 database schemas and 63,816 facts parsed.
- Story roundtrip: complete exported database schemas/facts unchanged.
- Experimental flag add and UUID-based removal: both roundtrips verified in scratch files outside the game save directory.
- Metadata LSF → LSX → LSF with original template → LSX: all XML node names and attributes matched exactly.
- Synthetic story generation and readback succeeded.
- Checksum-pinned offline bootstrap and .NET bridge build succeeded.
- Native template repack: every extracted payload byte, file-table order, physical order and compression flag preserved for two private native saves. Both checksums matched each source's original header. The compressed bytes can differ without altering any uncompressed payload.
- Regression tests include nested-path canonical checksum order, template member/order/compression preservation, missing/extra member rejection and an optional private native-save roundtrip.

The CLI tests and separate game-load observations provide the higher-level editor evidence. One diagnosed integrity-marker recovery loaded without the warning and was natively re-saved with a true marker and valid checksums on 2026-10-04; see [acceptance evidence](acceptance.md). A hotbar metadata output also loaded cleanly, but its subsequent native save contained true after an edited false value; UI effect and persistence remain unverified. The adapter never reports an in-game load check it did not perform, and all current save-edit operations remain experimental.

## Primary implementation references

- [PackageReader and package version handling](https://github.com/Norbyte/lslib/blob/v1.20.4/LSLib/LS/PackageReader.cs)
- [PackageWriter hashing and existing serializers](https://github.com/Norbyte/lslib/blob/v1.20.4/LSLib/LS/PackageWriter.cs)
- [Upstream corruption report #272](https://github.com/Norbyte/lslib/issues/272)
- [Upstream unchanged-repack warning report #292](https://github.com/Norbyte/lslib/issues/292)
- [Divine savegame zlib selection](https://github.com/Norbyte/lslib/blob/v1.20.4/Divine/CLI/CommandLinePackageProcessor.cs)
- [Resource loading/writing and metadata options](https://github.com/Norbyte/lslib/blob/v1.20.4/LSLib/LS/ResourceUtils.cs)
- [LSFWriter](https://github.com/Norbyte/lslib/blob/v1.20.4/LSLib/LS/Resources/LSF/LSFWriter.cs)
- [StoryReader/StoryWriter](https://github.com/Norbyte/lslib/blob/v1.20.4/LSLib/LS/Story/Story.cs)
- [Typed story values and validity flags](https://github.com/Norbyte/lslib/blob/v1.20.4/LSLib/LS/Story/Value.cs)
- [BG3SE debugger architecture](https://github.com/Norbyte/bg3se/blob/main/Docs/Debugger.md)
