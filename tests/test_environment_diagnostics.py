import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application import (
    DiagnosticStatus,
    DiagnosticTargetType,
    EnvironmentDiagnosticItem,
    EnvironmentDiagnostics,
    EnvironmentDiagnosticsResult,
)


def _item(available=True):
    status = DiagnosticStatus.AVAILABLE if available else DiagnosticStatus.NOT_FOUND
    return EnvironmentDiagnosticItem(
        DiagnosticTargetType.PYTHON, "python", status, available, "message"
    )


def test_enums_and_dtos_are_frozen_slotted_and_validate_contract(tmp_path):
    assert DiagnosticTargetType.EXTERNAL_TOOL.value == "external_tool"
    assert DiagnosticStatus.NOT_CONFIGURED.value == "not_configured"
    item = _item()
    result = EnvironmentDiagnosticsResult((item,), True, 1, 0, "Test", "python.exe")
    for value in (item, result):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.PYTHON, "", DiagnosticStatus.AVAILABLE, True, "x")
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.PYTHON, "x" * 101, DiagnosticStatus.AVAILABLE, True, "x")
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.PYTHON, "x", DiagnosticStatus.AVAILABLE, True, "")
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.PYTHON, "x", DiagnosticStatus.AVAILABLE, True, "x" * 501)
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.PYTHON, "x", DiagnosticStatus.AVAILABLE, True, "x", version="x" * 201)
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.PYTHON, "x", DiagnosticStatus.NOT_FOUND, True, "x")
    with pytest.raises(ValueError):
        EnvironmentDiagnosticItem(DiagnosticTargetType.EXTERNAL_TOOL, "x", DiagnosticStatus.AVAILABLE, True, "x", Path("relative"))
    with pytest.raises(ValueError):
        EnvironmentDiagnosticsResult((_item(),) * 51, True, 51, 0, "x", "python")
    with pytest.raises(ValueError):
        EnvironmentDiagnosticsResult((item,), True, 0, 1, "x", "python")


def test_constructor_validates_tool_and_required_names():
    with pytest.raises(ValueError):
        EnvironmentDiagnostics(tool_names=("strings", "strings"))
    with pytest.raises(ValueError):
        EnvironmentDiagnostics(tool_names=("",))
    with pytest.raises(ValueError):
        EnvironmentDiagnostics(tool_names=("bad\0name",))
    with pytest.raises(ValueError):
        EnvironmentDiagnostics(tool_names=("custom",))
    with pytest.raises(ValueError):
        EnvironmentDiagnostics(required_names=("python", "python"))


def test_diagnostic_order_defaults_and_injected_tools(tmp_path):
    executable = tmp_path / "python.exe"
    executable.write_text("fixture", encoding="utf-8")
    common = {
        "python_executable": str(executable.resolve()),
        "python_version_info": SimpleNamespace(major=3, minor=14, micro=0),
        "import_module": lambda _name: SimpleNamespace(TkVersion=8.6),
        "getenv": lambda _name: None,
        "which": lambda _name: None,
        "platform_name": "Windows",
    }
    default = EnvironmentDiagnostics(**common).run()
    assert [item.name for item in default.items] == [
        "python", "tkinter", "openai_configuration", "strings", "file",
        "exiftool", "readelf", "objdump", "nm", "binwalk",
    ]
    injected = EnvironmentDiagnostics(tool_names=("nm", "strings"), **common).run()
    assert [item.name for item in injected.items] == [
        "python", "tkinter", "openai_configuration", "nm", "strings"
    ]


def test_python_diagnostic_available_version_and_no_full_version(tmp_path):
    executable = tmp_path / "python.exe"
    executable.write_text("fixture", encoding="utf-8")
    result = EnvironmentDiagnostics(
        tool_names=(),
        python_executable=str(executable.resolve()),
        python_version_info=SimpleNamespace(major=3, minor=13, micro=5),
        import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
        getenv=lambda _name: None,
        platform_name="Windows",
    ).run()
    python = result.items[0]
    assert python.available and python.version == "3.13.5"
    assert python.executable_path is None
    assert result.python_executable_name == "python.exe"
    assert str(tmp_path) not in repr(result)


@pytest.mark.parametrize(
    ("importer", "status"),
    [
        (lambda _name: SimpleNamespace(TkVersion=8.6), DiagnosticStatus.AVAILABLE),
        (lambda _name: (_ for _ in ()).throw(ImportError()), DiagnosticStatus.NOT_FOUND),
        (lambda _name: (_ for _ in ()).throw(RuntimeError("secret")), DiagnosticStatus.ERROR),
    ],
)
def test_tkinter_import_diagnostics_without_window_creation(tmp_path, importer, status):
    executable = tmp_path / "python.exe"
    executable.write_text("x", encoding="utf-8")
    result = EnvironmentDiagnostics(
        tool_names=(),
        python_executable=str(executable.resolve()),
        import_module=importer,
        getenv=lambda _name: None,
        platform_name="Windows",
    ).run()
    assert result.items[1].status is status
    assert "secret" not in result.items[1].message


@pytest.mark.parametrize(
    ("value", "status"),
    [("sk-secret", DiagnosticStatus.AVAILABLE), (None, DiagnosticStatus.NOT_CONFIGURED), ("  ", DiagnosticStatus.NOT_CONFIGURED)],
)
def test_openai_configuration_checks_presence_only(tmp_path, value, status):
    executable = tmp_path / "python.exe"
    executable.write_text("x", encoding="utf-8")
    result = EnvironmentDiagnostics(
        tool_names=(),
        python_executable=str(executable.resolve()),
        import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
        getenv=lambda name: value if name == "OPENAI_API_KEY" else None,
        platform_name="Windows",
    ).run()
    item = result.items[2]
    assert item.status is status
    assert "sk-secret" not in repr(result)
    if item.available:
        assert "接続確認は行っていません" in item.message


