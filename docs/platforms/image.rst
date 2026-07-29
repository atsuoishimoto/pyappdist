Image archive (all platforms)
=============================

``format = "image"`` builds no installer: the run-in-place image tree itself is
the deliverable, archived into ``appdist/<target>/dist/``:

* ``<name>-<version>-<target>.zip`` — for Windows targets.
* ``<name>-<version>-<target>.tar.gz`` — for Linux and macOS targets (tar
  preserves the symlinks and permissions the image needs on those OSes).

The archive contains a single top-level directory ``<name>-<version>/`` holding
the image, so extracting it doesn't scatter files. Unlike the other formats,
``image`` is available on **every** platform value.

Use it when you don't want an installer — for example to deploy the tree with
your own tooling, unpack it into a container, or wrap it in a packaging system
pyappdist doesn't produce.

Build requirements
------------------

The same as building the image for that platform. Launchers follow the target
OS: a Windows target compiles the usual ``.exe`` launchers (MSVC build tools
required, unless ``no-launcher`` is set), while Linux/macOS targets get the same
relocatable shell-wrapper launchers as the ``.run`` installer (no toolchain).
The Windows launcher ``.exe`` files are code-signed when the target sets
``code-sign = true`` (or ``--code-sign`` is passed to ``pyappdist build``), with
the same command resolution as MSI targets — see :ref:`msi-code-signing`.
On Linux/macOS targets there is nothing to sign, so ``code-sign = true`` is
rejected there.

Configuration
-------------

``no-launcher``
   ``true`` skips launcher generation entirely, so the archive contains just the
   installed tree (default ``false``). Only valid with ``format = "image"``.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "windows-zip"
   platform = "windows-x86_64"
   format = "image"

   [[tool.pyappdist.targets]]
   name = "linux-tar"
   platform = "linux-x86_64"
   format = "image"
   # no-launcher = true   # archive the bare tree, without launchers

Run behavior
------------

Extract the archive anywhere and run the launchers from the extracted
directory — they locate the bundled interpreter relative to themselves, so no
installation step is needed. Nothing is registered with the OS (no shortcuts,
no ``.desktop`` entries, no uninstaller); integration and updates are the app's
own responsibility.
