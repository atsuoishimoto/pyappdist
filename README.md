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

[[tool.pyappdist.launchers]]
name = "myapp"              # produces myapp.exe
entry = "myapp:main"        # module:callable

[[tool.pyappdist.targets]]
platform = "windows-x86_64"
manufacturer = "Example Inc."
# scope = "user"            # "user" (default, no admin) or "machine" (Program Files)
```

Then add pyappdist and build:

```bash
uv add --dev pyappdist
uv run pyappdist build      # builds all targets: wheels -> runtime -> image -> launcher -> wix -> MSI
```

The result lands under `appdist/<target>/dist/`: a portable `.zip` and an `.msi` installer.

## Documentation

Full documentation: **https://pyappdist.readthedocs.io/en/latest/**

- [Installation & requirements](https://pyappdist.readthedocs.io/en/latest/installation.html)
- [Quick start](https://pyappdist.readthedocs.io/en/latest/quickstart.html)
- [How it works](https://pyappdist.readthedocs.io/en/latest/how-it-works.html)
- [Configuration reference](https://pyappdist.readthedocs.io/en/latest/configuration.html)
- [CLI reference](https://pyappdist.readthedocs.io/en/latest/cli.html)
- [Dependency resolution](https://pyappdist.readthedocs.io/en/latest/dependencies.html)
- [Code signing](https://pyappdist.readthedocs.io/en/latest/signing.html)
- [Samples](https://pyappdist.readthedocs.io/en/latest/samples.html)

## Status

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the config
schema, CLI, and output layout as it matures.

Windows x64 is the current target. macOS/Linux packaging, auto-update, and code-signing
certificates are out of scope for now. Distributed apps are not obfuscated, and unsigned
installers will trigger a SmartScreen warning.
