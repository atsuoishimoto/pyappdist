macOS
=====

``format = "macos"`` builds the same two artifacts as :doc:`linux` — a portable
tarball and a self-extracting ``.run`` installer — with the same per-user install
model. Build a macOS target **on macOS**: an Apple Silicon host for
``macos-aarch64``, an Intel host for ``macos-x86_64``.

* ``<name>-<version>-<target>.tar{.gz,.bz2,.xz}`` — the image tree.
* ``<name>-<version>-<target>.run`` — the self-extracting installer.

Only ``platform = "macos-aarch64"`` or ``"macos-x86_64"`` may use this format.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Required
     - Description
   * - ``compression``
     - no
     - Payload compression for the ``.tar`` and ``.run``: ``"gzip"``, ``"bzip2"`` or
       ``"xz"`` (default ``"gzip"``, because ``xz`` is not preinstalled on macOS).

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "macos-arm"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "macos"
   # compression = "gzip"                  # "gzip" | "bzip2" | "xz" (default "gzip")

Build requirements
------------------

None beyond pip and the chosen compressor — macOS launchers are relocatable shell
wrappers (no MSVC/WiX). Build on macOS; on a non-macOS host the step is skipped (the
image is still built).

Install behavior
----------------

The ``.run`` installer behaves exactly like the Linux one — it verifies the payload
SHA-256, copies into ``<prefix>/lib/<name>`` (``$HOME/.local`` by default), symlinks
each launcher into ``<prefix>/bin``, drops an ``uninstall.sh``, and supports
``--prefix`` / ``--uninstall``. No root is required.

.. code-block:: console

   $ ./myapp-1.0-macos-aarch64.run            # install into ~/.local
   $ ./myapp-1.0-macos-aarch64.run --uninstall

macOS has no freedesktop equivalent, so launcher ``icon`` and ``gui`` are ignored —
the installer creates the ``<prefix>/bin`` symlinks only. No ``.app`` bundle is
produced; GUI apps are launched from a terminal or by their ``bin`` name.