def test_external_tool_available_not_found_and_which_once(tmp_path):
    python = tmp_path / "python.exe"
    tool = tmp_path / "strings.exe"
    python.write_text("x", encoding="utf-8")
    tool.write_text("x", encoding="utf-8")
    calls = []

    def which(name):
        calls.append(name)
        return str(tool.resolve()) if name == "strings" else None

    result = EnvironmentDiagnostics(
        tool_names=("strings", "file"),
        python_executable=str(python.resolve()),
        import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
        getenv=lambda _name: None,
        which=which,
        platform_name="Windows",
    ).run()
    assert result.items[3].status is DiagnosticStatus.AVAILABLE
    assert result.items[3].executable_path == tool.resolve()
    assert result.items[4].status is DiagnosticStatus.NOT_FOUND
    assert calls == ["strings", "file"]


def test_external_tool_rejects_relative_missing_directory_symlink_and_non_executable(tmp_path):
    python = tmp_path / "python"
    python.write_text("x", encoding="utf-8")
    missing = tmp_path / "missing"
    directory = tmp_path / "directory"
    directory.mkdir()
    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        link = None
    non_exec = tmp_path / "non-exec"
    non_exec.write_text("x", encoding="utf-8")
    non_exec.chmod(0o600)
    paths = ["relative", str(missing.resolve()), str(directory.resolve())]
    expected = [DiagnosticStatus.INVALID_PATH] * 3
    if link is not None:
        paths.append(str(link.absolute()))
        expected.append(DiagnosticStatus.SYMLINK_REJECTED)
    paths.append(str(non_exec.resolve()))
    expected.append(DiagnosticStatus.NOT_EXECUTABLE)
    names = ("strings", "file", "exiftool", "readelf", "objdump")[: len(paths)]
    mapping = dict(zip(names, paths, strict=True))
    result = EnvironmentDiagnostics(
        tool_names=names,
        python_executable=str(python.resolve()),
        import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
        getenv=lambda _name: None,
        which=mapping.get,
        access=lambda path, _mode: path != non_exec,
        platform_name="Linux",
    ).run()
    assert [item.status for item in result.items[3:]] == expected


def test_required_defaults_ignore_optional_openai_and_tools(tmp_path):
    python = tmp_path / "python.exe"
    python.write_text("x", encoding="utf-8")
    kwargs = {
        "tool_names": ("strings",),
        "python_executable": str(python.resolve()),
        "import_module": lambda _name: SimpleNamespace(TkVersion=8.6),
        "getenv": lambda _name: None,
        "which": lambda _name: None,
        "platform_name": "Windows",
    }
    result = EnvironmentDiagnostics(**kwargs).run()
    assert result.all_required_available
    assert result.available_count == 2 and result.unavailable_count == 2
    required_openai = EnvironmentDiagnostics(
        required_names=("python", "tkinter", "openai_configuration"), **kwargs
    ).run()
    assert not required_openai.all_required_available


def test_item_error_continues_and_base_exceptions_propagate(tmp_path):
    python = tmp_path / "python.exe"
    python.write_text("x", encoding="utf-8")
    calls = []

    def which(name):
        calls.append(name)
        if name == "strings":
            raise RuntimeError("private error")

    diagnostics = EnvironmentDiagnostics(
        tool_names=("strings", "file"),
        python_executable=str(python.resolve()),
        import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
        getenv=lambda _name: None,
        which=which,
        platform_name="Windows",
    )
    result = diagnostics.run()
    assert result.items[3].status is DiagnosticStatus.ERROR
    assert result.items[4].status is DiagnosticStatus.NOT_FOUND
    assert "private error" not in result.items[3].message
    assert calls == ["strings", "file"]
    for error in (KeyboardInterrupt(), SystemExit()):
        with pytest.raises(type(error)):
            EnvironmentDiagnostics(
                tool_names=("strings",),
                python_executable=str(python.resolve()),
                import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
                getenv=lambda _name: None,
                which=lambda _name, error=error: (_ for _ in ()).throw(error),
                platform_name="Windows",
            ).run()


def test_diagnostics_are_deterministic_read_only_and_have_no_forbidden_operations(tmp_path):
    python = tmp_path / "python.exe"
    python.write_text("x", encoding="utf-8")
    environment = {"OPENAI_API_KEY": "secret"}
    diagnostics = EnvironmentDiagnostics(
        tool_names=(),
        python_executable=str(python.resolve()),
        import_module=lambda _name: SimpleNamespace(TkVersion=8.6),
        getenv=environment.get,
        platform_name="Windows",
    )
    assert diagnostics.run() == diagnostics.run()
    assert environment == {"OPENAI_API_KEY": "secret"}
    module = __import__("app.application.environment_diagnostics", fromlist=["*"])
    source = inspect.getsource(module).casefold()
    for forbidden in (
        "subprocess", "os.system", "socket", "urllib", "requests", "httpx",
        "thread", "asyncio", "multiprocessing", "sleep(", ".execute(",
        "externalprocessrunner", "challengeservice", "controller", "tk(",
        "write_text", "mkdir(", "environ[", "putenv", "openai.openai",
    ):
        assert forbidden not in source
