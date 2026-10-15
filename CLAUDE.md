# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

FlowAgent is a solo university capstone project (course: *Phát triển hệ thống thông minh*, topic: "AI Agent cho quản lý công việc"), also intended as a CV portfolio piece. **Hard deadline: 2026-10-30.** The user writes in Vietnamese; reply in Vietnamese. The user knows intermediate Python and does not yet know React.

Built so far (2026-10-14): DB layer, scheduler, agent with 17 tools (8 task tools, 4 calendar-event tools, 5 workflow tools: meeting notes → tasks, reschedule, schedule check, progress report, remember fact), Streamlit UI (chat with persistent history and long-term memory, Kanban, calendar, Gantt, report & export, API settings with a PIN), model fallback, the ML priority model, tests and CI. Agent evaluation harness (`evaluation/`, 116 cases: the original 102 plus 14 for the workflow tools) is in place. Still to do: improvement rounds (v2, v3), deployment, report.

## Course documents (`documentation/`)

- `DANH SÁCH CHỦ ĐỀ BÀI TẬP LỚN.docx`: list of course topics.
- `Project_Action Plan.docx` and `Project_Work Breakdown Structure.xlsx`: templates to fill in. The WBS uses week/day columns with Done / In-progress / Delayed status.
- `Project_Final Report.docx`: report template. It is ML-shaped (Data Acquisition, Training Methodology, EDA, Modeling, UI, Testing & Improvements). The project deliberately includes a trained ML model and a measurable agent eval so that every section has real content.
- Grading: Idea 10, Application 30, Result 30, Project Management 10, Presentation & Report 20.

## Agreed scope and stack (phase 1, until 2026-10-30)

- **All Python.** UI is **Streamlit**. React/Next.js and a FastAPI layer are deferred to phase 2 (after the deadline, for the CV). Do not introduce them earlier.
- **LLM: free tiers only.** Google Gemini (Flash family) is primary and Groq is the fallback. Both are accessed through LangChain chat-model wrappers, so the provider is a config switch. Throttle requests and cache results in evals because of free-tier rate limits. Keys live in `.env` (with a committed `.env.example`).
- **Agent:** `langchain.agents.create_agent` (LangChain 1.x on LangGraph) with middleware, plus LangGraph `interrupt` for human-in-the-loop confirmation. `langgraph.prebuilt.create_react_agent` is deprecated; do not use it.
- **DB: SQLite via SQLModel.** Switching to Postgres (Neon or Supabase) must only require changing the DB URL.
- **ML:** a priority classifier trained on about 36k resolved Apache Jira issues collected through the public REST API (Kaggle needs a login, so it was not used). The notebook compares a majority baseline, TF-IDF + LR, and multilingual sentence embeddings (fastembed `paraphrase-multilingual-MiniLM-L12-v2`, ONNX, no torch) + LR. TF-IDF is best on the English test set (macro-F1 0.41), but only the embedding model transfers to Vietnamese. Production uses embeddings + LR, trained on Apache plus 603 Gemini-generated Vietnamese tasks (`datasets/vietnamese_tasks_synthetic.csv`) with source-balanced sample weights. 48 of the 603 synthetic labels were corrected after a cross-validation-guided review against the generation rubric; the log is in `datasets/vietnamese_tasks_synthetic_relabels.csv`. This raised the Vietnamese macro-F1 from 0.29 to 0.70 and the personal tasks from 0.19 to 0.69, with Apache unchanged at 0.31. The saved artifact also carries a confidence threshold (0.55), chosen on a held-out 20% of the synthetic data. `PriorityPrediction.is_confident` is False below it, and `suggest_priority` then falls back to medium. `datasets/vietnamese_tasks_labeled.csv` (64 hand-labelled rows) is evaluation-only: never train or tune on it. `synthetic_tasks.filter_tasks` drops synthetic rows with cosine ≥ 0.75 to it.
- **Deploy:** Streamlit Community Cloud. CI with GitHub Actions running pytest and ruff.
- Out of scope for phase 1: multi-user auth, Google Calendar/Notion/Trello API sync, vector-DB memory, background reminder workers, sending email. Their lightweight stand-ins are in place: `.ics` and `.csv` export (`exports.py`), a `mailto:` draft of the progress report, and `MemoryNote` facts injected into the prompt.

