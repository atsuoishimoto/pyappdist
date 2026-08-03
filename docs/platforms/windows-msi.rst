Windows — MSI installer
=======================

``format = "msi"`` produces a Windows ``.msi`` installer.

* ``appdist/<target>/dist/<name>-<version>.msi`` — the installer.

The MSI is the direct-distribution path on Windows: users download the
installer and run it — no Store account, no Developer Mode. By default it
installs per-user, without administrator rights. The installer is unsigned
unless you enable signing, and unsigned installers trigger a Windows
SmartScreen warning — see :ref:`msi-code-signing` below.

Only ``platform = "windows-x86_64"`` or ``"windows-arm64"`` may use this
format. Building the ``windows-arm64`` variant requires an ARM64 Windows host
(for launcher source builds, also the "MSVC C++ ARM64 build tools" component);
x64 Windows cannot run the target runtime's ``python.exe``. The app ``version`` must be
dotted numeric (e.g. ``"1.2.3"``) — MSI's ProductVersion cannot express
pre-releases such as ``"1.0.0rc1"``, so those are rejected at load time (same
for ``msix``).

Build requirements
------------------

* **WiX v5** — to build the MSI. Pin to **v5.0.2**: v6/v7 require accepting a
  EULA that blocks an unattended ``wix build``.
* Only when you set ``license``, also add the WiX UI extension (once)::

     wix extension add -g WixToolset.UI.wixext/5.0.2

* **Optional — MSVC C++ build tools** (``cl.exe`` / ``rc.exe``), for launcher
  source builds only. Released pyappdist wheels bundle prebuilt launcher
  stubs that the build configures per app without a compiler; MSVC is used
  only when no stub is bundled (e.g. pyappdist installed from a git checkout)
  or with ``launcher-build = "source"``. Located automatically via
  ``vswhere``; no need to put ``cl.exe`` on ``PATH``.

If you don't have the toolchain yet, install it with ``winget`` from an
**elevated** PowerShell:

.. code-block:: powershell

   # WiX v5 — a .NET tool, so install the .NET SDK first
   winget install --id Microsoft.DotNet.SDK.10 -e
   dotnet tool install --global wix --version 5.0.2

Only for launcher source builds, also install the MSVC C++ build tools — the
build-only Build Tools (no full Visual Studio IDE) are enough:

.. code-block:: powershell

   # The "Desktop development with C++" workload
   winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

(The full Visual Studio Community edition,
``Microsoft.VisualStudio.2022.Community``, works too if you prefer the IDE —
use the same ``--override`` workload arguments.)

Configuration
-------------

``manufacturer`` (**required**)
   Manufacturer / vendor name. Required to generate the MSI; also used as the
   launcher's version-resource company name.

``scope``
   Install scope. ``"user"`` (default) makes a per-user package that installs
   into ``%LocalAppData%\Programs\<name>`` with no administrator rights
   (registry in ``HKCU``). ``"machine"`` installs into ``Program Files`` and
   requires admin (registry in ``HKLM``).

``upgrade-code``
   Stable upgrade GUID. **If omitted, pyappdist generates a UUID and writes it
   back into this target's table** on the first build. Must stay stable for
   the life of the product, and is per target. See `Upgrades`_.

``license``
   Path (relative to the project) to an **RTF** end-user license agreement.
   When set, the installer shows a one-page license dialog (WixUI_Minimal).

``code-sign`` / ``code-sign-command``
   Sign the launcher ``.exe``\ s and the ``.msi`` (default: unsigned). See
   :ref:`msi-code-signing`.

``allow-same-version-upgrades``
   Sets ``AllowSameVersionUpgrades="yes"`` on the WiX ``MajorUpgrade``
   (default ``false``). With it on, reinstalling the **same** version upgrades
   in place instead of erroring or installing side-by-side — convenient while
   iterating on a build without bumping the version. MSI-only; it has no
   effect on ``msix`` targets.

``add-to-path``
   Append the install folder — where the launcher ``.exe``\ s live — to
   ``PATH`` (default ``false``), so command-line launchers can be run by name
   from a terminal. The scope follows the package scope: a ``user`` install
   edits the per-user ``PATH``, a ``machine`` install the system one.
   Uninstalling removes exactly the appended entry. Windows applies the
   change to processes started *after* the install; already-open terminals
   must be reopened to see it.

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
   # add-to-path = true      # append the install folder to PATH

