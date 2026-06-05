macOS app bundle (.app / .dmg)
==============================

``format = "macapp"`` and ``format = "dmg"`` build a native macOS ``.app`` bundle — the
double-click-to-launch, Dock-able form a GUI app is distributed in — rather than the
``.run`` installer that :doc:`macos` produces. Use these for graphical apps; use
``macos`` for command-line tools.

* ``macapp`` assembles one ``<name>.app`` per launcher into ``appdist/<name>/dist/``.
* ``dmg`` does the same, then wraps the bundle(s) in a compressed ``<name>-<version>.dmg``
  disk image with the classic drag-to-``/Applications`` layout.

Both are **code-signed**; with a Developer ID identity they are also **notarized and
stapled** (see :doc:`../signing`). Build on macOS — an Apple Silicon host for
``macos-aarch64``, an Intel host for ``macos-x86_64``. On a non-macOS host the step is
skipped (the image is still built).

The bundle layout is the real install tree, unchanged: the python-build-standalone
runtime with your app pip-installed lands in ``Contents/Resources/python``, and a tiny
Mach-O launcher at ``Contents/MacOS/<name>`` ``execv``\ s the bundled interpreter. With
several launchers you get one ``.app`` each (a bundle has exactly one executable), all
packed into a single ``.dmg``.

Requirements
------------

``identifier`` (app-level) is **required** — the reverse-DNS CFBundleIdentifier (e.g.
``"com.example.myapp"``). The toolchain (``clang``, ``codesign``, ``hdiutil``, ``sips`` /
``iconutil`` for the icon, and ``xcrun notarytool`` / ``stapler`` for notarization) ships
with the Xcode command-line tools.

Configuration
-------------

All keys live on the macOS target table.

``icon``
   Path (relative to the project) to a source ``.png`` (ideally ≥1024×1024). Resized into
   an ``.icns`` via ``sips`` + ``iconutil``. A placeholder is generated if omitted.

``min_macos``
   Minimum macOS version. Sets both the bundle's ``LSMinimumSystemVersion`` and clang's
   ``-mmacosx-version-min``. Default ``"11.0"``.

``category``
   ``LSApplicationCategoryType`` (e.g. ``"public.app-category.utilities"``). Optional.

``signing_identity``
   Developer ID identity for distribution signing, e.g.
   ``"Developer ID Application: Your Name (TEAMID)"`` (or the
   ``PYAPPDIST_SIGNING_IDENTITY`` environment variable). When unset the bundle is **ad-hoc
   signed** — it runs locally but Gatekeeper rejects it on other machines. See
   :doc:`../signing`.

``team_id``
   Apple Developer Team ID (informational).

``notary_profile``
   ``notarytool`` keychain profile name (or ``PYAPPDIST_NOTARY_PROFILE``). When set
   **and** a Developer ID identity is configured, the artifact is notarized and stapled.

``entitlements``
   Path to a custom entitlements ``.plist``. The default grants only
   ``com.apple.security.cs.disable-library-validation`` (so the hardened interpreter can
   load third-party extension modules); supply your own to add, e.g., JIT entitlements.

.. code-block:: toml

   [tool.pyappdist]
   identifier = "com.example.myapp"       # required for macapp/dmg

   [[tool.pyappdist.targets]]
   name = "macos-arm-dmg"
   platform = "macos-aarch64"             # or "macos-x86_64" for Intel
   format = "dmg"                         # or "macapp" for the bare bundle
   # icon = "assets/app.png"
   # min_macos = "12.0"
   # signing_identity = "Developer ID Application: Your Name (TEAMID)"
   # notary_profile = "pyappdist-notary"

Install behavior
----------------

A ``.dmg`` is mounted; the user drags ``<name>.app`` into ``/Applications``. A bare
``.app`` (``format = "macapp"``) can be ``open``\ ed directly or shipped through your own
channel (a zip, a ``.dmg`` you decorate, or an auto-updater such as Sparkle).

A Developer-ID-signed, notarized, stapled bundle is accepted by Gatekeeper offline. An
ad-hoc bundle is not — expect ``spctl`` to reject it (run it locally via right-click →
Open, or sign with a Developer ID).
