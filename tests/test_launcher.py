"""Tests for the launcher bootstrap string generation (OS-independent, pure functions)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pyappdist.config import Config, LauncherConfig
from pyappdist.errors import BuildError
from pyappdist.image.layout import ImageLayout
from pyappdist.launcher import build as launcher_build
from pyappdist.launcher import winres
from pyappdist.launcher.build import _bootstrap


def _with_launcher(config: Config, launcher: LauncherConfig) -> Config:
    return dataclasses.replace(config, launchers=(launcher,))


def test_bootstrap_gui_callable_wraps_in_messagebox(sample_config: Config):
    spec = LauncherConfig(name="app", entry="pkg.mod:main", gui=True)
    out = _bootstrap(spec, _with_launcher(sample_config, spec))
    assert "from pkg.mod import main" in out
    assert "MessageBoxW" in out
    assert "sys.exit(main())" in out


def test_bootstrap_gui_module_form_no_wrapper(sample_config: Config):
    """The python -m (dotted) form is not wrapped, even for a GUI launcher."""
    spec = LauncherConfig(name="app", entry="pkg.mod", gui=True)
    out = _bootstrap(spec, _with_launcher(sample_config, spec))
    assert out == spec.bootstrap
    assert "runpy.run_module('pkg.mod'" in out
    assert "MessageBoxW" not in out


def test_bootstrap_console_uses_spec_bootstrap(sample_config: Config):
    spec = LauncherConfig(name="app", entry="pkg.mod:main", gui=False)
    assert _bootstrap(spec, _with_launcher(sample_config, spec)) == spec.bootstrap


# --- build.bat generation / vcvars failure --------------------------------


class _FakeProc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = "vcvars: cannot determine the Windows SDK version"


def _run_build_one(config: Config, tmp_path: Path, monkeypatch, returncode: int):
    """Drive _build_one with cmd.exe stubbed out; returns the generated build.bat text."""
    spec = config.launchers[0]
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=config.target, minor=config.python_minor
    )
    layout.image_dir.mkdir(parents=True)
    workdir = tmp_path / "_launcher_build"
    monkeypatch.setattr(
        launcher_build.subprocess, "run", lambda *a, **kw: _FakeProc(returncode)
    )
    launcher_build._build_one(
        config, spec, layout, r"C:\VS\vcvars64.bat", workdir, lambda m: None
    )
    return (workdir / spec.name / "build.bat").read_text(encoding="ascii")


def test_build_bat_checks_vcvars(sample_config: Config, tmp_path: Path, monkeypatch):
    # A failing vcvars must stop the batch immediately; without the check it fell
    # through to rc and surfaced as "'rc' is not recognized".
    with pytest.raises(BuildError):
        _run_build_one(sample_config, tmp_path, monkeypatch, launcher_build._VCVARS_EXIT)
    bat = (tmp_path / "_launcher_build" / "helloworld" / "build.bat").read_text()
    lines = [line.strip() for line in bat.splitlines() if line.strip()]
    call_at = lines.index("call %1 >nul")
    assert lines[call_at + 1] == f"if errorlevel 1 exit /b {launcher_build._VCVARS_EXIT}"


def test_vcvars_failure_names_the_cause(sample_config: Config, tmp_path: Path, monkeypatch):
    with pytest.raises(BuildError, match="Visual Studio environment script failed") as exc:
        _run_build_one(sample_config, tmp_path, monkeypatch, launcher_build._VCVARS_EXIT)
    # vcvars' own stderr reaches the user (only its stdout is silenced).
    assert "Windows SDK version" in str(exc.value)
    assert r"C:\VS\vcvars64.bat" in str(exc.value)


def test_compiler_failure_keeps_generic_message(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    # cl exits 2 on compile errors; that must not be mistaken for a vcvars failure.
    with pytest.raises(BuildError, match="launcher build failed") as exc:
        _run_build_one(sample_config, tmp_path, monkeypatch, 2)
    assert "Visual Studio environment script" not in str(exc.value)


# --- fixed args: one canonical split, rendered per launcher kind ------------


@pytest.mark.parametrize(
    "args,expected",
    [
        ("", ()),
        ("--verbose", ("--verbose",)),
        ("--path 'a b'", ("--path", "a b")),
        ('--path "a b"', ("--path", "a b")),
        ("-x *", ("-x", "*")),          # never glob-expanded
        ("--name 'it''s'", ("--name", "its")),
    ],
)
def test_argv_splits_with_posix_rules(args: str, expected: tuple[str, ...]):
    assert LauncherConfig(name="app", entry="m:main", args=args).argv == expected


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("plain", "plain"),
        ("a b", '"a b"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("C:\\dir\\", "C:\\dir\\"),          # no quoting needed, so no doubling
        ("C:\\a b\\", '"C:\\a b\\\\"'),      # trailing run doubled before the quote
        ('a\\"b', '"a\\\\\\"b"'),            # backslash before a quote is doubled
    ],
)
def test_msvc_quote(arg: str, expected: str):
    assert launcher_build.msvc_quote(arg) == expected


@pytest.mark.parametrize(
    "args,expected",
    [
        ("", ""),
        ("--verbose", "--verbose"),
        ("--path 'a b'", '--path "a b"'),   # one argument, not two
        ("-x *", "-x *"),                   # the child does not glob
    ],
)
def test_windows_fixed_args_are_requoted(args: str, expected: str):
    # launcher.c appends this verbatim, so it must already be MSVC-quoted.
    spec = LauncherConfig(name="app", entry="m:main", args=args)
    assert launcher_build._windows_fixed_args(spec) == expected


def test_macos_fixed_args_array():
    spec = LauncherConfig(name="app", entry="m:main", args="--path 'a b'")
    assert launcher_build._fixed_args_initializer(spec) == '{ "--path", "a b", NULL }'


def test_macos_fixed_args_empty():
    spec = LauncherConfig(name="app", entry="m:main")
    assert launcher_build._fixed_args_initializer(spec) == "{ NULL }"


# --- prebuilt stubs ----------------------------------------------------------


def test_use_prebuilt_modes(sample_config: Config, tmp_path: Path):
    stub = tmp_path / "stub.exe"

    # prebuilt (the default): the bundled stub is required.
    with pytest.raises(BuildError, match="bundle a prebuilt launcher"):
        launcher_build._use_prebuilt(sample_config, stub)
    stub.write_bytes(b"MZ")
    assert launcher_build._use_prebuilt(sample_config, stub) is True

    source = dataclasses.replace(sample_config, launcher_build="source")
    assert launcher_build._use_prebuilt(source, stub) is False


class _CapturedRun:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, cmd, *, cwd, **kw):
        self.calls.append((cmd, cwd))
        return _FakeProc(0)


def test_patch_prebuilt_windows(sample_config: Config, tmp_path: Path, monkeypatch):
    """The stub is copied, the manifest lists config + version resources, and the
    patch script runs with the image runtime's python (cwd = the gen dir)."""
    import json

    spec = sample_config.launchers[0]
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=sample_config.target,
        minor=sample_config.python_minor,
    )
    layout.image_dir.mkdir(parents=True)
    stub = tmp_path / "launcher-windows-x86_64-console.exe"
    stub.write_bytes(b"MZ-stub")
    run = _CapturedRun()
    monkeypatch.setattr(launcher_build.subprocess, "run", run)

    workdir = tmp_path / "_launcher_build"
    exe = launcher_build._patch_prebuilt_windows(
        sample_config, spec, layout, stub, workdir, lambda m: None
    )

    assert exe == layout.image_dir / "helloworld.exe"
    assert exe.read_bytes() == b"MZ-stub"

    gen = workdir / spec.name
    (cmd, cwd) = run.calls[0]
    assert cmd == [str(layout.python_exe), "patch_resources.py", "patch_manifest.json"]
    assert cwd == str(gen)
    assert (gen / "patch_resources.py").is_file()

    manifest = json.loads((gen / "patch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["exe"] == "launcher_out.exe"
    types = [entry["type"] for entry in manifest["resources"]]
    assert types == ["PYAPPDIST", 16]  # config + VERSIONINFO (no icon configured)
    for entry in manifest["resources"]:
        assert (gen / entry["file"]).is_file()

    cfg = (gen / manifest["resources"][0]["file"]).read_bytes().decode("utf-16-le")
    assert cfg.split("\0")[:2] == ["PADL1", "python\\python.exe"]


# --- the per-launcher interpreter copy (running-app icon) --------------------


def _ico(images: int = 1) -> bytes:
    """A minimal .ico with ``images`` 16x16 payloads."""
    import struct

    payload = b"IMG!"
    header = struct.pack("<HHH", 0, 1, images)
    entries = b""
    offset = 6 + 16 * images
    for _ in range(images):
        entries += struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(payload), offset)
        offset += len(payload)
    return header + entries + payload * images


def _icon_config(sample_config: Config, tmp_path: Path, name: str = "helloworld") -> Config:
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "app.ico").write_bytes(_ico())
    return dataclasses.replace(
        sample_config,
        project_dir=tmp_path,
        launchers=(
            LauncherConfig(
                name=name, entry="helloworld:main", gui=True,
                icons=(("windows", "assets/app.ico"),),
            ),
        ),
    )


