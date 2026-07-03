Windows — MSI installer
=======================

``format = "msi"`` produces a Windows ``.msi`` installer.

* ``appdist/<target>/dist/<name>-<version>.msi`` — the installer.

Only ``platform = "windows-x86_64"`` may use this format.

Build requirements
------------------

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — to compile the launcher
  ``.exe``. Located automatically via ``vswhere``; no need to put ``cl.exe`` on
  ``PATH``.
* **WiX v5** — to build the MSI. Pin to **v5.0.2**: v6/v7 require accepting a
  EULA that blocks an unattended ``wix build``.
* Only when you set ``license``, also add the WiX UI extension (once)::

     wix extension add -g WixToolset.UI.wixext/5.0.2

If you don't have the toolchain yet, install both with ``winget`` from an
**elevated** PowerShell — the build-only Build Tools (no full Visual Studio IDE)
are enough:

.. code-block:: powershell

   # MSVC C++ build tools (the "Desktop development with C++" workload)
   winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

   # WiX v5 — a .NET tool, so install the .NET SDK first
   winget install --id Microsoft.DotNet.SDK.10 -e
   dotnet tool install --global wix --version 5.0.2

(The full Visual Studio Community edition,
``Microsoft.VisualStudio.2022.Community``, works too if you prefer the IDE — use
the same ``--override`` workload arguments.)

Configuration
-------------

``manufacturer`` (**required**)
   Manufacturer / vendor name. Required to generate the MSI; also used as the
   launcher's version-resource company name.

``scope``
   Install scope. ``"user"`` (default) makes a per-user package that installs
   into ``%LocalAppData%\Programs\<name>`` with no administrator rights (registry
   in ``HKCU``). ``"machine"`` installs into ``Program Files`` and requires admin
   (registry in ``HKLM``).

``upgrade-code``
   Stable upgrade GUID. **If omitted, pyappdist generates a UUID and writes it
   back into this target's table** on the first build. Must stay stable for the
   life of the product, and is per target.

``license``
   Path (relative to the project) to an **RTF** end-user license agreement. When
   set, the installer shows a one-page license dialog (WixUI_Minimal).

``code-sign``
   Code-sign the launcher ``.exe`` and the ``.msi`` (default ``false``). See
   :ref:`msi-code-signing` below.

``code-sign-command``
   Signing command used when ``code-sign`` is true, unless overridden by the
   ``PYAPPDIST_SIGN_CMD`` environment variable. Defaults to a ``signtool``
   invocation. See :ref:`msi-code-signing` below.

``allow-same-version-upgrades``
   Sets ``AllowSameVersionUpgrades="yes"`` on the WiX ``MajorUpgrade`` (default
   ``false``). With it on, reinstalling the **same** version upgrades in place instead
   of erroring or installing side-by-side — convenient while iterating on a build
   without bumping the version. MSI-only; it has no effect on ``msix`` targets.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   scope = "user"            # "user" (default) or "machine"
   # upgrade-code = "..."    # auto-generated and written back if omitted
   # license = "EULA.rtf"    # optional EULA shown at install time
   # code-sign = true        # sign the .exe and .msi (see below)
   # allow-same-version-upgrades = false  # reinstall same version upgrades in place

Install behavior
----------------

A ``machine`` install always requires elevation: an admin gets a UAC consent
prompt, a standard user gets a UAC credential prompt (and cannot install without
admin rights). A ``user`` install never needs elevation.

For unattended installs, suppress the UI with ``/qn`` (silent) or ``/qb`` (progress
only); the license is then not shown and no acceptance step is required:

.. code-block:: bat

   msiexec /i app.msi /qn

Upgrades
--------

The MSI uses WiX ``MajorUpgrade`` keyed on ``upgrade-code``. Component GUIDs are
derived deterministically as ``uuid5(upgrade-code, install-relative-path)``, so the
same layout and the same ``upgrade-code`` always produce the same component
identity — installing a newer version cleanly replaces the old one. Keep
``upgrade-code`` stable for the life of the product. The generated value is written
back with ``tomlkit``, which preserves your file's existing formatting and comments.

Launchers are compiled native ``.exe`` stubs: ``gui = true`` uses ``pythonw.exe``
(no console) and ``icon`` is embedded into the executable and the Start-menu
shortcut.

.. _msi-code-signing:

Code signing
------------

MSI targets are unsigned by default. Enable signing with ``code-sign = true`` on the
target; ``pyappdist build`` then signs each launcher ``.exe`` after it is compiled and
the ``.msi`` after it is built.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "win"
   platform = "windows-x86_64"
   format = "msi"
   code-sign = true
   # code-sign-command = 'signtool.exe sign ... "{file}"'   # optional; default used if omitted

With ``code-sign = true`` the signing command is resolved in this order:

1. the ``PYAPPDIST_SIGN_CMD`` environment variable (highest priority);
2. the target's ``code-sign-command``;
3. a built-in default:
   ``signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"``.

The default uses ``/a`` to auto-select the best certificate from the Windows certificate
store, so a non-secret command line can live in ``pyproject.toml``; use
``PYAPPDIST_SIGN_CMD`` to override per machine (for example a ``.pfx`` whose password
must not be committed). The token ``{file}`` is replaced with the path of the artifact
being signed (appended to the command if absent).

When ``code-sign`` is unset (or ``false``), signing is skipped regardless of
``PYAPPDIST_SIGN_CMD``.

.. note::

   Obtaining and managing code-signing certificates is out of scope for
   pyappdist. Unsigned installers will trigger a Windows SmartScreen warning.
