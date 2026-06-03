How it works
============

pyappdist installs your app into a real Python runtime and ships that runtime.
There is no freezing and no code analysis.

.. code-block:: text

   your app  ───pip wheel───▶  app wheel ─┐
                                           ├─▶ wheelhouse ─pip install─▶ runtime image ─▶ package
   dependencies ─lockfile → pip wheel─────┘   (python-build-standalone)  + launcher       (by format)

The image — a self-contained, ready-to-run directory — is built the same way for
every target. Only the final **packaging** step branches by ``format``.

The pipeline
------------

#. **App wheel.** Your project is built into a wheel with ``pip wheel
   --no-deps`` using its own PEP 517 backend (so any backend works).

#. **Dependency wheels.** Dependencies are pinned from your project's lockfile,
   exported to a ``requirements.txt``, and turned into wheels by the *target*
   runtime's ``python`` (``pip wheel -r``). Resolving on the target interpreter
   keeps environment markers and wheel tags natively correct. See
   :doc:`dependencies`.

#. **Runtime.** A `python-build-standalone
   <https://github.com/astral-sh/python-build-standalone>`_ runtime for the
   requested version is downloaded, verified against its ``SHA256SUMS``, cached,
   and extracted.

#. **Image.** Every wheel in the wheelhouse is installed into the runtime offline
   (``pip install --no-index``), and the standard library / site-packages are
   byte-compiled. The result is a self-contained, ready-to-run directory.

#. **Launcher.** One launcher per ``[[tool.pyappdist.launchers]]`` entry. On
   Windows it is a small C stub (``launcher.exe``) compiled with MSVC; on
   Linux/macOS it is a relocatable shell wrapper. Either way it starts the bundled
   interpreter and runs your entry point.

#. **Packaging.** The image is turned into the target's package: an ``.msi`` (+
   portable ``.zip``) or ``.msix`` on Windows, or a ``.tar`` + self-extracting
   ``.run`` on Linux/macOS. See the per-format pages under
   :ref:`Output formats <config-formats>`.

The launcher
------------

On Windows the launcher is a thin C process, not an embedded interpreter:

* It spawns the bundled ``python.exe`` / ``pythonw.exe`` with ``-I`` (isolated
  mode) and strips ``PYTHON*`` environment variables, so the user's environment
  cannot interfere.
* Because it never embeds ``pythonXX.dll``, there is no C-API version coupling —
  the same stub works across Python versions.
* App-specific values (the interpreter path, the bootstrap program, fixed
  arguments, icon, and version resource) are baked into a generated header and
  ``.rc`` resource at build time; the C source is never edited.

On Linux/macOS the launcher is a relocatable shell wrapper that resolves its own
location and execs the bundled interpreter with the same isolated-mode bootstrap —
no compiler needed.

GUI startup errors (Windows)
----------------------------

GUI launchers run under ``pythonw.exe`` with no console, so a failed import would
otherwise vanish silently. For ``gui = true`` launchers, pyappdist wraps the
entry-point **import** in ``try/except`` and, on failure, shows the error in a
message box (via ``ctypes``). Exceptions raised *after* your entry point starts
running are your app's responsibility.

MSI upgrades
------------

The MSI uses WiX ``MajorUpgrade`` keyed on ``upgrade_code``. Component GUIDs are
derived deterministically as ``uuid5(upgrade_code, install-relative-path)``, so the
same layout and the same ``upgrade_code`` always produce the same component
identity — installing a newer version cleanly replaces the old one. Keep
``upgrade_code`` stable for the life of the product (pyappdist generates and
persists one for you if you omit it). The ``.run`` installers replace any existing
install in place; application-level updates are otherwise the app's own
responsibility.