## Architecture

```
src/flowagent/        core package, UI-agnostic (installed editable via requirements.txt)
  config.py           pydantic-settings, reads .env
  clock.py            now_local(): naive datetime in the configured timezone
  errors.py           FlowAgentError hierarchy
  db/                 models (Task, Project), schemas (TaskCreate/Update/Filter), session, crud
  planning/           scheduler.py: pure ranking (rank_tasks_for_today), busy-aware timeline (build_timeline,
                      plan_within_deadline), reschedule selection; calendar.py: recurrence expansion,
                      task→calendar entries, lanes, busy periods; alerts.py: conflicts and deadline risks;
                      progress.py: daily/weekly progress report
  schedule_queries.py session-level helpers shared by tools and UI (calendar entries, busy periods, conflicts)
  exports.py          .ics calendar and .csv task export (pure)
  agent/              tools.py (12 task/event tools), workflow_tools.py (5 workflow tools), toolset.py (ALL_TOOLS),
                      service.py (FlowAgent), factory.py, llm.py, llm_config.py, prompts.py, formatting.py
  security/           pin.py (scrypt hashing), pin_guard.py (unlock + lockout), secret_box.py (Fernet)
  ml/                 jira_collection (CLI), synthetic_tasks (CLI), text_cleaning, labels, embeddings, training, predictor, train_priority_model (CLI)
app/streamlit_app.py  entry point using st.navigation; pages live in app/views/ (chat, board, calendar_page + calendar_views + calendar_widgets, gantt, report, settings, alerts, shared)
tests/                pytest; conftest provides an in-memory engine, FIXED_NOW clock and tool_config
notebooks/priority_model.ipynb  EDA + model comparison; writes docs/figures/ml_*.png and docs/ml_results.json
datasets/             committed: vietnamese_tasks_labeled.csv (eval only), vietnamese_tasks_synthetic.csv (+ .json generation/filter metadata)
models/               committed trained artifact priority_classifier.joblib (+ metrics json)
evals/                cases.jsonl (116 cases, appended by scripts, edit carefully) and results/<label>.json plus summary.md
  (the harness code lives in src/flowagent/evaluation/: cases, checks, runner, report)
```

How a chat turn flows: the UI calls `FlowAgent.send(thread_id, text)`. `service.build_agent_graph` builds a `create_agent` graph with three middlewares: `dynamic_prompt` (injects the current time on every model call), `ToolErrorMiddleware(format_tool_error)` (returns `FlowAgentError` messages to the model; other exceptions propagate), and `ModelCallLimitMiddleware` (stops loops), plus `ModelFallbackMiddleware` when there are backup models. The reply is read back from `graph.get_state()`. If `snapshot.interrupts` is set, the reply carries `pending_confirmation`, and the UI later calls `resolve_confirmation(thread_id, is_approved)`, which resumes with `Command(resume=...)`.

