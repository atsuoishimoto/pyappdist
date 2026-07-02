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
   # args = "--profile default"# optional fixed arguments

   [[tool.pyappdist.targets]]
   name = "windows"
   platform = "windows-x86_64"
   format = "msi"
   manufacturer = "Example Inc."
   # upgrade-code = "..."    # auto-generated and written back if omitted

The project must build a wheel and its entry point must run from the installed
package — see :ref:`What your project must satisfy <project-prereqs>`.

Each ``[[tool.pyappdist.targets]]`` entry is one output package. ``format`` is
required and must match the platform's OS — pick the one(s) you need from
:ref:`Output formats <config-formats>` (``msi``/``msix`` on Windows, ``linux`` on
Linux, ``macos`` on macOS). See :doc:`configuration` for every option.

Build
-----

.. code-block:: bash

   uv add --dev pyappdist
   uv run pyappdist build            # the sole target: wheels -> runtime -> image -> launcher -> package

When several targets are defined, name the one(s) to build, e.g.
``uv run pyappdist build linux``. Each pipeline stage (``fetch-runtime``,
``build-wheels``, ``build-image``, ``build-launchers``, ``gen-wix``) is also its
own subcommand — see :doc:`cli`.

Outputs
-------

The shippable packages land under ``appdist/<target>/dist/`` — what exactly
depends on the target's format (see the format's page). Build intermediates
(runtime, wheelhouse, image) live separately under ``.appdist-build/<target>/``;
the ``image/`` directory there is itself a portable, runnable app. See
:ref:`Output layout <cli-output-layout>` for the full tree and the options that
relocate it.
