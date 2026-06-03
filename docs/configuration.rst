Configuration
=============

All configuration lives in your app's ``pyproject.toml`` under
``[tool.pyappdist]``. ``pyproject.toml`` is the single source of truth.

It has three parts:

* :ref:`[tool.pyappdist] <config-app>` — app-level settings (the runtime version,
  display name, dependency manager).
* :ref:`[[tool.pyappdist.launchers]] <config-launchers>` — one entry per executable
  to produce.
* :ref:`[[tool.pyappdist.targets]] <config-targets>` — one entry per output package.
  Format-specific keys are documented on each format's page (see
  :ref:`Output formats <config-formats>`).

.. _config-app:

``[tool.pyappdist]``
--------------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Required
     - Description
   * - ``python``
     - yes
     - Python version for the bundled runtime, as ``X.Y`` or ``X.Y.Z``
       (e.g. ``"3.12"``).
   * - ``name``
     - no
     - Display name of the app. Defaults to ``[project].name``.
   * - ``version``
     - no
     - Product version. Defaults to ``[project].version`` (then ``"0.0.0"``).
   * - ``manager``
     - no
     - Package manager used to pin dependencies: ``"uv"``, ``"poetry"``,
       ``"pipenv"``, ``"pdm"``, or ``"requirements.txt"``. Auto-detected from the
       lockfile when omitted. See :doc:`dependencies`.

.. code-block:: toml

   [tool.pyappdist]
   name = "My App"
   python = "3.12"

.. _config-launchers:

``[[tool.pyappdist.launchers]]``
--------------------------------

An array of tables — one entry per executable to produce. At least one is required
to build launchers. The same launcher set is used for every target; how a launcher
is realized depends on the format (a compiled ``.exe`` on Windows, a relocatable
shell wrapper on Linux/macOS).

.. list-table::
   :header-rows: 1
   :widths: 15 15 70

   * - Key
     - Required
     - Description
   * - ``name``
     - yes
     - Output executable name without extension (``"myapp"`` → ``myapp.exe`` on
       Windows).
   * - ``entry``
     - yes
     - Entry point as ``"module:callable"``. The callable is invoked with no
       arguments and its return value becomes the process exit code.
   * - ``gui``
     - no
     - ``true`` builds a windowed launcher using ``pythonw.exe`` (no console) on
       Windows. Defaults to ``false`` (console, ``python.exe``). Ignored on
       Linux/macOS.
   * - ``icon``
     - no
     - Path to an ``.ico`` file, relative to the project directory. Embedded in the
       Windows executable; on Linux it selects launchers that get a ``.desktop``
       entry; ignored on macOS.
   * - ``args``
     - no
     - Fixed arguments as a single string, prepended to the program's argv.

.. code-block:: toml

   [[tool.pyappdist.launchers]]
   name = "myapp"
   entry = "myapp:main"
   gui = false
   # icon = "assets/app.ico"
   # args = "--profile default"

   [[tool.pyappdist.launchers]]
   name = "myapp-gui"
   entry = "myapp.gui:main"
   gui = true
   icon = "assets/app.ico"

.. _config-targets:

``[[tool.pyappdist.targets]]``
------------------------------

An array of tables — one entry per output package. At least one target is required.
The individual pipeline stages apply to **all** targets by default; ``pyappdist
build`` builds the sole target, or the ones you name: ``pyappdist build <name>
<name>`` (see :doc:`cli`).

These keys are common to every format; the format-specific keys live on the
:ref:`format pages <config-formats>`.

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Required
     - Description
   * - ``platform``
     - yes
     - Distribution platform (see :ref:`Platform values <config-platforms>`).
   * - ``format``
     - yes
     - Output package. Must match the platform's OS: ``"msi"`` or ``"msix"`` on
       Windows, ``"linux"`` on Linux, ``"macos"`` on macOS. A mismatch (e.g.
       ``"msi"`` with ``linux-x86_64``) is rejected at load. See
       :ref:`Output formats <config-formats>`.
   * - ``name``
     - no
     - Label used to select this target on the command line and as its output
       subdirectory (``appdist/<name>/``). Defaults to ``platform``; must be unique.

.. _config-platforms:

Platform values
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 30 25 20

   * - ``platform``
     - python-build-standalone triple
     - OS
     - ``format``
   * - ``windows-x86_64``
     - ``x86_64-pc-windows-msvc``
     - windows
     - ``msi`` / ``msix``
   * - ``linux-x86_64``
     - ``x86_64-unknown-linux-gnu``
     - linux
     - ``linux``
   * - ``macos-aarch64``
     - ``aarch64-apple-darwin``
     - macos
     - ``macos``
   * - ``macos-x86_64``
     - ``x86_64-apple-darwin``
     - macos
     - ``macos``

.. _config-formats:

Output formats
~~~~~~~~~~~~~~

Each format has its own configuration keys, build requirements, and install
behavior:

.. list-table::
   :header-rows: 1
   :widths: 15 25 60

   * - Format
     - Output
     - Page
   * - ``msi``
     - ``.msi`` installer + portable ``.zip``
     - :doc:`formats/msi`
   * - ``msix``
     - ``.msix`` package (Store / sideloading)
     - :doc:`formats/msix`
   * - ``linux``
     - ``.tar.{gz,bz2,xz}`` + self-extracting ``.run``
     - :doc:`formats/linux`
   * - ``macos``
     - ``.tar.{gz,bz2,xz}`` + self-extracting ``.run``
     - :doc:`formats/macos`

A single project can declare several targets and produce all of these at once:

.. code-block:: toml

   [[tool.pyappdist.targets]]              # an MSI
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."

   [[tool.pyappdist.targets]]              # a Linux .tar.xz + .run installer
   name = "linux"
   platform = "linux-x86_64"
   format = "linux"

   [[tool.pyappdist.targets]]              # a macOS .tar.gz + .run installer
   name = "macos-arm"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "macos"
