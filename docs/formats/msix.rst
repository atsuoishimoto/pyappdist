MSIX (Microsoft Store / sideloading)
====================================

``format = "msix"`` packs the runtime image into a Windows ``.msix`` package. The
launchers are packaged as full-trust Win32 apps (``runFullTrust``), one
``<Application>`` per launcher.

* ``appdist/<target>/dist/<name>-<version>.msix`` — the package.

There is no portable ``.zip`` for this format (the ``.msix`` is the deliverable).
Only ``platform = "windows-x86_64"`` may use this format.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Required
     - Description
   * - ``manufacturer``
     - no
     - Vendor name; used as the launcher's version-resource company name and as the
       default publisher (``CN=<manufacturer>``).
   * - ``identity_name``
     - no
     - Package Identity Name (for the Store, the reserved ``Publisher.AppName``).
       Defaults to ``[project].name``.
   * - ``publisher``
     - no
     - Package Identity Publisher DN (e.g. ``"CN=Contoso"``). For the Store or
       signing it must match. Defaults to ``CN=<manufacturer>``.
   * - ``display_name``
     - no
     - App display name. Defaults to ``[tool.pyappdist].name``.
   * - ``logo``
     - no
     - Path to a source ``.png`` used for the package logos. A placeholder is
       generated if omitted.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "store"
   platform = "windows-x86_64"
   format = "msix"
   manufacturer = "Example Inc."
   # identity_name = "Contoso.MyApp"   # from Partner Center for the Store
   # publisher = "CN=Contoso"
   # display_name = "My App"
   # logo = "assets/logo.png"

Build requirements
------------------

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — to compile the launcher
  ``.exe`` (same as MSI).
* **makeappx** (Windows SDK) — located automatically, or set ``PYAPPDIST_MAKEAPPX``
  to its path.

No WiX is needed. On a non-Windows host the MSIX step is skipped (the image is
still built).

Signing and install
-------------------

The package is left **unsigned**: the Microsoft Store signs it for free on
submission (company registration is also free), and auto-updates are handled by the
Store.

To test an unsigned ``.msix`` locally, enable **Developer Mode** (Settings → For
developers; one-time, requires admin), then:

.. code-block:: text

   Add-AppxPackage -Register <image>\AppxManifest.xml   # loose, from the built image
   # or:  Add-AppxPackage -AllowUnsigned <app>.msix

Without the Store or Developer Mode, an unsigned MSIX cannot be installed (it would
need your own trusted code-signing certificate). To sign locally, see :doc:`/signing`.
