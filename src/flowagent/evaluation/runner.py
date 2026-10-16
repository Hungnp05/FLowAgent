import argparse
import hashlib
import json
import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import select

from flowagent.agent.llm import ModelSpec, build_chat_model, describe_llm_error, plan_model_chain
from flowagent.agent.llm_config import LlmConfig
from flowagent.agent.prompts import SYSTEM_PROMPT_TEMPLATE
from flowagent.agent.service import AgentReply, FlowAgent
from flowagent.agent.tools import PriorityPredictorFn, parse_optional_datetime
from flowagent.config import LlmProvider, get_settings
from flowagent.db import crud
from flowagent.db.models import Task
from flowagent.db.schemas import TaskCreate, TaskUpdate
from flowagent.db.session import IN_MEMORY_SQLITE_URL, create_db_engine, session_scope
from flowagent.errors import MissingApiKeyError
from flowagent.evaluation.cases import DEFAULT_CASES_PATH, EvalCase, SeedTask, load_cases
from flowagent.evaluation.checks import evaluate_case
from flowagent.evaluation.report import summarize_records
from flowagent.ml.predictor import DEFAULT_ARTIFACT_PATH, load_priority_predictor
from flowagent.planning.scheduler import WORKDAY_START

logger = logging.getLogger(__name__)

EVAL_NOW = datetime(2026, 10, 14, 10, 0)
RESULTS_DIR = Path("evals/results")
TRACKED_EVAL_PATHS = ("src", "evals/cases.jsonl")
DIRTY_SUFFIX = "-dirty"
THREAD_ID = "eval"
PAUSE_BETWEEN_CASES_SECONDS = 4.0
RETRY_WAIT_SECONDS = 30.0
MAX_ATTEMPTS = 3
SECONDS_PER_MINUTE = 60
DAILY_QUOTA_MARKERS = ("exceeded your current quota", "tokens per day", "requests per day")

AgentFactory = Callable[[Engine], FlowAgent]


@dataclass
class CaseRecord:
    id: str
    category: str
    utterance: str
    success: bool = False
    tool_selection_ok: bool = False
    passed_checks: int = 0
    total_checks: int = 0
    failed_checks: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    reply: str = ""
    latency_seconds: float = 0.0
    model_calls: int = 0
    total_tokens: int = 0
    model_name: str | None = None
    error: str | None = None


def seed_tasks(engine: Engine, tasks: list[SeedTask]) -> None:
    """Insert the case's starting tasks into a fresh database."""
    with session_scope(engine) as session:
        for seed in tasks:
            task = crud.create_task(
                session,
                TaskCreate(
                    title=seed.title,
                    priority=seed.priority,
                    deadline=parse_optional_datetime(seed.deadline),
                    planned_start=parse_optional_datetime(seed.planned_start, WORKDAY_START),
                    estimated_minutes=seed.estimated_minutes,
                ),
            )
            crud.update_task(session, task.id, TaskUpdate(status=seed.status))


def read_final_state(engine: Engine) -> tuple[list[Task], int]:
    """Return all tasks and the number of tasks that belong to a project."""
    with session_scope(engine) as session:
        tasks = list(session.exec(select(Task).order_by(Task.id)).all())
    return tasks, sum(task.project_id is not None for task in tasks)


def converse(agent: FlowAgent, utterance: str) -> tuple[AgentReply, list[AgentReply]]:
    """Send the utterance and approve any confirmation, returning the final and all replies."""
    replies = [agent.send(THREAD_ID, utterance)]
    if replies[-1].pending_confirmation is not None:
        replies.append(agent.resolve_confirmation(THREAD_ID, is_approved=True))
    return replies[-1], replies


def run_case_once(case: EvalCase, build_agent: AgentFactory) -> CaseRecord:
    """Run one case against a fresh in-memory database and score the outcome."""
    engine = create_db_engine(IN_MEMORY_SQLITE_URL)
    seed_tasks(engine, case.seed_tasks)
    started = time.perf_counter()
    final_reply, replies = converse(build_agent(engine), case.utterance)
    latency = time.perf_counter() - started
    tool_calls = [call for reply in replies for call in reply.tool_calls]
    tasks, project_task_count = read_final_state(engine)
    asked_confirmation = replies[0].pending_confirmation is not None
    outcome = evaluate_case(
        case, tool_calls, tasks, project_task_count, asked_confirmation, final_reply.text
    )
    return CaseRecord(
        id=case.id,
        category=case.category,
        utterance=case.utterance,
        success=outcome.is_success,
        tool_selection_ok=outcome.tool_selection_ok,
        passed_checks=outcome.passed_checks,
        total_checks=len(outcome.checks),
        failed_checks=[f"{c.name}: {c.detail}" for c in outcome.checks if not c.passed],
        tool_calls=[{"name": call.name, "args": call.args} for call in tool_calls],
        reply=final_reply.text,
        latency_seconds=round(latency, 2),
        model_calls=sum(reply.model_calls for reply in replies),
        total_tokens=sum(reply.total_tokens for reply in replies),
        model_name=final_reply.model_name,
    )


