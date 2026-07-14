Release history
===============

0.9.0
-----

2026/07/13

**uv projects now export PEP 751** ``pylock.toml`` **instead of**
``requirements.txt``. Per-package index pins in ``uv.lock`` (e.g. a PyTorch
CUDA index) survive the export — pip fetches the recorded URLs directly. The
runtime's bundled pip is upgraded in place when it is too old to understand
pylock files.

**MSI builds no longer fail on deep install trees (WiX MAX_PATH limit).**
``wix build`` now receives the image as an extended-length (``\\?\``) bind
path, working around WiX's cabinet builder crashing with a broken-pipe
``IOException`` when a source file's absolute path exceeds 260 characters
(e.g. PyTorch's deeply nested ``dist-info`` license files).

**pipenv extras no longer drop production dependencies.** Extras were passed
as repeated ``--categories`` flags, which replaced the default ``packages``
category and shipped an app missing its production dependencies; one combined
``--categories packages,<extras...>`` flag is emitted now.

**The Windows launcher ignores Ctrl+C/Ctrl+Break.** Python alone decides how
to shut down (finally blocks, atexit hooks, and buffered output are preserved)
and its real exit code propagates, as with CPython's ``py.exe`` launcher.

**.pyc files use hash-based invalidation.** Timestamp-based ``.pyc`` went
stale after MSI packaging (CAB timestamps have 2-second granularity), causing
recompiles on every cold start; ``--invalidation-mode checked-hash`` makes
validity independent of timestamps.

**perMachine MSI shortcuts register their keypath under HKLM.** It was
hardcoded to HKCU, breaking repair and upgrade component-detection for users
other than the installing admin.

**.run installer fixes.** ``--prefix`` is canonicalized to an absolute path
(relative prefixes produced dangling symlinks and broken ``uninstall.sh``);
upgrades run the previous install's ``uninstall.sh`` first so renamed or
removed launchers don't leave dangling ``bin`` symlinks and ``.desktop``
entries; payload tar ownership is normalized to root so a root install can't
hand the tree to an unrelated uid; ``.desktop`` ``Name`` entries are
disambiguated when an app installs several.

0.8.0
-----

2026/07/04

**Only the installer is emitted in** ``dist/`` *(breaking)*. The portable
``.zip`` (MSI/MSIX) and the ``.tar.{gz,bz2,xz}`` (Linux/macOS) are no longer
produced — each target now ships just its installer (``.msi``/``.msix``/``.run``).
The ``--no-zip`` build option is removed.

**Faster** ``.run`` **payload compression.** gzip and xz payloads are now
compressed through the external ``gzip``/``xz`` commands when available
(``xz -T0`` uses every core) at presets tuned for build speed, falling back to
Python's built-in single-threaded codecs otherwise.

0.7.0
-----

2026/06/10

**POSIX launchers are isolated from the host's PYTHON* environment.** The
Linux/macOS shell-wrapper launchers ran the bundled interpreter with a plain
``python3 -c <bootstrap>``, so a stray ``PYTHONHOME``/``PYTHONPATH`` (or any
``PYTHON*`` variable) in the user's environment leaked into the app — unlike
the Windows and macOS C launchers, which already pass ``-I`` and scrub
``PYTHON*``. The wrappers now mirror that isolation: ``PYTHON*`` is scrubbed
from the environment (so the app and anything it spawns don't inherit it) and
python runs with ``-I``.

**Windows launcher build robustness.** The ``vcvars64.bat`` path is now passed
to the generated ``build.bat`` as a batch argument, so a Visual Studio install
under a non-ASCII path no longer breaks the ASCII-only batch file; the app name
embedded in the GUI error-dialog bootstrap is properly escaped; and the
launcher itself now fails with exit code 124 when the assembled command line
would exceed Windows' 32768-character limit instead of silently dropping
arguments.

**Pipeline and installer robustness.** ``build-wheels`` clears stale wheels
from the wheelhouse first, so incremental stage runs can't hand pip two
conflicting versions of a package. The POSIX ``.run`` installer verifies the
decompressor and ``tar`` exist *before* removing a previous install, and quotes
the ``Exec`` path in generated ``.desktop`` files. ``notarytool`` output that
isn't valid JSON now produces a clear error instead of a traceback. The unused
``packaging`` dependency was dropped.

0.6.0
-----

2026/06/09

**Windows launchers no longer orphan their python child.** The launcher placed
the python process it spawned outside any job, so terminating the launcher (by a
parent process or Task Manager) left ``python.exe`` — and anything it had started
— running. The launcher now creates a kill-on-close Job Object
(``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``), starts the child suspended, assigns it
to the job, and only then resumes it, so killing the launcher tears down the
whole descendant tree. Job setup is best-effort: any failure falls back to
launching the child unmanaged rather than failing the launch.

0.5.0
-----

2026/06/08

**Non-ASCII launcher and app names on Windows.** The generated ``build.bat`` and
the launcher ``.rc`` were written as ASCII, so a non-ASCII launcher executable
name (or app name in the ``VERSIONINFO``) raised ``UnicodeEncodeError`` before
the toolchain even ran. The build now uses fixed ASCII basenames for every
``cl``/``rc`` input and output — keeping ``build.bat`` pure ASCII — and renames
the result to its (possibly non-ASCII) name in Python afterwards. The ``.rc`` is
emitted as UTF-8 prefixed with ``#pragma code_page(65001)`` so ``rc.exe`` decodes
non-ASCII resource strings without depending on the console codepage.

**More robust MSVC toolchain discovery.** Launcher compilation located MSVC with
a bare ``vswhere -latest``, which excluded the standalone "C++ Build Tools" SKU
and preview channels and could return an install without the C++ workload.
Discovery now mirrors setuptools — adding ``-products *``, ``-prerelease``, and
``-requires VC.Tools.x86.x64`` — raises a clear error when no suitable install is
found, and verifies that ``vcvars64.bat`` exists.

**Documentation.** Added a step-by-step Windows installer tutorial (including
brief MSVC + WiX setup steps), documented the auto-generated MSI ``upgrade-code``
in the examples and tutorial, spelled out the ``pip wheel`` and launcher
entry-point prerequisites, and corrected stale launcher, pipeline, and
output-path descriptions.

0.4.0
------

2026/06/07

**Build intermediates and final artifacts now live in separate trees**
*(breaking)*. Intermediates (runtime, wheelhouse, image, launcher build, ``.wxs``)
go to ``.appdist-build/<target>/`` while the shippable packages go to
``appdist/<target>/dist/``. The two base directories are chosen with the new
``--build-dir`` and ``--appdist-dir`` options; the old ``--out-dir`` is removed. A
full ``build`` wipes the per-target intermediates directory first for a clean build
(the downloaded runtime cache lives elsewhere, so this does not re-download).

**Same-version MSI upgrades.** A new MSI target key
``allow-same-version-upgrades`` (default ``false``) emits
``AllowSameVersionUpgrades="yes"`` on the WiX ``MajorUpgrade``, so reinstalling the
**same** version upgrades in place instead of erroring or installing side-by-side —
handy while iterating without bumping the version. MSI-only; setting it on an
``msix`` target prints a warning and has no effect.

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