def _image_layout(config: Config, tmp_path: Path) -> ImageLayout:
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=config.target, minor=config.python_minor
    )
    layout.python_dir.mkdir(parents=True)
    (layout.python_dir / "python.exe").write_bytes(b"MZ-python")
    (layout.python_dir / "pythonw.exe").write_bytes(b"MZ-pythonw")
    return layout


def test_stage_app_python_copies_and_patches(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    """A launcher with an icon starts its own copy of the interpreter, so the
    running app's windows no longer fall back to the python icon."""
    import json

    config = _icon_config(sample_config, tmp_path)
    spec = config.launchers[0]
    layout = _image_layout(config, tmp_path)
    run = _CapturedRun()
    monkeypatch.setattr(launcher_build.subprocess, "run", run)

    workdir = tmp_path / "_launcher_build"
    pyexe = launcher_build._stage_app_python(
        config, spec, layout, workdir, lambda m: None
    )

    assert pyexe == "python\\helloworld.exe"
    copy = layout.python_dir / "helloworld.exe"
    assert copy.read_bytes() == b"MZ-pythonw"          # gui -> pythonw.exe
    assert (layout.python_dir / "pythonw.exe").exists()  # the original stays

    gen = workdir / spec.name / "pyexe"
    (cmd, cwd) = run.calls[0]
    assert cmd == [str(layout.python_exe), "patch_resources.py", "patch_manifest.json"]
    assert cwd == str(gen)
    manifest = json.loads((gen / "patch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["exe"] == "pyexe_out.exe"
    names = [(entry["type"], entry["name"]) for entry in manifest["resources"]]
    # icon + the Qt-visible alias of the same group, then VERSIONINFO.
    assert names == [
        (winres.RT_ICON, 1),
        (winres.RT_GROUP_ICON, 1),
        (winres.RT_GROUP_ICON, "IDI_ICON1"),
        (winres.RT_VERSION, 1),
    ]


def test_stage_app_python_without_icon_shares_the_interpreter(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    spec = sample_config.launchers[0]
    layout = _image_layout(sample_config, tmp_path)
    run = _CapturedRun()
    monkeypatch.setattr(launcher_build.subprocess, "run", run)

    pyexe = launcher_build._stage_app_python(
        sample_config, spec, layout, tmp_path / "wd", lambda m: None
    )
    assert pyexe == "python\\python.exe"
    assert not run.calls  # nothing to patch, so no copy is made
    assert list(layout.python_dir.iterdir()) != []
    assert not (layout.python_dir / "helloworld.exe").exists()


def test_stage_app_python_avoids_overwriting_the_interpreter(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    """A launcher named "python"/"pythonw" must not clobber what it copied."""
    config = _icon_config(sample_config, tmp_path, name="pythonw")
    layout = _image_layout(config, tmp_path)
    monkeypatch.setattr(launcher_build.subprocess, "run", _CapturedRun())

    pyexe = launcher_build._stage_app_python(
        config, config.launchers[0], layout, tmp_path / "wd", lambda m: None
    )
    assert pyexe == "python\\pythonw_app.exe"
    assert (layout.python_dir / "pythonw.exe").read_bytes() == b"MZ-pythonw"


def test_patch_prebuilt_windows_points_at_the_interpreter_copy(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    """The launcher's config resource names the copy, not python.exe."""
    import json

    config = _icon_config(sample_config, tmp_path)
    spec = config.launchers[0]
    layout = _image_layout(config, tmp_path)
    stub = tmp_path / "stub.exe"
    stub.write_bytes(b"MZ-stub")
    monkeypatch.setattr(launcher_build.subprocess, "run", _CapturedRun())

    workdir = tmp_path / "_launcher_build"
    launcher_build._patch_prebuilt_windows(
        config, spec, layout, stub, workdir, lambda m: None
    )

    gen = workdir / spec.name
    manifest = json.loads((gen / "patch_manifest.json").read_text(encoding="utf-8"))
    cfg = (gen / manifest["resources"][0]["file"]).read_bytes().decode("utf-16-le")
    assert cfg.split("\0")[1] == "python\\helloworld.exe"
    assert (layout.python_dir / "helloworld.exe").is_file()


def test_patch_prebuilt_windows_failure_raises(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    spec = sample_config.launchers[0]
    layout = ImageLayout(
        image_dir=tmp_path / "image", target=sample_config.target,
        minor=sample_config.python_minor,
    )
    layout.image_dir.mkdir(parents=True)
    stub = tmp_path / "stub.exe"
    stub.write_bytes(b"MZ")
    monkeypatch.setattr(
        launcher_build.subprocess, "run", lambda *a, **kw: _FakeProc(1)
    )
    with pytest.raises(BuildError, match="resource patching failed"):
        launcher_build._patch_prebuilt_windows(
            sample_config, spec, layout, stub, tmp_path / "wd", lambda m: None
        )


def _macos_config(sample_config: Config) -> Config:
    from pyappdist.targets import get_target

    return dataclasses.replace(
        sample_config, target=get_target("macos-aarch64"), format="dmg",
        launchers=(
            LauncherConfig(name="app", entry="pkg.mod:main", args="--fixed 'a b'"),
        ),
    )


def test_prebuilt_one_macos_writes_sidecar(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    import json

    config = _macos_config(sample_config)
    spec = config.launchers[0]
    layout = ImageLayout(image_dir=tmp_path / "image", target=config.target, minor="3.12")
    layout.image_dir.mkdir(parents=True)
    stub = tmp_path / "launcher-macos-universal"
    stub.write_bytes(b"\xcf\xfa\xed\xfe")
    monkeypatch.setattr(launcher_build, "macos_stub", lambda: stub)

    exe = launcher_build._prebuilt_one_macos(config, spec, layout, lambda m: None)

    assert exe == layout.image_dir / "app"
    assert exe.read_bytes() == stub.read_bytes()
    sidecar = json.loads(
        (layout.image_dir / "app.launcher.json").read_text(encoding="utf-8")
    )
    assert sidecar == {
        "pyrel": "../Resources/python/bin/python3",
        "bootstrap": spec.bootstrap,
        "args": ["--fixed", "a b"],
    }


def test_macos_source_build_removes_stale_sidecar(
    sample_config: Config, tmp_path: Path, monkeypatch
):
    """Switching prebuilt -> source must not leave a sidecar that would
    override the compiled-in config (the launcher prefers the sidecar)."""
    config = _macos_config(sample_config)
    spec = config.launchers[0]
    layout = ImageLayout(image_dir=tmp_path / "image", target=config.target, minor="3.12")
    layout.image_dir.mkdir(parents=True)
    stale = layout.image_dir / "app.launcher.json"
    stale.write_text("{}", encoding="utf-8")

    def fake_clang(cmd, *, cwd, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"macho")
        return _FakeProc(0)

    monkeypatch.setattr(launcher_build.subprocess, "run", fake_clang)
    launcher_build._build_one_macos(config, spec, layout, tmp_path / "wd", lambda m: None)
    assert not stale.exists()
