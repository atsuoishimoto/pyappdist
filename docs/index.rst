pyappdist
=========


**Ship your Python app as a native installer straight from `pyproject.toml`.
If it installs with `pip`, it ships with pyappdist.**

pyappdist bridges the Python packaging ecosystem and native application
distribution. It reads your application's pyproject.toml and builds setup
packages for distribution: an .msi / .msix on Windows, a .dmg / .app bundle
or a self-extracting installer on macOS, and a self-extracting installer on
Linux.

For example, to build a Windows MSI, configure `pyproject.toml` like this:

.. code-block:: toml

   [tool.pyappdist]
   name = "My App"
   python = "3.12"

   [[tool.pyappdist.launchers]]
   name = "myapp"              # produces myapp.exe (or a shell wrapper on Linux/macOS)
   entry = "myapp:main"        # module:callable
   # gui = true                # use pythonw.exe (no console window) on Windows
   # icon = { windows = "assets/app.ico" }   # per-OS launcher icon table
   # args = "--serve"          # fixed leading arguments

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   # scope = "user"            # "user" (default, no admin) or "machine" (Program Files)

Then build the MSI package (on Windows):

.. code-block:: shell

   uvx pyappdist build

The result lands under ``appdist/<target>/dist/``.


Why pyappdist
-------------

Tools such as PyInstaller and Nuitka analyze your code, select only the
necessary files from the Python interpreter and dependency packages, and build
an executable or a directory from that minimal set of files.

The problem is that the selection is not always correct. Static analysis
cannot reliably find dynamically imported modules, data files, or plugins, so
these tools often need per-application adjustments — hidden-import
declarations, data-file lists, and library-specific hooks — and adding a new
dependency can break the build again.

Those tools trade complexity for smaller distributions. A typical Python
runtime adds roughly 100–150 MB. That used to matter more than it does today.

pyappdist makes the opposite trade-off: it builds a complete environment
according to the Python and PyPA specifications and creates the distribution
package from it. **What your application and its dependencies contain does
not matter** — there is nothing to hunt down and nothing to adjust per
application:

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
``.app`` uses an equivalent compiled Mach-O stub; Linux and the macOS ``.run``
use a relocatable shell wrapper. See :doc:`how-it-works`.


Output formats
--------------

One ``pyproject.toml`` can describe several output packages at once — each is a
:ref:`target <config-targets>` with its own platform and format:

:doc:`msi <platforms/windows-msi>`
   ``windows-x86_64`` / ``windows-arm64`` → ``.msi`` installer.

:doc:`msix <platforms/windows-msix>`
   ``windows-x86_64`` / ``windows-arm64`` → ``.msix`` (Store / sideloading).

:doc:`linux <platforms/linux>`
   ``linux-x86_64`` / ``linux-aarch64`` → ``.run`` installer.

:doc:`macos <platforms/macos-run>`
   ``macos-aarch64`` → ``.run`` installer, for
   **command-line tools**.

:doc:`macapp / dmg <platforms/macos-app>`
   ``macos-aarch64`` → a signed/notarized ``.app`` bundle, optionally
   inside a ``.dmg``, for **GUI apps**.

:doc:`image <platforms/image>`
   any platform → a ``.zip`` / ``.tar.gz`` of the image tree, with **no
   installer**.


Status
--------------

Beta: Core packaging workflows are ready for real-world use, although configuration details may still change before 1.0.


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
   platforms/image

.. toctree::
   :maxdepth: 2
   :caption: Reference

   configuration
   cli
   samples
   history
   GitHub <https://github.com/atsuoishimoto/pyappdist>

