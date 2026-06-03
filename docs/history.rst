Release history
===============

0.2.0
-----

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
