"""Generate an ``AppxManifest.xml`` for an MSIX package (pure function).

The packaged app is a full-trust Win32 app: each launcher becomes an ``<Application>``
with ``EntryPoint="Windows.FullTrustApplication"`` and the package declares the
``runFullTrust`` restricted capability. The image tree pyappdist already builds is the
package payload; ``makeappx`` packs it (see ``msix/build.py``).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..config import Config
from ..errors import ConfigError

FOUNDATION = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
RESCAP = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"

# Asset paths referenced from the manifest (staged into the image by msix/build.py).
STORE_LOGO = "Assets\\StoreLogo.png"
SQUARE150_LOGO = "Assets\\Square150x150Logo.png"
SQUARE44_LOGO = "Assets\\Square44x44Logo.png"


def generate_manifest(config: Config) -> str:
    """Return the AppxManifest.xml string for ``config`` (an msix-format target)."""
    if not config.launchers:
        raise ConfigError("MSIX generation requires at least one launcher")

    identity_name = config.msix.identity_name or config.dist_name
    # An explicit publisher is taken verbatim (the user supplies a complete DN that
    # must match the signing cert subject); the default derives a single-RDN DN, so
    # the value needs RFC 4514 escaping ("Acme, Inc." would otherwise parse as two RDNs).
    publisher = config.msix.publisher or f"CN={_rdn_escape(config.wix.manufacturer or config.name)}"
    display_name = config.msix.display_name or config.name
    publisher_display = config.wix.manufacturer or config.name
    version = _version4(config.version)
    arch = config.target.wix_arch  # "x64" / "arm64"

    ET.register_namespace("", FOUNDATION)
    ET.register_namespace("uap", UAP)
    ET.register_namespace("rescap", RESCAP)

    pkg = ET.Element(f"{{{FOUNDATION}}}Package")

    _sub(pkg, FOUNDATION, "Identity", Name=identity_name, Publisher=publisher,
         Version=version, ProcessorArchitecture=arch)

    props = _sub(pkg, FOUNDATION, "Properties")
    _text(props, FOUNDATION, "DisplayName", display_name)
    _text(props, FOUNDATION, "PublisherDisplayName", publisher_display)
    _text(props, FOUNDATION, "Logo", STORE_LOGO)

    deps = _sub(pkg, FOUNDATION, "Dependencies")
    _sub(deps, FOUNDATION, "TargetDeviceFamily", Name="Windows.Desktop",
         MinVersion="10.0.17763.0", MaxVersionTested="10.0.22621.0")

    res = _sub(pkg, FOUNDATION, "Resources")
    _sub(res, FOUNDATION, "Resource", Language="en-us")

    caps = _sub(pkg, FOUNDATION, "Capabilities")
    _sub(caps, RESCAP, "Capability", Name="runFullTrust")

    apps = _sub(pkg, FOUNDATION, "Applications")
    multi = len(config.launchers) > 1
    seen: set[str] = set()
    for spec in config.launchers:
        app_id = _unique(_app_id(spec.name), seen)
        app = _sub(apps, FOUNDATION, "Application", Id=app_id,
                   Executable=f"{spec.name}.exe", EntryPoint="Windows.FullTrustApplication")
        _sub(app, UAP, "VisualElements",
             DisplayName=f"{display_name} - {spec.name}" if multi else display_name,
             Description=display_name,
             BackgroundColor="transparent",
             Square150x150Logo=SQUARE150_LOGO,
             Square44x44Logo=SQUARE44_LOGO)

    ET.indent(pkg, space="  ")
    body = ET.tostring(pkg, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def _version4(version: str) -> str:
    """MSIX requires a 4-part numeric version; pad X.Y[.Z] -> X.Y.Z.0."""
    parts = (version.split(".") + ["0", "0", "0", "0"])[:4]
    return ".".join(parts)


def _rdn_escape(value: str) -> str:
    """Escape an X.500 RDN attribute value per RFC 4514 (for ``CN=<value>``)."""
    out = "".join("\\" + c if c in '\\,+"<>;=' else c for c in value)
    if out.startswith(("#", " ")):
        out = "\\" + out
    if out.endswith(" "):
        out = out[:-1] + "\\ "
    return out


def _app_id(name: str) -> str:
    """A valid MSIX Application Id (alphanumeric, must start with a letter)."""
    s = "".join(c for c in name if c.isalnum())
    if not s or s[0].isdigit():
        s = "App" + s
    return s


def _unique(candidate: str, seen: set[str]) -> str:
    out, n = candidate, 2
    while out in seen:
        out = f"{candidate}{n}"
        n += 1
    seen.add(out)
    return out


def _sub(parent: ET.Element, ns: str, tag: str, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ns}}}{tag}")
    for key, value in attrs.items():
        el.set(key, value)
    return el


def _text(parent: ET.Element, ns: str, tag: str, text: str) -> ET.Element:
    el = _sub(parent, ns, tag)
    el.text = text
    return el
