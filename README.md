# Codex CLI pet layout fork

This is an unofficial fork of [OpenAI Codex CLI](https://github.com/openai/codex)
that keeps transcript history and streaming responses at the full terminal width
when a pet is enabled. The pet occupies space beside the typing area (composer)
and its footer.

The layout changes adapt [makoto-soracom's work](https://github.com/makoto-soracom/codex/tree/makoto/pet-flicker-25004)
to current upstream Codex. See [pet layout details and attribution](PET_LAYOUT.md).

## Install or update this fork

With Node.js and npm installed, run the command for your platform. These
[prebuilt packages](https://github.com/imakris/codex/releases/latest) need no local
build or npm account.

**Windows x64:**

```powershell
npm install -g https://github.com/imakris/codex/releases/latest/download/codex-pet-win32-x64.tgz
```

**Linux x64:**

```sh
npm install -g https://github.com/imakris/codex/releases/latest/download/codex-pet-linux-x64.tgz
```

Start the fork with:

```sh
codex-pet
```

The separate `codex-pet` command can coexist with official `codex`; both share
normal Codex [configuration](docs/config.md) and
[authentication](docs/authentication.md).

## Updates and documentation

The fork automatically integrates upstream changes and publishes packages on
GitHub. Installed copies do not update themselves; repeat the installation
command above to get the latest published release. See
[installation and maintenance](PET_MAINTENANCE.md) for the synchronization
schedule, alternative Python installer, and troubleshooting.

Source clones can update with `git pull --ff-only`; see the
[source-clone instructions](PET_MAINTENANCE.md#source-clones).

For general usage, see the [upstream Codex documentation](https://developers.openai.com/codex).
This repository also has [contributing](docs/contributing.md) and
[source build instructions](docs/install.md).

This repository is licensed under the [Apache-2.0 License](LICENSE).
