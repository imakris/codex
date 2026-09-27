# Install and update the pet fork

The [Pet fork sync and release workflow](https://github.com/imakris/codex/actions/workflows/pet-release.yml)
merges upstream `openai/codex:main`, builds Windows x64 and Linux x64 packages,
and publishes verified builds to [GitHub Releases](https://github.com/imakris/codex/releases).
It runs daily at 07:17 UTC, after pushes to `pet-composer-layout`, and on manual
dispatch. It does not require this computer to be switched on.

## Install without compiling

With Node.js/npm installed, run the command for your platform. Run the same
command again to update to the latest successfully published release.

Windows x64:

```powershell
npm install -g https://github.com/imakris/codex/releases/latest/download/codex-pet-win32-x64.tgz
codex-pet
```

Linux x64:

```sh
npm install -g https://github.com/imakris/codex/releases/latest/download/codex-pet-linux-x64.tgz
codex-pet
```

These are self-contained `@imakris/codex-pet` npm tarballs hosted on GitHub;
there is no npm registry publication or npm account requirement. They install
the `codex-pet` command alongside an existing official `codex` installation.
Both use normal Codex configuration and authentication. The original npm
launcher and packaging helpers are reused, with a bundled-only native payload
and fork package identity. The fork launcher does not advertise the official
npm updater. Windows binaries are not signed by OpenAI.

Alternatively, download `pet_install.py` from the release and use Python 3.11+:

```sh
python pet_install.py install
python pet_install.py launch
python pet_install.py update
python pet_install.py status
```

The Python installer selects the platform, downloads assets from an immutable
release tag, verifies SHA256 checksums, checks package resources and runs a
version/help smoke check. It installs into immutable directories and atomically
selects the verified executable. Failed downloads or checks preserve the
previous executable. `--install-dir` and `--state-dir` can integrate an existing
launcher reading `current.json`. Installed applications do not update by
themselves; rerun an update command or schedule the download-only updater.

## Synchronization and publication

One workflow run captures the fork and upstream commits and prepares an
unpublished merge candidate. A conflict stops before builds. The exact candidate
is transferred to both builders using a Git bundle. Each builder checks the
required pet regression test inventory, runs all twelve tests through `just test`,
builds the canonical native package, and smoke-tests a fresh npm installation.

The payload includes the code-mode host, ripgrep, Windows sandbox helpers, or
the Linux bubblewrap and patched zsh resources. Linux bubblewrap is finalized
and hashed before the CLI build, following upstream's package integrity contract.
Build dependencies and checksum-verified V8 artifacts reuse upstream tooling.

Only after both platforms pass does the final job check that the fork has not
changed, push normally without forcing, upload the complete assets to a draft,
and publish it as the latest release. A build failure leaves the branch and
previous release intact. A publication failure can leave a verified branch
advance or draft; it does not replace the latest successful release. A later
run retries. Unchanged source with a matching published release skips builds.
Release metadata records the source and upstream commits; checksums cover the
packages, metadata and downloadable installer.

GitHub's hosted job queue and workflow concurrency serialize release attempts;
each isolated build declares four Cargo/CMake/native jobs. Local compilation
still uses the machine's real `queued-build` command. The hosted Windows job
uses the Visual Studio 2026 image and checks MSVC 14.51. Original OpenAI release
workflows depend on private runner groups, signing services and registry trust;
the fork's small workflow uses standard hosted runners and its repository token.
All synchronization/build/publication happens in one workflow, so it does not
depend on token-generated pushes triggering another workflow.

The gate covers the pet changes and package delivery, not the entire upstream
test suite. Required test renames/removals need review. Logs and failed steps
are visible in GitHub Actions. A scheduled time is not a guaranteed delivery
time. Check Actions if automatic releases stop.

Tooling checks: `python -m unittest discover -s scripts -p 'test_pet_*.py'`.
The previous local merge/build runner has been replaced by this workflow and
download-only installation; any retained installed copy is for rollback.
