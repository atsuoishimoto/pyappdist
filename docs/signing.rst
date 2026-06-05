Code signing
============

Windows
-------

Artifacts are unsigned by default. To sign each ``.exe`` and the ``.msi``, set
the ``PYAPPDIST_SIGN_CMD`` environment variable. The token ``{file}`` is replaced
with the path of the artifact being signed, and the command is run for each one.

.. code-block:: bash

   export PYAPPDIST_SIGN_CMD='signtool.exe sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "{file}"'

When the variable is unset, signing is skipped silently.

Signing happens as part of ``pyappdist build``: each launcher executable is
signed after it is compiled, and the MSI is signed after it is built.

.. note::

   Obtaining and managing code-signing certificates is out of scope for
   pyappdist. Unsigned installers will trigger a Windows SmartScreen warning.

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
   signing_identity = "Developer ID Application: Your Name (TEAMID)"
   notary_profile = "your-notary-profile"

``pyappdist build`` then deep-signs every Mach-O in the bundle with a hardened
runtime, signs the ``.dmg``, submits it to Apple's notary service, waits, and staples
the ticket so it validates offline. Verify the result::

   codesign --verify --deep --strict --verbose=2 dist/MyApp.app
   spctl -a -t open --context context:primary-signature dist/MyApp-1.0.dmg
   xcrun stapler validate dist/MyApp-1.0.dmg

Notarization runs only when **both** a Developer ID identity and a notary profile are
set; an ad-hoc build skips it. ``PYAPPDIST_SIGN_CMD`` (above) is also applied to the
``.dmg`` as an extra hook if set.
