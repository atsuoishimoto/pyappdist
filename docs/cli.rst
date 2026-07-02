Command-line interface
=======================

.. code-block:: text

   pyappdist <command> [target ...] [options]

Positional arguments are **target names** (from ``[[tool.pyappdist.targets]]``). With
none given, the command applies to **all** targets. The project directory defaults to the
current directory; use ``-C`` / ``--project`` to point elsewhere.

Common options
--------------

Available on every command:

``-C``, ``--project DIR``
   The application's project directory (the one containing ``pyproject.toml``).
   Defaults to the current directory.

``--appdist-dir DIR``
   Base directory for the final artifacts. Defaults to ``<project>/appdist``. Each
   target's shippable packages land in ``<appdist-dir>/<target>/dist/``.

``--build-dir DIR``
   Base directory for build intermediates (runtime, wheelhouse, image, launcher build,
   ``.wxs``). Defaults to ``<project>/.appdist-build``. Each target uses
   ``<build-dir>/<target>/``. A full ``build`` removes this per-target directory first
   for a clean build (the downloaded runtime cache is kept separately, so this does not
   re-download).

Commands that fetch the runtime (``build``, ``build-wheels``,
``fetch-runtime``, ``build-image``) also accept:

``--runtime-release TAG``
   Pin a specific python-build-standalone release tag.

.. _cli-output-layout:

Output layout
-------------

Build intermediates and final artifacts go to separate trees.

Intermediates land under ``.appdist-build/<target>/``:

``wheelhouse/``
   The app wheel + dependency wheels (and ``requirements.txt``).

``runtime/``
   The extracted python-build-standalone runtime.

``image/``
   The installed, ready-to-run app — itself a portable directory.

The shippable packages land under ``appdist/<target>/``:

``dist/``
   The shippable package(s) for the target's format — see the per-format pages
   under :ref:`Output formats <config-formats>`.

Commands
--------

``build``
~~~~~~~~~

Run the whole pipeline for each selected target: runtime → wheels → image →
launcher → (sign) → package. The package step branches by the target's ``format``
(see :ref:`Output formats <config-formats>`).

.. code-block:: bash

   uv run pyappdist build              # the sole target, or error if several are defined
   uv run pyappdist build win-user     # just the target named "win-user"
   uv run pyappdist build win-user win-machine   # both named targets

Unlike the individual pipeline stages (which default to *all* targets), ``build``
builds the single defined target when no name is given and otherwise requires an
explicit selection, so it never builds every target at once by accident.

Extra options: ``--no-compile`` (skip byte-compilation), ``--no-zip`` (skip the
portable zip). Plus the common and runtime options above.

``build-wheels``
~~~~~~~~~~~~~~~~

Build the app wheel and collect dependency wheels into ``<target>/wheelhouse``. Fetches
the runtime first (dependencies are resolved with the target interpreter).

``fetch-runtime``
~~~~~~~~~~~~~~~~~

Download, verify, and extract the python-build-standalone runtime into
``<target>/runtime``.

``build-image``
~~~~~~~~~~~~~~~

Assemble the runtime image: install the wheelhouse, byte-compile, build the
launcher(s), and create the portable zip. Options: ``--no-compile``,
``--no-zip``.

``build-launchers``
~~~~~~~~~~~~~~~~~~~

(Re)build the launcher(s) into an existing image. Requires a prior
``build-image``. The launcher kind follows the target's ``format``: a Windows
``launcher.exe`` (MSVC) for ``msi``/``msix``, or a compiled Mach-O stub (clang)
for the macOS ``.app`` (``macapp``/``dmg``). For ``linux`` and ``macos``
(``.tar``/``.run``) the launcher is a shell wrapper written during packaging, so
this command is a no-op.

``gen-wix``
~~~~~~~~~~~

Scan an existing image and generate the WiX ``.wxs`` file. Requires a prior
``build-image``. This also generates and persists the target's ``upgrade-code`` if it
is unset.

Examples
--------

.. code-block:: bash

   # Full build of a sample (all its targets)
   uv run pyappdist build -C samples/pandascli

   # Build only specific targets by name
   uv run pyappdist build win-user win-machine
