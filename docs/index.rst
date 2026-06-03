pyappdist
=========

**Turn a Python app into a Windows installer — and it just works.**

.. warning::

   **Alpha.** pyappdist is under active development. It works end-to-end today,
   but the config schema, CLI, and output layout may still change without notice.

pyappdist does **not** freeze your code. Instead of bundling Python and your app
into a single executable (and fighting hidden imports, data files, and plugins
along the way), it installs your app into a real, dedicated Python runtime —
exactly the way ``pip`` would — and ships that.

Because the runtime is a normal Python environment, **most apps run as-is**: no
hooks, no ``--hidden-import``, no ``--add-data``, no per-library workarounds. If
it runs under ``uv run``, it almost certainly runs after ``pyappdist build``.

Why "just works"
----------------

Freezers reconstruct your app by static analysis, so anything dynamic tends to
break and needs manual patching. pyappdist skips all of that:

* **Real install layout** — ``dist-info``, entry points, ``.pth`` files, and
  package data are exactly where the package authors put them.
  ``importlib.metadata`` / ``importlib.resources`` behave identically to a normal
  install.
* **Real binary wheels** — C extensions and platform wheels (incl. ``abi3``) are
  installed unmodified, with the real interpreter and DLL search paths. No
  bundling guesswork.
* **Real GUI stacks** — Qt plugins ship in PySide6's normal wheel layout;
  matplotlib's TkAgg backend uses the runtime's bundled tkinter. They just load.

The launcher is a tiny C stub that starts the bundled ``python.exe`` /
``pythonw.exe`` as a subprocess, so there is no ``pythonXX.dll`` embedding and no
C-API version risk — the stub never changes when the Python version does.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   installation
   quickstart
   how-it-works
   configuration
   cli
   dependencies
   signing
   samples
   history
   GitHub <https://github.com/atsuoishimoto/pyappdist>

Status
------

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the
config schema, CLI, and output layout as it matures.

Windows x64 is the current target. macOS/Linux packaging, auto-update, and
code-signing certificates are out of scope for now. Distributed apps are not
obfuscated, and unsigned installers will trigger a SmartScreen warning.
