# smoke

A minimal app for verifying pyappdist end-to-end with an **editable** install (the
working-tree `src/pyappdist`).

```bash
uv run pyappdist build .
```

This produces `smoke-0.1.0.msi` and a portable zip under `appdist/dist/`. Running the
built `smoke.exe` prints `pyappdist e2e smoke: OK` and the Python version.

See [../README.md](../README.md) for details.
