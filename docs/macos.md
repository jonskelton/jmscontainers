# macOS guide

jms supports Apple Silicon Macs running macOS 15 or newer. It selects
[apple/container](https://github.com/apple/container) automatically; there is
no runtime switch.

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

This jms release is qualified against apple/container 1.2.2 and normally
requires that exact version. Homebrew can publish a newer runtime before jms
qualifies it. To use that version for one invocation, explicitly name it:

```sh
JMS_RUNTIME_ACCEPT=1.3.0 jms launch ~/path/to/project
```

jms warns that the combination is unqualified. Prefer upgrading jms once a
release supporting the new runtime is available.

## Security boundary

Each container runs in its own lightweight virtual machine. This is a
hardware-virtualized boundary, but it does not protect anything deliberately
mounted into the VM: the project is writable, and approved agent state is
read-write. See [SECURITY.md](../SECURITY.md) for the complete trust model.

## Troubleshooting

Check the three user-visible prerequisites first:

```sh
python3 --version
container --version
command -v jms
```

Python must be 3.11 or newer, the runtime must match the qualified version (or
be explicitly accepted), and `jms` must resolve from `~/.local/bin`.
