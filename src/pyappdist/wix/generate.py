"""Pure function that generates WiX v4 XML from the neutral IR (DirNode).

``scope`` is a build-time choice: ``"user"`` (default) makes a per-user package that
installs into ``%LocalAppData%\\Programs\\<name>`` with no admin, and ``"machine"`` makes
a per-machine package that installs into ``Program Files`` (requires admin). An optional
``[tool.pyappdist.wix].license`` (an RTF EULA) adds a one-page license dialog via the
stock WixUI_Minimal set, which needs the ``WixToolset.UI.wixext`` extension at build
time. File@Source is emitted as a path relative to the image root and resolved via the
``wix build -b <image>`` bind path (no absolute paths are embedded, so golden comparisons
stay stable).
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

from ..config import Config
from ..errors import ConfigError
from .guid import is_guid, stable_guid
from .scan import DirNode

WIX_NS = "http://wixtoolset.org/schemas/v4/wxs"
WIX_UI_NS = "http://wixtoolset.org/schemas/v4/wxs/ui"

# Filename the license RTF is staged to next to the .wxs (see wix/build.py); referenced
# from WixUILicenseRtf so it resolves relative to the wix build working directory.
LICENSE_STAGED_NAME = "pyappdist_license.rtf"


def generate_wxs(config: Config, tree: DirNode) -> str:
    """Return the WiX XML string from ``config`` and the scanned ``tree``."""
    manufacturer = config.wix.manufacturer
    upgrade_code = config.wix.upgrade_code
    if not manufacturer:
        raise ConfigError("MSI generation requires [tool.pyappdist.wix].manufacturer")
    if not upgrade_code or not is_guid(upgrade_code):
        raise ConfigError(
            "MSI generation requires a valid GUID in [tool.pyappdist.wix].upgrade-code"
        )

    # scope is a build-time choice (no install-time dialog):
    #   user    -> per-user package, installs into %LocalAppData%\Programs\<Name>, HKCU,
    #              no admin (ProgramFilesFolder is never used, so no redirection issues).
    #   machine -> per-machine package, installs into Program Files, HKLM, requires admin.
    per_user = config.wix.scope == "user"
    pkg_scope = "perUser" if per_user else "perMachine"
    install_root_reg = "HKCU" if per_user else "HKLM"

    ET.register_namespace("", WIX_NS)
    ET.register_namespace("ui", WIX_UI_NS)
    wix = ET.Element(_q("Wix"))
    pkg = _sub(
        wix, "Package",
        Name=config.name,
        Manufacturer=manufacturer,
        Version=config.version,
        UpgradeCode=str(upgrade_code).upper(),
        Language="1033",
        Codepage="65001",
        Scope=pkg_scope,
    )
    _sub(pkg, "MajorUpgrade", DowngradeErrorMessage="A newer version is already installed.")
    _sub(pkg, "MediaTemplate", EmbedCab="yes")

    # An optional license shows a one-page EULA via the stock WixUI_Minimal set; the RTF
    # is staged next to the .wxs by wix/build.py under LICENSE_STAGED_NAME.
    if config.wix.license:
        _ui_sub(pkg, "WixUI", Id="WixUI_Minimal")
        _sub(pkg, "WixVariable", Id="WixUILicenseRtf", Value=LICENSE_STAGED_NAME)

    reg_key = f"Software\\{manufacturer}\\{config.name}"
    component_ids: list[str] = []

    # Application body (copy the image tree as-is). The install root is the only thing
    # that differs by scope; everything below uses the INSTALLFOLDER property.
    if per_user:
        root = _sub(pkg, "StandardDirectory", Id="LocalAppDataFolder")
        programs = _sub(root, "Directory", Id="dir_programs", Name="Programs")
        install = _sub(programs, "Directory", Id="INSTALLFOLDER", Name=config.name)
    else:
        root = _sub(pkg, "StandardDirectory", Id="ProgramFiles64Folder")
        install = _sub(root, "Directory", Id="INSTALLFOLDER", Name=config.name)
    _emit_dir(install, tree, str(upgrade_code), component_ids)

    # Registry entry recording the install location (usable for uninstall detection, etc.)
    reg_comp = _sub(install, "Component", Id="cmp_registry", Guid=stable_guid(upgrade_code, "::registry"))
    _sub(
        reg_comp, "RegistryValue",
        Root=install_root_reg, Key=reg_key, Name="InstallDir",
        Type="string", Value="[INSTALLFOLDER]", KeyPath="yes",
    )
    component_ids.append("cmp_registry")

    # Start menu shortcuts (one per launcher)
    if config.launchers:
        menu = _sub(pkg, "StandardDirectory", Id="ProgramMenuFolder")
        sc_dir = _sub(menu, "Directory", Id="ShortcutFolder", Name=config.name)
        sc_comp = _sub(sc_dir, "Component", Id="cmp_shortcuts", Guid=stable_guid(upgrade_code, "::shortcuts"))
        for spec in config.launchers:
            _sub(
                sc_comp, "Shortcut",
                Id=f"sc_{_h(spec.name)}",
                Name=spec.name,
                Target=f"[INSTALLFOLDER]{spec.name}.exe",
                WorkingDirectory="INSTALLFOLDER",
            )
        _sub(sc_comp, "RemoveFolder", Id="rm_ShortcutFolder", On="uninstall")
        _sub(
            sc_comp, "RegistryValue",
            Root="HKCU", Key=reg_key, Name="installed",
            Type="integer", Value="1", KeyPath="yes",
        )
        component_ids.append("cmp_shortcuts")

    feature = _sub(pkg, "Feature", Id="Main", Title=config.name, Level="1")
    for cid in component_ids:
        _sub(feature, "ComponentRef", Id=cid)

    ET.indent(wix, space="  ")
    body = ET.tostring(wix, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _emit_dir(parent: ET.Element, node: DirNode, upgrade_code: str, component_ids: list[str]) -> None:
    for f in node.files:
        cid = f"cmp_{_h(f.rel)}"
        comp = _sub(parent, "Component", Id=cid, Guid=stable_guid(upgrade_code, f.rel))
        _sub(comp, "File", Id=f"fil_{_h(f.rel)}", Source=f.rel.replace("/", "\\"), KeyPath="yes")
        component_ids.append(cid)
    for d in node.subdirs:
        sub = _sub(parent, "Directory", Id=f"dir_{_h(d.rel)}", Name=d.name)
        _emit_dir(sub, d, upgrade_code, component_ids)


def _q(tag: str) -> str:
    return f"{{{WIX_NS}}}{tag}"


def _sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, _q(tag))
    for key, value in attrs.items():
        el.set(key, value)
    return el


def _ui_sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    """Like ``_sub`` but in the WixUI extension namespace (e.g. ``ui:WixUI``)."""
    el = ET.SubElement(parent, f"{{{WIX_UI_NS}}}{tag}")
    for key, value in attrs.items():
        el.set(key, value)
    return el


def _h(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
