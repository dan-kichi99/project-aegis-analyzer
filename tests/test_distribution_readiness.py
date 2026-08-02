from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_windows_scripts_use_only_repository_venv_and_safe_module_entrypoints():
    expected = {
        "scripts/run_cli.ps1": "app.main",
        "scripts/run_gui.ps1": "app.gui_main",
        "scripts/check_environment.ps1": "app.diagnostics_main",
    }
    for path, module in expected.items():
        text = _text(path)
        assert '.venv\\Scripts\\python.exe' in text
        assert f"-m {module}" in text
        assert "@args" in text or module == "app.diagnostics_main"
        assert "pip install" not in text
        assert "ExecutionPolicy" not in text
        assert "OPENAI_API_KEY" not in text
        assert "C:\\Users\\" not in text
        assert "OneDrive" not in text


def test_env_example_contains_only_empty_required_secret_setting():
    text = _text(".env.example")
    assignments = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert assignments == ["OPENAI_API_KEY="]
    assert "sk-" not in text
    assert "C:\\Users\\" not in text


def test_gitignore_excludes_private_and_generated_files():
    text = _text(".gitignore")
    for value in (".env", ".venv/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "build/", "dist/"):
        assert value in text


def test_readme_documents_real_entrypoints_and_safety_constraints():
    text = _text("README.md")
    for value in (
        "python.exe -m app.main",
        "python.exe -m app.gui_main",
        "python.exe -m app.diagnostics_main",
        "run_cli.ps1",
        "run_gui.ps1",
        "check_environment.ps1",
        "完全なサンドボックスではありません",
        "Flagは候補",
        "強制終了しません",
        "外部Tool",
        "OPENAI_API_KEY",
    ):
        assert value in text


def test_distribution_text_files_contain_no_known_secrets_or_personal_paths():
    paths = (
        "README.md", ".env.example", "scripts/run_cli.ps1",
        "scripts/run_gui.ps1", "scripts/check_environment.ps1",
    )
    forbidden = (
        "OPENAI_API_KEY_TEST_SECRET", "AWS_SECRET_ACCESS_KEY_TEST_SECRET",
        "GITHUB_TOKEN_TEST_SECRET", "C:\\Users\\danki", "OneDrive",
        "/home/secret-user",
    )
    combined = "\n".join(_text(path) for path in paths)
    assert all(value not in combined for value in forbidden)


def test_requirements_adds_no_packager_network_or_gui_dependency():
    requirements = {
        line.strip().casefold()
        for line in _text("requirements.txt").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "pyinstaller" not in requirements
    assert "requests" not in requirements
    assert "tkinter" not in requirements
    assert "tiktoken" not in requirements
