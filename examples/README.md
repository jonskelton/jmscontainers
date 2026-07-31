# Examples

Each directory is a small project definition ready to inspect or copy. Build it
from this checkout after building the base image:

```sh
jms build --base
tmp=$(mktemp -d)
cp -R examples/odin "$tmp/odin"
jms build --trust --no-auth -w "$tmp/odin"
```

Use `jms build --no-cache -w "$tmp/odin"` to rebuild the copied example from
scratch, for instance after refreshing the shared base with
`jms build --base --pull --no-cache`.

- `odin/` layers the standard jms image with an Odin toolchain and common
  reverse-engineering tools.
- `data-science/` layers the standard image with Python data tooling.
- `go/` layers the standard image with the Go toolchain (plus gopls and
  delve), since the base image no longer bundles it.
- `rust/` layers the standard image with the Rust toolchain (plus rustfmt,
  clippy, and rust-analyzer), since the base image no longer bundles it.
- `clean-slate/` demonstrates a standalone Fedora image. It creates the
  required `isolation` user itself and pins the project-image user ABI to
  UID/GID `1000:1000`.

These examples are intentionally illustrative. Review and adapt package
versions, network use, and host mounts before approving them.

The checked-in definitions cannot be launched directly because jms protects its
own checkout from becoming a project mount or build context. Copy an example to
an independent project directory first; the real-runtime integration tier does
the same thing.
