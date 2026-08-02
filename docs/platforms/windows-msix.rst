Windows — MSIX (Microsoft Store / sideloading)
==============================================

``format = "msix"`` packs the runtime image into a Windows ``.msix`` package.
The launchers are packaged as full-trust Win32 apps (``runFullTrust``), one
``<Application>`` per launcher.

* ``appdist/<target>/dist/<name>-<version>.msix`` — the package.

MSIX is first and foremost the Microsoft Store's package format: you submit
the package unsigned, the Store signs it and distributes updates. Installing
it *outside* the Store is also possible, but then Windows requires either a
trusted code-signing signature or Developer Mode — see
:ref:`msix-install` below for the three ways to get the package installed.

Only ``platform = "windows-x86_64"`` or ``"windows-arm64"`` may use this
format. Building the ``windows-arm64`` variant requires an ARM64 Windows host
(with the "MSVC C++ ARM64 build tools" component installed); x64 Windows cannot
run the target runtime's ``python.exe``. The app ``version`` must be dotted
numeric (e.g. ``"1.2.3"``), same as :doc:`MSI <windows-msi>` — pre-releases
such as ``"1.0.0rc1"`` are rejected at load time.

Build requirements
------------------

* **MSVC C++ build tools** (``cl.exe`` / ``rc.exe``) — to compile the launcher
  ``.exe``\ s (same as :doc:`MSI <windows-msi>`; see its
  :ref:`install steps <platforms/windows-msi:Build requirements>`).
* **makeappx** (Windows SDK) — to pack the ``.msix``. Located automatically,
  or set ``PYAPPDIST_WIN_MAKEAPPX`` to its path. The MSVC Build Tools install
  above already brings it in via the Windows SDK; to install the Windows SDK
  on its own:

  .. code-block:: powershell

     winget install --id Microsoft.WindowsSDK.10.0.26100 -e

No WiX is needed.

Configuration
-------------

``manufacturer``
   Vendor name. Shown to users as the package's publisher display name, used
   as the launcher's version-resource company name, and the source of the
   default ``publisher`` below.

``identity-name``
   Package Identity Name — the package's internal identity, not shown to
   users. Defaults to ``[project].name``. For the Store this must be the
   name reserved for your app in Partner Center (``Publisher.AppName``).

``publisher``
   Package Identity Publisher, an X.500 distinguished name such as
   ``"CN=Contoso"``. Defaults to ``CN=<manufacturer>``, or ``CN=<app name>``
   when ``manufacturer`` is also unset. Two cases require an exact match: for
   the Store it must equal the Publisher value Partner Center assigns to your
   account; for a signed sideload it must equal the signing certificate's
   subject (see :ref:`msix-sideload`).

``display-name``
   App display name, shown in the Start menu and in Settings → Apps.
   Defaults to ``[tool.pyappdist].name``.

``logo``
   Path to a source ``.png`` used for the package logos (the one image is
   scaled into every logo slot). A placeholder is generated if omitted.

``code-sign`` / ``code-sign-command``
   Sign the launcher ``.exe``\ s and the ``.msix`` (default: unsigned).
   Needed only for :ref:`sideloading <msix-sideload>`; works exactly as for
   MSI — see :ref:`msi-code-signing`.

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
   # code-sign = true                  # only for sideloading outside the Store

.. _msix-install:

Signing and install
-------------------

Windows refuses to install an MSIX unless it is signed by a certificate the
machine trusts, with two exceptions: packages from the Microsoft Store (the
Store signs them itself), and machines with Developer Mode enabled (which
accept unsigned packages for testing). pyappdist therefore leaves the
package **unsigned by default**; pick the path below that matches how you
distribute.

Distributing through the Microsoft Store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nothing extra to do at build time. Submit the unsigned ``.msix`` in Partner
Center: the Store signs it for free on ingestion (company registration is
also free) and handles auto-updates. Set ``identity-name`` and ``publisher``
to the values Partner Center reserves for your app.

Testing locally during development
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To try a build on your own machine without any certificate, first enable
**Developer Mode** (Settings → System → For developers; one-time, requires
admin). Then install the just-built package from a PowerShell on that
machine:

.. code-block:: powershell

   Add-AppxPackage -AllowUnsigned .\appdist\<target>\dist\<name>-<version>.msix

(``-AllowUnsigned`` requires Windows 11.) Alternatively, skip the ``.msix``
file entirely and register the built image *in place* — the app then runs
directly out of the ``appdist/<target>/image`` tree, so a rebuild takes
effect without reinstalling:

.. code-block:: powershell

   Add-AppxPackage -Register .\appdist\<target>\image\AppxManifest.xml

Either way the app appears in the Start menu like a normal install; remove
it from Settings → Apps or with ``Remove-AppxPackage``.

.. _msix-sideload:

Sideloading a signed package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To distribute outside the Store — to users who should not need Developer
Mode — the ``.msix`` must be signed with a code-signing certificate that the
installing machines trust, and the certificate's subject must exactly match
the manifest ``publisher`` (e.g. both ``CN=Contoso``) or Windows rejects the
install.

Set ``code-sign = true`` on the target (or pass ``--code-sign`` to
``pyappdist build``): the launcher ``.exe``\ s and the ``.msix`` are then
signed with the command resolved from ``PYAPPDIST_WIN_SIGN_CMD``, the
target's ``code-sign-command``, or the built-in ``signtool`` default — see
:ref:`msi-code-signing` for the details. Users install the signed package by
double-clicking it (App Installer) or with ``Add-AppxPackage <app>.msix`` —
no Developer Mode required.
