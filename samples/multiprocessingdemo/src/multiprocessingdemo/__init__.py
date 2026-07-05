"""multiprocessing sample for pyappdist.

Demonstrates that Python's :mod:`multiprocessing` works through the pyappdist
launcher. The launcher runs the bundled interpreter directly, so
``sys.executable`` points at the shipped ``python`` and the ``spawn`` start
method (the default on Windows and macOS) re-launches that same interpreter to
create worker processes -- no ``multiprocessing.set_executable()`` needed.

Two things make this safe under the launcher's ``python -I -c "..."`` bootstrap:

* The worker (:func:`_work`) is a module-level function, so ``spawn`` children
  can pickle and re-import it.
* All process creation happens inside :func:`main` (never at import time), and
  :func:`multiprocessing.freeze_support` is called first -- the standard,
  portable guard.
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def _work(n: int) -> tuple[int, int, int]:
    """A CPU-bound task run in a worker process.

    Returns ``(input, result, worker_pid)`` so the parent can show that the
    tasks really ran in separate processes.
    """
    total = sum(i * i for i in range(n * 100_000))
    return n, total, os.getpid()


def main() -> int:
    # Required before any process is started so a spawned child that re-imports
    # this module and reaches here does not itself start a new pool. It is a
    # no-op on non-frozen CPython (as shipped here) but is the portable guard.
    multiprocessing.freeze_support()

    print(f"parent pid     : {os.getpid()}")
    print(f"sys.executable : {sys.executable}")
    print(f"cpu_count      : {os.cpu_count()}")
    print(f"start method   : {multiprocessing.get_start_method()}")

    inputs = list(range(1, 9))
    with multiprocessing.Pool() as pool:
        results = pool.map(_work, inputs)

    worker_pids = sorted({pid for _, _, pid in results})
    print("\nresults (input -> sum of squares, worker pid):")
    for n, total, pid in results:
        print(f"  {n} -> {total} (pid {pid})")
    print(f"\nran across {len(worker_pids)} worker process(es): {worker_pids}")
    print("multiprocessing OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
