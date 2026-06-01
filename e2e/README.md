# e2e

End-to-end verification projects that run pyappdist as an **editable** install (the
working-tree `src/pyappdist`).

The apps under `samples/` reference pyappdist **from PyPI** (they are the published,
user-facing examples). The projects here instead set `[tool.uv.sources]` to
`pyappdist = { path = "../../", editable = true }`, so they build with **the
`src/pyappdist` you are currently editing**. Use them to exercise branch changes
end-to-end (wheels → runtime → image → launcher → wix → MSI) on your machine.

## Usage

```bash
cd e2e/smoke
uv run pyappdist build          # builds all targets; or `uv run pyappdist build -C e2e/smoke` from the repo root
```

Confirm the editable reference is in effect:

```bash
uv run python -c "import pyappdist, pathlib; print(pathlib.Path(pyappdist.__file__).resolve())"
# -> should print <repo>/src/pyappdist/__init__.py (not the PyPI copy)
```

## Projects

- `smoke/` — a minimal, dependency-free console app. Smoke-tests the whole build
  pipeline. It defines three targets: an **MSI** (`user` scope, with a license dialog), an
  **MSIX** (`format = "msix"`, named `msix`), and a macOS **DMG** (`macos-arm64`,
  `format = "dmg"`). `uv run pyappdist build` builds all of them (each is skipped on a host
  that can't build it); `uv run pyappdist build msix` / `uv run pyappdist build macos-arm64`
  builds just one.

> Building the MSI target needs the WiX UI extension once
> (`wix extension add -g WixToolset.UI.wixext/5.0.2`); the MSIX target needs the Windows
> SDK `makeappx` (located automatically). Installing the unsigned `.msix` locally needs
> **Developer Mode** (`Add-AppxPackage -Register <image>\AppxManifest.xml`).
>
> When running from WSL, the build output must live on a Windows volume (`/mnt/...`),
> because cmd.exe cannot start from a UNC path.
>
> The `macos-arm64` target is **native-only** (Apple Silicon) and needs the Xcode Command
> Line Tools (`clang`/`codesign`/`hdiutil`/`iconutil`/`sips`). The MVP signs **ad-hoc**, so
> the result runs locally but is rejected by Gatekeeper (`spctl`) on other machines.
