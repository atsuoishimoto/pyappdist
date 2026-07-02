Installation
============

pyappdist is a build-time tool. Add it to your application project's development
dependencies and run it from there.

.. code-block:: bash

   uv add --dev pyappdist

Any PEP 517/621 project works (uv, poetry, hatch, pdm, plain pip). If you do not
use uv, install pyappdist into the environment you build from in the usual way,
e.g. ``pip install pyappdist`` or ``poetry add --group dev pyappdist``.

The Python runtime itself is downloaded from `python-build-standalone
<https://github.com/astral-sh/python-build-standalone>`_ and cached under
``~/.cache/pyappdist/runtime``; you do not install it yourself.

Build-time toolchain
--------------------

pyappdist builds the app wheel with ``python -m pip``, so producing the
*wheelhouse* and the runtime image needs nothing beyond pip. Producing the final
**package** needs a per-format toolchain, documented on each format's page:

* :doc:`MSI <platforms/windows-msi>` — MSVC build tools + WiX v5.
* :doc:`MSIX <platforms/windows-msix>` — MSVC build tools + ``makeappx``
  (Windows SDK).
* :doc:`Linux <platforms/linux>` / :doc:`macOS <platforms/macos-run>` — none
  beyond pip and the chosen compressor (the launchers are shell wrappers).
* :doc:`macapp / dmg <platforms/macos-app>` — the Xcode command-line tools.

Each format is built on its own OS. When a format's OS doesn't match the build
host, the package step is skipped and only the image is produced — except that a
Windows MSI/MSIX can also be cross-built from WSL (see
:ref:`wsl-cross-build`).

Package manager (for dependency pinning)
----------------------------------------

Dependencies are pinned from your project's lockfile, exported via your package
manager (uv / poetry / pipenv / PDM). The relevant tool must be available at
build time. See :doc:`dependencies` for details.
