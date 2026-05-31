Quick start
===========

Add a ``[tool.pyappdist]`` section to your app's ``pyproject.toml``:

.. code-block:: toml

   [project]
   name = "myapp"
   version = "1.0.0"

   [tool.pyappdist]
   name = "My App"
   identifier = "com.example.myapp"
   python = "3.12"
   target = "windows-x86_64"
   # manager = "uv"            # optional; auto-detected from lockfile if omitted

   [[tool.pyappdist.launchers]]
   name = "myapp"              # produces myapp.exe
   entry = "myapp:main"        # module:callable
   gui = false                 # true -> pythonw.exe (no console)
   # icon = "assets/app.ico"   # optional
   # args = "--profile default"# optional fixed arguments

   [tool.pyappdist.wix]
   manufacturer = "Example Inc."
   # upgrade_code = "..."   # stable GUID for upgrades; auto-generated and written
                            # back here on first build if omitted

See :doc:`configuration` for every option.

Build everything
----------------

.. code-block:: bash

   uv add --dev pyappdist
   uv run pyappdist build .          # wheels -> runtime -> image -> launcher -> wix -> MSI

Build step by step
------------------

Each stage of the pipeline is also its own subcommand:

.. code-block:: bash

   uv run pyappdist build-wheels    .   # app + deps -> appdist/wheelhouse
   uv run pyappdist fetch-runtime   .   # python-build-standalone -> appdist/runtime
   uv run pyappdist build-image     .   # install into the runtime + launcher(s) + portable zip
   uv run pyappdist build-launchers .   # (re)build launcher.exe into the image
   uv run pyappdist gen-wix         .   # generate the WiX .wxs from the image

See :doc:`cli` for the full command reference.

Outputs
-------

Everything lands under ``appdist/``:

==================  ==========================================================
Directory           Contents
==================  ==========================================================
``wheelhouse/``     the app wheel + dependency wheels (and ``requirements.txt``)
``runtime/``        the extracted python-build-standalone runtime
``image/``          the installed, ready-to-run app (a portable directory)
``dist/``           shippable artifacts: the portable ``.zip`` and the ``.msi``
==================  ==========================================================

The image directory itself is a portable app —
``appdist/dist/<name>-<version>-portable.zip`` is shippable on its own, and
``appdist/dist/<name>-<version>.msi`` is the installer.
