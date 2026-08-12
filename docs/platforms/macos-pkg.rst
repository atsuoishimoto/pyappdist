macOS — .pkg installer
======================

.. note::

   Three macOS distributions exist. **This page** (``format = "pkg"``) builds a
   native installer package that installs the ``.app`` bundle(s) into
   ``/Applications`` system-wide — the double-clickable installer Mac users
   expect, and the package format MDM tools (Jamf, Intune, …) deploy. For a
   drag-to-install disk image see :doc:`macos-app`; for a per-user install with
   no admin rights, use the ``.run`` installer (:doc:`macos-run`).

``format = "pkg"`` first builds the same signed ``.app`` bundle(s) as
``macapp``/``dmg`` (one per launcher), then wraps them in a distribution package:

* The bundles are installed into ``/Applications``. The install is **system
  scope** — Installer.app asks for an administrator password.
* Launchers with ``gui = false`` are additionally symlinked into
  ``/usr/local/bin`` by a ``postinstall`` script, so command-line tools are on
  ``PATH`` after the install. A launcher with ``app-entry = false`` produces
  no ``.app`` (and so no Launchpad entry) — its executable lives inside the
  first visible launcher's bundle, and the symlink points there.
* The output is ``appdist/<target>/dist/<name>-<version>.pkg``.

Like ``macapp``/``dmg``, this is **native-only**: build on macOS — an Apple
Silicon host for ``macos-aarch64``, an Intel host for ``macos-x86_64``. The
packaging tools (``pkgbuild`` / ``productbuild``) ship with the Xcode Command
Line Tools; see :doc:`macos-app` for the toolchain setup.

In the configuration, ``identifier`` (app-level) is **required** — the ``.pkg``
receipt identifier is derived from it (``<identifier>.pkg``).

Configuration
-------------

All the ``.app``-bundle keys from :doc:`macos-app` apply unchanged —
``min-macos``, ``category``, ``signing-identity``, ``team-id``,
``notary-profile``, ``entitlements``, and the per-launcher ``icon`` table —
because the payload *is* the same ``.app`` bundle. Two keys are specific to
``pkg``:

``license``
   Path (relative to the project) to a license file — plain text (``.txt``),
   RTF (``.rtf``), or HTML (``.html``). When set, Installer.app shows the file
   as a license page: the user must click *Agree* in the standard
   agree/disagree prompt before the install can continue.

``installer-identity``
   A **Developer ID Installer** identity, e.g.
   ``"Developer ID Installer: Your Name (TEAMID)"`` (or the
   ``PYAPPDIST_MACOS_INSTALLER_IDENTITY`` environment variable, which overrides
   this key), used to sign the
   ``.pkg`` itself. This is a *different certificate type* from the
   ``Developer ID Application`` identity that signs the bundles — create both in
   the Apple Developer portal. When unset the package is left unsigned: it
   installs locally, but Gatekeeper rejects it elsewhere and it cannot be
   notarized.

.. code-block:: toml

   [tool.pyappdist]
   identifier = "com.example.myapp"       # required for pkg (and macapp/dmg)

   [[tool.pyappdist.launchers]]
   name = "myapp"
   entry = "myapp:main"
   icon = { macos = "assets/myapp.png" }  # the .app icon (per launcher)

   [[tool.pyappdist.targets]]
   name = "macos-arm-pkg"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "pkg"
   # license = "LICENSE.rtf"              # installer license page (.txt/.rtf/.html)
   # min-macos = "12.0"
   # signing-identity = "Developer ID Application: Your Name (TEAMID)"
   # installer-identity = "Developer ID Installer: Your Name (TEAMID)"
   # notary-profile = "your-notary-profile"

Code signing and notarization
-----------------------------

Two identities are involved:

1. The ``.app`` bundles inside the package are deep-signed with the
   **Developer ID Application** identity (``signing-identity``), exactly as for
   ``macapp``/``dmg`` — ad-hoc when unset. See :ref:`macos-signing`.
2. The ``.pkg`` itself is signed with the **Developer ID Installer** identity
   (``installer-identity``) via ``productbuild --sign``.

Prerequisite (one-time): create the *Developer ID Installer* certificate, the
same way as the Application one — in Xcode (Settings → Accounts → Manage
Certificates → **+** → *Developer ID Installer*) or in the Developer portal
(Certificates → **+**; downloading the ``.cer`` and double-clicking installs it
into the login keychain). Only the Account Holder can create Developer ID
certificates. Confirm it is installed::

   security find-identity -v | grep "Developer ID Installer"
   #  N) ... "Developer ID Installer: Your Name (TEAMID)"

Note the plain ``-v`` — the ``-p codesigning`` filter used for the Application
identity does not list Installer certificates, which sign packages, not code.
Apple also caps Developer ID certificates at five per type per team, so to sign
on another machine, export the existing certificate with its private key
(Keychain Access → export as ``.p12``) instead of creating a new one.

Notarization (``notary-profile``) submits the ``.pkg`` directly to Apple and
staples the ticket. It runs only when *both* identities are configured — an
unsigned package, or one containing ad-hoc-signed bundles, would be rejected by
the notary service, so pyappdist skips submission with a note in either case.

Verify the result::

   pkgutil --check-signature dist/myapp-1.0.pkg
   spctl -a -t install -vv dist/myapp-1.0.pkg
   xcrun stapler validate dist/myapp-1.0.pkg

Install behavior
----------------

Double-clicking the ``.pkg`` runs Installer.app: it requires an administrator
password and installs into ``/Applications`` on the boot volume (the installer
offers no other destination). The same package deploys unattended through MDM
(Jamf, Intune, …) or the command line::

   sudo installer -pkg myapp-1.0.pkg -target /

Upgrades are in place: installing a newer ``.pkg`` replaces the bundles under
``/Applications`` (the components are pinned there — a copy the user moved
elsewhere is not followed).

Uninstalling
------------

``.pkg`` has no built-in uninstaller. To remove the app: drag the ``.app``
bundle(s) out of ``/Applications``, delete any ``/usr/local/bin`` symlinks the
installer created for command-line launchers, and forget the receipt::

   sudo pkgutil --forget com.example.myapp.pkg