Non-obvious mechanics:
- **Tools get their dependencies from the run config.** `ToolDeps(engine, clock)` is placed in `config["configurable"][DEPS_CONFIG_KEY]`, and tools take a `config: RunnableConfig` parameter that LangChain hides from the LLM schema. Tests call tools directly with `tool.invoke(args, tool_config)`.
- **Datetimes are naive local time (`Asia/Ho_Chi_Minh`) everywhere.** SQLModel fields must be typed `pydantic.NaiveDatetime`: the current SQLModel rejects naive `datetime` fields unless they are annotated this way.
- **Tool date arguments are strings** in `YYYY-MM-DD HH:MM` format, parsed by `parse_local_datetime`. A bare date means 23:59 for `deadline` and 09:00 (`WORKDAY_START`) for `planned_start`. The rule that the start must not be after the deadline is enforced only in `crud.ensure_start_before_deadline` (raises `InvalidScheduleError`), so the form and the agent share it.
- **`delete_task` calls `interrupt()` outside any DB session.** When the run resumes, the tool body re-runs from the top, so code before the interrupt must stay read-only.
- **Conversation memory is a `SqliteSaver`** (`langgraph-checkpoint-sqlite`) on `data/chat_history.db` (`CHAT_HISTORY_PATH`), created once by `st.cache_resource`. The current `thread_id` is stored in `AppSetting` (`SettingKey.CHAT_THREAD_ID`), so every tab shares one conversation and it survives restarts; "Cuộc trò chuyện mới" just writes a new id. The chat page renders `FlowAgent.history(thread_id)` and `FlowAgent.pending_confirmation(thread_id)` from the checkpoint instead of keeping its own copy. Tests and the eval still use `InMemorySaver`.
- **Long-term memory is the `MemoryNote` table.** `remember_fact` adds a note (accent-insensitive duplicates are reused); `FlowAgent._read_memories` feeds every note into the system prompt on each model call. Notes are deleted only from the chat sidebar, so there is no destructive memory tool.
- **Every confirmation goes through `interrupt()` with `{"action", "summary"}`.** Actions: `delete_task`, `delete_event`, `create_tasks_from_notes` (preview before bulk creation) and `reschedule_tasks` (bulk update). The chat page maps the action to its question and button label (`CONFIRMATION_TEXTS`). Code before the interrupt must stay read-only because the tool body re-runs on resume.
- **Scheduling around busy time.** `build_timeline` fills each day's window (09:00 + `daily_work_minutes`) minus busy periods, splitting a step across gaps; with no busy periods it matches the old behaviour. Busy periods are timed event occurrences plus work blocks of other open tasks over 60 days (`read_busy_periods`); all-day events and deadline markers never block time. `plan_within_deadline` tries 4, 5, 6, 7, then 8 hours a day and reports when even 8 hours miss `finish_by`. `reschedule_tasks` moves a project's open tasks (in their current order), or every overdue / missed-start task ordered by `score_task`, and sets each task's `planned_start` and `deadline` to its new slot.
- **Create/update tools append clash warnings.** `create_task`, `update_task`, `create_event` and `update_event` add "⚠️ Trùng giờ" lines from `read_conflicts_for` over the next 14 days; the prompt tells the model to relay them.
- **LLM configuration has two layers.** `load_llm_config` lays values saved on the "Cài đặt API" page (the `AppSetting` table, keyed by `SettingKey`, whose values match the `LlmConfig` and `Settings` field names) over the `.env` defaults. A blank field deletes the row, so `.env` applies again. API keys are Fernet-encrypted with `data/secret.key`. If that file is lost (for example on an ephemeral host), decryption raises `SecretDecryptionError` and the user must re-enter the keys.
- **Model fallback order comes from `plan_model_chain`:** the primary provider's model, then the Gemini fallback model, then the other provider. Providers without a key are skipped. `factory.create_flow_agent` builds the primary model and its fallbacks. The UI caches the agent per config (`build_agent_for_config(hash(config), _config)`) and shares one `InMemorySaver`, so chat history survives a settings change.
- **The PIN guard returns `UnlockResult` instead of raising.** A raised exception would make `session_scope` roll back the failed-attempt counter. Lockout state is stored in `AppSetting`. Unlocking is per browser session (`st.session_state`). A forgotten PIN is reset only from the terminal (`flowagent-reset-pin`, defined in `security/reset_pin.py`). It deletes the PIN, the lockout state and the saved API keys, and keeps tasks and model names. There is deliberately no reset button in the web UI.
- **Gemini model names get retired often.** On 2026-10-14, `gemini-2.5-flash` returned 404 for new keys, and the full Flash models returned 503 or 504 under load. `gemini-3.1-flash-lite` was fast and reliable for tool calling, and it honours `temperature=0` (`gemini-3.5-flash-lite` ignores it). List the available models with `google.genai.Client(api_key=...).models.list()` before changing the default. `describe_llm_error` maps provider failures to hints shown in the UI.
- **The priority model is optional at runtime.** `ToolDeps.predict_priority` is a `Callable[[str], PriorityPrediction] | None`. When `create_task` gets no priority, it calls the model through `suggest_priority`, which falls back to medium if the model is missing or fails. The UI loads the model via `get_priority_predictor()`, which returns None if `models/priority_classifier.joblib` is absent. `PriorityPrediction` lives in `ml/labels.py` so the agent can import it without loading fastembed. The first prediction downloads the encoder (about 220 MB) into `data/models/`.
- **ML data pipeline:** raw CSV in `data/raw/`, cached embeddings in `data/processed/` (validated by a text fingerprint), all gitignored. Rebuild them with `flowagent-collect-jira`, then `flowagent-train-priority` (it reuses the embedding cache).
- **The agent evaluation is state-based.** Each case seeds a fresh in-memory DB, runs the real agent with a fixed clock (`EVAL_NOW` = Wed 2026-10-14 10:00, so "thứ 6 tuần sau" = 2026-10-23), auto-approves delete confirmations, then checks the final tasks. Tasks are matched by accent-folded title keywords. Tool selection passes when every expected tool was called and no unexpected *mutating* tool was; read-only lookups are always allowed. The eval runs on the primary model only (no fallback) and retries provider errors up to 3 times with a 30 s wait. Each result records the git commit and prompt hash, so commit before an eval run you want to report.
- **The calendar page mirrors the MobiAssistant Android app** (`E:/code/MobiAssistant`, `presentation/calendar/CalendarScreen.kt`): week, month, year and day views; `ScheduleEvent` rows with recurrence, reminder and priority; tasks drawn as virtual entries (📌 work block, ⏰ deadline, ✓ when done; key `task:<id>#…`) that are never stored as events. Recurrences are always computed from the original start (`nth_occurrence`), so a 31st-of-month event does not drift. Android push reminders are replaced by an in-page "Sắp tới" banner (`upcoming_reminders`).
- **Tasks vs calendar events in the agent:** the prompt sends time-boxed or recurring activities ("hằng ngày", "mỗi sáng", meetings, gym) to `create_event` with a `recurrence`, and deliverables with a deadline to `create_task`. Converting a task into a recurring event means `create_event` followed by `delete_task` (confirmed). `delete_event` interrupts like `delete_task`, with `action="delete_event"` in the payload. The v1–v3 eval runs used only the 8 task tools. Case `create-18` ("chạy bộ … mỗi sáng") now expects `create_event`, so runs after v3 are not directly comparable on that case.
- **Streamlit dialogs are opened through session state** (`calendar_dialog` key with statically decorated `@st.dialog` functions and `on_dismiss=close_dialog`). Calling a dialog only inside a button branch loses it on the rerun its own Lưu button triggers. The day timeline is HTML in `st.iframe`, so titles must stay `html.escape`d.
- **The eval set grew from 102 to 116 cases** (categories notes, reschedule, alerts, report, memory, plus `project-11` with a target date). `v4-preview.json` is a run of only those 14 cases; v1–v3 cover the original 102, so compare versions on the shared cases.
- **Agent tests use `ScriptedChatModel`** (a `GenericFakeChatModel` whose `bind_tools` returns itself) to play back scripted tool calls without an API key.

