from dataclasses import dataclass

from flowagent.db.models import Priority

JIRA_PRIORITY_TO_APP: dict[str, Priority] = {
    "Blocker": Priority.URGENT,
    "Urgent": Priority.URGENT,
    "P0": Priority.URGENT,
    "Critical": Priority.HIGH,
    "High": Priority.HIGH,
    "P1": Priority.HIGH,
    "Major": Priority.MEDIUM,
    "Normal": Priority.MEDIUM,
    "P2": Priority.MEDIUM,
    "Minor": Priority.LOW,
    "Low": Priority.LOW,
    "Trivial": Priority.LOW,
    "P3": Priority.LOW,
    "P4": Priority.LOW,
}


@dataclass(frozen=True)
class PriorityPrediction:
    priority: Priority
    confidence: float


PRIORITY_ORDER: tuple[Priority, ...] = (
    Priority.LOW,
    Priority.MEDIUM,
    Priority.HIGH,
    Priority.URGENT,
)


def map_jira_priority(jira_priority: str) -> Priority | None:
    """Map one of Apache Jira's priority schemes onto the app's four levels, or None if unusable."""
    return JIRA_PRIORITY_TO_APP.get(jira_priority.strip())


def jira_priority_label(jira_priority: str) -> str | None:
    """Return the app priority value ('low'...'urgent') for a Jira priority, or None if unusable."""
    priority = map_jira_priority(jira_priority)
    return priority.value if priority else None
