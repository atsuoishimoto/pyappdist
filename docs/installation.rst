Installation
============

pyappdist is a build-time tool. Add it to your application project's development
dependencies and run it from there.

.. code-block:: bash

   uv add --dev pyappdist

Any PEP 517/621 project works (uv, poetry, hatch, pdm, plain pip). If you do not
use uv, install pyappdist into the environment you build from in the usual way,
e.g. ``pip install pyappdist`` or ``poetry add --group dev pyappdist``.

Build-time requirements
-----------------------

pyappdist builds the app wheel with ``python -m pip``, so producing the
*wheelhouse* needs nothing beyond pip. To produce the **native artifacts** (the
launcher executable and the MSI) you also need:

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — used to compile
  ``launcher.exe``. Located via ``vswhere``.
* **WiX v5** — builds the MSI:

  .. code-block:: bash

     dotnet tool install --global wix --version 5.0.2

  .. note::

     Pin to **v5.0.2**. WiX v6/v7 require accepting the Open Source Maintenance
     Fee EULA, which blocks an unattended ``wix build``.

  Only if you set ``[tool.pyappdist.wix].license`` (to show a license dialog), also
  add the UI extension (pin it to v5 as well):

  .. code-block:: bash

     wix extension add -g WixToolset.UI.wixext/5.0.2

The Python runtime itself is downloaded from `python-build-standalone
<https://github.com/astral-sh/python-build-standalone>`_ and cached under
``~/.cache/pyappdist/runtime``; you do not install it yourself.

Package manager (for dependency pinning)
----------------------------------------

Dependencies are pinned from your project's lockfile, exported via your package
manager (uv / poetry / pipenv / PDM). The relevant tool must be available at
build time. See :doc:`dependencies` for details.

Cross-building from WSL
-----------------------

You can build a Windows distribution from WSL. pyappdist invokes the Windows
toolchain (``python.exe``, MSVC, ``wix``) through the WSL/Windows interop bridge,
running each tool from within the ``appdist`` tree and passing paths relative to
that working directory (interop converts the cwd to the Windows side, so no
``wslpath`` conversion is needed). Do not share a single virtual environment
between the Linux and Windows sides.
