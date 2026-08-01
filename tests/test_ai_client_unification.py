import inspect
from pathlib import Path

import app.main
from app.client.base_client import BaseAIClient
from app.client.openai_client import OpenAIClient
from app.controller.controller import Controller


class FakeAIClient(BaseAIClient):
    def generate(self, prompt: str) -> str:
        return f"response for {prompt}"


class FakeAnalyzer:
    def analyze(self, question: str) -> str:
        return "Unknown"


class FakeKnowledgeRetriever:
    def retrieve(self, category: str, question: str) -> list[str]:
        return []


class FakePromptManager:
    def build(
        self,
        question: str,
        category: str,
        knowledge: list[str],
    ) -> str:
        return question


class FakeJudge:
    def evaluate(self, category: str, answer: str) -> str:
        return answer


def test_controller_uses_official_base_ai_client_type():
    annotation = inspect.signature(Controller.__init__).parameters[
        "ai_client"
    ].annotation

    assert annotation is BaseAIClient


def test_legacy_ai_imports_are_absent_from_python_sources():
    legacy_package = ("app" + ".ai").encode()
    project_root = Path(__file__).resolve().parents[1]

    for source_root in (project_root / "app", project_root / "tests"):
        for source_file in source_root.rglob("*.py"):
            assert legacy_package not in source_file.read_bytes()


def test_legacy_ai_client_source_files_are_removed():
    legacy_dir = Path(__file__).resolve().parents[1] / "app" / "ai"

    assert not (legacy_dir / "base.py").exists()
    assert not (legacy_dir / "openai_client.py").exists()
    assert not (legacy_dir / "__init__.py").exists()


def test_official_openai_client_inherits_official_base_client():
    assert issubclass(OpenAIClient, BaseAIClient)


def test_fake_ai_client_runs_through_controller_process():
    controller = Controller(
        analyzer=FakeAnalyzer(),  # type: ignore[arg-type]
        knowledge_retriever=FakeKnowledgeRetriever(),  # type: ignore[arg-type]
        prompt_manager=FakePromptManager(),  # type: ignore[arg-type]
        ai_client=FakeAIClient(),
        judge=FakeJudge(),  # type: ignore[arg-type]
    )

    assert controller.process("test question") == "response for test question"


def test_main_uses_official_openai_client():
    assert app.main.OpenAIClient is OpenAIClient
