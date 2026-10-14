import argparse
import csv
import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import asdict, dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)

JIRA_SEARCH_URL = "https://issues.apache.org/jira/rest/api/2/search"
DEFAULT_PROJECTS = (
    "KAFKA",
    "SPARK",
    "HADOOP",
    "HIVE",
    "FLINK",
    "CASSANDRA",
    "HBASE",
    "CAMEL",
    "IGNITE",
    "ZOOKEEPER",
    "SOLR",
    "NIFI",
)
DEFAULT_ISSUES_PER_PROJECT = 3000
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 120
PAUSE_BETWEEN_REQUESTS_SECONDS = 1.0
REQUESTED_FIELDS = "summary,description,priority,issuetype,created"
USER_AGENT = "FlowAgent-student-research/0.1"
DEFAULT_OUTPUT_PATH = Path("data/raw/apache_jira_issues.csv")


@dataclass(frozen=True)
class JiraIssue:
    key: str
    project: str
    issue_type: str
    priority: str
    created: str
    summary: str
    description: str


def build_search_url(project: str, start_at: int, page_size: int) -> str:
    """Build the REST search URL for resolved issues of one project, newest first."""
    jql = f"project = {project} AND resolution is not EMPTY ORDER BY created DESC"
    query = urllib.parse.urlencode(
        {"jql": jql, "startAt": start_at, "maxResults": page_size, "fields": REQUESTED_FIELDS}
    )
    return f"{JIRA_SEARCH_URL}?{query}"


def fetch_json(url: str) -> dict:
    """Download and decode one JSON page from the Jira API."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.load(response)


def parse_issue(raw_issue: dict) -> JiraIssue | None:
    """Convert a raw API issue into a JiraIssue, skipping issues without a priority."""
    issue_fields = raw_issue["fields"]
    if not issue_fields.get("priority"):
        return None
    return JiraIssue(
        key=raw_issue["key"],
        project=raw_issue["key"].split("-")[0],
        issue_type=(issue_fields.get("issuetype") or {}).get("name", ""),
        priority=issue_fields["priority"]["name"],
        created=(issue_fields.get("created") or "")[:10],
        summary=issue_fields.get("summary") or "",
        description=issue_fields.get("description") or "",
    )


def iterate_project_issues(project: str, limit: int) -> Iterator[JiraIssue]:
    """Yield up to limit resolved issues of a project, paging politely through the API."""
    start_at = 0
    while start_at < limit:
        page = fetch_json(build_search_url(project, start_at, min(PAGE_SIZE, limit - start_at)))
        raw_issues = page.get("issues", [])
        for raw_issue in raw_issues:
            issue = parse_issue(raw_issue)
            if issue is not None:
                yield issue
        start_at += len(raw_issues)
        if not raw_issues or start_at >= page.get("total", 0):
            return
        time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)


def write_issues(issues: Iterator[JiraIssue], output_path: Path) -> int:
    """Stream issues into a UTF-8 CSV file and return how many rows were written."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=[field.name for field in fields(JiraIssue)])
        writer.writeheader()
        for issue in issues:
            writer.writerow(asdict(issue))
            row_count += 1
    return row_count


def collect_issues(projects: tuple[str, ...], limit_per_project: int) -> Iterator[JiraIssue]:
    """Yield issues from every project in turn, logging progress per project."""
    for project in projects:
        logger.info("Collecting %s ...", project)
        yield from iterate_project_issues(project, limit_per_project)


def main() -> None:
    """Download resolved Apache Jira issues to CSV for training the priority model."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Collect public Apache Jira issues.")
    parser.add_argument("--projects", nargs="+", default=list(DEFAULT_PROJECTS))
    parser.add_argument("--limit-per-project", type=int, default=DEFAULT_ISSUES_PER_PROJECT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    row_count = write_issues(
        collect_issues(tuple(args.projects), args.limit_per_project), args.output
    )
    logger.info("Wrote %d issues to %s", row_count, args.output)


if __name__ == "__main__":
    main()
