How it works
============

pyappdist installs your app into a real Python runtime and ships that runtime.
There is no freezing and no code analysis.

.. code-block:: text

   your app  ───pip wheel───▶  app wheel ─┐
                                           ├─▶ wheelhouse ─pip install─▶ runtime image ─┬─▶ portable .zip
   dependencies ─lockfile → pip wheel(win)─┘   (python-build-standalone)  + launcher.exe └─▶ WiX ──▶ .msi

The pipeline
------------

#. **App wheel.** Your project is built into a wheel with ``pip wheel
   --no-deps`` using its own PEP 517 backend (so any backend works).

#. **Dependency wheels.** Dependencies are pinned from your project's lockfile,
   exported to a ``requirements.txt``, and turned into wheels by the *target*
   runtime's ``python.exe`` (``pip wheel -r``). Resolving on the target
   interpreter keeps environment markers and wheel tags natively correct. See
   :doc:`dependencies`.

#. **Runtime.** A `python-build-standalone
   <https://github.com/astral-sh/python-build-standalone>`_ runtime for the
   requested version is downloaded, verified against its ``SHA256SUMS``, cached,
   and extracted.

#. **Image.** Every wheel in the wheelhouse is installed into the runtime offline
   (``pip install --no-index``), and the standard library / site-packages are
   byte-compiled. The result is a self-contained, ready-to-run directory.

#. **Launcher.** A small C stub (``launcher.exe``) is compiled per launcher. It
   starts the bundled ``python.exe`` (console) or ``pythonw.exe`` (GUI) as a
   subprocess and runs your entry point.

#. **Packaging.** The image is zipped into a portable archive, and a WiX ``.wxs``
   is generated and built into an ``.msi``.

The launcher
------------

The launcher is a thin C process, not an embedded interpreter:

* It spawns the bundled ``python.exe`` / ``pythonw.exe`` with
  ``-I`` (isolated mode) and strips ``PYTHON*`` environment variables, so the
  user's environment cannot interfere.
* Because it never embeds ``pythonXX.dll``, there is no C-API version coupling —
  the same stub works across Python versions.
* App-specific values (the interpreter path, the bootstrap program, fixed
  arguments, icon, and version resource) are baked into a generated header and
  ``.rc`` resource at build time; the C source is never edited.

GUI startup errors
------------------

GUI launchers run under ``pythonw.exe`` with no console, so a failed import would
otherwise vanish silently. For ``gui = true`` launchers, pyappdist wraps the
entry-point **import** in ``try/except`` and, on failure, shows the error in a
message box (via ``ctypes``). Exceptions raised *after* your entry point starts
running are your app's responsibility.

Upgrades
--------

The MSI uses WiX ``MajorUpgrade`` keyed on ``upgrade_code``. Component GUIDs are
derived deterministically as ``uuid5(upgrade_code, install-relative-path)``, so
the same layout and the same ``upgrade_code`` always produce the same component
identity — installing a newer version cleanly replaces the old one. Keep
``upgrade_code`` stable for the life of the product (pyappdist generates and
persists one for you if you omit it).
