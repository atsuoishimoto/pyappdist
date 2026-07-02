Windows — MSIX (Microsoft Store / sideloading)
==============================================

``format = "msix"`` packs the runtime image into a Windows ``.msix`` package. The
launchers are packaged as full-trust Win32 apps (``runFullTrust``), one
``<Application>`` per launcher.

* ``appdist/<target>/dist/<name>-<version>.msix`` — the package.

There is no portable ``.zip`` for this format (the ``.msix`` is the deliverable).
Only ``platform = "windows-x86_64"`` may use this format.

Configuration
-------------

``manufacturer``
   Vendor name; used as the launcher's version-resource company name and as the
   default publisher (``CN=<manufacturer>``).

``identity-name``
   Package Identity Name (for the Store, the reserved ``Publisher.AppName``).
   Defaults to ``[project].name``.

``publisher``
   Package Identity Publisher DN (e.g. ``"CN=Contoso"``). For the Store or
   signing it must match. Defaults to ``CN=<manufacturer>``.

``display-name``
   App display name. Defaults to ``[tool.pyappdist].name``.

``logo``
   Path to a source ``.png`` used for the package logos. A placeholder is
   generated if omitted.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "store"
   platform = "windows-x86_64"
   format = "msix"
   manufacturer = "Example Inc."
   # identity-name = "Contoso.MyApp"   # from Partner Center for the Store
   # publisher = "CN=Contoso"
   # display-name = "My App"
   # logo = "assets/logo.png"

Build requirements
------------------

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — to compile the launcher
  ``.exe`` (same as :doc:`MSI <windows-msi>`; see its
  :ref:`install steps <platforms/windows-msi:Build requirements>`).
* **makeappx** (Windows SDK) — located automatically, or set ``PYAPPDIST_MAKEAPPX``
  to its path.

No WiX is needed.

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
need your own trusted code-signing certificate). For sideloading, the signing
certificate's subject must match the manifest ``Publisher``.

MSIX is **not** covered by the MSI ``code-sign`` key: the package is signed only
when the ``PYAPPDIST_SIGN_CMD`` environment variable is set. The command receives
the artifact path via the ``{file}`` token, exactly as described in
:ref:`msi-code-signing`.
