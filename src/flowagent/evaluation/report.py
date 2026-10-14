import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path("evals/results")
SUMMARY_PATH = RESULTS_DIR / "summary.md"
PERCENT_METRICS = ("success_rate", "tool_selection_accuracy", "check_accuracy", "error_rate")
P95_QUANTILE_INDEX = 18


def summarize_group(records: list[dict]) -> dict[str, float]:
    """Compute accuracy, latency and cost metrics for a group of case records."""
    total_checks = sum(record["total_checks"] for record in records)
    latencies = [record["latency_seconds"] for record in records if not record["error"]]
    return {
        "cases": len(records),
        "success_rate": sum(record["success"] for record in records) / len(records),
        "tool_selection_accuracy": sum(record["tool_selection_ok"] for record in records)
        / len(records),
        "check_accuracy": sum(record["passed_checks"] for record in records) / total_checks
        if total_checks
        else 1.0,
        "error_rate": sum(record["error"] is not None for record in records) / len(records),
        "mean_latency_seconds": statistics.fmean(latencies) if latencies else 0.0,
        "p95_latency_seconds": statistics.quantiles(latencies, n=20)[P95_QUANTILE_INDEX]
        if len(latencies) >= 2
        else (latencies[0] if latencies else 0.0),
        "mean_model_calls": statistics.fmean(record["model_calls"] for record in records),
        "mean_tokens": statistics.fmean(record["total_tokens"] for record in records),
    }


def summarize_records(records: list[dict]) -> dict:
    """Summarize all records overall and per category."""
    by_category: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)
    return {
        "overall": summarize_group(records),
        "by_category": {
            name: summarize_group(group) for name, group in sorted(by_category.items())
        },
    }


def format_metric(name: str, value: float) -> str:
    """Render a metric as a percentage or a short decimal."""
    return f"{value:.0%}" if name in PERCENT_METRICS else f"{value:.1f}"


def build_comparison_table(results: list[dict]) -> str:
    """Render a Markdown table comparing overall metrics across evaluation versions."""
    metrics = list(results[0]["summary"]["overall"])
    header = "| Metric | " + " | ".join(f"{r['label']} ({r['model']})" for r in results) + " |"
    divider = "|---" * (len(results) + 1) + "|"
    rows = [
        f"| {metric} | "
        + " | ".join(format_metric(metric, r["summary"]["overall"][metric]) for r in results)
        + " |"
        for metric in metrics
    ]
    return "\n".join([header, divider, *rows])


def build_category_table(result: dict) -> str:
    """Render per-category success and tool accuracy for one version."""
    rows = [
        f"| {name} | {group['cases']} | {group['success_rate']:.0%} | "
        f"{group['tool_selection_accuracy']:.0%} | {group['check_accuracy']:.0%} |"
        for name, group in result["summary"]["by_category"].items()
    ]
    header = "| Category | Cases | Success | Tool selection | Checks |\n|---|---|---|---|---|"
    return "\n".join([header, *rows])


def main() -> None:
    """Write a Markdown comparison of every saved evaluation run."""
    parser = argparse.ArgumentParser(description="Compare FlowAgent evaluation runs.")
    parser.add_argument("labels", nargs="*", help="Labels to compare, default: all results")
    args = parser.parse_args()
    paths = [RESULTS_DIR / f"{label}.json" for label in args.labels] or sorted(
        path for path in RESULTS_DIR.glob("*.json")
    )
    results = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    sections = ["# Agent evaluation\n", build_comparison_table(results)]
    sections += [f"\n## {r['label']} by category\n\n{build_category_table(r)}" for r in results]
    SUMMARY_PATH.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(SUMMARY_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
