pyappdist
=========

**Build native installers for Python apps without hunting down hidden imports, data files, or plugins.**

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

Output formats
--------------

One ``pyproject.toml`` can describe several output packages at once — each is a
:ref:`target <config-targets>` with its own platform and format:

:doc:`msi <platforms/windows-msi>`
   ``windows-x86_64`` → ``.msi`` installer + portable ``.zip``.

:doc:`msix <platforms/windows-msix>`
   ``windows-x86_64`` → ``.msix`` (Store / sideloading).

:doc:`linux <platforms/linux>`
   ``linux-x86_64`` → ``.tar.{gz,bz2,xz}`` + ``.run`` installer.

:doc:`macos <platforms/macos-run>`
   ``macos-aarch64`` → ``.tar.{gz,bz2,xz}`` + ``.run`` installer, for
   **command-line tools**.

:doc:`macapp / dmg <platforms/macos-app>`
   ``macos-aarch64`` → a signed/notarized ``.app`` bundle, optionally
   inside a ``.dmg``, for **GUI apps**.

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

On Windows the launcher is a tiny C stub that starts the bundled ``python.exe`` /
``pythonw.exe`` as a subprocess, so there is no ``pythonXX.dll`` embedding and no
C-API version risk — the stub never changes when the Python version does. The macOS
``.app`` uses an equivalent compiled Mach-O stub; Linux and the macOS ``.tar``/``.run``
use a relocatable shell wrapper. See :doc:`how-it-works`.

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   installation
   tutorial

.. toctree::
   :maxdepth: 2
   :caption: Concepts

   how-it-works
   dependencies

.. toctree::
   :maxdepth: 2
   :caption: Shipping guides

   platforms/windows-msi
   platforms/windows-msix
   platforms/linux
   platforms/macos-run
   platforms/macos-app

.. toctree::
   :maxdepth: 2
   :caption: Reference

   configuration
   cli
   samples
   history
   GitHub <https://github.com/atsuoishimoto/pyappdist>

Status
------

**Alpha** — the pipeline works end-to-end, but expect breaking changes to the
config schema, CLI, and output layout as it matures.

Targets today are Windows x64 (``msi``, ``msix``), Linux x64 (``linux``), and
macOS arm64/x64 (``macos``). Auto-update and code-signing certificates are out of
scope for now; optional :ref:`code signing <msi-code-signing>` of the Windows
artifacts is available. Distributed apps are not obfuscated, and unsigned Windows
installers will trigger a SmartScreen warning.
