Linux — tarball / .run installer
================================

``format = "linux"`` builds a real Linux distribution and emits two artifacts in
``appdist/<target>/dist/``:

* ``<name>-<version>-<target>.tar{.gz,.bz2,.xz}`` — the image tree under a top-level
  directory (extension follows ``compression``). Users who don't want an installer
  just extract it and run ``<dir>/<launcher>``.
* ``<name>-<version>-<target>.run`` — a self-extracting installer (a POSIX shell
  script with the compressed tarball appended).

Only ``platform = "linux-x86_64"`` may use this format.

Configuration
-------------

``categories``
   freedesktop ``.desktop`` ``Categories`` value (default ``"Utility;"``). Used
   only for launchers that define an ``icon``.

``compression``
   Payload compression for the ``.tar`` and ``.run``: ``"gzip"``, ``"bzip2"`` or
   ``"xz"`` (default ``"xz"``). The matching decompressor must be present on the
   target machine at install time.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "linux"
   platform = "linux-x86_64"
   format = "linux"
   # categories = "Utility;Development;"   # for launchers that set an icon
   # compression = "xz"                    # "gzip" | "bzip2" | "xz" (default "xz")

Build requirements
------------------

None beyond pip and the chosen compressor.

Install behavior
----------------

The ``.run`` installer verifies the payload's SHA-256 before extracting, so a
corrupted download is rejected rather than half-installed. It needs no root and no
FUSE: it copies the tree into ``<prefix>/lib/<name>`` (``$HOME/.local`` by default;
override with ``--prefix``), symlinks each launcher into ``<prefix>/bin``, and — only
for launchers that set an ``icon`` — writes a ``.desktop`` entry. It also drops an
``uninstall.sh`` next to the install, and ``./<app>.run --uninstall`` removes it.

.. code-block:: console

   $ ./myapp-1.0-linux-x86_64.run            # install into ~/.local
   $ ./myapp-1.0-linux-x86_64.run --prefix ~/opt
   $ ./myapp-1.0-linux-x86_64.run --uninstall

Each launcher becomes a small relocatable shell wrapper that runs the entry point
with the bundled interpreter (``gui`` has no effect on Linux). Application updates
are the app's own responsibility — pyappdist provides no auto-update mechanism.
