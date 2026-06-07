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

.. _config-prereqs:

What your project must satisfy
------------------------------

pyappdist installs your app the same way ``pip`` would — it builds wheels and
installs them into the bundled runtime, it never freezes source files directly.
Two things about the project therefore have to be true before it can be packaged.

1. The project must build a wheel with pip
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Your app must be a proper installable package, not a loose collection of
scripts. Concretely, running

.. code-block:: bash

   pip wheel --no-deps .

in the project directory must succeed and produce a ``.whl`` file. Any modern
build backend works (setuptools, hatchling, flit, poetry-core, …) as long as
``pyproject.toml`` declares a ``[build-system]`` and ``pip wheel`` can build it.
If ``pip wheel`` fails — or there is no packaging metadata at all — pyappdist
cannot distribute the app.

2. Each launcher must run from the installed wheel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A launcher never executes a source file by path. It runs against the
**installed** package, in exactly one of these two forms — which one is chosen by
the launcher's :ref:`entry <config-launchers>`:

* ``python -m <module>`` — used when ``entry`` has **no** colon (``"myapp.cli"``).
  ``python -m <module>`` must work once the wheel is installed.
* ``python -c "from <module> import <callable>; <callable>()"`` — used when
  ``entry`` is ``"module:callable"`` (``"myapp:main"``). The callable must be
  importable from the installed package and callable with no arguments.

The easiest way to confirm both conditions is to reproduce what pyappdist does, in
a throwaway virtualenv:

.. code-block:: bash

   python -m venv /tmp/check && /tmp/check/bin/python -m pip install .
   /tmp/check/bin/python -m myapp.cli                          # entry = "myapp.cli"
   /tmp/check/bin/python -c "from myapp import main; main()"   # entry = "myapp:main"

If those run from the *installed* package, the corresponding launcher will work.
If they only work in your source checkout (because they read files that the wheel
doesn't include, or import a top-level script that isn't part of the package),
fix the packaging first — the launcher would fail the same way.

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

:doc:`msi <formats/msi>`
   ``.msi`` installer + portable ``.zip``.

:doc:`msix <formats/msix>`
   ``.msix`` package (Store / sideloading).

:doc:`linux <formats/linux>`
   ``.tar.{gz,bz2,xz}`` + self-extracting ``.run``.

:doc:`macos <formats/macos>`
   ``.tar.{gz,bz2,xz}`` + self-extracting ``.run``.

:doc:`macapp / dmg <formats/macapp>`
   A macOS ``.app`` bundle (``macapp``), optionally wrapped in a ``.dmg`` (``dmg``);
   Developer-ID-signed and notarized when configured.

A single project can declare several targets and produce all of these at once:

.. code-block:: toml

   [[tool.pyappdist.targets]]              # an MSI
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."

   [[tool.pyappdist.targets]]              # a Linux .tar.xz + .run installer
   name = "linux"
   platform = "linux-x86_64"
   format = "linux"

   [[tool.pyappdist.targets]]              # a macOS .tar.gz + .run installer
   name = "macos-arm"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "macos"
