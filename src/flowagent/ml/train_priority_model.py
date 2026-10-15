import argparse
import csv
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from flowagent.ml.embeddings import embed_texts, embed_texts_cached
from flowagent.ml.jira_collection import DEFAULT_OUTPUT_PATH
from flowagent.ml.predictor import DEFAULT_ARTIFACT_PATH, save_classifier
from flowagent.ml.training import (
    LABEL_COLUMN,
    RANDOM_SEED,
    TEXT_COLUMN,
    ModelScores,
    apply_confidence_threshold,
    build_embedding_classifier,
    choose_confidence_threshold,
    prepare_dataset,
    score_predictions,
    source_balanced_weights,
    split_dataset,
)

logger = logging.getLogger(__name__)

EMBEDDING_CACHE_PATH = Path("data/processed/issue_embeddings.npy")
SYNTHETIC_EMBEDDING_CACHE_PATH = Path("data/processed/synthetic_embeddings.npy")
VIETNAMESE_EVAL_PATH = Path("datasets/vietnamese_tasks_labeled.csv")
SYNTHETIC_TASKS_PATH = Path("datasets/vietnamese_tasks_synthetic.csv")
METRICS_PATH = Path("models/priority_classifier_metrics.json")
APACHE_SOURCE = "apache"
SYNTHETIC_SOURCE = "synthetic"
ALL_DOMAINS = "all"
VALIDATION_SIZE = 0.2


@dataclass(frozen=True)
class FeatureSet:
    features: np.ndarray
    labels: list[str]
    sources: list[str]


def load_raw_issues(csv_path: Path) -> pd.DataFrame:
    """Read the collected Jira CSV, allowing very long description fields."""
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)
    return pd.read_csv(csv_path, engine="python")


def embed_apache_splits(dataset: pd.DataFrame) -> tuple[FeatureSet, FeatureSet]:
    """Embed the cleaned Apache issues and return train and test feature sets."""
    train_set, test_set = split_dataset(dataset)
    embeddings = embed_texts_cached(dataset[TEXT_COLUMN].tolist(), EMBEDDING_CACHE_PATH)
    row_positions = {index: position for position, index in enumerate(dataset.index)}

    def to_feature_set(subset: pd.DataFrame) -> FeatureSet:
        """Pick the embedding rows that belong to one split."""
        rows = [row_positions[index] for index in subset.index]
        labels = subset[LABEL_COLUMN].tolist()
        return FeatureSet(embeddings[rows], labels, [APACHE_SOURCE] * len(labels))

    return to_feature_set(train_set), to_feature_set(test_set)


def embed_synthetic_tasks(synthetic_tasks: pd.DataFrame) -> FeatureSet:
    """Embed the synthetic Vietnamese tasks as an extra training source."""
    texts = synthetic_tasks[TEXT_COLUMN].tolist()
    labels = synthetic_tasks[LABEL_COLUMN].tolist()
    features = embed_texts_cached(texts, SYNTHETIC_EMBEDDING_CACHE_PATH)
    return FeatureSet(features, labels, [SYNTHETIC_SOURCE] * len(labels))


def combine_feature_sets(*feature_sets: FeatureSet) -> FeatureSet:
    """Stack several feature sets into one training set."""
    return FeatureSet(
        np.vstack([feature_set.features for feature_set in feature_sets]),
        [label for feature_set in feature_sets for label in feature_set.labels],
        [source for feature_set in feature_sets for source in feature_set.sources],
    )


def fit_source_balanced(training: FeatureSet) -> LogisticRegression:
    """Fit the embedding classifier with every source contributing equal total weight."""
    return build_embedding_classifier().fit(
        training.features, training.labels, sample_weight=source_balanced_weights(training.sources)
    )


def predict_with_threshold(
    classifier: LogisticRegression, features: np.ndarray, threshold: float
) -> list[str]:
    """Predict labels, replacing low-confidence predictions with medium."""
    return apply_confidence_threshold(
        classifier.predict_proba(features), list(classifier.classes_), threshold
    )


