"""Notarization + stapling via ``xcrun notarytool`` / ``xcrun stapler``.

After Developer ID signing (:mod:`.sign`), the artifact is submitted to Apple's notary
service and, once accepted, the ticket is stapled so it validates offline.

Credentials are supplied through a ``notarytool`` **keychain profile** created once with
``xcrun notarytool store-credentials <profile> --apple-id … --team-id … --password …``;
pyappdist never handles the Apple ID password or API key directly. The profile name comes
from ``notary_profile`` (or ``PYAPPDIST_NOTARY_PROFILE``).

``notarytool`` accepts a ``.dmg``/``.pkg``/``.zip`` — not a bare ``.app`` — so a ``.app`` is
zipped (``ditto``) for submission, then the **bundle** is stapled (you cannot staple a zip).
A ``.dmg`` is submitted and stapled directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ..config import Config
from ..errors import BuildError

_PROFILE_ENV = "PYAPPDIST_NOTARY_PROFILE"


def resolve_notary_profile(config: Config) -> str | None:
    """The notarytool keychain profile from config or environment, if any."""
    return config.macos.notary_profile or os.environ.get(_PROFILE_ENV)


def notarize_and_staple(artifact: Path, profile: str, *, log=print) -> None:
    """Submit a ``.dmg``/``.pkg``/``.zip`` for notarization, wait, then staple it."""
    _submit(artifact, profile, log=log)
    _staple(artifact, log=log)


def notarize_app(app: Path, profile: str, *, log=print) -> None:
    """Notarize a ``.app`` (zipped for submission) and staple the bundle itself."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"{app.stem}.zip"
        _run(
            ["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)],
            what="ditto (zip for notarization)",
        )
        _submit(zip_path, profile, log=log)
    _staple(app, log=log)  # staple the bundle, not the zip


def _submit(artifact: Path, profile: str, *, log) -> None:
    log(f"notarize: submitting {artifact.name} (profile {profile!r}); waiting for Apple…")
    proc = subprocess.run(
        ["xcrun", "notarytool", "submit", str(artifact),
         "--keychain-profile", profile, "--wait", "--output-format", "json"],
        capture_output=True, text=True, errors="replace",
    )
    # --wait exits 0 once a terminal status is reached; parse the JSON and require Accepted.
    status, submission_id = _parse_status(proc.stdout)
    if proc.returncode != 0 or status != "Accepted":
        hint = ""
        if submission_id:
            hint = (
                "\nInspect the log with: xcrun notarytool log "
                f"{submission_id} --keychain-profile {profile}"
            )
        raise BuildError(
            f"notarization failed for {artifact.name} (status={status!r}):\n"
            f"{proc.stdout}\n{proc.stderr}{hint}"
        )
    log(f"notarize: accepted {artifact.name}")


def _parse_status(stdout: str) -> tuple[str | None, str | None]:
    """Extract (status, submission id) from ``notarytool --output-format json`` output."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None, None
    return data.get("status"), data.get("id")


def _staple(target: Path, *, log) -> None:
    log(f"notarize: stapling {target.name}")
    _run(["xcrun", "stapler", "staple", str(target)], what="stapler staple")


def _run(cmd: list[str], *, what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"{what} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
