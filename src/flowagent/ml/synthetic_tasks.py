import argparse
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from flowagent.agent.llm import ModelSpec, build_chat_model
from flowagent.config import get_settings
from flowagent.db.models import PRIORITY_ORDER
from flowagent.ml.embeddings import embed_texts

logger = logging.getLogger(__name__)

PROMPT_VERSION = 1
TASKS_PER_REQUEST = 10
PAUSE_BETWEEN_REQUESTS_SECONDS = 4.0
MIN_WORDS, MAX_WORDS = 4, 25
NEAR_DUPLICATE_SIMILARITY = 0.95
EVAL_LEAKAGE_SIMILARITY = 0.75
LABEL_WORD_PATTERN = re.compile(r"khẩn cấp|ưu tiên", re.IGNORECASE)
DEFAULT_OUTPUT_PATH = Path("datasets/vietnamese_tasks_synthetic.csv")
EVAL_SET_PATH = Path("datasets/vietnamese_tasks_labeled.csv")
TRAILING_PUNCTUATION = ".;,!"
WHITESPACE_PATTERN = re.compile(r"\s+")

THEMES: dict[str, tuple[str, ...]] = {
    "personal": (
        "học tập và thi cử",
        "công việc và sự nghiệp",
        "sức khoẻ",
        "gia đình và người thân",
        "tài chính và hoá đơn",
        "nhà cửa và sinh hoạt",
        "giấy tờ và thủ tục hành chính",
        "giải trí và sở thích",
    ),
    "software": (
        "sự cố hệ thống và hạ tầng",
        "bảo mật",
        "thanh toán và đơn hàng",
        "giao diện người dùng",
        "hiệu năng",
        "dữ liệu và báo cáo",
        "kiểm thử và chất lượng mã",
        "tài liệu và quy trình phát triển",
    ),
}
DOMAIN_DESCRIPTIONS = {
    "personal": "công việc cá nhân trong đời sống của một sinh viên hoặc người đi làm",
    "software": "công việc trong một nhóm phát triển phần mềm",
}
LABEL_DEFINITIONS = {
    "urgent": "phải xử lý ngay trong vài giờ tới; chậm trễ gây hậu quả nghiêm trọng "
    "(nguy hiểm sức khoẻ, mất tiền, mất dữ liệu, hệ thống ngừng hoạt động, lỗ hổng bảo mật)",
    "high": "quan trọng, cần xong trong vài ngày; chậm trễ gây ảnh hưởng đáng kể",
    "medium": "việc thường ngày cần làm nhưng không gấp; chậm vài ngày không sao",
    "low": "việc tuỳ ý, ảnh hưởng nhỏ, làm khi rảnh hoặc có thể bỏ qua",
}
PROMPT_TEMPLATE = """Viết {count} mô tả công việc KHÁC NHAU bằng tiếng Việt tự nhiên.
- Loại: {domain_description}, chủ đề "{theme}".
- Mức độ ưu tiên thực tế của TẤT CẢ các việc: {label_definition}.
- Mỗi câu dài 6-18 từ, viết như người dùng ghi vào ứng dụng quản lý công việc.
- KHÔNG dùng các từ nói thẳng mức độ như "khẩn cấp", "gấp", "ưu tiên", "quan trọng", "không quan trọng";
  mức độ phải thể hiện qua chính nội dung công việc.
- Đa dạng cách diễn đạt, không lặp lại cùng một mẫu câu."""


class GeneratedTask(BaseModel):
    text: str


class GeneratedBatch(BaseModel):
    tasks: list[GeneratedTask] = Field(min_length=1)


@dataclass(frozen=True)
class SyntheticTask:
    text: str
    label: str
    domain: str
    theme: str


def build_generation_prompt(domain: str, label: str, theme: str, count: int) -> str:
    """Fill the generation prompt for one domain, priority level and theme."""
    return PROMPT_TEMPLATE.format(
        count=count,
        domain_description=DOMAIN_DESCRIPTIONS[domain],
        theme=theme,
        label_definition=LABEL_DEFINITIONS[label],
    )


def normalize_task_text(text: str) -> str:
    """Collapse whitespace and drop trailing punctuation so duplicates compare equal."""
    return WHITESPACE_PATTERN.sub(" ", text).strip().rstrip(TRAILING_PUNCTUATION).strip()


def has_valid_length(text: str) -> bool:
    """Keep only task descriptions of a realistic length."""
    return MIN_WORDS <= len(text.split()) <= MAX_WORDS


