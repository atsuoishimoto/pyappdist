Code signing
============

Windows (MSI)
-------------

MSI targets are unsigned by default. Enable signing with ``code-sign = true`` on the
target; ``pyappdist build`` then signs each launcher ``.exe`` after it is compiled and
the ``.msi`` after it is built.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "win"
   platform = "windows-x86_64"
   format = "msi"
   code-sign = true
   # code-sign-command = 'signtool.exe sign ... "{file}"'   # optional; default used if omitted

With ``code-sign = true`` the signing command is resolved in this order:

1. the ``PYAPPDIST_SIGN_CMD`` environment variable (highest priority);
2. the target's ``code-sign-command``;
3. a built-in default:
   ``signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"``.

The default uses ``/a`` to auto-select the best certificate from the Windows certificate
store, so a non-secret command line can live in ``pyproject.toml``; use
``PYAPPDIST_SIGN_CMD`` to override per machine (for example a ``.pfx`` whose password
must not be committed). The token ``{file}`` is replaced with the path of the artifact
being signed (appended to the command if absent).

When ``code-sign`` is unset (or ``false``), signing is skipped regardless of
``PYAPPDIST_SIGN_CMD``.

.. note::

   Obtaining and managing code-signing certificates is out of scope for
   pyappdist. Unsigned installers will trigger a Windows SmartScreen warning.

.. note::

   MSIX is not covered by ``code-sign``. Packages submitted to the Microsoft Store are
   re-signed on ingestion; for sideloading the package must be signed with a certificate
   whose subject matches the manifest ``Publisher``. MSIX is signed only when
   ``PYAPPDIST_SIGN_CMD`` is set.

macOS (macapp / dmg)
--------------------

The :doc:`macapp / dmg <formats/macapp>` formats are always code-signed. Without a
configured identity the bundle is **ad-hoc** signed (``codesign -s -``): it runs on
the build machine but Gatekeeper rejects it elsewhere. To distribute, sign with a
**Developer ID Application** certificate and **notarize**.

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

Then configure the target (or use the ``PYAPPDIST_SIGNING_IDENTITY`` /
``PYAPPDIST_NOTARY_PROFILE`` environment variables):

.. code-block:: toml

   [[tool.pyappdist.targets]]
   name = "macos-arm-dmg"
   platform = "macos-aarch64"
   format = "dmg"
   signing-identity = "Developer ID Application: Your Name (TEAMID)"
   notary-profile = "your-notary-profile"

``pyappdist build`` then deep-signs every Mach-O in the bundle with a hardened
runtime, signs the ``.dmg``, submits it to Apple's notary service, waits, and staples
the ticket so it validates offline. Verify the result::

   codesign --verify --deep --strict --verbose=2 dist/MyApp.app
   spctl -a -t open --context context:primary-signature dist/MyApp-1.0.dmg
   xcrun stapler validate dist/MyApp-1.0.dmg

Notarization runs only when **both** a Developer ID identity and a notary profile are
set; an ad-hoc build skips it. ``PYAPPDIST_SIGN_CMD`` (above) is also applied to the
``.dmg`` as an extra hook if set.
