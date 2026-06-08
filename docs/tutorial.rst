Tutorial: a Windows installer from scratch
==========================================

This walkthrough builds a real Windows ``.msi`` installer for a tiny tkinter GUI,
starting from an empty directory. It follows the path pyappdist itself takes:
scaffold a proper package, confirm it builds a wheel, confirm its launcher command
runs from that wheel, then add the pyappdist config and build the installer.

tkinter is used on purpose: it is part of the Python standard library and ships
with the bundled python-build-standalone runtime, so the app needs **no
third-party dependencies** — keeping the focus on packaging.

.. note::

   The final MSI step needs the Windows toolchain (MSVC + WiX). Run the build on
   Windows, or cross-build from WSL — see :doc:`formats/msi` and
   :doc:`installation`. Steps 1–4 are plain Python and work on any OS.

Step 1 — Scaffold a package with uv
-----------------------------------

pyappdist packages an *installable* project, so start from a packaged layout
rather than a loose script. ``uv init --package`` creates exactly that — a ``src/``
package, a ``[build-system]``, and a console-script entry point:

.. code-block:: bash

   uv init --package hellotk
   cd hellotk

You get a ``pyproject.toml`` like this (note the ``[project.scripts]`` entry —
``hellotk = "hellotk:main"`` — which is the same ``module:callable`` form
pyappdist's launcher uses):

.. code-block:: toml

   [project]
   name = "hellotk"
   version = "0.1.0"
   requires-python = ">=3.11"
   dependencies = []

   [project.scripts]
   hellotk = "hellotk:main"

   [build-system]
   requires = ["uv_build>=0.8.17,<0.9.0"]
   build-backend = "uv_build"

and a stub ``src/hellotk/__init__.py`` with a ``main()`` function.

Step 2 — Write the tkinter "hello world"
----------------------------------------

Replace ``src/hellotk/__init__.py`` with a small windowed app. Keep the entry
point a **plain function named** ``main`` that takes no arguments and returns an
exit code — that is exactly what the launcher will call:

.. code-block:: python

   import tkinter as tk


   def main() -> int:
       root = tk.Tk()
       root.title("Hello Tk")
       root.geometry("320x160")
       tk.Label(root, text="Hello from pyappdist!", font=("Segoe UI", 16)).pack(expand=True)
       tk.Button(root, text="Quit", command=root.destroy).pack(pady=12)
       root.mainloop()
       return 0

Run it the normal way while developing:

.. code-block:: bash

   uv run hellotk

A window should appear. (``tkinter`` is included in the standard python.org
Windows installer; if ``import tkinter`` fails locally, install/repair Python with
the *tcl/tk* option. This does not affect the built app — the bundled runtime
already includes tkinter.)

Step 3 — Test that the project builds a wheel
---------------------------------------------

pyappdist installs your app the way ``pip`` would, so the **first requirement** is
that the project builds a wheel. Confirm it:

.. code-block:: bash

   uv build --wheel

This must succeed and drop a ``.whl`` in ``dist/``:

.. code-block:: text

   Successfully built dist/hellotk-0.1.0-py3-none-any.whl

(The equivalent without uv is ``python -m pip wheel --no-deps .``.) If this fails,
fix the packaging before going further — pyappdist cannot distribute an app that
does not build a wheel. See :ref:`What your project must satisfy <config-prereqs>`.

Step 4 — Test the launcher command from the installed wheel
-----------------------------------------------------------

The **second requirement** is that the launcher's entry point runs against the
*installed* package — not a source file on disk. The launcher will invoke your
``"hellotk:main"`` entry in this exact form::

   python -c "from hellotk import main; main()"

Verify it the same way pyappdist will, in a throwaway environment built from the
wheel:

.. code-block:: bash

   python -m venv ../check
   ../check/bin/python -m pip install dist/hellotk-0.1.0-py3-none-any.whl   # Windows: ..\check\Scripts\python.exe
   ../check/bin/python -c "from hellotk import main; main()"

If the window opens from that clean environment, the launcher will work. If it
only ran under ``uv run`` (because it depended on files in your checkout that the
wheel doesn't include), fix the packaging now.

.. tip::

   The other entry form is ``python -m <module>``: set ``entry = "hellotk.cli"``
   (no colon) for an app whose startup lives under
   ``if __name__ == "__main__":``. This tutorial uses the ``module:callable`` form.

Step 5 — Add the pyappdist configuration
----------------------------------------

Add pyappdist as a dev dependency:

.. code-block:: bash

   uv add --dev pyappdist

Then add a ``[tool.pyappdist]`` section to ``pyproject.toml``. One launcher
(``gui = true`` so it starts via ``pythonw.exe`` with no console window — right for
a GUI), and one Windows MSI target:

.. code-block:: toml

   [tool.pyappdist]
   name = "Hello Tk"
   python = "3.12"

   launchers = [
     { name = "hellotk", entry = "hellotk:main", gui = true },
   ]

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   # upgrade-code = "..."    # auto-generated and written back if omitted

The ``entry`` is the very command you tested in step 4, and ``gui = true`` is
what makes the console window disappear. See :doc:`configuration` for every key
and :doc:`formats/msi` for the MSI-specific options.

Step 6 — Build the installer
----------------------------

.. note::

   This step needs the Windows toolchain: **MSVC C++ build tools** (to compile
   the launcher ``.exe``) and **WiX v5** (to build the MSI). If you don't have
   them yet, install both with ``winget`` from an **elevated** PowerShell — the
   build-only Build Tools (no full Visual Studio IDE) are enough:

   .. code-block:: powershell

      # MSVC C++ build tools (the "Desktop development with C++" workload)
      winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

      # WiX v5 — a .NET tool, so install the .NET SDK first
      winget install --id Microsoft.DotNet.SDK.10 -e
      dotnet tool install --global wix --version 5.0.2

   pyappdist locates MSVC automatically via ``vswhere``; no need to put
   ``cl.exe`` on ``PATH``. Pin WiX to **5.0.2** — v6/v7 require accepting a EULA
   that blocks an unattended ``wix build``. (The full Visual Studio Community
   edition, ``Microsoft.VisualStudio.2022.Community``, works too if you prefer
   the IDE — use the same ``--override`` workload arguments.) See
   :doc:`formats/msi` for the toolchain details and :doc:`installation` for the
   WSL cross-build path.

Build the Windows target:

.. code-block:: bash

   uv run pyappdist build windows

pyappdist runs the full pipeline — exports your locked dependencies (none here),
builds wheels with the target runtime, installs them into a fresh
python-build-standalone runtime, compiles the ``hellotk.exe`` launcher, and packs
it all with WiX. The artifacts land under ``appdist/windows/dist/``:

.. code-block:: text

   appdist/windows/dist/hellotk-0.1.0.msi             # the installer
   appdist/windows/dist/hellotk-0.1.0-portable.zip    # the same image, runnable in place

Double-click the ``.msi`` to install (a per-user install needs no admin rights);
``hellotk`` then appears in the Start menu and launches your tkinter window — with
its own private Python runtime, independent of any Python on the machine.

.. note::

   The MSI step requires MSVC build tools and WiX v5. On a non-Windows host the
   package step is skipped and only the image under ``appdist/windows/image/`` is
   produced, unless you cross-build from WSL. See :doc:`formats/msi` for the
   toolchain setup and :doc:`installation` for the WSL path.

Step 7 — Confirm the ``upgrade-code``
-------------------------------------

The ``upgrade-code`` is the **stable identity of your product across versions**. An
MSI uses it (via WiX ``MajorUpgrade``) to recognize an installed copy and replace it
in place when the user installs a newer version, instead of leaving two copies
side by side. It must therefore stay the same for the entire life of the product —
only the version number changes between releases.

You left it out of the config in step 5, so on this first build pyappdist generated
a UUID and **wrote it back** into your ``pyproject.toml``. Open the file and you will
now find a concrete value where the comment used to be:

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   upgrade-code = "6f6c2d6e-1b2a-5c3d-8e4f-9a0b1c2d3e4f"   # generated on the first build

Commit this value and keep it: build the same project again and the line stays
unchanged, so every release shares one ``upgrade-code`` and upgrades cleanly. (If
you prefer to pick the GUID yourself, set ``upgrade-code`` before the first build
and pyappdist will leave it alone.) See :doc:`formats/msi` for the full upgrade
behavior.

Where to go next
----------------

* :doc:`configuration` — every configuration key.
* :doc:`samples` — runnable examples with dependencies, C extensions, and other GUI
  stacks (PySide6, pygame, NiceGUI).
* :doc:`formats/msix`, :doc:`formats/linux`, :doc:`formats/macos` — add more targets
  to the same ``pyproject.toml`` to ship other platforms from one project.
