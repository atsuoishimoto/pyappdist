"""Pure function that generates WiX v4 XML from the neutral IR (DirNode).

``scope`` is a build-time choice: ``"user"`` (default) makes a per-user package that
installs into ``%LocalAppData%\\Programs\\<name>`` with no admin, and ``"machine"`` makes
a per-machine package that installs into ``Program Files`` (requires admin). An optional
``[tool.pyappdist.wix].license`` (an RTF EULA) adds a one-page license dialog via the
stock WixUI_Minimal set, which needs the ``WixToolset.UI.wixext`` extension at build
time. An optional ``add-to-path`` appends the install folder to PATH via the Environment
table, at the user or system level matching ``scope``. File@Source is emitted as a path
relative to the image root and resolved via the
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
# by bare name from WixUILicenseRtf, which wix resolves through the bind path build.py
# passes for that directory.
LICENSE_STAGED_NAME = "pyappdist_license.rtf"

# Same staging trick for the product icon: the source .ico is copied next to the .wxs
# by wix/build.py and referenced by name from Icon/@SourceFile.
ICON_STAGED_NAME = "pyappdist_product.ico"

# Icon table entry id referenced by ARPPRODUCTICON. Windows Installer keys the Icon
# table by this name, so it carries the .ico extension by convention.
_PRODUCT_ICON_ID = "pyappdist_product.ico"


def product_icon(config: Config) -> str | None:
    """The launcher icon to use as the product icon, or None.

    Add/Remove Programs shows a single icon per product, so the first launcher that
    declares a Windows icon supplies it — matching what the user sees on the shortcut
    of the app's main entry point.
    """
    for spec in config.launchers:
        icon = spec.icon_for("windows")
        if icon:
            return icon
    return None


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
    major_upgrade_attrs = {"DowngradeErrorMessage": "A newer version is already installed."}
    if config.wix.allow_same_version_upgrades:
        major_upgrade_attrs["AllowSameVersionUpgrades"] = "yes"
    _sub(pkg, "MajorUpgrade", **major_upgrade_attrs)
    _sub(pkg, "MediaTemplate", EmbedCab="yes")

    # Without ARPPRODUCTICON the product shows the generic Windows Installer icon in
    # Add/Remove Programs. The .ico is staged next to the .wxs by wix/build.py, so the
    # SourceFile is a bare name resolved through the staged-file bind path (same
    # approach as the license RTF).
    if product_icon(config):
        _sub(pkg, "Icon", Id=_PRODUCT_ICON_ID, SourceFile=ICON_STAGED_NAME)
        _sub(pkg, "Property", Id="ARPPRODUCTICON", Value=_PRODUCT_ICON_ID)

    # An optional license shows a one-page EULA via the stock WixUI_Minimal set; the RTF
    # is staged next to the .wxs by wix/build.py under LICENSE_STAGED_NAME and found
    # through that directory's bind path.
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

    # Start menu shortcuts (one per launcher with app-entry; a hidden launcher's
    # .exe is still installed — it just gets no Start Menu presence)
    visible = [spec for spec in config.launchers if spec.app_entry]
    if visible:
        menu = _sub(pkg, "StandardDirectory", Id="ProgramMenuFolder")
        sc_dir = _sub(menu, "Directory", Id="ShortcutFolder", Name=config.name)
        sc_comp = _sub(sc_dir, "Component", Id="cmp_shortcuts", Guid=stable_guid(upgrade_code, "::shortcuts"))
        for spec in visible:
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
            Root=install_root_reg, Key=reg_key, Name="installed",
            Type="integer", Value="1", KeyPath="yes",
        )
        component_ids.append("cmp_shortcuts")

    # Optional PATH registration: append INSTALLFOLDER (where the launcher .exes live)
    # to PATH via the Environment table, scoped like the package — per-user edits the
    # user's PATH (HKCU\Environment, no elevation), per-machine the system PATH (HKLM).
    # Permanent="no" lets uninstall strip exactly the appended entry. Environment can't
    # be a KeyPath, so a registry value anchors the component.
    if config.wix.add_to_path:
        path_comp = _sub(install, "Component", Id="cmp_path", Guid=stable_guid(upgrade_code, "::path"))
        _sub(
            path_comp, "Environment",
            Id="env_path", Name="PATH", Value="[INSTALLFOLDER]",
            Action="set", Part="last", Separator=";",
            Permanent="no", System="no" if per_user else "yes",
        )
        _sub(
            path_comp, "RegistryValue",
            Root=install_root_reg, Key=reg_key, Name="PathRegistered",
            Type="integer", Value="1", KeyPath="yes",
        )
        component_ids.append("cmp_path")

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
