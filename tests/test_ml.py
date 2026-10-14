import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from flowagent.db.models import Priority
from flowagent.ml.jira_collection import build_search_url, parse_issue
from flowagent.ml.labels import map_jira_priority
from flowagent.ml.predictor import PriorityPredictor
from flowagent.ml.text_cleaning import build_issue_text, strip_jira_markup
from flowagent.ml.training import prepare_dataset, score_predictions


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
