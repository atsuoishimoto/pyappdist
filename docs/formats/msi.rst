MSI (Windows installer)
=======================

``format = "msi"`` produces a Windows ``.msi`` installer, plus a portable ``.zip``
of the same image that runs without installation.

* ``appdist/<target>/dist/<name>-<version>.msi`` — the installer.
* ``appdist/<target>/dist/<name>-<version>-portable.zip`` — the image tree, runnable
  in place (skip with ``--no-zip``).

Only ``platform = "windows-x86_64"`` may use this format.

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
   :doc:`/signing`.

``code-sign-command``
   Signing command used when ``code-sign`` is true, unless overridden by the
   ``PYAPPDIST_SIGN_CMD`` environment variable. Defaults to a ``signtool`` invocation.
   See :doc:`/signing`.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   scope = "user"            # "user" (default) or "machine"
   # license = "EULA.rtf"    # optional EULA shown at install time
   # code-sign = true        # sign the .exe and .msi (see /signing)

Build requirements
------------------

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — to compile the launcher
  ``.exe``. Located via ``vswhere``.
* **WiX v5** (``dotnet tool install --global wix --version 5.0.2``) — to build the
  MSI. Pin to **v5.0.2**: v6/v7 require accepting an EULA that blocks an unattended
  ``wix build``.
* Only when you set ``license``, also add the WiX UI extension (once)::

     wix extension add -g WixToolset.UI.wixext/5.0.2

On a non-Windows host the MSI step is skipped (the image is still built); see
:doc:`/installation` for cross-building from WSL.

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
shortcut. Optional code signing of the launchers and the MSI is available via
:doc:`/signing`.
