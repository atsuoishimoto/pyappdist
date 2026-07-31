Windows — MSIX (Microsoft Store / sideloading)
==============================================

``format = "msix"`` packs the runtime image into a Windows ``.msix`` package. The
launchers are packaged as full-trust Win32 apps (``runFullTrust``), one
``<Application>`` per launcher.

* ``appdist/<target>/dist/<name>-<version>.msix`` — the package.

Only ``platform = "windows-x86_64"`` or ``"windows-arm64"`` may use this
format. Building the ``windows-arm64`` variant requires an ARM64 Windows host
(with the "MSVC C++ ARM64 build tools" component installed); x64 Windows cannot
run the target runtime's ``python.exe``.

Build requirements
------------------

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — to compile the launcher
  ``.exe`` (same as :doc:`MSI <windows-msi>`; see its
  :ref:`install steps <platforms/windows-msi:Build requirements>`).
* **makeappx** (Windows SDK) — located automatically, or set ``PYAPPDIST_WIN_MAKEAPPX``
  to its path. It is included in the Windows SDK that the MSVC Build Tools
  install pulls in; standalone, it comes with the Windows SDK installer or

  .. code-block:: powershell

     winget install --id Microsoft.WindowsSDK.10.0.26100 -e

No WiX is needed.

Configuration
-------------

``manufacturer``
   Vendor name; used as the launcher's version-resource company name and as the
   default publisher (``CN=<manufacturer>``; when unset, the app ``name`` is
   used instead).

``identity-name``
   Package Identity Name (for the Store, the reserved ``Publisher.AppName``).
   Defaults to ``[project].name``.

``publisher``
   Package Identity Publisher DN (e.g. ``"CN=Contoso"``). For the Store or
   signing it must match. Defaults to ``CN=<manufacturer>``, or
   ``CN=<app name>`` when ``manufacturer`` is also unset.

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

To sign yourself, set ``code-sign = true`` on the target (or pass ``--code-sign``
to ``pyappdist build``): the launcher ``.exe``\ s and the ``.msix`` are then signed
with the command resolved from ``PYAPPDIST_WIN_SIGN_CMD``, the target's
``code-sign-command``, or the built-in ``signtool`` default — exactly as described
in :ref:`msi-code-signing`.
