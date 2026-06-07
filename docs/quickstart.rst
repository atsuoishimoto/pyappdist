Quick start
===========

Add a ``[tool.pyappdist]`` section to your app's ``pyproject.toml``:

.. code-block:: toml

   [project]
   name = "myapp"
   version = "1.0.0"

   [tool.pyappdist]
   name = "My App"
   python = "3.12"
   # manager = "uv"            # optional; auto-detected from lockfile if omitted

   [[tool.pyappdist.launchers]]
   name = "myapp"              # produces myapp.exe on Windows
   entry = "myapp:main"        # module:callable
   gui = false                 # true -> pythonw.exe (no console)
   # icon = "assets/app.ico"   # optional
   # args = "--profile default"# optional fixed arguments

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   # upgrade-code = "..."    # auto-generated and written back if omitted

Each ``[[tool.pyappdist.targets]]`` entry is one output package. ``format`` is
required and must match the platform's OS — pick the one(s) you need from
:ref:`Output formats <config-formats>` (``msi``/``msix`` on Windows, ``linux`` on
Linux, ``macos`` on macOS). See :doc:`configuration` for every option.

Build everything
----------------

.. code-block:: bash

   uv add --dev pyappdist
   uv run pyappdist build            # the sole target: wheels -> runtime -> image -> launcher -> package

When several targets are defined, name the one(s) to build, e.g.
``uv run pyappdist build linux``. See :doc:`cli`.

Build step by step
------------------

Each stage of the pipeline is also its own subcommand:

.. code-block:: bash

   uv run pyappdist fetch-runtime       # python-build-standalone -> <target>/runtime
   uv run pyappdist build-wheels        # app + deps -> <target>/wheelhouse
   uv run pyappdist build-image         # install into the runtime + launcher(s) + portable zip
   uv run pyappdist build-launchers     # (re)build launcher.exe into the image (Windows)
   uv run pyappdist gen-wix             # generate the WiX .wxs from the image (MSI)

See :doc:`cli` for the full command reference.

Outputs
-------

Build intermediates and final artifacts go to separate trees.

Intermediates land under ``.appdist-build/<target>/`` (a full ``build`` wipes this
per-target directory first):

``wheelhouse/``
   The app wheel + dependency wheels (and ``requirements.txt``).

``runtime/``
   The extracted python-build-standalone runtime.

``image/``
   The installed, ready-to-run app (a portable directory).

The shippable packages land under ``appdist/<target>/dist/``:

``dist/``
   The shippable package(s) for the target's format.

The image directory itself is a portable app. The shippable artifacts in ``dist/``
depend on the format — see the per-format pages under
:ref:`Output formats <config-formats>`. Override the two base directories with
``--appdist-dir`` and ``--build-dir`` (see :doc:`cli`).
