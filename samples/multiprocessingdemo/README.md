# multiprocessingdemo

A pyappdist sample that exercises Python's `multiprocessing` through the
launcher. It starts a `multiprocessing.Pool`, runs a CPU-bound task across
several worker processes, and prints each worker's PID so you can confirm the
work really ran in separate processes.

Why it works in a pyappdist distribution: the launcher runs the *bundled*
interpreter directly (`python -I -c "..."`), so `sys.executable` points at the
shipped `python`. On Windows and macOS multiprocessing defaults to the `spawn`
start method, which re-launches `sys.executable` — i.e. the bundled runtime —
to create children. No `set_executable()` call is needed. The worker function
is module-level (so `spawn` can re-import it) and all process creation happens
inside `main()` behind `multiprocessing.freeze_support()`.

The launcher is `gui = false`, so the distribution launches via `python.exe`
(console shown) and you can read the worker PIDs.

## Build the distribution

```bash
pyappdist build
```

## Confirm via the launcher

After building, run the launcher and check the output lists several distinct
worker PIDs and ends with `multiprocessing OK`:

- **Windows** — install the `.msi` (or unzip the portable `.zip`) and run
  `multiprocessingdemo.exe`.
- **Linux** — extract the `.tar.gz` (or run the `.run` installer) and run
  `bin/multiprocessingdemo`.
