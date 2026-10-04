# Install and update the pet fork

The [Pet fork sync and release workflow](https://github.com/imakris/codex/actions/workflows/pet-release.yml)
integrates current upstream `openai/codex:main`, builds Windows x64 and Linux x64 packages,
and publishes verified builds to [GitHub Releases](https://github.com/imakris/codex/releases).
It is scheduled daily at 07:17 Berlin time (`Europe/Berlin`) year-round, and also
runs after pushes to `pet-composer-layout` and on manual dispatch. Scheduled
runs attempt a new verified release even when source is unchanged. It does not
require this computer to be switched on.

The schedule follows Berlin's daylight saving time automatically: 05:17 UTC in
summer and 06:17 UTC in winter. GitHub can delay scheduled starts; publication
follows successful verification.

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

A push run first checks the current fork tip against the latest published
release and skips before fetching upstream when that tip is already released.
Other runs capture the fork and current upstream commits and three-way merge
their source trees, preserving all net fork changes and prior conflict resolutions.
A conflict stops before builds. The integrated tree becomes one unpublished
fork commit whose sole parent is the captured upstream tip, so repeated upstream
refreshes do not accumulate fork commits. If the maintained tip already has
that parent and tree, its source identity is reused. The exact candidate
is transferred to both builders using a Git bundle. Each builder checks the
required pet regression test inventory, runs all twelve tests through `just test`,
builds the canonical native package, and smoke-tests a fresh npm installation.

The payload includes the code-mode host, ripgrep, Windows sandbox helpers, or
the Linux bubblewrap and patched zsh resources. Linux bubblewrap is finalized
and hashed before the CLI build, following upstream's package integrity contract.
Build dependencies and checksum-verified V8 artifacts reuse upstream tooling.

Only after both platforms pass does the final job check that the fork has not
changed, promote with an explicit `--force-with-lease` on that exact previous tip,
upload the complete assets to a draft,
and publish it as the latest release. A build failure leaves the branch and
previous release intact. A publication failure can leave a verified branch
rewrite or draft; it does not replace the latest successful release. The lease
also rejects a concurrent update arriving after the final check. Existing
release tags and assets remain immutable even when the branch is rewritten. A later
run retries. Scheduled runs build and verify a new release even when source is
unchanged. Manual runs refresh upstream and skip builds when the prepared
candidate already has a matching published release.
Release metadata records the source and upstream commits; checksums cover the
packages, metadata and downloadable installer.

## Source clones

The published `pet-composer-layout` branch is rewritten after verified upstream
updates to keep one net fork commit. Existing release tags still retain their
original source history. Installed packages are unaffected by branch rewrites.

A fresh clone follows the compact history while leaving an existing clone and
its local work intact. To resynchronize an existing source branch, record its
current `origin/pet-composer-layout` commit **before** fetching, then fetch origin.
Only reset when `git status --short` is empty and
`git log <recorded-origin-tip>..pet-composer-layout` contains no local commits.
With both checks empty, switch to `pet-composer-layout` and run
`git reset --hard origin/pet-composer-layout`.

If either check finds work, do not reset. Save local commits on a backup branch
and commit or separately copy uncommitted and untracked work, then reconcile
the changes onto the new tip before replacing the local branch.
If the previous remote tip is unavailable, keep the existing clone and
use a fresh clone. An ordinary pull can restore the old merge history, so it is
not the resynchronization path for this branch.

## Hosted verification

GitHub's hosted job queue and workflow concurrency serialize release attempts.
The concurrency group retains up to 100 pending requests, so a promotion push
does not replace an already pending scheduled or manual run. Each isolated
build declares four Cargo/CMake/native jobs. Local compilation
still uses the machine's real `queued-build` command. The hosted Windows job
uses the Visual Studio 2026 image and checks MSVC 14.51. Original OpenAI release
workflows depend on private runner groups, signing services and registry trust;
the fork's small workflow uses standard hosted runners. Source promotion uses
the dedicated `PET_SYNC_TOKEN`; release API requests use `GITHUB_TOKEN`.
All synchronization/build/publication happens in one workflow, so it does not
depend on token-generated pushes triggering another workflow.

## Synchronization credentials

Upstream merges can change files in `.github/workflows`. GitHub's built-in
`GITHUB_TOKEN` cannot push those changes even with `contents: write`. The publish
job's checkout uses a dedicated fine-grained personal access token stored in the
repository Actions secret `PET_SYNC_TOKEN`:

1. In [GitHub's fine-grained token settings](https://github.com/settings/personal-access-tokens),
   create a token with resource owner **imakris** and select only **imakris/codex**.
2. Grant repository permissions **Contents: Read and write** and
   **Workflows: Read and write**. Choose an expiration date and plan to rotate the
   token before it expires.
3. Save the token as **PET_SYNC_TOKEN** under
   [repository Settings > Secrets and variables > Actions](https://github.com/imakris/codex/settings/secrets/actions).
   Keep the token value out of source files, logs, and chat.

Only the publish checkout receives this token for the source push. Preparation,
builders, and release API requests retain the built-in repository token.
GitHub documents the [workflow-file permission requirement](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)
and [additional credential options](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token#granting-additional-permissions).

Unlike `GITHUB_TOKEN`, a personal access token's pushes trigger matching push
workflows. Advancing the branch therefore queues another pet release run.
Workflow concurrency starts it after the active release attempt finishes. When
the current fork tip matches the published release, the follow-up skips before
fetching upstream. Scheduled and manual runs refresh upstream; human pushes
that change the fork tip and runs without a matching public release still
prepare and verify a candidate.

To rotate credentials, create a replacement token with the same repository
selection and permissions, update `PET_SYNC_TOKEN`, and revoke the superseded
token once any publishing job using it has finished. After setup, rotation, or
a permissions failure, start a fresh manual run from `pet-composer-layout`.
A run that reaches source promotion checks the credential; an unchanged-source
run that skips builds does not. Missing, expired, or revoked credentials stop
source promotion and leave the latest successful release available.

The gate covers the pet changes and package delivery, not the entire upstream
test suite. Required test renames/removals need review. Logs and failed steps
are visible in GitHub Actions. A scheduled time is not a guaranteed delivery
time. Check Actions if automatic releases stop.

Tooling checks: `python -m unittest discover -s scripts -p 'test_pet_*.py'`.
The previous local merge/build runner has been replaced by this workflow and
download-only installation; any retained installed copy is for rollback.
