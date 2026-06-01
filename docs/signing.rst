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

macOS
-----

macOS code is **always signed** — the only question is with what identity.

**Ad-hoc (default).** With no identity configured, pyappdist deep-signs the bundle
ad-hoc (``codesign -s -``), signing every nested Mach-O (the bundled interpreter, each
``.so``/``.dylib``, the launcher) from the inside out. This is enough to run the app on
the machine that built it, but Gatekeeper **rejects** it elsewhere (``spctl`` reports
``rejected``). No Apple account is needed.

**Developer ID + notarization.** Set ``signing_identity`` on the target (or the
``PYAPPDIST_SIGNING_IDENTITY`` environment variable) to a Developer ID identity, e.g.
``"Developer ID Application: Your Name (TEAMID)"``. pyappdist then signs with the
**hardened runtime** (``--options runtime``), a secure ``--timestamp``, and entitlements
(a bundled-python default — ``allow-jit``, ``allow-unsigned-executable-memory``,
``disable-library-validation`` — unless you point ``entitlements`` at your own plist).

To **notarize**, also set ``notary_profile`` (or ``PYAPPDIST_NOTARY_PROFILE``) to a
``notarytool`` keychain profile created once with::

   xcrun notarytool store-credentials <profile> \
     --apple-id you@example.com --team-id TEAMID --password <app-specific-password>

The build then submits the ``.dmg`` (or, for ``format = "app"``, a zip of the bundle) with
``notarytool submit --wait`` and, on acceptance, staples the ticket
(``stapler staple``) so it validates offline. Notarization is skipped (with a notice) when
the signature is ad-hoc, since Apple only notarizes Developer ID-signed code.

.. code-block:: toml

   [[tool.pyappdist.targets]]
   platform = "macos-arm64"
   format = "dmg"
   signing_identity = "Developer ID Application: Your Name (TEAMID)"
   notary_profile = "my-notary-profile"
   # team_id = "TEAMID"
   # entitlements = "build/app.entitlements"   # optional; a default is used otherwise

.. note::

   Developer ID signing and notarization require an Apple Developer Program membership
   (paid). pyappdist never handles your Apple ID password or API key — those live only in
   the ``notarytool`` keychain profile. Signing and notarization run **natively on macOS**;
   there is no cross-build.

Verifying a signed + notarized build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once you have a Developer ID certificate, no code changes are needed — set the identity and
notary profile and build:

.. code-block:: bash

   # one-time: confirm the certificate is in the keychain
   security find-identity -v -p codesigning
   # one-time: create the notarytool keychain profile
   xcrun notarytool store-credentials my-notary-profile \
     --apple-id you@example.com --team-id TEAMID --password <app-specific-password>

   # build with signing + notarization (config keys also work instead of env vars)
   cd e2e/smoke
   PYAPPDIST_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
   PYAPPDIST_NOTARY_PROFILE="my-notary-profile" \
   uv run pyappdist build macos-arm64

The build log should show ``codesign (Developer ID …)`` then
``notarize: submitting … / accepted / stapling`` (notarization can take a few minutes).
Then verify the result — the key difference from an ad-hoc build is that Gatekeeper now
**accepts** it:

.. code-block:: bash

   DMG=appdist/macos-arm64/dist/smoke-0.1.0.dmg
   xcrun stapler validate "$DMG"                 # ticket stapled to the dmg
   spctl -a -t open --context context:primary-signature -vvv "$DMG"   # dmg accepted

   # mount and check the app inside
   hdiutil attach "$DMG" -nobrowse -mountpoint /tmp/mnt
   codesign --verify --deep --strict --verbose=2 /tmp/mnt/*.app
   spctl -a -t exec -vvv /tmp/mnt/*.app          # "accepted" (was "rejected" for ad-hoc)
   hdiutil detach /tmp/mnt

If notarization comes back ``Invalid``, read the per-submission log to see which binary or
entitlement was rejected::

   xcrun notarytool log <submission-id> --keychain-profile my-notary-profile

The most common fix is entitlements: the bundled-python defaults
(``disable-library-validation`` etc.) cover most apps, but you can override them with the
``entitlements`` key if a dependency needs something more specific.
