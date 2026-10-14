from dataclasses import dataclass

import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from flowagent.ml.labels import PRIORITY_ORDER, jira_priority_label
from flowagent.ml.text_cleaning import build_issue_text

TEXT_COLUMN = "text"
LABEL_COLUMN = "label"
TEST_SIZE = 0.2
RANDOM_SEED = 42
MIN_TEXT_CHARS = 10
MAX_ITERATIONS = 2000
TFIDF_MAX_FEATURES = 50_000
TFIDF_MIN_DOCUMENT_FREQUENCY = 3
CLASS_LABELS = [priority.value for priority in PRIORITY_ORDER]


@dataclass(frozen=True)
class ModelScores:
    accuracy: float
    macro_f1: float
    weighted_f1: float
    per_class_f1: dict[str, float]


def prepare_dataset(raw_issues: pd.DataFrame) -> pd.DataFrame:
    """Map priorities to app labels, build model text, and drop unusable or duplicate rows."""
    labelled = raw_issues.assign(
        label=raw_issues["priority"].astype(str).map(jira_priority_label),
        text=[
            build_issue_text(str(summary), "" if pd.isna(description) else str(description))
            for summary, description in zip(
                raw_issues["summary"], raw_issues["description"], strict=True
            )
        ],
    )
    usable = labelled.dropna(subset=[LABEL_COLUMN])
    usable = usable[usable[TEXT_COLUMN].str.len() >= MIN_TEXT_CHARS]
    return usable.drop_duplicates(subset=[TEXT_COLUMN])


def split_dataset(dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into stratified train and test sets with a fixed seed."""
    return train_test_split(
        dataset, test_size=TEST_SIZE, random_state=RANDOM_SEED, stratify=dataset[LABEL_COLUMN]
    )


def build_majority_baseline() -> DummyClassifier:
    """Return a classifier that always predicts the most frequent class."""
    return DummyClassifier(strategy="most_frequent")


def build_tfidf_classifier() -> Pipeline:
    """Return a TF-IDF word/bigram features plus class-balanced logistic regression pipeline."""
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=TFIDF_MIN_DOCUMENT_FREQUENCY,
                    max_features=TFIDF_MAX_FEATURES,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(class_weight="balanced", max_iter=MAX_ITERATIONS),
            ),
        ]
    )


def build_embedding_classifier() -> LogisticRegression:
    """Return a class-balanced logistic regression for sentence-embedding features."""
    return LogisticRegression(class_weight="balanced", max_iter=MAX_ITERATIONS)


def score_predictions(true_labels: pd.Series, predicted_labels: list[str]) -> ModelScores:
    """Compute accuracy, macro and weighted F1, and per-class F1 for one model."""
    report = classification_report(
        true_labels, predicted_labels, labels=CLASS_LABELS, output_dict=True, zero_division=0
    )
    return ModelScores(
        accuracy=accuracy_score(true_labels, predicted_labels),
        macro_f1=f1_score(true_labels, predicted_labels, average="macro", zero_division=0),
        weighted_f1=f1_score(true_labels, predicted_labels, average="weighted", zero_division=0),
        per_class_f1={label: report[label]["f1-score"] for label in CLASS_LABELS},
    )