Design rules that span modules:
- **Keep the core independent of the UI.** `app/` imports from `src/flowagent`, never the other way round. Phase 2 will put FastAPI in front of the same core.
- **The LLM never writes to the DB directly.** It picks a tool, the tool arguments are validated with Pydantic, and only then are CRUD functions called.
- **Destructive tools (delete, bulk update) must go through a LangGraph `interrupt`** and wait for user confirmation in the UI.
- **Scheduling and "what should I do today" ordering are computed in `planning/`** (deterministic, testable). The LLM only explains the result.
- **The system prompt must inject the current date and timezone `Asia/Ho_Chi_Minh`,** so relative Vietnamese dates ("thứ 6 tuần sau", "chiều mai") resolve correctly.
- **`create_project_plan` (goal → steps with durations → scheduled tasks → Gantt) is the headline feature.** The LLM writes the steps directly as tool arguments, and `build_timeline` assigns `planned_start` and `deadline`.
- **Eval results** (tool-selection accuracy, argument accuracy, success rate, latency) are kept per iteration (v1, v2, v3) because they feed report section 3.5 and the CV.

## Code conventions

**Comments: each function or method gets exactly one comment,** a one-line docstring that says what it does. For example, `"""Return tasks due within the next N days, sorted by deadline."""`.
- No multi-line docstrings: no Args/Returns/Raises sections.
- No inline `#` comments, no block comments, no commented-out code.
- If code seems to need a comment, rename things or extract a function instead.
- Classes and modules get no comment unless asked.

