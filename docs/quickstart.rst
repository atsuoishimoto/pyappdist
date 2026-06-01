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
   name = "myapp"              # produces myapp.exe
   entry = "myapp:main"        # module:callable
   gui = false                 # true -> pythonw.exe (no console)
   # icon = "assets/app.ico"   # optional
   # args = "--profile default"# optional fixed arguments

   [[tool.pyappdist.targets]]
   platform = "windows-x86_64"
   manufacturer = "Example Inc."
   # scope = "user"         # "user" (default, no admin) or "machine" (Program Files)
   # upgrade_code = "..."   # stable GUID; auto-generated and written back on first build

See :doc:`configuration` for every option.

Build everything
----------------

.. code-block:: bash

   uv add --dev pyappdist
   uv run pyappdist build            # all targets: wheels -> runtime -> image -> launcher -> wix -> MSI

Build step by step
------------------

Each stage of the pipeline is also its own subcommand:

.. code-block:: bash

   uv run pyappdist build-wheels        # app + deps -> <target>/wheelhouse
   uv run pyappdist fetch-runtime       # python-build-standalone -> <target>/runtime
   uv run pyappdist build-image         # install into the runtime + launcher(s) + portable zip
   uv run pyappdist build-launchers     # (re)build launcher.exe into the image
   uv run pyappdist gen-wix             # generate the WiX .wxs from the image

See :doc:`cli` for the full command reference.

Outputs
-------

Each target's output lands under ``appdist/<target>/``:

==================  ==========================================================
Directory           Contents
==================  ==========================================================
``wheelhouse/``     the app wheel + dependency wheels (and ``requirements.txt``)
``runtime/``        the extracted python-build-standalone runtime
``image/``          the installed, ready-to-run app (a portable directory)
``dist/``           shippable artifacts: the portable ``.zip`` and the ``.msi``
==================  ==========================================================

The image directory itself is a portable app —
``appdist/<target>/dist/<name>-<version>-portable.zip`` is shippable on its own, and
``appdist/<target>/dist/<name>-<version>.msi`` is the installer.