Launchers
---------

Launchers are compiled native ``.exe`` stubs: ``gui = true`` uses
``pythonw.exe`` (no console) and the launcher's ``icon = { windows = "*.ico" }``
is embedded into the executable and the Start-menu shortcut.

The **first** launcher that declares a Windows icon also supplies the product
icon shown in Add/Remove Programs (Settings → Apps), via ``ARPPRODUCTICON``.
With no Windows launcher icon the product keeps the generic Windows Installer
icon there.

Install behavior
----------------

A ``machine`` install always requires elevation: an admin gets a UAC consent
prompt, a standard user gets a UAC credential prompt (and cannot install
without admin rights). A ``user`` install never needs elevation.

For unattended installs, suppress the UI with ``/qn`` (silent) or ``/qb``
(progress only); the license is then not shown and no acceptance step is
required:

.. code-block:: bat

   msiexec /i app.msi /qn

Upgrades
--------

The MSI uses WiX ``MajorUpgrade`` keyed on ``upgrade-code``. Component GUIDs
are derived deterministically as ``uuid5(upgrade-code,
install-relative-path)``, so the same layout and the same ``upgrade-code``
always produce the same component identity — installing a newer version
cleanly replaces the old one. Keep ``upgrade-code`` stable for the life of
the product. The generated value is written back with ``tomlkit``, which
preserves your file's existing formatting and comments.

Windows Installer compares only the **first three** fields of ProductVersion
when deciding whether an install is an upgrade. A four-field version is
accepted, but two releases differing solely in the fourth field
(``1.2.3.4`` → ``1.2.3.5``) are the same version to it: ``MajorUpgrade`` does
not fire, and without ``allow-same-version-upgrades`` the install errors or
the two versions end up side by side. pyappdist prints a warning when an msi
target is built from a four-field version. (``msix`` is unaffected — its
Identity Version uses all four fields.)

.. _msi-code-signing:

Code signing
------------

Windows targets are unsigned by default, and an unsigned installer triggers a
Windows SmartScreen warning when users download and run it. Signing removes
the warning (after the certificate builds reputation) but requires a
code-signing certificate — obtaining and managing one is out of scope for
pyappdist.

Enable signing with ``code-sign = true`` on the target, or force it from the
command line with ``pyappdist build --code-sign`` (``--no-code-sign`` forces
it off, for example on a machine without a certificate). ``pyappdist build``
then signs each launcher ``.exe`` after it is compiled and the ``.msi`` after
it is built. The same keys work identically on ``msix`` targets (the launcher
``.exe``\ s and the ``.msix``) and on Windows ``image`` targets (the launcher
``.exe``\ s).

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "win"
   platform = "windows-x86_64"
   format = "msi"
   code-sign = true
   # code-sign-command = 'signtool.exe sign ... "{file}"'   # optional; default used if omitted

With signing enabled the signing command is resolved in this order:

1. the ``PYAPPDIST_WIN_SIGN_CMD`` environment variable (highest priority);
2. the target's ``code-sign-command``;
3. a built-in default:
   ``signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"``.

The default uses ``/a`` to auto-select the best certificate from the Windows
certificate store, so a non-secret command line can live in
``pyproject.toml``; use ``PYAPPDIST_WIN_SIGN_CMD`` to override per machine
(for example a ``.pfx`` whose password must not be committed). The
environment variable only supplies the *command*: with ``code-sign`` unset
(or ``false``) and no ``--code-sign``, signing is skipped regardless of
``PYAPPDIST_WIN_SIGN_CMD``. The retired ``PYAPPDIST_SIGN_CMD`` variable
(which used to both enable signing and supply the command for some formats)
is ignored with a warning.

However the command is supplied, it runs with the artifact's directory as
the working directory, and the token ``{file}`` is replaced with the
artifact's file name (appended to the command if absent) — this is what makes
signing work when cross-building from WSL, where ``signtool.exe`` cannot
resolve Linux paths. Any other file referenced in the command (such as a
``.pfx``) must therefore be given as an absolute path — a Windows-side path
like ``D:\certs\app.pfx`` when cross-building.
