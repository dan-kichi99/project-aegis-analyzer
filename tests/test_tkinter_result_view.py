import importlib
import inspect
from dataclasses import replace

import pytest

from app.presentation import (
    AgentViewModel,
    ApplicationPresenter,
    ResultViewModel,
)


class FakeWidget:
    def __init__(self, _parent=None, **values):
        self.values = values
        self.items = []
        self.content = ""
        self.bindings = {}
        self.clipboard_calls = 0
        self.clipboard_content = None

    def pack(self, **_values):
        return None

    def configure(self, **values):
        self.values.update(values)

    def delete(self, *_values):
        self.items.clear()
        self.content = ""

    def insert(self, _position, value):
        if "state" in self.values:
            self.content += value
        else:
            self.items.append(value)

    def bind(self, event, callback):
        self.bindings[event] = callback

    def invoke(self):
        return self.values["command"]()

    def clipboard_clear(self):
        self.clipboard_calls += 1
        self.clipboard_content = None

    def clipboard_append(self, value):
        self.clipboard_content = value


def _patch_widgets(monkeypatch):
    result_module = importlib.import_module("app.gui.result_view")
    agent_module = importlib.import_module("app.gui.agent_result_view")
    for module in (result_module, agent_module):
        for name in ("Frame", "Label", "Text", "Listbox", "Button"):
            monkeypatch.setattr(module.tk, name, FakeWidget)
    return result_module, agent_module


def _result(**changes):
    value = ResultViewModel(
        False,
        "Rev",
        "解析回答",
        None,
        72,
        "解析理由",
        ("最初の手順", "次の手順"),
        None,
    )
    return replace(value, **changes)


def _agent(**changes):
    value = AgentViewModel(
        "rev",
        ("rev", "crypto"),
        "completed",
        81,
        ("証拠1", "証拠2"),
        ("FLAG{candidate}",),
        ("flag: A, B",),
        True,
    )
    return replace(value, **changes)


def test_import_is_safe_and_creates_no_root_or_mainloop():
    for name in ("app.gui.result_view", "app.gui.agent_result_view"):
        source = inspect.getsource(importlib.import_module(name))
        assert "tk.Tk(" not in source
        assert "mainloop(" not in source


def test_result_none_and_clear_remove_previous_values(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate="FLAG{old}", warning="候補の警告"))
    view.render(None)
    assert view.solved_label.values["text"] == "解析結果はまだありません"
    assert view.flag_candidate_label.values["text"] == "Flag候補：候補なし"
    assert view.warning_label.values["text"] == ""
    assert view.answer_text.content == ""
    assert view.reason_text.content == ""
    assert view.next_actions_list.items == []


def test_result_status_category_confidence_and_candidate_rules(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(solved=True, flag_candidate="FLAG{candidate}"))
    assert view.solved_label.values["text"] == "解決状態：解決済み"
    assert view.category_label.values["text"] == "カテゴリ：Rev"
    assert view.confidence_label.values["text"] == "信頼度：72%"
    assert view.flag_candidate_label.values["text"] == "Flag候補：FLAG{candidate}"
    assert "正解Flag" not in view.flag_candidate_label.values["text"]
    view.render(_result(confidence=None))
    assert view.solved_label.values["text"] == "解決状態：未解決"
    assert view.confidence_label.values["text"] == "信頼度：未設定"


def test_result_text_warning_and_actions_are_presented_without_interpretation(
    monkeypatch,
):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(warning="Flagは候補です。"))
    assert view.answer_text.content == "解析回答"
    assert view.reason_text.content == "解析理由"
    assert view.warning_label.values["text"] == "Flagは候補です。"
    assert view.next_actions_list.items == ["最初の手順", "次の手順"]
    assert view.answer_text.values["state"] == "disabled"
    assert view.reason_text.values["state"] == "disabled"


def test_copy_button_enabled_and_copies_flag_via_clipboard_api(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate="FLAG{copyme}"))
    assert view.copy_button.values["state"] == "normal"

    view.copy_button.invoke()

    assert view.frame.clipboard_calls == 1
    assert view.frame.clipboard_content == "FLAG{copyme}"
    assert view.copy_message_label.values["text"] == "コピーしました。"


def test_copy_button_disabled_and_no_clipboard_call_without_flag(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate=None))
    assert view.copy_button.values["state"] == "disabled"

    view.flag_candidate_label.bindings["<Double-Button-1>"](None)

    assert view.frame.clipboard_calls == 0
    assert view.copy_message_label.values["text"] == ""


