from collections.abc import Callable, Sequence
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from flowagent.db.models import Priority
from flowagent.errors import ModelArtifactError
from flowagent.ml.embeddings import EMBEDDING_MODEL_NAME, embed_texts
from flowagent.ml.labels import PriorityPrediction

DEFAULT_ARTIFACT_PATH = Path("models/priority_classifier.joblib")

Embedder = Callable[[Sequence[str]], np.ndarray]


class PriorityPredictor:
    def __init__(
        self, classifier: LogisticRegression, embed: Embedder, confidence_threshold: float = 0.0
    ) -> None:
        """Pair a trained classifier with its encoder and the minimum confidence to trust it."""
        self._classifier = classifier
        self._embed = embed
        self._confidence_threshold = confidence_threshold

    def predict(self, text: str) -> PriorityPrediction:
        """Predict the priority of one task description with the model's confidence."""
        probabilities = self._classifier.predict_proba(self._embed([text]))[0]
        best_index = int(np.argmax(probabilities))
        confidence = float(probabilities[best_index])
        return PriorityPrediction(
            priority=Priority(self._classifier.classes_[best_index]),
            confidence=confidence,
            is_confident=confidence >= self._confidence_threshold,
        )


def save_classifier(
    classifier: LogisticRegression, artifact_path: Path, confidence_threshold: float = 0.0
) -> None:
    """Persist the classifier with its encoder name and the confidence threshold to apply."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "classifier": classifier,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "confidence_threshold": confidence_threshold,
    }
    joblib.dump(artifact, artifact_path)


def load_priority_predictor(artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> PriorityPredictor:
    """Load the saved classifier and wire it to the multilingual encoder."""
    artifact = joblib.load(artifact_path)
    if artifact["embedding_model"] != EMBEDDING_MODEL_NAME:
        raise ModelArtifactError(
            f"Model được huấn luyện với encoder khác: {artifact['embedding_model']}"
        )
    threshold = artifact.get("confidence_threshold", 0.0)
    return PriorityPredictor(artifact["classifier"], embed_texts, threshold)
