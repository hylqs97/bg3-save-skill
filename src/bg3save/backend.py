"""Invoke the licensed LSLib toolchain; never decode LSPK/LSF ourselves."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from .errors import SaveError

MAX_SAVE_BYTES = 512 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 10000


def cache_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "bg3-save-skill"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_entries(entries: list[dict]) -> None:
    if not entries or len(entries) > MAX_ENTRIES:
        raise SaveError("invalid_archive", "Empty archive or too many entries")
    seen, total = set(), 0
    for entry in entries:
        name = entry.get("name", "").replace("\\", "/")
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or re.match(r"^[A-Za-z]:", name)
                or any(part in (".", "..", "") or part.endswith((".", " "))
                       or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                       for part in name.split("/"))
                or any(character in name for character in ':\x00<>|"?*')
                or any(ord(character) < 32 for character in name)):
            raise SaveError("unsafe_archive_path", f"Rejected archive member {name!r}")
        folded = name.casefold()
        if folded in seen:
            raise SaveError("duplicate_archive_path", f"Duplicate archive member {name!r}")
        seen.add(folded)
        if entry.get("deleted"):
            raise SaveError("deleted_archive_member", "Deleted entries are not supported for save editing")
        size = entry.get("size")
        if not isinstance(size, int) or size < 0:
            raise SaveError("invalid_archive", "Invalid uncompressed size")
        total += size
    if total > MAX_UNPACKED_BYTES:
        raise SaveError("archive_too_large", "Unpacked size exceeds the 2 GiB safety limit")


class Backend:
    def __init__(self, divine=None, bridge=None):
        config = {}
        config_file = cache_root() / "toolchain.json"
        if config_file.is_file():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8-sig"))
            except (ValueError, OSError) as error:
                raise SaveError("invalid_toolchain_config", str(error)) from error
            if not isinstance(config, dict):
                raise SaveError("invalid_toolchain_config", "toolchain.json must contain an object")
            for field in ("divine", "bridge"):
                if config.get(field) is not None and not isinstance(config[field], str):
                    raise SaveError("invalid_toolchain_config", f"toolchain.json/{field} must be a path string or null")
        self.divine = Path(divine or os.environ.get("BG3SAVE_DIVINE") or config.get("divine") or "Divine.exe")
        self.bridge = Path(bridge or os.environ.get("BG3SAVE_BRIDGE") or config.get("bridge")
                           or cache_root() / "bridge" / "Bg3Save.LSLibBridge.dll")

    def _run(self, command: list[str], *, json_output=False, timeout=180):
        try:
            process = subprocess.run(command, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SaveError("backend_unavailable", "Install the pinned LSLib toolchain or supply --divine and --bridge",
                            details=str(error)) from error
        if process.returncode:
            raise SaveError("backend_error", "LSLib rejected the operation",
                            details=(process.stderr or process.stdout)[-3000:])
        if json_output:
            try:
                return json.loads(process.stdout)
            except ValueError as error:
                raise SaveError("backend_invalid_json", "Invalid bridge result") from error
        return process.stdout

    def call(self, command: str, *args, json_output=True):
        return self._run(["dotnet", str(self.bridge), command, *map(str, args)], json_output=json_output)

    def list_package(self, path: Path) -> dict:
        if not path.is_file() or path.suffix.lower() != ".lsv":
            raise SaveError("invalid_save", "Expected an existing .lsv file")
        if path.stat().st_size > MAX_SAVE_BYTES:
            raise SaveError("save_too_large", "Save exceeds 512 MiB")
        result = self.call("package-list", path)
        if result.get("parts", 1) != 1:
            raise SaveError("split_archive_unsupported", "Multi-part save packages are not supported")
        validate_entries(result["entries"])
        return result

    def unpack(self, source: Path, destination: Path) -> dict:
        package = self.list_package(source)
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise SaveError("unsafe_destination", "Unpack destination must be empty")
        self._run([str(self.divine), "-g", "bg3", "-a", "extract-package", "-s", str(source), "-d", str(destination)])
        files = {p.relative_to(destination).as_posix().casefold(): p for p in destination.rglob("*") if p.is_file()}
        for entry in package["entries"]:
            path = files.get(entry["name"].replace("\\", "/").casefold())
            if path is None or path.stat().st_size != entry["size"] or path.is_symlink():
                raise SaveError("unpack_mismatch", "Extraction did not match the archive manifest")
        if len(files) != len(package["entries"]):
            raise SaveError("unpack_mismatch", "Unexpected extracted archive member")
        return package

    def convert(self, source: Path, destination: Path, *, template: Path | None = None) -> None:
        args = [source, destination]
        if template is not None:
            args.extend(["--template", template])
        self.call("resource-convert", *args, json_output=False)

    def repack(self, directory: Path, output: Path, version: int, *, template: Path | None = None) -> None:
        if output.exists():
            raise SaveError("output_exists", "Repack output already exists")
        args = [directory, output, version]
        if template is not None:
            args.extend(["--template", template])
        self.call("package-create", *args)

    def read_story(self, path: Path, json_path: Path) -> dict:
        self.call("story-read", path, json_path, json_output=False)
        return json.loads(json_path.read_text(encoding="utf-8-sig"))