def test_double_click_on_flag_label_copies_flag(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate="FLAG{double}"))

    view.flag_candidate_label.bindings["<Double-Button-1>"](None)

    assert view.frame.clipboard_calls == 1
    assert view.frame.clipboard_content == "FLAG{double}"
    assert view.copy_message_label.values["text"] == "コピーしました。"


def test_clear_removes_previous_flag_and_copy_message(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate="FLAG{old}"))
    view.copy_button.invoke()

    view.clear()

    assert view.flag_candidate_label.values["text"] == "Flag候補：候補なし"
    assert view.copy_button.values["state"] == "disabled"
    assert view.copy_message_label.values["text"] == ""
    view.flag_candidate_label.bindings["<Double-Button-1>"](None)
    assert view.frame.clipboard_calls == 1


def test_rerender_does_not_leak_previous_flag_or_copy_message(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate="FLAG{first}"))
    view.copy_button.invoke()

    view.render(_result(flag_candidate=None))

    assert view.flag_candidate_label.values["text"] == "Flag候補：候補なし"
    assert view.copy_button.values["state"] == "disabled"
    assert view.copy_message_label.values["text"] == ""
    view.flag_candidate_label.bindings["<Double-Button-1>"](None)
    assert view.frame.clipboard_calls == 1


def test_copy_does_not_swallow_callback_exceptions(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    view = result_module.AnalysisResultView(object())
    view.render(_result(flag_candidate="FLAG{boom}"))

    def _raise():
        raise RuntimeError("clipboard unavailable")

    monkeypatch.setattr(view.frame, "clipboard_clear", _raise)

    with pytest.raises(RuntimeError):
        view.copy_button.invoke()


def test_agent_none_and_clear_remove_previous_values(monkeypatch):
    _result_module, agent_module = _patch_widgets(monkeypatch)
    view = agent_module.AgentResultView(object())
    view.render(_agent())
    view.clear()
    assert view.primary_agent_label.values["text"] == "専門Agent結果はありません"
    assert view.flag_candidates_list.items == []
    assert view.evidence_list.items == []
    assert view.conflicts_list.items == []


def test_agent_fields_lists_order_and_fallback_are_displayed(monkeypatch):
    _result_module, agent_module = _patch_widgets(monkeypatch)
    view = agent_module.AgentResultView(object())
    view.render(_agent())
    assert view.primary_agent_label.values["text"] == "主担当Agent：rev"
    assert view.executed_agents_label.values["text"] == "実行Agent：rev、crypto"
    assert view.status_label.values["text"] == "状態：completed"
    assert view.confidence_label.values["text"] == "信頼度：81%"
    assert view.fallback_label.values["text"] == "fallback使用"
    assert view.flag_candidates_list.items == ["FLAG{candidate}"]
    assert view.evidence_list.items == ["証拠1", "証拠2"]
    assert view.conflicts_list.items == ["flag: A, B"]


def test_agent_unset_values_do_not_claim_a_correct_flag(monkeypatch):
    _result_module, agent_module = _patch_widgets(monkeypatch)
    view = agent_module.AgentResultView(object())
    view.render(
        _agent(
            primary_agent=None,
            confidence=None,
            flag_candidates=(),
            used_fallback=False,
        )
    )
    assert view.primary_agent_label.values["text"] == "主担当Agent：未設定"
    assert view.confidence_label.values["text"] == "信頼度：未設定"
    assert view.fallback_label.values["text"] == "fallbackなし"
    assert view.flag_candidates_list.items == ["候補なし"]
    assert "正解" not in inspect.getsource(agent_module.AgentResultView)


def test_panel_renders_both_views_and_does_not_change_state(monkeypatch):
    result_module, _agent_module = _patch_widgets(monkeypatch)
    state = replace(
        ApplicationPresenter().initial_state(), result=_result(), agent=_agent()
    )
    panel = result_module.AnalysisResultPanel(object())
    panel.render(state)
    assert panel.result_view.answer_text.content == "解析回答"
    assert panel.agent_view.evidence_list.items == ["証拠1", "証拠2"]
    assert state.result.answer == "解析回答"
    assert state.agent.evidence == ("証拠1", "証拠2")


def test_views_only_depend_on_application_view_models_and_have_no_actions():
    sources = "\n".join(
        inspect.getsource(importlib.import_module(name))
        for name in ("app.gui.result_view", "app.gui.agent_result_view")
    )
    for forbidden in (
        "JudgeResult",
        "AgentAggregateResult",
        "Controller",
        "ChallengeService",
        "subprocess",
        "thread",
        "asyncio",
        "sleep(",
        ".execute(",
        ".approve(",
        "stdout",
        "stderr",
        "api_key",
        "prompt",
    ):
        assert forbidden not in sources
