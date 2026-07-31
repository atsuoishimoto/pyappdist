"""Build a distribution ``.pkg`` that installs the ``.app`` bundle(s) into ``/Applications``.

The signed bundles are staged under a payload root, packed into a component package
with ``pkgbuild``, and wrapped into a distribution package with ``productbuild``.
The install is **system scope**: the distribution enables only the ``localSystem``
domain, so Installer.app asks for admin credentials and the payload lands in
``/Applications`` (a per-user install is what the ``.run`` installer provides).

``pkgbuild``'s component analysis marks ``.app`` bundles *relocatable* by default —
the installer would then update a copy the user moved elsewhere instead of installing
into ``/Applications`` — so the analyzed component plist is rewritten with
``BundleIsRelocatable = false`` before packing.

Launchers with ``gui = false`` get a ``postinstall`` script that symlinks their
bundle executable into ``/usr/local/bin`` (the script runs as root in the system
domain, so creating the symlinks there is allowed).

Signing uses a **Developer ID Installer** identity (``installer-identity`` /
``PYAPPDIST_MACOS_INSTALLER_IDENTITY``) — a different certificate type from the Developer
ID Application identity that signs the bundles themselves (:mod:`.sign`). Without
one the ``.pkg`` is left unsigned (installable locally, but not notarizable).
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..config import Config
from ..errors import BuildError

_INSTALLER_IDENTITY_ENV = "PYAPPDIST_MACOS_INSTALLER_IDENTITY"


def resolve_installer_identity(config: Config) -> str | None:
    """The Developer ID Installer identity from config or environment, if any."""
    return config.macos.installer_identity or os.environ.get(_INSTALLER_IDENTITY_ENV)


def package_identifier(config: Config) -> str:
    """The component package identifier (the receipt id ``pkgutil`` records).

    Suffixed with ``.pkg`` so it never collides with a bundle's CFBundleIdentifier
    (with a single launcher the ``.app`` uses ``config.identifier`` verbatim).
    """
    return f"{config.identifier}.pkg"


def distribution_xml(config: Config, pkg_filename: str) -> str:
    """The ``productbuild --distribution`` XML for the component package.

    ``<domains enable_localSystem="true"/>`` fixes the install to the system domain
    of the boot volume (admin required); the home-directory domain is deliberately
    not enabled. ``<allowed-os-versions>`` mirrors the bundles' ``min-macos``.
    """
    pkg_id = package_identifier(config)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<installer-gui-script minSpecVersion="2">\n'
        f"    <title>{escape(config.name)}</title>\n"
        '    <options customize="never" require-scripts="false"/>\n'
        '    <domains enable_localSystem="true"/>\n'
        "    <volume-check>\n"
        "        <allowed-os-versions>\n"
        f"            <os-version min={quoteattr(config.macos.min_macos)}/>\n"
        "        </allowed-os-versions>\n"
        "    </volume-check>\n"
        "    <choices-outline>\n"
        '        <line choice="default"/>\n'
        "    </choices-outline>\n"
        '    <choice id="default" visible="false">\n'
        f"        <pkg-ref id={quoteattr(pkg_id)}/>\n"
        "    </choice>\n"
        f"    <pkg-ref id={quoteattr(pkg_id)} version={quoteattr(config.version)}>"
        f"{escape(pkg_filename)}</pkg-ref>\n"
        "</installer-gui-script>\n"
    )


def pin_bundle_locations(component_plist: bytes) -> bytes:
    """Rewrite a ``pkgbuild --analyze`` component plist with relocation disabled.

    ``BundleIsRelocatable = false`` on every component makes the installer always
    put (and upgrade) the bundles under the packaged path — ``/Applications`` —
    instead of following a copy the user moved or renamed.
    """
    components = plistlib.loads(component_plist)
    for component in components:
        component["BundleIsRelocatable"] = False
    return plistlib.dumps(components)


def postinstall_script(config: Config) -> str | None:
    """The ``postinstall`` shell script symlinking CLI launchers into ``/usr/local/bin``.

    Only launchers with ``gui = false`` get a symlink (a GUI app is launched from
    ``/Applications``, not from PATH); returns None when there is nothing to link.
    The ``.app`` naming mirrors ``bundle.build_macos_apps``: with a single launcher
    the bundle is named after the app-level ``name``, otherwise after each launcher.
    """
    cli = [spec for spec in config.launchers if not spec.gui]
    if not cli:
        return None
    single = len(config.launchers) == 1
    lines = [
        "#!/bin/sh",
        "set -e",
        "mkdir -p /usr/local/bin",
    ]
    for spec in cli:
        label = config.name if single else spec.name
        target = f"/Applications/{label}.app/Contents/MacOS/{spec.name}"
        link = f"/usr/local/bin/{spec.name}"
        lines.append(f"ln -sfn {shlex.quote(target)} {shlex.quote(link)}")
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


def build_pkg(
    config: Config, apps: list[Path], out_pkg: Path, build_dir: Path, *, log=print
) -> Path:
    """Create ``out_pkg`` from the given signed ``.app`` bundles."""
    if not apps:
        raise BuildError("no .app bundles to package into a pkg")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    root = build_dir / "root"
    applications = root / "Applications"
    applications.mkdir(parents=True)
    for app in apps:
        shutil.copytree(app, applications / app.name, symlinks=True)

    component_plist = build_dir / "component.plist"
    _run(
        ["pkgbuild", "--analyze", "--root", str(root), str(component_plist)],
        what="pkgbuild --analyze",
    )
    component_plist.write_bytes(pin_bundle_locations(component_plist.read_bytes()))

    cmd = [
        "pkgbuild",
        "--root", str(root),
        "--component-plist", str(component_plist),
        "--identifier", package_identifier(config),
        "--version", config.version,
        "--install-location", "/",
    ]
    script = postinstall_script(config)
    if script is not None:
        scripts_dir = build_dir / "scripts"
        scripts_dir.mkdir()
        postinstall = scripts_dir / "postinstall"
        postinstall.write_text(script, encoding="utf-8")
        postinstall.chmod(0o755)
        cmd += ["--scripts", str(scripts_dir)]
    component_pkg = build_dir / "component.pkg"
    cmd.append(str(component_pkg))
    log(f"macos: pkgbuild -> {component_pkg.name}")
    _run(cmd, what="pkgbuild")

    dist_xml = build_dir / "distribution.xml"
    dist_xml.write_text(distribution_xml(config, component_pkg.name), encoding="utf-8")

    out_pkg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "productbuild",
        "--distribution", str(dist_xml),
        "--package-path", str(build_dir),
    ]
    identity = resolve_installer_identity(config)
    if identity:
        log(f"macos: signing pkg with Developer ID Installer identity {identity!r}")
        cmd += ["--sign", identity, "--timestamp"]
    else:
        log("macos: pkg left unsigned (set installer-identity / "
            f"{_INSTALLER_IDENTITY_ENV} for Developer ID Installer)")
    cmd.append(str(out_pkg))
    log(f"macos: productbuild -> {out_pkg}")
    _run(cmd, what="productbuild")
    if not out_pkg.exists():
        raise BuildError(f"productbuild produced no package: {out_pkg}")
    return out_pkg


def _run(cmd: list[str], *, what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise BuildError(f"{what} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