def generate_tasks(chat_model: BaseChatModel) -> Iterator[SyntheticTask]:
    """Ask the LLM for tasks of every domain, priority level and theme combination."""
    structured_model = chat_model.with_structured_output(GeneratedBatch)
    for domain, themes in THEMES.items():
        for label in (priority.value for priority in PRIORITY_ORDER):
            for theme in themes:
                prompt = build_generation_prompt(domain, label, theme, TASKS_PER_REQUEST)
                batch = structured_model.invoke(prompt)
                logger.info("%s / %s / %s: %d tasks", domain, label, theme, len(batch.tasks))
                for task in batch.tasks:
                    yield SyntheticTask(normalize_task_text(task.text), label, domain, theme)
                time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)


def drop_exact_duplicates(tasks: pd.DataFrame) -> pd.DataFrame:
    """Remove tasks with invalid length, label words, or text already seen (case-insensitive)."""
    has_label_word = tasks["text"].str.contains(LABEL_WORD_PATTERN)
    valid = tasks[tasks["text"].map(has_valid_length) & ~has_label_word]
    return valid.loc[~valid["text"].str.casefold().duplicated()]


def find_near_duplicates(embeddings: np.ndarray, threshold: float) -> list[bool]:
    """Flag rows whose embedding is almost identical to an earlier kept row."""
    normalized = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    is_duplicate: list[bool] = []
    kept: list[np.ndarray] = []
    for vector in normalized:
        similar = bool(kept) and float(np.max(np.stack(kept) @ vector)) >= threshold
        is_duplicate.append(similar)
        if not similar:
            kept.append(vector)
    return is_duplicate


def find_eval_leakage(
    candidate_embeddings: np.ndarray, eval_embeddings: np.ndarray, threshold: float
) -> list[bool]:
    """Flag rows too similar to any evaluation sentence, so the test set stays unseen."""
    candidates = candidate_embeddings / np.linalg.norm(candidate_embeddings, axis=1, keepdims=True)
    evaluation = eval_embeddings / np.linalg.norm(eval_embeddings, axis=1, keepdims=True)
    return list((candidates @ evaluation.T).max(axis=1) >= threshold)


def filter_tasks(tasks: pd.DataFrame, eval_texts: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply length, exact, near-duplicate and leakage filters and report how many each removed."""
    unique = drop_exact_duplicates(tasks)
    embeddings = embed_texts(unique["text"].tolist())
    near_duplicate = np.array(find_near_duplicates(embeddings, NEAR_DUPLICATE_SIMILARITY))
    leaked = np.array(
        find_eval_leakage(embeddings, embed_texts(eval_texts), EVAL_LEAKAGE_SIMILARITY)
    )
    kept = unique[~near_duplicate & ~leaked]
    report = {
        "generated": len(tasks),
        "after_length_and_exact_dedup": len(unique),
        "near_duplicates_removed": int(near_duplicate.sum()),
        "eval_leakage_removed": int((leaked & ~near_duplicate).sum()),
        "kept": len(kept),
    }
    return kept, report


def build_generator_spec() -> ModelSpec:
    """Describe the Gemini model configured in .env that generates the tasks."""
    settings = get_settings()
    return ModelSpec("gemini", settings.gemini_model, settings.gemini_api_key)


def generate_raw_tasks() -> tuple[pd.DataFrame, dict[str, object]]:
    """Call the LLM for every domain, level and theme and return unfiltered tasks plus metadata."""
    spec = build_generator_spec()
    chat_model = build_chat_model(spec, get_settings())
    raw_tasks = pd.DataFrame(asdict(task) for task in generate_tasks(chat_model))
    metadata = {
        "generator": spec.label,
        "prompt_version": PROMPT_VERSION,
        "created": date.today().isoformat(),
    }
    return raw_tasks, metadata


def main() -> None:
    """Generate (or re-filter) and save the synthetic Vietnamese training set."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate synthetic Vietnamese labelled tasks.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--refilter", action="store_true", help="Re-filter the saved file only.")
    args = parser.parse_args()
    metadata_path = args.output.with_suffix(".json")
    if args.refilter:
        raw_tasks = pd.read_csv(args.output)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        raw_tasks, metadata = generate_raw_tasks()
    kept, report = filter_tasks(raw_tasks, pd.read_csv(EVAL_SET_PATH)["text"].tolist())
    kept.to_csv(args.output, index=False)
    metadata |= {"leakage_threshold": EVAL_LEAKAGE_SIMILARITY, f"filter_{len(raw_tasks)}": report}
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved %d tasks to %s: %s", len(kept), args.output, metadata)


if __name__ == "__main__":
    main()
