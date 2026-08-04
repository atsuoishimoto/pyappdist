Configuration
=============

All configuration lives in your app's ``pyproject.toml`` under
``[tool.pyappdist]``. ``pyproject.toml`` is the single source of truth.

It has three parts:

* :ref:`[tool.pyappdist] <config-app>` — app-level settings (the runtime version,
  display name, dependency manager).
* :ref:`[[tool.pyappdist.launchers]] <config-launchers>` — one entry per executable
  to produce.
* :ref:`[[tool.pyappdist.targets]] <config-targets>` — one entry per output package:
  a few keys common to every format, plus the keys of the target's
  :ref:`output format <config-formats>`.

This page describes **every** configuration key. The per-format pages cover the
rest — build requirements, install behavior, signing walkthroughs — and are
linked from each :ref:`format section <config-formats>` below.

Before configuring anything, make sure the project itself is packageable — see
:ref:`What your project must satisfy <project-prereqs>`.

.. _config-app:

``[tool.pyappdist]``
--------------------

``python`` (required)
   Python version for the bundled runtime, as ``X.Y`` or ``X.Y.Z``
   (e.g. ``"3.12"``).

``name``
   Display name of the app. Defaults to ``[project].name``.

``version``
   Product version. When omitted (the usual case), the version is taken from
   the app wheel pyappdist builds during ``build-wheels``: that PEP 517 build
   runs the project's own build backend, so both a static
   ``[project].version`` and a backend-computed dynamic one (hatch-vcs,
   setuptools-scm, …) are honored, in PEP 440 normalized form. Set this key to
   pin the product version independently of the wheel.

   When any target uses ``format = "msi"`` or ``"msix"``, the version must be
   dotted numeric (e.g. ``"1.2.3"``) — MSI's ProductVersion cannot express
   pre-releases. The check runs as soon as the version is known: at load time
   for an explicit ``version`` (``"1.0.0rc1"`` is rejected immediately),
   otherwise right after ``build-wheels`` — so building between VCS tags
   (e.g. setuptools-scm's ``1.2.3.dev4+g1a2b3c``) fails there.

   Up to four fields are accepted, but Windows Installer compares only the
   **first three** when deciding whether an install is an upgrade. Two MSI
   releases differing solely in the fourth field (``1.2.3.4`` → ``1.2.3.5``)
   are the same version to it, so ``MajorUpgrade`` does not fire; pyappdist
   warns when an msi target is built from such a version. (MSIX is unaffected —
   its Identity Version uses all four fields.)

   Without an explicit ``version``, the standalone ``build-launchers`` and
   ``gen-wix`` commands need the wheelhouse from a prior ``build-wheels`` run
   to know the version.

``manager``
   Package manager used to pin dependencies: ``"uv"``, ``"poetry"``,
   ``"pipenv"``, ``"pdm"``, or ``"requirements.txt"``. Auto-detected from the
   lockfile when omitted. See :doc:`dependencies`.

``identifier``
   CFBundleIdentifier in reverse-DNS form (e.g. ``"com.example.myapp"``).
   **Required** when any target uses ``format = "macapp"``, ``"dmg"``, or
   ``"pkg"``; unused by the other formats. With multiple launchers each bundle
   derives ``<identifier>.<launcher>``.

.. code-block:: toml

   [tool.pyappdist]
   name = "My App"
   python = "3.12"
   # identifier = "com.example.myapp"   # required for macapp/dmg/pkg targets

.. _config-launchers:

``[[tool.pyappdist.launchers]]``
--------------------------------

An array of tables — one entry per executable to produce. At least one is required
to build launchers. The same launcher set is used for every target; how a launcher
is realized depends on the format (a compiled ``.exe`` on Windows, a relocatable
shell wrapper on Linux/macOS).

``name`` (required)
   Output executable name without extension (``"myapp"`` → ``myapp.exe`` on
   Windows). Because the name becomes a filename and an installer record, it
   must not contain whitespace, control characters, or any of ``<>:"/\|?*``.

``entry`` (required)
   Entry point, in one of two forms:

   * ``"module:callable"`` — import ``callable`` from ``module`` and invoke it with
     no arguments; its return value becomes the process exit code.
   * ``"module.path"`` (no colon) — run the module as ``python -m module.path``
     (executed with ``__name__ == "__main__"``). Use this for apps whose startup
     lives under an ``if __name__ == "__main__":`` guard (e.g. NiceGUI).

``gui``
   ``true`` builds a windowed launcher using ``pythonw.exe`` (no console) on
   Windows. Defaults to ``false`` (console, ``python.exe``). On Linux it only
   affects launchers that also set an ``icon``: the generated ``.desktop``
   entry gets ``Terminal=false`` when ``true`` (``Terminal=true`` otherwise).
   Ignored by the macOS ``.run``.

``icon``
   A **per-OS table** of icon paths (relative to the project directory); each key is
   optional:

   * ``windows`` — an ``.ico``, embedded in the ``.exe``.
   * ``macos`` — a ``.png`` (ideally ≥1024×1024), converted to the ``.app``'s ``.icns``.
   * ``linux`` — an image (``.png`` recommended) used for the ``.desktop`` entry.

   A plain string is **not** accepted — give the format each platform needs. An omitted
   key means that platform gets no icon (macOS falls back to a generated placeholder).

``args``
   Fixed arguments, prepended to the program's argv. Two forms:

   * **Shell form** — a single string, split into individual arguments with
     **POSIX shell quoting rules**, at build time, on every platform — so
     ``args = "--path 'a b'"`` is always the two arguments ``--path`` and
     ``a b``. A string that cannot be parsed (an unbalanced quote, say) is
     rejected at load time.
   * **Exec form** — an array of strings, used verbatim as the argument list
     with no splitting at all: ``args = ["--path", "a b"]`` is exactly those
     two arguments, with no quoting to get right.

   Either way, each launcher embeds the resulting argument list in the form its
   own OS needs, and nothing is glob-expanded or re-split when the app runs.

.. code-block:: toml

   [[tool.pyappdist.launchers]]
   name = "myapp"
   entry = "myapp:main"
   gui = false
   # args = "--profile default"

   [[tool.pyappdist.launchers]]
   name = "myapp-gui"
   entry = "myapp.gui:main"
   gui = true
   icon = { windows = "assets/app.ico", macos = "assets/app.png", linux = "assets/app.png" }

.. _config-targets:

``[[tool.pyappdist.targets]]``
------------------------------

An array of tables — one entry per output package. At least one target is required.
The individual pipeline stages apply to **all** targets by default; ``pyappdist
build`` builds the sole target, or the ones you name: ``pyappdist build <name>
<name>`` (see :doc:`cli`).

These keys are common to every format; the format-specific keys are described
under :ref:`Output formats <config-formats>` below.

``platform`` (required)
   Distribution platform (see :ref:`Platform values <config-platforms>`).

``format`` (required)
   Output package format. Must match the platform's OS — a mismatch (e.g.
   ``"msi"`` with ``linux-x86_64``) is rejected at load:

   * ``"msi"`` — Windows ``.msi`` installer. Windows platforms only.
   * ``"msix"`` — Windows ``.msix`` package (Store / sideloading). Windows
     platforms only.
   * ``"linux"`` — self-extracting ``.run`` installer. Linux platforms only.
   * ``"macos"`` — self-extracting ``.run`` installer, like the Linux one, for
     command-line tools. macOS platforms only.
   * ``"macapp"`` — a ``.app`` bundle, for GUI distribution. macOS platforms
     only.
   * ``"dmg"`` — the same ``.app`` bundle(s), wrapped in a ``.dmg`` disk image.
     macOS platforms only.
   * ``"pkg"`` — a system-scope ``.pkg`` installer that puts the ``.app``
     bundle(s) into ``/Applications``. macOS platforms only.
   * ``"image"`` — no installer, an archive of the image tree. The exception:
     valid on **every** platform.

