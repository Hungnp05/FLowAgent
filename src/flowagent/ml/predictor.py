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
    def __init__(self, classifier: LogisticRegression, embed: Embedder) -> None:
        """Pair a trained classifier with the encoder that produces its input features."""
        self._classifier = classifier
        self._embed = embed

    def predict(self, text: str) -> PriorityPrediction:
        """Predict the priority of one task description with the model's confidence."""
        probabilities = self._classifier.predict_proba(self._embed([text]))[0]
        best_index = int(np.argmax(probabilities))
        return PriorityPrediction(
            priority=Priority(self._classifier.classes_[best_index]),
            confidence=float(probabilities[best_index]),
        )


def save_classifier(classifier: LogisticRegression, artifact_path: Path) -> None:
    """Persist the classifier together with the name of the encoder it was trained on."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"classifier": classifier, "embedding_model": EMBEDDING_MODEL_NAME}, artifact_path)


def load_priority_predictor(artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> PriorityPredictor:
    """Load the saved classifier and wire it to the multilingual encoder."""
    artifact = joblib.load(artifact_path)
    if artifact["embedding_model"] != EMBEDDING_MODEL_NAME:
        raise ModelArtifactError(
            f"Model được huấn luyện với encoder khác: {artifact['embedding_model']}"
        )
    return PriorityPredictor(artifact["classifier"], embed_texts)
