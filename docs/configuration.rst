Configuration
=============

All configuration lives in your app's ``pyproject.toml`` under
``[tool.pyappdist]``. ``pyproject.toml`` is the single source of truth.

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
   * - ``identifier``
     - no
     - Reverse-DNS application identifier (e.g. ``"com.example.myapp"``).
   * - ``target``
     - no
     - Distribution target. Defaults to ``"windows-x86_64"``. See
       :ref:`configuration:Targets`.
   * - ``manager``
     - no
     - Package manager used to pin dependencies: ``"uv"``, ``"poetry"``,
       ``"pipenv"``, ``"pdm"``, or ``"requirements.txt"``. Auto-detected from the
       lockfile when omitted. See :doc:`dependencies`.

.. code-block:: toml

   [tool.pyappdist]
   name = "My App"
   identifier = "com.example.myapp"
   python = "3.12"
   target = "windows-x86_64"

Targets
~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 45 30

   * - ``target``
     - python-build-standalone triple
     - OS
   * - ``windows-x86_64``
     - ``x86_64-pc-windows-msvc``
     - windows
   * - ``linux-x86_64``
     - ``x86_64-unknown-linux-gnu``
     - linux

``windows-x86_64`` is the real distribution target. ``linux-x86_64`` exists
mainly for validating the pipeline on Linux (no MSI is produced for it).

``[[tool.pyappdist.launchers]]``
--------------------------------

An array of tables — one entry per executable to produce. At least one is
required to build launchers.

.. list-table::
   :header-rows: 1
   :widths: 15 15 70

   * - Key
     - Required
     - Description
   * - ``name``
     - yes
     - Output executable name without extension (``"myapp"`` → ``myapp.exe``).
   * - ``entry``
     - yes
     - Entry point as ``"module:callable"``. The callable is invoked with no
       arguments and its return value becomes the process exit code.
   * - ``gui``
     - no
     - ``true`` builds a windowed launcher using ``pythonw.exe`` (no console).
       Defaults to ``false`` (console, ``python.exe``).
   * - ``icon``
     - no
     - Path to an ``.ico`` file, relative to the project directory. Embedded in
       the executable.
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

``[tool.pyappdist.wix]``
------------------------

Settings for the WiX/MSI installer.

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Required
     - Description
   * - ``manufacturer``
     - for MSI
     - Manufacturer / vendor name. Required to generate the MSI; also used as the
       launcher's version-resource company name.
   * - ``upgrade_code``
     - no
     - Stable upgrade GUID. **If omitted, pyappdist generates a UUID and writes it
       back into this table** on first build (so subsequent upgrades stay
       consistent). It must remain stable for the life of the product.
   * - ``scope``
     - no
     - Install scope of the MSI, a build-time choice. ``"user"`` (default) makes a
       per-user package that installs into ``%LocalAppData%\Programs\<name>`` with no
       administrator rights (registry in ``HKCU``). ``"machine"`` makes a per-machine
       package that installs into ``Program Files`` and requires administrator rights
       (registry in ``HKLM``). There is no install-time scope dialog.
   * - ``license``
     - no
     - Optional path (relative to the project) to an **RTF** end-user license
       agreement. When set, the installer shows a one-page license dialog
       (WixUI_Minimal). Works with either scope.

.. code-block:: toml

   [tool.pyappdist.wix]
   manufacturer = "Example Inc."
   # upgrade_code is filled in automatically on first build
   scope = "user"          # "user" (default) or "machine"
   license = "EULA.rtf"     # optional EULA shown at install time

.. note::

   A ``machine`` install always requires elevation: an admin gets a UAC consent prompt,
   a standard user gets a UAC credential prompt (and cannot install without admin
   rights). A ``user`` install never needs elevation.

   For unattended installs, suppress the UI with ``/qn`` (silent) or ``/qb`` (progress
   only); the license is then not shown and no acceptance step is required:

   .. code-block:: bat

      msiexec /i app.msi /qn

   Building a package with a ``license`` requires the WiX UI extension; install it once
   with ``wix extension add -g WixToolset.UI.wixext/5.0.2``.

.. note::

   The ``upgrade_code`` is written back using ``tomlkit``, which preserves your
   file's existing formatting and comments.