**Naming:**
- `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Names say what something is or does: `overdue_tasks`, `estimate_duration_hours`, not `data`, `tmp`, `res`, `x`, `handle`, `process`.
- Functions start with a verb (`create_task`, `rank_tasks_for_today`). Booleans read as questions (`is_overdue`, `has_subtasks`).
- Include units in names when they matter (`duration_minutes`, `deadline_utc`).
- Code identifiers are in English. Vietnamese is for user-facing text and prompts only.

**Functions:**
- One responsibility each. Keep them short (around 30 lines at most). Prefer early returns over nested `if`.
- No magic numbers or strings: put them in named constants or `config.py`.
- Full type hints on every signature. Use Pydantic or SQLModel models for structured data instead of raw dicts.
- Pure logic (`planning/`, `ml/`) takes inputs as arguments and does no I/O, so it can be unit-tested.

**Structure and hygiene:**
- No duplicated logic. Shared helpers go in the module that owns the concept, not in a generic `utils.py`.
- Raise specific exceptions. Never write a bare `except:`, and never swallow errors silently.
- No `print` for diagnostics: use `logging`.
- Code must pass `ruff check` and `ruff format`. Remove unused imports, variables and dead code.

## Commands

Use the Python 3.12 venv at `.venv`. The system `python` is 3.10 and too old.

```
py -3.12 -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/streamlit run app/streamlit_app.py
.venv/Scripts/python -m pytest                                          # all tests
.venv/Scripts/python -m pytest tests/test_scheduler.py::test_build_timeline_spans_working_days
.venv/Scripts/ruff check --fix . && .venv/Scripts/ruff format .
```

ML and notebook (install the extra with `pip install -e ".[dev,notebook]"`):
```
.venv/Scripts/flowagent-collect-jira                 # ~1 min, writes data/raw/apache_jira_issues.csv
.venv/Scripts/flowagent-generate-tasks [--refilter]  # ~64 Gemini calls; --refilter re-applies filters without the LLM
.venv/Scripts/flowagent-train-priority               # writes models/priority_classifier.joblib + metrics
.venv/Scripts/python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.kernel_name=flowagent notebooks/priority_model.ipynb
```
Agent evaluation (about 102 cases × 5-15 s on the free tier, so run it in the background):
```
.venv/Scripts/flowagent-eval --label v2 [--only create-,notes-] [--resume]   # writes evals/results/v2.json; without --resume it overwrites
.venv/Scripts/flowagent-eval-report [v1 v2]                # writes evals/results/summary.md
```

Run nbconvert via `python -m`. `.venv/Scripts/jupyter nbconvert` resolves the `jupyter-nbconvert` subcommand on PATH and picks the system Python 3.10 one. The `flowagent` kernel was registered with `python -m ipykernel install --sys-prefix --name flowagent`. Ruff also lints notebooks (E402/E501 are ignored for `*.ipynb`).

To smoke-test a UI page without a browser, use `streamlit.testing.v1.AppTest.from_string` with code that puts `app` on `sys.path` and calls `render_<page>_page()`.
