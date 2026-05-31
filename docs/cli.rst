Command-line interface
=======================

.. code-block:: text

   pyappdist <command> [project] [options]

``project`` is the path to the application's project directory (the one
containing ``pyproject.toml``). It defaults to the current directory (``.``).

Common options
--------------

Available on every command:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Option
     - Description
   * - ``--target TARGET``
     - Override the distribution target (e.g. ``windows-x86_64`` /
       ``linux-x86_64``).
   * - ``--out-dir DIR``
     - Output directory. Defaults to ``<project>/appdist``.

Commands that fetch the runtime (``build``, ``build-wheels``,
``fetch-runtime``, ``build-image``) also accept:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Option
     - Description
   * - ``--runtime-release TAG``
     - Pin a specific python-build-standalone release tag.
   * - ``--runtime-source PATH``
     - Use a local runtime ``tar.gz`` instead of downloading (offline).

Commands
--------

``build``
~~~~~~~~~

Run the whole pipeline: wheels → runtime → image → launcher → (sign) → zip →
WiX → MSI → (sign).

.. code-block:: bash

   uv run pyappdist build .

Extra options: ``--no-compile`` (skip byte-compilation), ``--no-zip`` (skip the
portable zip). Plus the common and runtime options above.

``build-wheels``
~~~~~~~~~~~~~~~~

Build the app wheel and collect dependency wheels into
``appdist/wheelhouse``. Fetches the runtime first (dependencies are resolved
with the target interpreter).

``fetch-runtime``
~~~~~~~~~~~~~~~~~

Download, verify, and extract the python-build-standalone runtime into
``appdist/runtime``.

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
``build-image``. This also generates and persists ``upgrade_code`` if it is
unset.

Examples
--------

.. code-block:: bash

   # Full build of a sample
   uv run pyappdist build samples/pandascli

   # Cross-validate the pipeline on Linux
   uv run pyappdist build-image . --target linux-x86_64

   # Offline runtime from a local archive
   uv run pyappdist fetch-runtime . --runtime-source ./cpython-3.12.tar.gz
