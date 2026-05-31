# pyappdist

**Turn a Python app into a Windows installer — and it just works.**

> ⚠️ **Alpha.** pyappdist is under active development. It works end-to-end today, but the
> config schema, CLI, and output layout may still change without notice.

pyappdist does **not** freeze your code. Instead of bundling Python and your app into a
single executable (and fighting hidden imports, data files, and plugins along the way),
it installs your app into a real, dedicated Python runtime — exactly the way `pip` would —
and ships that.

Because the runtime is a normal Python environment, **most apps run as-is**: no hooks, no
`--hidden-import`, no `--add-data`, no per-library workarounds. If it runs under `uv run`,
it almost certainly runs after `pyappdist build`. C extensions, `abi3` wheels, Qt plugins,
and tkinter-based GUIs work unmodified because the install layout is real.

## Quick start

Add a `[tool.pyappdist]` section to your app's `pyproject.toml`:

```toml
[tool.pyappdist]
name = "My App"
python = "3.12"
target = "windows-x86_64"

[[tool.pyappdist.launchers]]
name = "myapp"              # produces myapp.exe
entry = "myapp:main"        # module:callable

[tool.pyappdist.wix]
manufacturer = "Example Inc."
```

Then add pyappdist and build:

```bash
uv add --dev pyappdist
uv run pyappdist build .    # wheels -> runtime -> image -> launcher -> wix -> MSI
```

The result lands under `appdist/dist/`: a portable `.zip` and an `.msi` installer.

## Documentation

Full documentation lives in the [`docs/`](docs/) directory (Sphinx / Read the Docs):

- [Installation & requirements](docs/installation.rst)
- [Quick start](docs/quickstart.rst)
- [How it works](docs/how-it-works.rst)
- [Configuration reference](docs/configuration.rst)
- [CLI reference](docs/cli.rst)
- [Dependency resolution](docs/dependencies.rst)
- [Code signing](docs/signing.rst)
- [Samples](docs/samples.rst)

## Status

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the config
schema, CLI, and output layout as it matures.

Windows x64 is the current target. macOS/Linux packaging, auto-update, and code-signing
certificates are out of scope for now. Distributed apps are not obfuscated, and unsigned
installers will trigger a SmartScreen warning.
