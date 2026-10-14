from datetime import datetime

from langchain_core.messages import AIMessage
from sqlalchemy import Engine

from flowagent.agent.service import FlowAgent, ToolCallRecord
from flowagent.db.models import Priority, Task, TaskStatus
from flowagent.evaluation.cases import EvalCase
from flowagent.evaluation.checks import evaluate_case, fold_text, is_tool_selection_correct
from flowagent.evaluation.report import summarize_records
from flowagent.evaluation.runner import (
    is_daily_quota_exhausted,
    ordered_records,
    pause_after_case,
    run_case_once,
)
from tests.conftest import fixed_clock
from tests.test_agent_service import ScriptedChatModel, tool_call_message

CREATE_CASE = EvalCase.model_validate(
    {
        "id": "create-x",
        "category": "create",
        "utterance": "Thêm việc nộp báo cáo vào thứ 6 tuần sau, ưu tiên cao",
        "expect": {
            "tools": ["create_task"],
            "tasks": [{"match": ["bao cao"], "deadline": "2026-10-23 23:59", "priority": "high"}],
            "task_count": 1,
        },
    }
)


def make_task(
    title: str, deadline: datetime | None = None, priority: Priority = Priority.MEDIUM
) -> Task:
    """Build an unsaved task for scoring tests."""
    return Task(id=1, title=title, deadline=deadline, priority=priority, status=TaskStatus.TODO)


def test_fold_text_removes_vietnamese_accents() -> None:
    """Accents, đ and case are ignored when matching titles."""
    assert fold_text("Nộp BÁO CÁO đúng hạn") == "nop bao cao dung han"


def test_tool_selection_rejects_unexpected_mutation() -> None:
    """Calling a state-changing tool the case did not expect fails tool selection."""
    calls = [ToolCallRecord("create_task", {}), ToolCallRecord("delete_task", {})]
    assert not is_tool_selection_correct(CREATE_CASE, calls)


def test_tool_selection_allows_read_only_lookups() -> None:
    """Extra read-only calls such as list_tasks are allowed."""
    calls = [ToolCallRecord("list_tasks", {}), ToolCallRecord("create_task", {})]
    assert is_tool_selection_correct(CREATE_CASE, calls)


def test_evaluate_case_success_and_field_failure() -> None:
    """Matching fields succeed; a wrong deadline is reported as a failed check."""
    calls = [ToolCallRecord("create_task", {})]
    right = make_task("Nộp báo cáo", datetime(2026, 10, 23, 23, 59), Priority.HIGH)
    wrong = make_task("Nộp báo cáo", datetime(2026, 10, 16, 23, 59), Priority.HIGH)
    assert evaluate_case(CREATE_CASE, calls, [right], 0, False, "").is_success
    outcome = evaluate_case(CREATE_CASE, calls, [wrong], 0, False, "")
    assert not outcome.is_success
    assert [check.name for check in outcome.checks if not check.passed] == ["bao cao.deadline"]


def test_run_case_once_scores_a_scripted_agent(engine: Engine) -> None:
    """The runner seeds a database, drives the agent and scores the final state."""
    replies = [
        tool_call_message(
            "create_task",
            {"title": "Nộp báo cáo", "deadline": "2026-10-23 23:59", "priority": "high"},
        ),
        AIMessage("Đã thêm."),
    ]

    def build_agent(case_engine: Engine) -> FlowAgent:
        """Build an agent that plays back the scripted replies."""
        return FlowAgent(ScriptedChatModel(messages=iter(replies)), case_engine, clock=fixed_clock)

    record = run_case_once(CREATE_CASE, build_agent)
    assert record.success
    assert record.tool_calls[0]["name"] == "create_task"


def test_summarize_records_computes_rates() -> None:
    """Summary rates are averaged over cases and checks."""
    records = [
        {
            "category": "a",
            "success": True,
            "tool_selection_ok": True,
            "passed_checks": 2,
            "total_checks": 2,
            "error": None,
            "latency_seconds": 1.0,
            "model_calls": 2,
            "total_tokens": 100,
        },
        {
            "category": "a",
            "success": False,
            "tool_selection_ok": True,
            "passed_checks": 1,
            "total_checks": 2,
            "error": None,
            "latency_seconds": 3.0,
            "model_calls": 2,
            "total_tokens": 300,
        },
    ]
    overall = summarize_records(records)["overall"]
    assert overall["success_rate"] == 0.5
    assert overall["check_accuracy"] == 0.75
    assert overall["mean_latency_seconds"] == 2.0


def test_ordered_records_merges_partial_runs_in_case_order() -> None:
    """Records from earlier runs are kept and listed in case-file order."""
    other_case = CREATE_CASE.model_copy(update={"id": "create-y"})
    records = {"create-y": {"id": "create-y"}, "create-x": {"id": "create-x"}}
    assert [r["id"] for r in ordered_records([CREATE_CASE, other_case], records)] == [
        "create-x",
        "create-y",
    ]


def test_daily_quota_error_is_detected() -> None:
    """Only the daily quota error stops a run; other errors do not."""
    assert is_daily_quota_exhausted({"error": "429 ... You exceeded your current quota, ..."})
    assert is_daily_quota_exhausted({"error": "Rate limit reached ... on tokens per day (TPD)"})
    assert not is_daily_quota_exhausted({"error": "503 UNAVAILABLE"})
    assert not is_daily_quota_exhausted({"error": None})


def test_pause_after_case_respects_token_rate_limit() -> None:
    """A case using 4000 tokens under an 8000 tokens/minute limit waits 30 seconds."""
    assert pause_after_case({"total_tokens": 4000}, tokens_per_minute=8000) == 30
    assert pause_after_case({"total_tokens": 10}, tokens_per_minute=8000) == 4.0
    assert pause_after_case({"total_tokens": 4000}, tokens_per_minute=None) == 4.0