def select_rows(feature_set: FeatureSet, rows: Sequence[int]) -> FeatureSet:
    """Return the subset of a feature set at the given row positions."""
    return FeatureSet(
        feature_set.features[list(rows)],
        [feature_set.labels[row] for row in rows],
        [feature_set.sources[row] for row in rows],
    )


def tune_confidence_threshold(apache_train: FeatureSet, synthetic: FeatureSet) -> dict:
    """Choose the confidence threshold on a held-out 20% of the synthetic Vietnamese data."""
    train_rows, validation_rows = train_test_split(
        range(len(synthetic.labels)),
        test_size=VALIDATION_SIZE,
        random_state=RANDOM_SEED,
        stratify=synthetic.labels,
    )
    validation = select_rows(synthetic, validation_rows)
    classifier = fit_source_balanced(
        combine_feature_sets(apache_train, select_rows(synthetic, train_rows))
    )
    threshold, validation_macro_f1 = choose_confidence_threshold(
        classifier.predict_proba(validation.features), list(classifier.classes_), validation.labels
    )
    unthresholded = score_predictions(
        pd.Series(validation.labels), predict_with_threshold(classifier, validation.features, 0.0)
    )
    return {
        "threshold": threshold,
        "validation_rows": len(validation_rows),
        "validation_macro_f1_without_threshold": unthresholded.macro_f1,
        "validation_macro_f1_with_threshold": validation_macro_f1,
    }


def score_on_vietnamese_tasks(
    classifier: LogisticRegression, threshold: float = 0.0
) -> dict[str, ModelScores]:
    """Score the hand-labelled Vietnamese tasks overall and per domain."""
    vietnamese_tasks = pd.read_csv(VIETNAMESE_EVAL_PATH)
    features = embed_texts(vietnamese_tasks[TEXT_COLUMN].tolist())
    predicted = vietnamese_tasks.assign(
        predicted=predict_with_threshold(classifier, features, threshold)
    )
    groups = [(ALL_DOMAINS, predicted), *predicted.groupby("domain")]
    return {
        str(domain): score_predictions(group[LABEL_COLUMN], list(group["predicted"]))
        for domain, group in groups
    }


def evaluate(classifier: LogisticRegression, apache_test: FeatureSet, threshold: float) -> dict:
    """Report Apache test and Vietnamese evaluation scores for one threshold."""
    apache_predictions = predict_with_threshold(classifier, apache_test.features, threshold)
    return {
        "apache_test": asdict(score_predictions(apache_test.labels, apache_predictions)),
        "vietnamese_tasks": {
            domain: asdict(scores)
            for domain, scores in score_on_vietnamese_tasks(classifier, threshold).items()
        },
    }


def main() -> None:
    """Train the production priority classifier on Apache plus synthetic data and save it."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Train the FlowAgent priority classifier.")
    parser.add_argument("--input", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH)
    args = parser.parse_args()
    apache_train, apache_test = embed_apache_splits(prepare_dataset(load_raw_issues(args.input)))
    training, tuning = apache_train, {"threshold": 0.0}
    if SYNTHETIC_TASKS_PATH.exists():
        synthetic = embed_synthetic_tasks(pd.read_csv(SYNTHETIC_TASKS_PATH))
        tuning = tune_confidence_threshold(apache_train, synthetic)
        training = combine_feature_sets(apache_train, synthetic)
    classifier = fit_source_balanced(training)
    save_classifier(classifier, args.output, tuning["threshold"])
    metrics = {
        "training_rows_by_source": pd.Series(training.sources).value_counts().to_dict(),
        "confidence_threshold_tuning": tuning,
        "with_threshold": evaluate(classifier, apache_test, tuning["threshold"]),
        "without_threshold": evaluate(classifier, apache_test, 0.0),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Saved model to %s; metrics: %s", args.output, json.dumps(metrics))


if __name__ == "__main__":
    main()
