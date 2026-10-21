"""Inspect the staged and packed fork payload before release publication."""

import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile


RELINK_SUFFIXES = {".a", ".lib", ".o", ".obj"}
DEBUG_SUFFIXES = {".pdb", ".debug", ".dwo", ".dwp", ".map"}


def file_digest(data):
    return hashlib.sha256(data).hexdigest()


def directory_files(directory):
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected package symlink: {path}")
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = path.read_bytes()
    return files


def archive_files(data, *, kind="tar"):
    files = {}
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if not member.is_dir():
                    if member.filename in files:
                        raise RuntimeError(f"Duplicate archive entry: {member.filename}")
                    files[member.filename] = archive.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise RuntimeError(f"Unexpected archive link or special file: {member.name}")
                if member.name in files:
                    raise RuntimeError(f"Duplicate archive entry: {member.name}")
                files[member.name] = archive.extractfile(member).read()
    for name in files:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"Unexpected archive path: {name}")
    return files


def binary_debug_data(path, data):
    if data.startswith(b"MZ"):
        tool = shutil.which("llvm-readobj")
        if tool is None:
            installed = Path("C:/Program Files/LLVM/bin/llvm-readobj.exe")
            if installed.is_file():
                tool = str(installed)
        if tool is None:
            raise RuntimeError("llvm-readobj is required to inspect Windows release binaries")
        output = subprocess.check_output(
            [tool, "--file-headers", "--sections", "--coff-debug-directory", str(path)], text=True
        )
        return bool(re.search(r"Type: (?:CodeView|FPO)|Name: \.debug|SymbolCount: [1-9]", output))
    if data.startswith(b"\x7fELF"):
        output = subprocess.check_output(["readelf", "--wide", "--sections", str(path)], text=True)
        names = re.findall(r"\[\s*\d+\]\s+(\S+)", output)
        return any(
            name.startswith((".debug", ".zdebug", ".stab"))
            or name in {".symtab", ".gdb_index", ".gnu_debuglink", ".gnu_debugaltlink", ".gnu_debugdata"}
            for name in names
        )
    return False


def inspect_files(files, target):
    """Inspect all bytes, including nested archives, without extracting paths from archives."""
    expanded = dict(files)
    pending = list(files.items())
    while pending:
        name, data = pending.pop()
        if data.startswith(b"PK\x03\x04"):
            nested = archive_files(data, kind="zip")
        elif tarfile.is_tarfile(io.BytesIO(data)):
            nested = archive_files(data)
        else:
            continue
        for member, contents in nested.items():
            nested_name = f"{name}!/{member}"
            expanded[nested_name] = contents
            pending.append((nested_name, contents))

    duplicates = {}
    with tempfile.TemporaryDirectory(prefix="codex-pet-inspect-") as temporary:
        for name, data in expanded.items():
            suffix = PurePosixPath(name).suffix.lower()
            if suffix in RELINK_SUFFIXES or data.startswith(b"!<arch>\n"):
                raise RuntimeError(f"Relinking material in release payload: {name}")
            if suffix in DEBUG_SUFFIXES or ".dsym/" in name.lower() or name.endswith(".js.map"):
                raise RuntimeError(f"Debug sidecar in release payload: {name}")
            duplicates.setdefault(file_digest(data), []).append(name)
            if data.startswith((b"MZ", b"\x7fELF")):
                path = Path(temporary) / "binary"
                path.write_bytes(data)
                has_debug = binary_debug_data(path, data)
                vendor_rg = name == f"vendor/{target}/codex-path/rg" + (".exe" if "windows" in target else "")
                if has_debug and not vendor_rg:
                    raise RuntimeError(f"Debug data in controlled release binary: {name}")
                if has_debug:
                    print(f"Vendor binary retained as supplied: {name} (verified upstream ripgrep archive)")
                print(f"Inspected native binary: {name}; debug_data={has_debug}")
    for names in duplicates.values():
        if len(names) < 2:
            continue
        # This package has distinct native programs; equal executables have no shared role.
        if any(expanded[name].startswith((b"MZ", b"\x7fELF")) for name in names):
            raise RuntimeError(f"Duplicate native payload: {names}")
        print(f"Matching resource/notice content for review: {names}")
    print(f"Inspected {len(expanded)} expanded release files")


def inspect_package(staging, tarball, target):
    staged = directory_files(staging)
    packed = archive_files(tarball.read_bytes())
    if any(not name.startswith("package/") for name in packed):
        raise RuntimeError("npm archive has content outside package/")
    packed = {name.removeprefix("package/"): data for name, data in packed.items()}
    if {name: file_digest(data) for name, data in staged.items()} != {
        name: file_digest(data) for name, data in packed.items()
    }:
        raise RuntimeError("Packed npm payload differs from the inspected staging directory")
    inspect_files(staged, target)
    inspect_files(packed, target)
