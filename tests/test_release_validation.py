import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_changelog_and_checklist_are_complete():
    assert _text("VERSION") == "Project Aegis\nv1.0.0\n"
    changelog = _text("CHANGELOG.md")
    assert "v1.0.0" in changelog
    assert "Initial Stable Release" in changelog
    checklist = _text("RELEASE_CHECKLIST.md")
    for item in (
        "pytest成功",
        "Ruff成功",
        "git diff --check成功",
        "GUI起動",
        "CLI起動",
        "Diagnostics起動",
        "README確認",
        ".env.example",
        ".gitignore",
    ):
        assert item in checklist


def test_release_entrypoints_are_import_safe_and_publish_main_functions():
    for module_name in ("app.main", "app.gui_main", "app.diagnostics_main"):
        module = importlib.import_module(module_name)
        assert callable(module.main)


def test_cli_source_does_not_import_or_create_gui():
    source = _text("app/main.py")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(name.startswith(("tkinter", "app.gui")) for name in imported)
    assert "mainloop(" not in source
    assert "Tk(" not in source


def test_gui_entrypoint_creates_root_and_mainloop_only_inside_functions():
    source = _text("app/gui_main.py")
    tree = ast.parse(source)
    top_level_calls = [
        node
        for statement in tree.body
        for node in ast.walk(statement)
        if not isinstance(statement, (ast.FunctionDef, ast.ClassDef))
        and isinstance(node, ast.Call)
    ]
    assert not any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr in {"Tk", "mainloop"}
        for call in top_level_calls
    )
    assert "root.mainloop()" in source


def test_diagnostics_entrypoint_displays_no_paths_or_secret_values():
    source = _text("app/diagnostics_main.py")
    assert "executable_path" not in source
    assert "OPENAI_API_KEY" not in source
    assert "traceback" not in source.casefold()
    assert "stdout" not in source.casefold()
    assert "stderr" not in source.casefold()


def test_release_documents_cover_setup_commands_and_safety_warnings():
    readme = _text("README.md")
    for required in (
        "py -3 -m venv .venv",
        "pip install -r requirements.txt",
        "OPENAI_API_KEY",
        "python.exe -m app.main",
        "python.exe -m app.gui_main",
        "python.exe -m app.diagnostics_main",
        "python.exe -m pytest -q",
        "python.exe -m ruff check app tests",
        "完全なサンドボックスではありません",
        "Flagは候補",
    ):
        assert required in readme


def test_release_files_contain_no_test_secrets_or_personal_paths():
    paths = (
        "VERSION",
        "CHANGELOG.md",
        "RELEASE_CHECKLIST.md",
        "README.md",
        ".env.example",
    )
    forbidden = (
        "OPENAI_API_KEY_TEST_SECRET",
        "AWS_SECRET_ACCESS_KEY_TEST_SECRET",
        "GITHUB_TOKEN_TEST_SECRET",
        "C:\\Users\\danki",
        "OneDrive",
        "/home/secret-user",
    )
    content = "\n".join(_text(path) for path in paths)
    assert all(secret not in content for secret in forbidden)


def test_runtime_source_has_no_shell_true_eval_exec_or_thread_kill():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "app").rglob("*.py"))
    )
    forbidden = ("shell=True", "shell = True", "Thread.kill", "os.system(")
    assert all(value not in source for value in forbidden)
    tree_nodes = [
        node
        for path in sorted((ROOT / "app").rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"eval", "exec"}
        for node in tree_nodes
    )
