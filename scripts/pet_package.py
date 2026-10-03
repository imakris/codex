#!/usr/bin/env python3
"""Wrap a prebuilt canonical Codex package in a standalone fork npm tarball."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
os.environ.setdefault("CODEX_REPO_ROOT", str(REPO_ROOT))

from codex_package.cli import parse_package_version
from codex_package.layout import validate_package_dir
from codex_package.targets import PACKAGE_VARIANTS, TARGET_SPECS

TARGETS = {
    "x86_64-pc-windows-msvc": "win32",
    "x86_64-unknown-linux-musl": "linux",
}
RELEASE_URL = "https://github.com/imakris/codex/releases/latest/download"


def stage_package(package_dir: Path, staging_dir: Path, target: str, version: str) -> None:
    """Reuse upstream staging and validate every mandatory native resource."""
    platform = TARGETS[target]
    spec = TARGET_SPECS[target]
    parse_package_version(version)
    validate_package_dir(
        package_dir, PACKAGE_VARIANTS["codex"], spec, include_zsh=spec.is_linux
    )
    metadata = json.loads((package_dir / "codex-package.json").read_text(encoding="utf-8"))
    if metadata.get("version") != version:
        raise RuntimeError("Canonical package version does not match npm version")

    module_spec = importlib.util.spec_from_file_location(
        "upstream_npm_builder", REPO_ROOT / "codex-cli/scripts/build_npm_package.py"
    )
    builder = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(builder)
    builder.prepare_staging_dir(staging_dir)
    builder.stage_sources(staging_dir, version, "codex")
    shutil.copytree(package_dir, staging_dir / "vendor" / target)
    shutil.copy2(REPO_ROOT / "LICENSE", staging_dir / "LICENSE")
    shutil.copy2(REPO_ROOT / "NOTICE", staging_dir / "NOTICE")

    package_json = staging_dir / "package.json"
    package = json.loads(package_json.read_text(encoding="utf-8"))
    package.update(
        name="@imakris/codex-pet",
        description="Unofficial Codex CLI fork with composer-only pet layout",
        bin={"codex-pet": "bin/codex.js"},
        os=[platform],
        cpu=["x64"],
        files=["bin", "vendor", "LICENSE", "NOTICE"],
        repository={"type": "git", "url": "git+https://github.com/imakris/codex.git"},
    )
    package.pop("optionalDependencies", None)
    package_json.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    (staging_dir / "README.md").write_text(
        "# Codex pet fork\n\nUnofficial build from https://github.com/imakris/codex.\n\n"
        f"Install or update: `npm install -g {RELEASE_URL}/codex-pet-{platform}-x64.tgz`.\n\n"
        "Run `codex-pet`. Node.js is required; no compiler is needed.\n",
        encoding="utf-8",
    )

    launcher = staging_dir / "bin/codex.js"
    launcher.write_text(fork_launcher(launcher.read_text(encoding="utf-8")), encoding="utf-8")


def fork_launcher(source: str) -> str:
    """Keep upstream spawning semantics while pinning lookup to this payload."""
    start = "const platformPackage = PLATFORM_PACKAGE_BY_TARGET[targetTriple];"
    end = "const binaryPath = findCodexExecutable();"
    if source.count(start) != 1 or source.count(end) != 1:
        raise RuntimeError("Upstream launcher changed; review bundled executable lookup")
    first, last = source.index(start), source.index(end)
    if first >= last:
        raise RuntimeError("Upstream launcher executable lookup is out of order")
    replacement = '''function findCodexExecutable() {
  const executable = path.join(
    __dirname, "..", "vendor", targetTriple, "bin",
    process.platform === "win32" ? "codex.exe" : "codex",
  );
  if (!existsSync(executable)) {
    throw new Error(
      `Missing bundled Codex executable. Reinstall: npm install -g RELEASE_URL/codex-pet-${process.platform}-x64.tgz`,
    );
  }
  return executable;
}

'''.replace("RELEASE_URL", RELEASE_URL)
    source = source[:first] + replacement + source[last:]
    managed_flag = 'env[packageManagerEnvVar] = "1";'
    if source.count(managed_flag) != 1:
        raise RuntimeError("Upstream launcher changed; review update ownership flags")
    # Native npm update actions install @openai/codex, so this fork must not opt in.
    return source.replace(managed_flag, "")


def npm_command() -> str:
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if executable is None:
        raise RuntimeError("npm is required to package or install the fork")
    return executable


def pack_package(staging_dir: Path, output_path: Path) -> Path:
    """Use npm's pack format, resolving npm.cmd explicitly on Windows."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-pet-pack-") as temporary:
        packed = Path(temporary)
        result = subprocess.check_output(
            [npm_command(), "pack", "--ignore-scripts", "--json", "--pack-destination", str(packed)],
            cwd=staging_dir,
            text=True,
        )
        filename = json.loads(result)[0]["filename"]
        shutil.move(str(packed / filename), output_path)
    return output_path


def smoke(tarball: Path, prefix: Path, target: str) -> None:
    """Install into an empty prefix and exercise the installed native payload."""
    if prefix.exists() and any(prefix.iterdir()):
        raise RuntimeError("Smoke installation prefix must be empty")
    subprocess.run(
        [npm_command(), "install", "--global", "--prefix", str(prefix), "--ignore-scripts",
         "--no-audit", "--no-fund", str(tarball.resolve())],
        check=True,
    )
    modules = prefix / ("node_modules" if os.name == "nt" else "lib/node_modules")
    installed = modules / "@imakris/codex-pet"
    spec = TARGET_SPECS[target]
    native = installed / "vendor" / target
    validate_package_dir(native, PACKAGE_VARIANTS["codex"], spec, include_zsh=spec.is_linux)
    for argument in ("--version", "--help"):
        subprocess.run(["node", str(installed / "bin/codex.js"), argument], check=True)
    subprocess.run(
        [str(native / "bin" / f"codex-code-mode-host{spec.exe_suffix}"), "--help"],
        check=True,
    )
    subprocess.run([str(native / "codex-path" / spec.rg_name), "--version"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--version", type=parse_package_version, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="codex-pet-npm-") as temporary:
        staging = Path(temporary) / "package"
        stage_package(args.package_dir, staging, args.target, args.version)
        tarball = pack_package(
            staging, args.output_dir / f"codex-pet-{TARGETS[args.target]}-x64.tgz"
        )
        if args.smoke:
            smoke(tarball, Path(temporary) / "installed", args.target)
        print(tarball)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
