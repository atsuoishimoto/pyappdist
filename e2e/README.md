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
  pipeline, including the `user` scope and a license dialog.

> `smoke/` sets a `license`, so building it needs the WiX UI extension once:
> `wix extension add -g WixToolset.UI.wixext/5.0.2`.
>
> When running from WSL, the build output must live on a Windows volume (`/mnt/...`),
> because cmd.exe cannot start from a UNC path.
