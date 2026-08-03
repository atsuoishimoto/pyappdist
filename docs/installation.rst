Installation
============

pyappdist is a build-time tool. Add it to your application project's development
dependencies and run it from there.

.. code-block:: bash

   uv add --dev pyappdist

Any PEP 517/621 project works (uv, poetry, hatch, pdm, plain pip). If you do not
use uv, install pyappdist into the environment you build from in the usual way,
e.g. ``pip install pyappdist`` or ``poetry add --group dev pyappdist``.

Build-time toolchain
--------------------

pyappdist builds the app wheel with ``python -m pip``, so producing the
*wheelhouse* and the runtime image needs nothing beyond pip. The compiled
launchers need **no C compiler**: released pyappdist wheels bundle prebuilt
launcher stubs that the build configures per app (see the ``launcher-build``
target key). A compiler is only used as a fallback when no stub is bundled
(e.g. an install from a git checkout) or with ``launcher-build = "source"``.
Producing the final **package** needs a per-format toolchain, documented on
each format's page:

* :doc:`MSI <platforms/windows-msi>` — WiX v5 (MSVC build tools only for
  launcher source builds).
* :doc:`MSIX <platforms/windows-msix>` — ``makeappx`` (Windows SDK; MSVC build
  tools only for launcher source builds).
* :doc:`Linux <platforms/linux>` / :doc:`macOS <platforms/macos-run>` — none
  (the launchers are shell scripts).
* :doc:`macapp / dmg <platforms/macos-app>` / :doc:`pkg <platforms/macos-pkg>` —
  the Xcode command-line tools (``codesign`` etc.; ``clang`` only for launcher
  source builds).
* :doc:`image <platforms/image>` — a Windows target uses the usual ``.exe``
  launchers (prebuilt stubs, or MSVC as fallback); none for Linux/macOS, or
  with ``no-launcher``.

Each format is built on its own OS.

Package manager (for dependency pinning)
----------------------------------------

Dependencies are pinned from your project's lockfile, exported via your package
manager (uv / poetry / pipenv / PDM). The relevant tool must be available at
build time. See :doc:`dependencies` for details.
