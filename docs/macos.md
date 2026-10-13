# macOS guide

jms supports Apple Silicon Macs running macOS 15 or newer. It selects
[apple/container](https://github.com/apple/container) automatically; there is
no runtime switch. **Docker Desktop is not supported**: jms runs only the
`container` CLI, whose separate VM per container is the boundary jms
relies on.

## Install

```sh
brew install container python
git clone https://github.com/jonskelton/jmscontainers.git
cd jmscontainers
make install
export PATH="$HOME/.local/bin:$PATH"
jms build --base
```

Homebrew Python is required because the Command Line Tools version may be
older than Python 3.11. `make install` puts `jms` in `~/.local/bin`; add the
export above to your shell profile to make it permanent.

apple/container normally needs `container system start` once per boot. jms
checks the service and starts it automatically.

## Runtime version

jms requires apple/container 1.2.2 or newer and accepts whatever version
Homebrew installs at or above that. This jms release was qualified against
apple/container 1.5.0. A newer 1.x runs silently; a 2.0 or later runs with
a one-line warning that the combination is unqualified. If a newer runtime
breaks something, jms fails with a parse or runtime error naming the
command; report it, and pin Homebrew's `container` back meanwhile.

## Security boundary

Each container runs in its own lightweight virtual machine. This is a
hardware-virtualized boundary, but it does not protect anything deliberately
mounted into the VM: the project is writable, and approved agent state is
read-write. See [SECURITY.md](../SECURITY.md) for the complete trust model.

## Disk usage

The shared base is roughly 3 GB, and jms keeps each project's two newest
images. Images jms can no longer see stay on disk: an old base left without
a name after `jms build --base`, and the images of a project whose
directory you deleted (`jms clean` and `jms trust revoke --purge-images`
need the directory to exist). Before deleting a checkout, run
`jms clean --images` in it. For what is already left over, use
apple/container's own commands; jms does not run these for you:

```sh
container image list      # every image, with its name
jms trust list            # "missing" marks a deleted checkout
```

A project image is named `jmscontainers-<directory>-<id>:<tag>`, where
`<id>` is the first eight characters of the id `jms trust list` prints.
Remove one with `container image delete <name>:<tag>`, then drop the stale
approval with `jms trust prune`. Check `container image --help` for a
prune command before relying on one; any prune sweeps every unnamed image
in the runtime, not only the ones jms left. (Not yet verified on a Mac:
whether apple/container keeps the replaced base as an unnamed image.)

## Resource limits

jms passes no CPU or memory option to `container run`, and
`jmscontainer.toml` has no key for one, so each container's VM gets
apple/container's default allocation (see `container run --help`). The VM
caps what an agent can consume; the manifest cannot raise or lower it.

## Proxies

jms has no proxy settings of its own and passes none to `container`.
Whether apple/container forwards your shell's proxy variables into builds
and containers has not been qualified. To give a project's containers a
proxy, set `HTTPS_PROXY` and friends under `[env]` in its
`jmscontainer.toml`; anything set there is visible to the agent.

## Troubleshooting

Check the three user-visible prerequisites first:

```sh
python3 --version
container --version
command -v jms
```

Python must be 3.11 or newer, the runtime must be apple/container 1.2.2 or
newer (see [Runtime version](#runtime-version); there is no override for an
older one), and `jms` must resolve from `~/.local/bin`.
