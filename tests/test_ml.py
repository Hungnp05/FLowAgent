import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from flowagent.db.models import Priority
from flowagent.ml.jira_collection import build_search_url, parse_issue
from flowagent.ml.labels import map_jira_priority
from flowagent.ml.predictor import PriorityPredictor
from flowagent.ml.synthetic_tasks import (
    build_generation_prompt,
    find_eval_leakage,
    find_near_duplicates,
    has_valid_length,
    normalize_task_text,
)
from flowagent.ml.text_cleaning import build_issue_text, strip_jira_markup
from flowagent.ml.training import (
    apply_confidence_threshold,
    choose_confidence_threshold,
    prepare_dataset,
    score_predictions,
    source_balanced_weights,
)


@pytest.mark.parametrize(
    ("jira_priority", "expected"),
    [
        ("Blocker", Priority.URGENT),
        ("Critical", Priority.HIGH),
        ("Major", Priority.MEDIUM),
        ("Trivial", Priority.LOW),
        ("P1", Priority.HIGH),
        ("Not a Priority", None),
    ],
)
def test_map_jira_priority(jira_priority: str, expected: Priority | None) -> None:
    """Every Apache priority scheme maps onto the app's four levels; unusable ones map to None."""
    assert map_jira_priority(jira_priority) == expected


def test_strip_jira_markup_removes_code_traces_and_urls() -> None:
    """Code blocks, stack-trace lines, URLs and wiki markup are removed."""
    raw = (
        "*Broker* fails, see [docs|https://kafka.apache.org]\n"
        "{code:java}int x = 1;{code}\n"
        "    at org.apache.kafka.Foo.bar(Foo.java:10)\n"
        "More at https://example.com/x"
    )
    assert strip_jira_markup(raw) == "Broker fails, see docs More at"


def test_build_issue_text_truncates_description() -> None:
    """The description is cleaned and cut to the requested length after the summary."""
    assert build_issue_text("Crash on start", "x" * 50, max_description_chars=10) == (
        "Crash on start. xxxxxxxxxx"
    )


def test_build_issue_text_without_description() -> None:
    """Summary alone is used when there is no description."""
    assert build_issue_text("Crash on start", "") == "Crash on start"


def test_prepare_dataset_maps_labels_and_drops_unusable_rows() -> None:
    """Rows with unknown priorities, tiny text or duplicate text are removed."""
    raw_issues = pd.DataFrame(
        {
            "summary": [
                "Broker crash on startup",
                "Broker crash on startup",
                "ok",
                "Typo in docs page",
            ],
            "description": [None, None, None, "Fix it"],
            "priority": ["Blocker", "Blocker", "Major", "Not a Priority"],
        }
    )
    dataset = prepare_dataset(raw_issues)
    assert dataset["label"].tolist() == ["urgent"]


def test_score_predictions_reports_macro_f1() -> None:
    """Perfect predictions score 1.0 on every metric for the classes present."""
    scores = score_predictions(pd.Series(["low", "high"]), ["low", "high"])
    assert scores.accuracy == 1.0
    assert scores.per_class_f1["low"] == 1.0


def test_predictor_returns_priority_and_confidence() -> None:
    """The predictor maps the classifier's most likely class to a Priority with its probability."""
    features = np.array([[0.0], [0.1], [1.0], [1.1]])
    classifier = LogisticRegression().fit(features, ["low", "low", "urgent", "urgent"])
    predictor = PriorityPredictor(classifier, lambda texts: np.array([[1.2] for _ in texts]))
    prediction = predictor.predict("anything")
    assert prediction.priority == Priority.URGENT
    assert 0.5 < prediction.confidence <= 1.0


def test_parse_issue_skips_issues_without_priority() -> None:
    """Issues with no priority field are ignored; others keep project and date."""
    raw_issue = {
        "key": "KAFKA-1",
        "fields": {
            "summary": "s",
            "description": None,
            "priority": {"name": "Major"},
            "issuetype": {"name": "Bug"},
            "created": "2026-10-01T10:00:00.000+0000",
        },
    }
    issue = parse_issue(raw_issue)
    assert (issue.project, issue.created, issue.description) == ("KAFKA", "2026-10-01", "")
    assert parse_issue({"key": "KAFKA-2", "fields": {"priority": None}}) is None


def test_build_search_url_encodes_jql() -> None:
    """The search URL asks for resolved issues of one project with paging."""
    url = build_search_url("KAFKA", 1000, 500)
    assert "project+%3D+KAFKA" in url
    assert "startAt=1000" in url and "maxResults=500" in url


def test_source_balanced_weights_give_each_source_equal_total() -> None:
    """A small source gets proportionally larger weights so both sources sum to the same total."""
    weights = source_balanced_weights(["apache"] * 8 + ["synthetic"] * 2)
    assert weights[:8].sum() == pytest.approx(weights[8:].sum())
    assert weights.sum() == pytest.approx(10)


def test_find_near_duplicates_keeps_first_occurrence() -> None:
    """Only later rows nearly identical to an earlier kept row are flagged."""
    embeddings = np.array([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]])
    assert find_near_duplicates(embeddings, threshold=0.95) == [False, True, False]


def test_find_eval_leakage_flags_rows_close_to_eval_set() -> None:
    """Candidates too similar to an evaluation sentence are flagged as leakage."""
    candidates = np.array([[1.0, 0.0], [0.0, 1.0]])
    evaluation = np.array([[0.98, 0.02]])
    assert find_eval_leakage(candidates, evaluation, threshold=0.9) == [True, False]


def test_normalize_and_length_filters() -> None:
    """Whitespace and trailing punctuation are normalised and too-short tasks rejected."""
    assert normalize_task_text("  Đi   chợ mua rau.  ") == "Đi chợ mua rau"
    assert not has_valid_length("Đi chợ")
    assert has_valid_length("Đi chợ mua rau cho cả tuần")


def test_build_generation_prompt_contains_definition_and_theme() -> None:
    """The prompt carries the label definition and theme, and forbids leaking the label word."""
    prompt = build_generation_prompt("personal", "urgent", "sức khoẻ", 10)
    assert "sức khoẻ" in prompt and "vài giờ" in prompt and '"khẩn cấp"' in prompt


def test_apply_confidence_threshold_falls_back_to_medium() -> None:
    """Rows below the threshold become medium; confident rows keep their best class."""
    probabilities = np.array([[0.1, 0.2, 0.7, 0.0], [0.3, 0.2, 0.45, 0.05]])
    classes = ["high", "low", "medium", "urgent"]
    assert apply_confidence_threshold(probabilities, classes, 0.5) == ["medium", "medium"]
    confident = np.array([[0.8, 0.1, 0.1, 0.0]])
    assert apply_confidence_threshold(confident, classes, 0.5) == ["high"]


def test_choose_confidence_threshold_prefers_lowest_best() -> None:
    """When no threshold helps, the lowest candidate (no fallback) is kept."""
    probabilities = np.array([[0.9, 0.1], [0.2, 0.8]])
    threshold, score = choose_confidence_threshold(probabilities, ["high", "low"], ["high", "low"])
    assert threshold == 0.0
    assert score > 0


def test_predictor_flags_low_confidence() -> None:
    """A prediction below the saved threshold is marked as not confident."""
    features = np.array([[0.0], [0.1], [1.0], [1.1]])
    classifier = LogisticRegression().fit(features, ["low", "low", "urgent", "urgent"])
    predictor = PriorityPredictor(classifier, lambda texts: np.array([[0.55] for _ in texts]), 0.9)
    assert not predictor.predict("anything").is_confident
