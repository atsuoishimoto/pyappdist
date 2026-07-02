macOS — tarball / .run (command-line tools)
===========================================

.. note::

   Two macOS distributions exist. **This page** (``format = "macos"``) ships a
   per-user ``.tar`` / ``.run`` installer whose launchers land in
   ``<prefix>/bin`` — right for **command-line tools**. For a double-click
   **GUI app** (a signed/notarized ``.app`` or ``.dmg``), use
   :doc:`macos-app` instead.

``format = "macos"`` builds the same two artifacts as :doc:`linux` — a portable
tarball and a self-extracting ``.run`` installer — with the same per-user install
model. Build a macOS target **on macOS**: an Apple Silicon host for
``macos-aarch64``, an Intel host for ``macos-x86_64``.

* ``<name>-<version>-<target>.tar{.gz,.bz2,.xz}`` — the image tree.
* ``<name>-<version>-<target>.run`` — the self-extracting installer.

Only ``platform = "macos-aarch64"`` or ``"macos-x86_64"`` may use this format.

Build requirements
------------------

None. The launchers are shell scripts and the payload is compressed with
Python's own ``tarfile`` — unlike :doc:`macos-app`, this format needs no Xcode
Command Line Tools.

Configuration
-------------

``compression``
   Payload compression for the ``.tar`` and ``.run``: ``"gzip"``, ``"bzip2"`` or
   ``"xz"`` (default ``"gzip"``, because ``xz`` is not preinstalled on macOS).

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "macos-arm"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "macos"
   # compression = "gzip"                  # "gzip" | "bzip2" | "xz" (default "gzip")

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
the installer creates the ``<prefix>/bin`` symlinks only. This format produces no
``.app`` bundle; it suits command-line tools launched by their ``bin`` name.
