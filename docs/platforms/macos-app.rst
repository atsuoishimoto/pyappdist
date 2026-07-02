macOS — .app / .dmg (GUI apps)
==============================

.. note::

   Two macOS distributions exist. **This page** (``format = "macapp"`` /
   ``"dmg"``) builds the double-click-to-launch, Dock-able ``.app`` bundle a
   GUI app is distributed in. For a **command-line tool** installed into
   ``<prefix>/bin``, use :doc:`macos-run` instead.

``format = "macapp"`` and ``format = "dmg"`` build a native macOS ``.app`` bundle:

* ``macapp`` assembles one ``<name>.app`` per launcher into ``appdist/<name>/dist/``.
* ``dmg`` does the same, then wraps the bundle(s) in a compressed ``<name>-<version>.dmg``
  disk image with the classic drag-to-``/Applications`` layout.

Both are **code-signed**; with a Developer ID identity they are also **notarized and
stapled** (see :ref:`macos-signing` below). Build on macOS — an Apple Silicon host for
``macos-aarch64``, an Intel host for ``macos-x86_64``.

The bundle layout is the real install tree, unchanged: the python-build-standalone
runtime with your app pip-installed lands in ``Contents/Resources/python``, and a tiny
Mach-O launcher at ``Contents/MacOS/<name>`` ``execv``\ s the bundled interpreter. With
several launchers you get one ``.app`` each (a bundle has exactly one executable), all
packed into a single ``.dmg``.

Build requirements
------------------

The whole toolchain (``clang``, ``codesign``, ``hdiutil``, ``sips`` / ``iconutil``
for the icon, and ``xcrun notarytool`` / ``stapler`` for notarization) ships with
the **Xcode Command Line Tools**. If they are not installed yet, install them from
a terminal — a dialog confirms the download; the full Xcode IDE is not required:

.. code-block:: console

   $ xcode-select --install

In the configuration, ``identifier`` (app-level) is **required** — the reverse-DNS
CFBundleIdentifier (e.g. ``"com.example.myapp"``).

Configuration
-------------

All keys live on the macOS target table, **except the icon**: each ``.app``'s icon comes
from its launcher's ``icon`` table — the ``macos`` key (a ``.png``), resized into an
``.icns`` via ``sips`` + ``iconutil`` (a placeholder is generated when absent). See
:ref:`launcher icon <config-launchers>`. So multiple launchers can have distinct icons.

``min-macos``
   Minimum macOS version. Sets both the bundle's ``LSMinimumSystemVersion`` and clang's
   ``-mmacosx-version-min``. Default ``"11.0"``.

``category``
   ``LSApplicationCategoryType`` (e.g. ``"public.app-category.utilities"``). Optional.

``signing-identity``
   Developer ID identity for distribution signing, e.g.
   ``"Developer ID Application: Your Name (TEAMID)"`` (or the
   ``PYAPPDIST_SIGNING_IDENTITY`` environment variable). When unset the bundle is **ad-hoc
   signed** — it runs locally but Gatekeeper rejects it on other machines. See
   :ref:`macos-signing` below.

``team-id``
   Apple Developer Team ID (informational).

``notary-profile``
   ``notarytool`` keychain profile name (or ``PYAPPDIST_NOTARY_PROFILE``). When set
   **and** a Developer ID identity is configured, the artifact is notarized and stapled.

``entitlements``
   Path to a custom entitlements ``.plist``. The default grants only
   ``com.apple.security.cs.disable-library-validation`` (so the hardened interpreter can
   load third-party extension modules); supply your own to add, e.g., JIT entitlements.

.. code-block:: toml

   [tool.pyappdist]
   identifier = "com.example.myapp"       # required for macapp/dmg

   [[tool.pyappdist.launchers]]
   name = "myapp"
   entry = "myapp:main"
   icon = { macos = "assets/myapp.png" }  # the .app icon (per launcher)

   [[tool.pyappdist.targets]]
   name = "macos-arm-dmg"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "dmg"                         # or "macapp" for the bare bundle
   # min-macos = "12.0"
   # signing-identity = "Developer ID Application: Your Name (TEAMID)"
   # notary-profile = "your-notary-profile"

.. _macos-signing:

Code signing and notarization
-----------------------------

The bundle is always code-signed. Without a configured identity it is **ad-hoc**
signed (``codesign -s -``): it runs on the build machine but Gatekeeper rejects it
elsewhere. To distribute, sign with a **Developer ID Application** certificate and
**notarize**.

Prerequisites (one-time):

1. Enroll in the Apple Developer Program and create a *Developer ID Application*
   certificate (Xcode → Settings → Accounts, or the Developer portal). Confirm it is
   installed::

      security find-identity -v -p codesigning
      # 1) ... "Developer ID Application: Your Name (TEAMID)"

2. Create a ``notarytool`` keychain profile from an `app-specific password
   <https://account.apple.com>`_ (Sign-In & Security → App-Specific Passwords). The
   password authorizes the *tool*, not one app — one profile notarizes every build.
   pyappdist never sees the password; it lives only in the keychain::

      xcrun notarytool store-credentials your-notary-profile \
          --apple-id you@example.com --team-id TEAMID

Then set ``signing-identity`` and ``notary-profile`` on the target (or use the
``PYAPPDIST_SIGNING_IDENTITY`` / ``PYAPPDIST_NOTARY_PROFILE`` environment
variables), as in the configuration example above.

``pyappdist build`` then deep-signs every Mach-O in the bundle with a hardened
runtime, signs the ``.dmg``, submits it to Apple's notary service, waits, and staples
the ticket so it validates offline. Verify the result::

   codesign --verify --deep --strict --verbose=2 dist/MyApp.app
   spctl -a -t open --context context:primary-signature dist/MyApp-1.0.dmg
   xcrun stapler validate dist/MyApp-1.0.dmg

Notarization runs only when **both** a Developer ID identity and a notary profile are
set; an ad-hoc build skips it. ``PYAPPDIST_SIGN_CMD`` (see
:ref:`msi-code-signing`) is also applied to the ``.dmg`` as an extra hook if set.

Install behavior
----------------

A ``.dmg`` is mounted; the user drags ``<name>.app`` into ``/Applications``. A bare
``.app`` (``format = "macapp"``) can be ``open``\ ed directly or shipped through your own
channel (a zip, a ``.dmg`` you decorate, or an auto-updater such as Sparkle).

A Developer-ID-signed, notarized, stapled bundle is accepted by Gatekeeper offline. An
ad-hoc bundle is not — expect ``spctl`` to reject it (run it locally via right-click →
Open, or sign with a Developer ID).