def run_case(case: EvalCase, build_agent: AgentFactory) -> CaseRecord:
    """Run a case, retrying provider failures such as rate limits before recording an error."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return run_case_once(case, build_agent)
        except Exception as error:
            logger.warning("%s attempt %d failed: %s", case.id, attempt, describe_llm_error(error))
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_WAIT_SECONDS)
            last_error = f"{type(error).__name__}: {error}"[:300]
    return CaseRecord(case.id, case.category, case.utterance, error=last_error)


def build_eval_agent_factory(
    provider: LlmProvider | None, model_name: str | None
) -> tuple[AgentFactory, str]:
    """Create agents on a chosen provider/model (default: primary) with the fixed eval clock."""
    settings = get_settings()
    config = LlmConfig(
        llm_provider=settings.llm_provider,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
        gemini_fallback_model=settings.gemini_fallback_model,
        groq_api_key=settings.groq_api_key,
        groq_model=settings.groq_model,
    )
    chain = plan_model_chain(config)
    primary_spec = next((spec for spec in chain if spec.provider == provider), None) or chain[0]
    if provider is not None and primary_spec.provider != provider:
        raise MissingApiKeyError(f"Chưa có API key cho {provider} trong .env.")
    if model_name:
        primary_spec = ModelSpec(primary_spec.provider, model_name, primary_spec.api_key)
    chat_model = build_chat_model(primary_spec, settings)
    predictor: PriorityPredictorFn | None = None
    if DEFAULT_ARTIFACT_PATH.exists():
        predictor = load_priority_predictor().predict

    def build_agent(engine: Engine) -> FlowAgent:
        """Build a fresh agent bound to one case's database."""
        return FlowAgent(chat_model, engine, clock=lambda: EVAL_NOW, predict_priority=predictor)

    return build_agent, primary_spec.label


def load_previous_records(output_path: Path, model_label: str) -> dict[str, dict]:
    """Return every record from an earlier run of the same model, keyed by case id."""
    if not output_path.exists():
        return {}
    previous = json.loads(output_path.read_text(encoding="utf-8"))
    if previous["model"] != model_label:
        raise ValueError(f"{output_path} was produced by {previous['model']}, not {model_label}")
    return {record["id"]: record for record in previous["cases"]}


def pause_after_case(record: dict, tokens_per_minute: int | None) -> float:
    """Return how long to wait so the run stays under a tokens-per-minute rate limit."""
    if not tokens_per_minute:
        return PAUSE_BETWEEN_CASES_SECONDS
    seconds_for_tokens = record["total_tokens"] * SECONDS_PER_MINUTE / tokens_per_minute
    return max(PAUSE_BETWEEN_CASES_SECONDS, seconds_for_tokens)


def is_daily_quota_exhausted(record: dict) -> bool:
    """Detect the provider's daily quota error, after which further cases cannot succeed."""
    error = record["error"] or ""
    return any(marker in error for marker in DAILY_QUOTA_MARKERS)


def ordered_records(all_cases: list[EvalCase], records_by_id: dict[str, dict]) -> list[dict]:
    """List the known records in case-file order."""
    return [records_by_id[case.id] for case in all_cases if case.id in records_by_id]


def save_results(output_path: Path, label: str, model_label: str, records: list[dict]) -> dict:
    """Write all records collected so far plus their summary, so progress survives outages."""
    result = {
        "label": label,
        "model": model_label,
        "git_commit": current_git_commit(),
        "prompt_sha": hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode()).hexdigest()[:12],
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summarize_records(records),
        "cases": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_git(*args: str) -> str:
    """Run a git command and return its trimmed output."""
    completed = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def current_git_commit() -> str:
    """Return the short commit hash, marked '-dirty' when agent code or cases are uncommitted."""
    try:
        commit = run_git("rev-parse", "--short", "HEAD")
        uncommitted = run_git("status", "--porcelain", "--", *TRACKED_EVAL_PATHS)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit}{DIRTY_SUFFIX}" if uncommitted else commit


def main() -> None:
    """Run the evaluation cases, saving after every case, and optionally resume a stopped run."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Evaluate the FlowAgent agent on labelled cases.")
    parser.add_argument("--label", required=True, help="Version label, e.g. v1")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--only", help="Run only cases whose id starts with one of these comma-separated prefixes"
    )
    parser.add_argument("--provider", choices=["gemini", "groq"], help="Provider to evaluate")
    parser.add_argument("--model", help="Override the model name of that provider")
    parser.add_argument("--resume", action="store_true", help="Skip cases already finished")
    parser.add_argument(
        "--tokens-per-minute",
        type=int,
        help="Provider token rate limit; paces cases to stay under it",
    )
    args = parser.parse_args()
    all_cases = load_cases(args.cases)
    prefixes = tuple(args.only.split(",")) if args.only else ("",)
    cases = [case for case in all_cases if case.id.startswith(prefixes)]
    build_agent, model_label = build_eval_agent_factory(args.provider, args.model)
    output_path = RESULTS_DIR / f"{args.label}.json"
    records_by_id = load_previous_records(output_path, model_label) if args.resume else {}
    for index, case in enumerate(cases, start=1):
        previous = records_by_id.get(case.id)
        if previous is not None and previous["error"] is None:
            continue
        record = asdict(run_case(case, build_agent))
        records_by_id[case.id] = record
        save_results(
            output_path, args.label, model_label, ordered_records(all_cases, records_by_id)
        )
        logger.info(
            "[%d/%d] %s success=%s %s",
            index,
            len(cases),
            case.id,
            record["success"],
            record["failed_checks"] or record["error"] or "",
        )
        if is_daily_quota_exhausted(record):
            logger.error("Daily quota exhausted; stopping. Re-run later with --resume.")
            break
        time.sleep(pause_after_case(record, args.tokens_per_minute))
    records = ordered_records(all_cases, records_by_id)
    result = save_results(output_path, args.label, model_label, records)
    logger.info("Saved %s: %s", output_path, json.dumps(result["summary"]["overall"]))


if __name__ == "__main__":
    main()
