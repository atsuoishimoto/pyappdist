Release history
===============

0.3.1
------

2026/06/07

**Windows launcher build no longer breaks when the current directory is excluded
from the executable search path.** The launcher build step now invokes the
generated batch file as ``.\build.bat`` instead of a bare ``build.bat``. On
systems where ``NoDefaultCurrentDirectoryInExePath`` is set, ``cmd.exe`` does not
search the current directory for the script, so the previous form failed to find
it and the MSI build aborted during launcher compilation.

**Quieter launcher compile.** The Windows launcher C source now uses
``_snwprintf_s`` (with ``_TRUNCATE``) instead of the deprecated ``_snwprintf``,
removing the MSVC ``C4996`` warning while guaranteeing null-termination on
truncation.

0.3.0
------

2026/06/06

**macOS .app / .dmg packages.** Two new GUI formats build native macOS
bundles: ``format = "macapp"`` produces a ``.app`` bundle and ``format = "dmg"``
wraps it in a disk image. A Mach-O launcher stub is compiled with ``clang``, the
``.app`` is assembled with an ``Info.plist`` and an ``icns`` icon, then
deep-codesigned (ad-hoc by default; Developer ID + hardened runtime when
``signing-identity`` is set) and, with a ``notary-profile``, notarized via
``notarytool`` and stapled. These formats require the app-level ``identifier``
(reverse-DNS CFBundleIdentifier) and build only on a macOS host.

**Per-OS launcher icons.** ``[[launchers]].icon`` is now a per-OS table —
``icon = { windows = "*.ico", macos = "*.png", linux = "*.png" }`` (each key
optional; a plain string is rejected). This replaces the old single ``.ico`` and
the target-level macOS icon, so each launcher can carry its own icon per OS.

**Opt-in MSI code signing.** Set ``code-sign = true`` on an MSI target to sign
the launcher ``.exe`` and the ``.msi``. The signing command is resolved with the
precedence ``PYAPPDIST_SIGN_CMD`` (env) > ``code-sign-command`` (config) > a
built-in ``signtool`` default. MSIX and the macOS ``.dmg`` keep their previous
environment-variable-only behavior.

**Per-target extras.** Each target may set an ``extras`` list selecting
``[project.optional-dependencies]`` extras to bundle. The names are passed
through to the lockfile export using the manager's own flag (uv ``--extra``,
poetry ``--extras``, pdm ``--group``, pipenv ``--categories``). The default is
empty (production dependencies only); extras are ignored with a warning in
``requirements.txt`` mode.

**python -m launcher entry.** A launcher ``entry`` may now be a colon-less
dotted ``"module.path"``, run as ``python -m module.path``
(``runpy.run_module`` with ``__name__ == "__main__"``), alongside the existing
``"module:callable"`` form. This packages apps whose startup lives under an
``if __name__ == "__main__":`` guard (e.g. NiceGUI) without modification.

**Config keys are now kebab-case** *(breaking)*. All underscore-separated
``[tool.pyappdist]`` keys were renamed to hyphenated form: ``upgrade-code``,
``code-sign``, ``code-sign-command``, ``identity-name``, ``display-name``,
``min-macos``, ``signing-identity``, ``team-id``, ``notary-profile``. Update
existing ``pyproject.toml`` files accordingly.

**Installer reports installed commands.** The POSIX self-extracting ``.run``
installer now lists the command names it symlinked into ``<prefix>/bin`` when it
finishes.

0.2.0
-----

2026/06/03


**Multiple output formats and targets.** A project can now produce several
packages from one configuration. The single ``[tool.pyappdist.wix]`` table plus
a single target has been replaced by a ``[[tool.pyappdist.targets]]`` array,
where each entry is one output package with its own ``platform`` and ``format``.
``format`` is now **required** and is validated against the platform's OS
(``msi``/``msix`` for Windows, ``linux`` for Linux, ``macos`` for macOS), so a
mismatch is reported as a configuration error at load time instead of failing
mid-build.

**MSIX output (Microsoft Store).** A new ``format = "msix"`` produces an
unsigned, full-trust Win32 ``.msix`` package — emitting ``AppxManifest.xml``
(one ``<Application>`` per launcher) and packing the image with ``makeappx``.
The Store signs the package on ingestion; local installs require Developer Mode.

**Linux packages.** A new ``format = "linux"`` builds a real Linux distribution
using relocatable shell-wrapper launchers (no MSVC), and emits two artifacts: a
``.tar.gz`` of the image tree and a self-extracting ``.run`` installer. The
installer is per-user (installs under ``$HOME/.local``, no root and no FUSE),
symlinks launchers into ``bin``, and writes a ``.desktop`` file for launchers
that declare an ``icon``.

**macOS packages.** A new ``format = "macos"`` (platforms ``macos-aarch64`` and
``macos-x86_64``) ships the same per-user tarball + self-extracting ``.run`` as
Linux, built on the matching macOS host. The default payload compression is
``gzip`` (``xz`` is not preinstalled on macOS), and — with no freedesktop
equivalent — launcher ``icon``/``gui`` are ignored, so the installer just
symlinks launchers into ``<prefix>/bin``.

**MSI install scope and licensing.** Install scope is now a build-time
machine/user choice: ``scope = "user"`` (default; installs per-user under
``%LocalAppData%\Programs``) or ``scope = "machine"`` (Program Files). The MSI
license (EULA) is now optional, and per-user installs get a proper user-folder
redirect.

**Internals.** Runtime extraction now uses the ``tarfile`` ``"tar"`` filter, and
the ``runtime_source`` option was dropped.

**Docs and samples.** Per-format details are now documented as independent
sections rather than notes; sample apps were translated to English; an
end-to-end editable-install verification project was added; each output format
now has its own documentation page; and design and migration notes for macOS
support were added.
