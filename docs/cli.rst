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
   ``.wxs``). Defaults to the ``PYAPPDIST_BUILD_DIR`` environment variable if set, else
   ``<project>/.appdist-build``. Each target uses ``<build-dir>/<target>/``. A full
   ``build`` removes this per-target directory first for a clean build (the downloaded
   runtime cache is kept separately, so this does not re-download).

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
   The app wheel + dependency wheels (and the exported dependency file —
   ``pylock.toml`` for the uv manager, ``requirements.txt`` for the others).

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

Extra options: ``--no-compile`` (skip byte-compilation), and
``--code-sign`` / ``--no-code-sign`` — force code signing on or off for every
selected target, overriding each target's ``code-sign`` key (see
:ref:`msi-code-signing`; targets whose format has no signable artifact note the
flag and continue). Plus the common and runtime options above.

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

Assemble the runtime image: install the wheelhouse, byte-compile, and build the
launcher(s). Options: ``--no-compile``.

``build-launchers``
~~~~~~~~~~~~~~~~~~~

(Re)build the launcher(s) into an existing image. Requires a prior
``build-image``. The launcher kind follows the target's ``format``: a Windows
``launcher.exe`` for ``msi``/``msix``, or a Mach-O stub for the macOS ``.app``
(``macapp``/``dmg``/``pkg``) — both produced from the bundled prebuilt stubs,
or compiled with MSVC / clang when the target sets
``launcher-build = "source"``. For ``linux`` and ``macos`` (``.run``) the launcher is a shell
wrapper written during packaging, so this command is a no-op.

.. _cli-build-prebuilt:

``build-prebuilt``
~~~~~~~~~~~~~~~~~~

Compile the prebuilt launcher stubs that released wheels normally bundle, into
this pyappdist installation's ``resources/prebuilt/`` (or ``--out``). A
development/release tool, not a pipeline stage: run it once when using
pyappdist from a source checkout — which bundles no stubs — and subsequent
builds take the default ``launcher-build = "prebuilt"`` path with no C
compiler needed at app-build time.

Positional arguments select what to build: ``windows-x86_64`` /
``windows-arm64`` (a console + gui ``.exe`` pair each; needs a Windows host,
or WSL with Visual Studio) and ``macos`` (one universal Mach-O; needs a macOS
host). With no selection, everything the host's toolchain can produce is
built and the rest is skipped with a note; naming an unbuildable selector is
an error. ``--build-dir`` overrides where intermediates go (``$PYAPPDIST_BUILD_DIR``,
else ``<out>/.build``; on WSL it must be on a Windows volume).

.. code-block:: bash

   uv run pyappdist build-prebuilt          # everything this host can build
   uv run pyappdist build-prebuilt macos    # just the universal macOS stub

``gen-wix``
~~~~~~~~~~~

Scan an existing image and generate the WiX ``.wxs`` file. Requires a prior
``build-image``. This also generates and persists the target's ``upgrade-code`` if it
is unset.

Examples
--------

.. code-block:: bash

   # Build one target of a sample (the samples define several targets, so
   # ``build`` requires naming the one(s) to build)
   uv run pyappdist build win32-msi -C samples/pandascli

   # Build only specific targets by name
   uv run pyappdist build win-user win-machine
