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

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Option
     - Description
   * - ``-C``, ``--project DIR``
     - The application's project directory (the one containing ``pyproject.toml``).
       Defaults to the current directory.
   * - ``--out-dir DIR``
     - Output base directory. Defaults to ``<project>/appdist``. Each target builds into
       ``<out-dir>/<target>/``.

Commands that fetch the runtime (``build``, ``build-wheels``,
``fetch-runtime``, ``build-image``) also accept:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Option
     - Description
   * - ``--runtime-release TAG``
     - Pin a specific python-build-standalone release tag.

Commands
--------

``build``
~~~~~~~~~

Run the whole pipeline for each selected target: wheels → runtime → image → launcher →
(sign) → zip → WiX → MSI → (sign).

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

(Re)build ``launcher.exe`` into an existing image. Requires a prior
``build-image``. Windows toolchain (MSVC) only.

``gen-wix``
~~~~~~~~~~~

Scan an existing image and generate the WiX ``.wxs`` file. Requires a prior
``build-image``. This also generates and persists the target's ``upgrade_code`` if it
is unset.

Examples
--------

.. code-block:: bash

   # Full build of a sample (all its targets)
   uv run pyappdist build -C samples/pandascli

   # Build only specific targets by name
   uv run pyappdist build win-user win-machine
