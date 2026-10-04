#!/usr/bin/env python3
"""Install a checksum-pinned upstream toolchain outside the source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = "1.20.4"
SHA256 = "5e02368fb8acafda9b45acba37a3f3bf507fc3d65a083a159abbeab06337190e"
ASSET_URL = f"https://github.com/Norbyte/lslib/releases/download/v{VERSION}/ExportTool-v{VERSION}.zip"
LICENSE_URL = f"https://raw.githubusercontent.com/Norbyte/lslib/v{VERSION}/LICENSE"


def default_cache() -> Path:
    base = Path(os.environ["LOCALAPPDATA"]) if os.name == "nt" and os.environ.get("LOCALAPPDATA") else Path.home() / ".cache"
    return base / "bg3-save-skill"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, output: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "bg3-save-skill/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response, output.open("wb") as destination:
        shutil.copyfileobj(response, destination)


def safe_extract(archive: Path, directory: Path) -> None:
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            normalized = info.filename.replace("\\", "/")
            name = PurePosixPath(normalized)
            if name.is_absolute() or ".." in name.parts or ":" in normalized or "\x00" in normalized:
                raise ValueError("Unsafe path in official dependency archive")
            # A ZIP symlink must never redirect later extraction outside the cache.
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Dependency ZIP contains a symlink")
            target = (directory / Path(*name.parts)).resolve()
            if not target.is_relative_to(directory.resolve()):
                raise ValueError("Dependency path escaped the cache")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an existing official ZIP; SHA256 is still checked.")
    parser.add_argument("--cache-dir", type=Path, default=default_cache())
    parser.add_argument("--no-build", action="store_true", help="Fetch LSLib only; a .NET SDK is required to build later.")
    args = parser.parse_args()
    cache = args.cache_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"ExportTool-v{VERSION}.zip"
    if args.archive:
        chosen = args.archive.expanduser().resolve()
        if sha256(chosen) != SHA256:
            raise ValueError("LSLib ZIP SHA256 mismatch; refusing installation")
        if chosen != archive:
            shutil.copyfile(chosen, archive)
    elif not archive.exists() or sha256(archive) != SHA256:
        with tempfile.TemporaryDirectory(prefix="bg3save-download-", dir=cache) as temporary:
            staged = Path(temporary) / "toolchain.zip"
            fetch(ASSET_URL, staged)
            if sha256(staged) != SHA256:
                raise ValueError("Downloaded LSLib ZIP SHA256 mismatch; refusing installation")
            shutil.copyfile(staged, archive)
    if sha256(archive) != SHA256:
        raise ValueError("Cached LSLib archive failed SHA256 validation")
    upstream = cache / f"lslib-{VERSION}"
    if not (upstream / "Packed" / "Tools" / "LSLib.dll").exists():
        safe_extract(archive, upstream)
    tools = upstream / "Packed" / "Tools"
    if not (tools / "LSLib.dll").is_file():
        raise ValueError("Official release does not contain expected Packed/Tools/LSLib.dll")
    # Store the upstream permission notice next to the externally cached distribution.
    license_path = upstream / "LICENSE.LSLib.txt"
    if not license_path.exists():
        license_path.write_text(LSLIB_LICENSE, encoding="utf-8")
    bridge_directory = cache / "bridge"
    bridge = bridge_directory / "Bg3Save.LSLibBridge.dll"
    if not args.no_build:
        if not shutil.which("dotnet"):
            raise RuntimeError("Install .NET SDK 8 or newer, then rerun bootstrap. LSLib was cached successfully.")
        project = Path(__file__).resolve().parent / "lslib-bridge" / "Bg3Save.LSLibBridge.csproj"
        command = ["dotnet", "build", str(project), "-c", "Release", "--nologo", "-o", str(bridge_directory),
                   f"-p:LSLibDir={tools}", f"-p:BaseIntermediateOutputPath={cache / 'obj'}/"]
        completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if completed.returncode:
            print(completed.stdout, file=sys.stderr)
            print(completed.stderr, file=sys.stderr)
            raise RuntimeError("LSLib bridge build failed")
    divine = tools / ("Divine.exe" if os.name == "nt" else "Divine.dll")
    manifest = {
        "schema_version": 1,
        "lslib_version": VERSION,
        "lslib_archive_sha256": SHA256,
        "source_url": ASSET_URL,
        "license": "MIT",
        "license_file": str(license_path),
        "lslib_dir": str(tools),
        "divine": str(divine),
        "bridge": str(bridge) if bridge.exists() else None,
        "platform_support": "Windows x64 tested; other platforms experimental",
    }
    manifest_path = cache / "toolchain.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"installed": True, "manifest": str(manifest_path), **manifest}, indent=2))
    return 0


LSLIB_LICENSE = """The MIT License (MIT)

Copyright (c) 2015 Norbyte

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(json.dumps({"installed": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(2)
