import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from flowagent.ml.embeddings import embed_texts, embed_texts_cached
from flowagent.ml.jira_collection import DEFAULT_OUTPUT_PATH
from flowagent.ml.predictor import DEFAULT_ARTIFACT_PATH, save_classifier
from flowagent.ml.training import (
    LABEL_COLUMN,
    TEXT_COLUMN,
    ModelScores,
    build_embedding_classifier,
    prepare_dataset,
    score_predictions,
    split_dataset,
)

logger = logging.getLogger(__name__)

EMBEDDING_CACHE_PATH = Path("data/processed/issue_embeddings.npy")
VIETNAMESE_EVAL_PATH = Path("datasets/vietnamese_tasks_labeled.csv")
METRICS_PATH = Path("models/priority_classifier_metrics.json")


def load_raw_issues(csv_path: Path) -> pd.DataFrame:
    """Read the collected Jira CSV, allowing very long description fields."""
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)
    return pd.read_csv(csv_path, engine="python")


def train_and_score(dataset: pd.DataFrame) -> tuple[object, ModelScores, int, int]:
    """Fit the embedding classifier on the train split and score it on the test split."""
    train_set, test_set = split_dataset(dataset)
    embeddings = embed_texts_cached(dataset[TEXT_COLUMN].tolist(), EMBEDDING_CACHE_PATH)
    row_positions = {index: position for position, index in enumerate(dataset.index)}
    train_rows = [row_positions[index] for index in train_set.index]
    test_rows = [row_positions[index] for index in test_set.index]
    classifier = build_embedding_classifier().fit(embeddings[train_rows], train_set[LABEL_COLUMN])
    test_scores = score_predictions(
        test_set[LABEL_COLUMN], list(classifier.predict(embeddings[test_rows]))
    )
    return classifier, test_scores, len(train_set), len(test_set)


def score_on_vietnamese_tasks(classifier: object) -> ModelScores:
    """Measure cross-lingual transfer on the hand-labelled Vietnamese task set."""
    vietnamese_tasks = pd.read_csv(VIETNAMESE_EVAL_PATH)
    predictions = classifier.predict(embed_texts(vietnamese_tasks[TEXT_COLUMN].tolist()))
    return score_predictions(vietnamese_tasks[LABEL_COLUMN], list(predictions))


def main() -> None:
    """Train the production priority classifier and save it with its evaluation metrics."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Train the FlowAgent priority classifier.")
    parser.add_argument("--input", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH)
    args = parser.parse_args()
    dataset = prepare_dataset(load_raw_issues(args.input))
    logger.info("Prepared %d labelled issues", len(dataset))
    classifier, test_scores, train_size, test_size = train_and_score(dataset)
    vietnamese_scores = score_on_vietnamese_tasks(classifier)
    save_classifier(classifier, args.output)
    metrics = {
        "train_size": train_size,
        "test_size": test_size,
        "apache_test": asdict(test_scores),
        "vietnamese_tasks": asdict(vietnamese_scores),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Saved model to %s; metrics: %s", args.output, json.dumps(metrics))


if __name__ == "__main__":
    main()
