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
   * - ``manager``
     - no
     - Package manager used to pin dependencies: ``"uv"``, ``"poetry"``,
       ``"pipenv"``, ``"pdm"``, or ``"requirements.txt"``. Auto-detected from the
       lockfile when omitted. See :doc:`dependencies`.

.. code-block:: toml

   [tool.pyappdist]
   name = "My App"
   python = "3.12"

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

``[[tool.pyappdist.targets]]``
------------------------------

An array of tables — one entry per output package. ``pyappdist build`` builds them all
by default, or only the ones you name: ``pyappdist build <name> <name>``. At least one
target is required.

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Required
     - Description
   * - ``platform``
     - yes
     - Distribution platform (see the table below).
   * - ``name``
     - no
     - Label used to select this target on the command line and as its output
       subdirectory (``appdist/<name>/``). Defaults to ``platform``; must be unique.
   * - ``format``
     - **yes**
     - Output package, required and bound to the platform OS: ``"msi"`` or ``"msix"``
       (for the Microsoft Store or sideloading) on Windows, or ``"linux"`` (a portable
       ``.tar.gz`` plus a self-extracting ``.run`` installer) on Linux. A format that does
       not match the platform's OS is rejected. The keys below are grouped by which format
       uses them.
   * - ``manufacturer``
     - for MSI
     - Manufacturer / vendor name. Required to generate the MSI; also used as the
       launcher's version-resource company name and the MSIX PublisherDisplayName.
   * - ``upgrade_code``
     - no
     - *(MSI)* Stable upgrade GUID. **If omitted, pyappdist generates a UUID and writes
       it back into this target's table** on first build. Must stay stable for the life
       of the product, and is per target.
   * - ``scope``
     - no
     - *(MSI)* Install scope. ``"user"`` (default) makes a per-user package that installs
       into ``%LocalAppData%\Programs\<name>`` with no administrator rights (registry in
       ``HKCU``). ``"machine"`` installs into ``Program Files`` and requires admin
       (registry in ``HKLM``).
   * - ``license``
     - no
     - *(MSI)* Optional path (relative to the project) to an **RTF** end-user license
       agreement. When set, the installer shows a one-page license dialog (WixUI_Minimal).
   * - ``identity_name``
     - no
     - *(MSIX)* Package Identity Name (for the Store, the reserved ``Publisher.AppName``).
       Defaults to ``[project].name``.
   * - ``publisher``
     - no
     - *(MSIX)* Package Identity Publisher DN (e.g. ``"CN=Contoso"``); for the Store or
       signing it must match. Defaults to ``CN=<manufacturer>``.
   * - ``display_name``
     - no
     - *(MSIX)* App display name. Defaults to ``[tool.pyappdist].name``.
   * - ``logo``
     - no
     - *(MSIX)* Path to a source PNG used for the package logos. A placeholder is
       generated if omitted.
   * - ``categories``
     - no
     - *(Linux)* freedesktop ``.desktop`` ``Categories`` value (default ``"Utility;"``).
       Used only for launchers that define an ``icon``.

.. code-block:: toml

   [[tool.pyappdist.targets]]              # an MSI
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   scope = "user"            # "user" (default) or "machine"
   # license = "EULA.rtf"    # optional EULA shown at install time

   [[tool.pyappdist.targets]]              # an MSIX for the Store
   name = "store"
   platform = "windows-x86_64"
   format = "msix"
   manufacturer = "Example Inc."
   # identity_name = "Contoso.MyApp"   # from Partner Center for the Store
   # publisher = "CN=Contoso"
   # logo = "assets/logo.png"

   [[tool.pyappdist.targets]]              # a Linux .tar.gz + .run installer
   platform = "linux-x86_64"
   format = "linux"
   # categories = "Utility;Development;"   # for launchers that set an icon

Platform values
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 45 30

   * - ``platform``
     - python-build-standalone triple
     - OS
   * - ``windows-x86_64``
     - ``x86_64-pc-windows-msvc``
     - windows
   * - ``linux-x86_64``
     - ``x86_64-unknown-linux-gnu``
     - linux

``windows-x86_64`` is the Windows distribution target (``format = "msi"`` or ``"msix"``);
``linux-x86_64`` is the Linux target (``format = "linux"``). ``format`` is required and must
match the platform's OS — pairing, say, ``"msi"`` with ``linux-x86_64`` is rejected at load.

.. note::

   A ``machine`` install always requires elevation: an admin gets a UAC consent prompt,
   a standard user gets a UAC credential prompt (and cannot install without admin
   rights). A ``user`` install never needs elevation.

   For unattended installs, suppress the UI with ``/qn`` (silent) or ``/qb`` (progress
   only); the license is then not shown and no acceptance step is required:

   .. code-block:: bat

      msiexec /i app.msi /qn

   Building a target with a ``license`` requires the WiX UI extension; install it once
   with ``wix extension add -g WixToolset.UI.wixext/5.0.2``.

.. note::

   The ``upgrade_code`` is written back using ``tomlkit``, which preserves your
   file's existing formatting and comments.

.. note::

   **MSIX** (``format = "msix"``) packs the same image with ``makeappx`` (Windows SDK;
   located automatically, or set ``PYAPPDIST_MAKEAPPX`` to its path). The
   package is left **unsigned**: the Microsoft Store signs it for free on submission
   (company registration is also free), and auto-updates are handled by the Store. The
   launchers are packaged as full-trust Win32 apps (``runFullTrust``).

   To test an unsigned ``.msix`` locally, enable **Developer Mode** (Settings → For
   developers; one-time, requires admin), then::

      Add-AppxPackage -Register <image>\AppxManifest.xml   # loose, from the built image
      # or:  Add-AppxPackage -AllowUnsigned <app>.msix

   Without the Store or Developer Mode, an unsigned MSIX cannot be installed (it would
   need your own trusted code-signing certificate).

.. note::

   **Linux** (``format = "linux"``) builds two artifacts in ``appdist/<name>/dist/``:

   * ``<name>-<version>-<target>.tar.gz`` — the image tree under a top-level directory.
     Users who don't want an installer just extract it and run ``<dir>/<launcher>``.
   * ``<name>-<version>-<target>.run`` — a self-extracting installer (a POSIX shell
     script with the tarball appended). It needs no root and no FUSE: it copies the tree
     into ``<prefix>/lib/<name>`` (``$HOME/.local`` by default; override with
     ``--prefix``), symlinks each launcher into ``<prefix>/bin``, and — only for
     launchers that set an ``icon`` — writes a ``.desktop`` entry. It also drops an
     ``uninstall.sh`` next to the install, and ``./<app>.run --uninstall`` removes it.

   .. code-block:: console

      $ ./myapp-1.0-linux-x86_64.run            # install into ~/.local
      $ ./myapp-1.0-linux-x86_64.run --prefix ~/opt
      $ ./myapp-1.0-linux-x86_64.run --uninstall

   Each launcher becomes a small relocatable shell wrapper that runs the entry point
   with the bundled interpreter. Application updates are the app's own responsibility
   (pyappdist provides no auto-update mechanism).
