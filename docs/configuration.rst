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

Before configuring anything, make sure the project itself is packageable — see
:ref:`What your project must satisfy <project-prereqs>`.

All keys at a glance
--------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Where
     - Keys
   * - :ref:`[tool.pyappdist] <config-app>`
     - ``python`` · ``name`` · ``version`` · ``manager`` · ``identifier``
   * - :ref:`[[tool.pyappdist.launchers]] <config-launchers>`
     - ``name`` · ``entry`` · ``gui`` · ``icon`` · ``args``
   * - :ref:`[[tool.pyappdist.targets]] <config-targets>` (all formats)
     - ``name`` · ``platform`` · ``format`` · ``extras``
   * - targets, ``format = "msi"`` — :doc:`platforms/windows-msi`
     - ``manufacturer`` · ``scope`` · ``upgrade-code`` · ``license`` ·
       ``code-sign`` · ``code-sign-command`` · ``allow-same-version-upgrades``
   * - targets, ``format = "msix"`` — :doc:`platforms/windows-msix`
     - ``manufacturer`` · ``identity-name`` · ``publisher`` · ``display-name`` ·
       ``logo``
   * - targets, ``format = "linux"`` — :doc:`platforms/linux`
     - ``categories`` · ``compression``
   * - targets, ``format = "macos"`` — :doc:`platforms/macos-run`
     - ``compression``
   * - targets, ``format = "macapp"`` / ``"dmg"`` — :doc:`platforms/macos-app`
     - ``min-macos`` · ``category`` · ``signing-identity`` · ``team-id`` ·
       ``notary-profile`` · ``entitlements``

.. _config-app:

``[tool.pyappdist]``
--------------------

``python`` (required)
   Python version for the bundled runtime, as ``X.Y`` or ``X.Y.Z``
   (e.g. ``"3.12"``).

``name``
   Display name of the app. Defaults to ``[project].name``.

``version``
   Product version. Defaults to ``[project].version`` (then ``"0.0.0"``).

``manager``
   Package manager used to pin dependencies: ``"uv"``, ``"poetry"``,
   ``"pipenv"``, ``"pdm"``, or ``"requirements.txt"``. Auto-detected from the
   lockfile when omitted. See :doc:`dependencies`.

``identifier``
   CFBundleIdentifier in reverse-DNS form (e.g. ``"com.example.myapp"``).
   **Required** when any target uses ``format = "macapp"`` or ``"dmg"``; unused by the
   other formats. With multiple launchers each bundle derives
   ``<identifier>.<launcher>``.

.. code-block:: toml

   [tool.pyappdist]
   name = "My App"
   python = "3.12"
   # identifier = "com.example.myapp"   # required for macapp/dmg targets

.. _config-launchers:

``[[tool.pyappdist.launchers]]``
--------------------------------

An array of tables — one entry per executable to produce. At least one is required
to build launchers. The same launcher set is used for every target; how a launcher
is realized depends on the format (a compiled ``.exe`` on Windows, a relocatable
shell wrapper on Linux/macOS).

``name`` (required)
   Output executable name without extension (``"myapp"`` → ``myapp.exe`` on
   Windows).

``entry`` (required)
   Entry point, in one of two forms:

   - ``"module:callable"`` — import ``callable`` from ``module`` and invoke it with
     no arguments; its return value becomes the process exit code.
   - ``"module.path"`` (no colon) — run the module as ``python -m module.path``
     (executed with ``__name__ == "__main__"``). Use this for apps whose startup
     lives under an ``if __name__ == "__main__":`` guard (e.g. NiceGUI).

``gui``
   ``true`` builds a windowed launcher using ``pythonw.exe`` (no console) on
   Windows. Defaults to ``false`` (console, ``python.exe``). Ignored on
   Linux/macOS.

``icon``
   A **per-OS table** of icon paths (relative to the project directory); each key is
   optional:

   * ``windows`` — an ``.ico``, embedded in the ``.exe``.
   * ``macos`` — a ``.png`` (ideally ≥1024×1024), converted to the ``.app``'s ``.icns``.
   * ``linux`` — an image (``.png`` recommended) used for the ``.desktop`` entry.

   A plain string is **not** accepted — give the format each platform needs. An omitted
   key means that platform gets no icon (macOS falls back to a generated placeholder).

``args``
   Fixed arguments as a single string, prepended to the program's argv.

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

These keys are common to every format; the format-specific keys live on the
:ref:`format pages <config-formats>`.

``platform`` (required)
   Distribution platform (see :ref:`Platform values <config-platforms>`).

``format`` (required)
   Output package. Must match the platform's OS: ``"msi"`` or ``"msix"`` on
   Windows, ``"linux"`` on Linux, and on macOS either ``"macos"`` (a portable
   ``.run`` installer, like Linux) or ``"macapp"`` / ``"dmg"`` (a ``.app`` bundle,
   optionally inside a ``.dmg``, for GUI distribution). A mismatch (e.g. ``"msi"``
   with ``linux-x86_64``) is rejected at load. See
   :ref:`Output formats <config-formats>`.

``name`` (required)
   Label used to select this target on the command line and as its output
   subdirectory — artifacts in ``appdist/<name>/``, intermediates in
   ``.appdist-build/<name>/``. Must be unique across targets.

``extras`` (optional)
   A list of ``[project.optional-dependencies]`` extras to bundle for this target,
   passed through to the lockfile export (e.g. uv's ``--extra``). Defaults to an
   empty list, i.e. production dependencies only (dev excluded). See
   :doc:`dependencies`.

.. _config-platforms:

Platform values
~~~~~~~~~~~~~~~~

``windows-x86_64``
   Triple ``x86_64-pc-windows-msvc`` · OS windows · format ``msi`` / ``msix``.

``linux-x86_64``
   Triple ``x86_64-unknown-linux-gnu`` · OS linux · format ``linux``.

``macos-aarch64``
   Triple ``aarch64-apple-darwin`` · OS macos · format ``macos`` / ``macapp`` / ``dmg``.

``macos-x86_64``
   Triple ``x86_64-apple-darwin`` · OS macos · format ``macos`` / ``macapp`` / ``dmg``.

.. _config-formats:

Output formats
~~~~~~~~~~~~~~

Each format has its own configuration keys, build requirements, and install
behavior:

:doc:`msi <platforms/windows-msi>`
   ``.msi`` installer + portable ``.zip``.

:doc:`msix <platforms/windows-msix>`
   ``.msix`` package (Store / sideloading).

:doc:`linux <platforms/linux>`
   ``.tar.{gz,bz2,xz}`` + self-extracting ``.run``.

:doc:`macos <platforms/macos-run>`
   ``.tar.{gz,bz2,xz}`` + self-extracting ``.run``, for command-line tools.

:doc:`macapp / dmg <platforms/macos-app>`
   A macOS ``.app`` bundle (``macapp``), optionally wrapped in a ``.dmg`` (``dmg``),
   for GUI apps; Developer-ID-signed and notarized when configured.

A single project can declare several targets and produce all of these at once:

.. code-block:: toml

   [[tool.pyappdist.targets]]              # an MSI
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   # upgrade-code = "..."    # auto-generated and written back if omitted

   [[tool.pyappdist.targets]]              # a Linux .tar.xz + .run installer
   name = "linux"
   platform = "linux-x86_64"
   format = "linux"

   [[tool.pyappdist.targets]]              # a macOS .tar.gz + .run installer
   name = "macos-arm"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "macos"