``name`` (required)
   Label used to select this target on the command line and as its output
   subdirectory — artifacts in ``appdist/<name>/``, intermediates in
   ``.appdist-build/<name>/``. Must be unique across targets. Because it
   becomes a path component, it must not contain whitespace, control
   characters, or any of ``<>:"/\|?*``, must not be ``.`` or ``..``, and must
   not end with ``.``.

``extras`` (optional)
   A list of ``[project.optional-dependencies]`` extras to bundle for this target,
   passed through to the lockfile export (e.g. uv's ``--extra``). Defaults to an
   empty list, i.e. production dependencies only (dev excluded). See
   :doc:`dependencies`.

``launcher-build`` (optional)
   How the compiled launchers are produced, on the formats whose launcher is a
   native binary — ``msi`` / ``msix``, ``macapp`` / ``dmg`` / ``pkg``, and
   ``image`` on Windows platforms (elsewhere the launchers are shell wrappers
   and the key is rejected):

   * ``"auto"`` (default) — use the prebuilt launcher stub bundled with
     pyappdist when present (released wheels bundle stubs for every supported
     target, so **no C compiler is needed**), else compile from source.
   * ``"prebuilt"`` — require the bundled stub; fail rather than compile.
   * ``"source"`` — always compile the launcher with MSVC / clang.

   A prebuilt launcher is byte-identical to a source-built one in behavior:
   the per-app values are patched into the ``.exe`` as Windows resources
   (config, icon, version info), or written as a sidecar
   ``Contents/Resources/pyappdist-launcher.json`` for the macOS ``.app``
   (sealed by the bundle's code signature). The prebuilt macOS stub targets
   macOS 11.0+; ``min-macos`` still sets ``LSMinimumSystemVersion``, but only
   a source build compiles with a different deployment target.

.. _config-platforms:

Platform values
~~~~~~~~~~~~~~~~

Every platform additionally accepts format ``image``.

``windows-x86_64``
   Triple ``x86_64-pc-windows-msvc`` · OS windows · format ``msi`` / ``msix``.

``windows-arm64``
   Triple ``aarch64-pc-windows-msvc`` · OS windows · format ``msi`` / ``msix``.
   Building requires an ARM64 Windows host (the pipeline runs the target
   runtime's ``python.exe``, which x64 Windows cannot execute).

``linux-x86_64``
   Triple ``x86_64-unknown-linux-gnu`` · OS linux · format ``linux``.

``linux-aarch64``
   Triple ``aarch64-unknown-linux-gnu`` · OS linux · format ``linux``.
   Building requires an aarch64 Linux host (or binfmt/qemu user emulation),
   since the pipeline runs the target runtime's ``python``.

``macos-aarch64``
   Triple ``aarch64-apple-darwin`` · OS macos · format ``macos`` / ``macapp`` /
   ``dmg`` / ``pkg``.

``macos-x86_64``
   Triple ``x86_64-apple-darwin`` · OS macos · format ``macos`` / ``macapp`` /
   ``dmg`` / ``pkg``.

.. _config-formats:

Output formats
--------------

Each format adds its own keys to the target table, next to the common keys
above; a key used on a format it is not valid for is rejected at load. This
section describes every format-specific key. Each format's page covers what
this page does not: build requirements, install behavior, and the signing /
notarization walkthroughs.

``msi`` — Windows installer
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds ``dist/<name>-<version>.msi``. Details: :doc:`platforms/windows-msi`.

``manufacturer`` (**required**)
   Manufacturer / vendor name. Required to generate the MSI; also used as the
   launcher's version-resource company name.

``scope``
   Install scope:

   * ``"user"`` (default) — per-user package that installs into
     ``%LocalAppData%\Programs\<name>`` with no administrator rights (registry
     in ``HKCU``).
   * ``"machine"`` — installs into ``Program Files`` and requires admin
     (registry in ``HKLM``).

``upgrade-code``
   Stable upgrade GUID. **If omitted, pyappdist generates a UUID and writes it
   back into this target's table** on the first build. Must stay stable for the
   life of the product, and is per target.

``license``
   Path (relative to the project) to an **RTF** end-user license agreement. When
   set, the installer shows a one-page license dialog (WixUI_Minimal).

``allow-same-version-upgrades``
   Sets ``AllowSameVersionUpgrades="yes"`` on the WiX ``MajorUpgrade`` (default
   ``false``). With it on, reinstalling the **same** version upgrades in place instead
   of erroring or installing side-by-side — convenient while iterating on a build
   without bumping the version. MSI-only; it has no effect on ``msix`` targets.

``add-to-path``
   Append the install folder — where the launcher ``.exe``\ s live — to ``PATH``
   (default ``false``), so command-line launchers can be run by name from a
   terminal. The scope follows the package scope: a ``user`` install edits the
   per-user ``PATH``, a ``machine`` install the system one. Uninstalling removes
   exactly the appended entry. Windows applies the change to processes started
   *after* the install; already-open terminals must be reopened to see it.

``code-sign`` / ``code-sign-command``
   Sign the launcher ``.exe``\ s and the ``.msi`` — see
   :ref:`Windows code signing <config-win-code-sign>`.

``msix`` — Windows package (Store / sideloading)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds ``dist/<name>-<version>.msix``, left unsigned by default (the Microsoft
Store signs it on submission). Details: :doc:`platforms/windows-msix`.

``manufacturer``
   Vendor name; used as the launcher's version-resource company name and as the
   default publisher (``CN=<manufacturer>``; when unset, the app ``name`` is
   used instead).

``identity-name``
   Package Identity Name (for the Store, the reserved ``Publisher.AppName``).
   Defaults to ``[project].name``.

``publisher``
   Package Identity Publisher DN (e.g. ``"CN=Contoso"``). Must match the
   Partner Center value (Store) or the signing certificate's subject
   (sideloading). Defaults to ``CN=<manufacturer>``, or ``CN=<app name>``
   when ``manufacturer`` is also unset.

``display-name``
   App display name. Defaults to ``[tool.pyappdist].name``.

``logo``
   Path to a source ``.png`` used for the package logos. A placeholder is
   generated if omitted.

``code-sign`` / ``code-sign-command``
   Sign the launcher ``.exe``\ s and the ``.msix`` yourself instead of relying
   on the Store — see :ref:`Windows code signing <config-win-code-sign>`.

.. _config-win-code-sign:

Windows code signing keys
~~~~~~~~~~~~~~~~~~~~~~~~~

These two keys are valid on any target with a signable Windows artifact —
``msi``, ``msix``, and ``image`` on a Windows platform; anywhere else they are
rejected at load. The full signing workflow is described in
:ref:`msi-code-signing`.

``code-sign``
   Code-sign the Windows artifacts (default ``false``): each launcher ``.exe``
   after it is compiled, and the ``.msi`` / ``.msix`` after it is built.
   Overridable per build with ``pyappdist build --code-sign`` /
   ``--no-code-sign``.

``code-sign-command``
   Signing command used when signing is enabled. The token ``{file}`` is
   replaced with the artifact's file name (appended if absent). With signing
   enabled, the command is resolved in this order:

   1. the ``PYAPPDIST_WIN_SIGN_CMD`` environment variable (highest priority);
   2. the target's ``code-sign-command``;
   3. a built-in default:
      ``signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"``.

``linux`` — .run installer
~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds a self-extracting per-user installer
``dist/<name>-<version>-<target>.run``. Details: :doc:`platforms/linux`.

``categories``
   freedesktop ``.desktop`` ``Categories`` value (default ``"Utility;"``). Used
   only for launchers that define an ``icon``.

``compression``
   Payload compression for the ``.run``: ``"gzip"``, ``"bzip2"`` or
   ``"xz"`` (default ``"xz"``). The matching decompressor must be present on the
   target machine at install time.

``macos`` — .run installer (command-line tools)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds the same self-extracting per-user ``.run`` installer as ``linux``;
launcher ``icon`` and ``gui`` are ignored (macOS has no freedesktop
integration). Build on a macOS host. Details: :doc:`platforms/macos-run`.

``compression``
   Payload compression for the ``.run``: ``"gzip"``, ``"bzip2"`` or
   ``"xz"`` (default ``"gzip"``, because ``xz`` is not preinstalled on macOS).

``macapp`` / ``dmg`` — .app bundle (GUI apps)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds one code-signed ``.app`` bundle per launcher into ``dist/``
(``macapp``), optionally wrapped in a ``dist/<name>-<version>.dmg`` disk image
(``dmg``). Native-only — build on a macOS host. The app-level ``identifier``
is **required**, and each ``.app``'s icon comes from its launcher's
``icon = { macos = ... }`` key (see :ref:`launchers <config-launchers>`), not
from a target key. Details: :doc:`platforms/macos-app`.

``min-macos``
   Minimum macOS version. Sets both the bundle's ``LSMinimumSystemVersion`` and clang's
   ``-mmacosx-version-min``. Default ``"11.0"``.

``category``
   ``LSApplicationCategoryType`` (e.g. ``"public.app-category.utilities"``). Optional.

``signing-identity``
   Developer ID identity for distribution signing, e.g.
   ``"Developer ID Application: Your Name (TEAMID)"``. The
   ``PYAPPDIST_MACOS_SIGNING_IDENTITY`` environment variable overrides this key.
   When neither is set the bundle is **ad-hoc signed** — it runs locally but
   Gatekeeper rejects it on other machines. See :ref:`macos-signing`.

``team-id``
   Apple Developer Team ID (informational).

``notary-profile``
   ``notarytool`` keychain profile name (the ``PYAPPDIST_MACOS_NOTARY_PROFILE``
   environment variable overrides this key). When set **and** a Developer ID
   identity is configured, the artifact is notarized and stapled.

``entitlements``
   Path to a custom entitlements ``.plist``. The default grants only
   ``com.apple.security.cs.disable-library-validation`` (so the hardened interpreter can
   load third-party extension modules); supply your own to add, e.g., JIT entitlements.

``pkg`` — macOS installer package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds the same signed ``.app`` bundle(s) as ``macapp`` / ``dmg``, then wraps
them in a system-scope ``dist/<name>-<version>.pkg`` that installs into
``/Applications`` (MDM-deployable). Native-only — build on a macOS host; the
app-level ``identifier`` is **required**. All the ``macapp`` / ``dmg`` keys
above apply unchanged, plus one key specific to ``pkg``. Details:
:doc:`platforms/macos-pkg`.

``installer-identity``
   A **Developer ID Installer** identity, e.g.
   ``"Developer ID Installer: Your Name (TEAMID)"`` (the
   ``PYAPPDIST_MACOS_INSTALLER_IDENTITY`` environment variable overrides this
   key), used to sign the ``.pkg`` itself. This is a *different certificate type* from the
   ``Developer ID Application`` identity that signs the bundles — create both in
   the Apple Developer portal. When unset the package is left unsigned: it
   installs locally, but Gatekeeper rejects it elsewhere and it cannot be
   notarized.

``image`` — archive, no installer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Archives the image tree itself into ``dist/<name>-<version>-<target>.zip``
(Windows targets) or ``.tar.gz`` (Linux/macOS targets). Valid on **every**
platform. Details: :doc:`platforms/image`.

``no-launcher``
   ``true`` skips launcher generation entirely, so the archive contains just the
   installed tree (default ``false``). Only valid with ``format = "image"``.

``code-sign`` / ``code-sign-command``
   On Windows platforms only: sign the launcher ``.exe``\ s — see
   :ref:`Windows code signing <config-win-code-sign>`. On Linux/macOS targets
   there is nothing to sign, so ``code-sign = true`` is rejected there.

Multi-target example
~~~~~~~~~~~~~~~~~~~~

A single project can declare several targets and produce all of these at once:

.. code-block:: toml

   [[tool.pyappdist.targets]]              # an MSI
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   # upgrade-code = "..."    # auto-generated and written back if omitted

   [[tool.pyappdist.targets]]              # a Linux .run installer
   name = "linux"
   platform = "linux-x86_64"
   format = "linux"

   [[tool.pyappdist.targets]]              # a macOS .run installer
   name = "macos-arm"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "macos"

.. _config-env-vars:

Environment variables
---------------------

Build-time settings that pyappdist reads from the environment. Platform-specific
variables carry the platform in their name (``PYAPPDIST_WIN_*`` /
``PYAPPDIST_MACOS_*``), and every variable takes precedence over the
corresponding config key.

``PYAPPDIST_WIN_SIGN_CMD``
   Windows. Signing command for Windows artifacts; overrides
   ``code-sign-command``. See :ref:`Windows code signing keys
   <config-win-code-sign>`.

``PYAPPDIST_WIN_WIX``
   Windows. Absolute path to the ``wix`` executable, instead of looking up
   ``wix.exe`` on ``PATH`` (``msi`` format).

``PYAPPDIST_WIN_MAKEAPPX``
   Windows. Absolute path to ``makeappx.exe``, instead of searching ``PATH``
   and the Windows SDK install locations (``msix`` format).

``PYAPPDIST_MACOS_SIGNING_IDENTITY``
   macOS. Developer ID Application identity; overrides ``signing-identity``
   (``macapp`` / ``dmg`` / ``pkg`` formats). See :doc:`platforms/macos-app`.

``PYAPPDIST_MACOS_NOTARY_PROFILE``
   macOS. ``notarytool`` keychain profile name; overrides ``notary-profile``.

``PYAPPDIST_MACOS_INSTALLER_IDENTITY``
   macOS. Developer ID Installer identity; overrides ``installer-identity``
   (``pkg`` format). See :doc:`platforms/macos-pkg`.
