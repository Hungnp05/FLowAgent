import re

DEFAULT_MAX_DESCRIPTION_CHARS = 300
JIRA_BLOCK_PATTERN = re.compile(
    r"\{(code|noformat|quote)[^}]*\}.*?\{\1\}", re.DOTALL | re.IGNORECASE
)
STACK_TRACE_LINE_PATTERN = re.compile(
    r"^\s*(at [\w.$<>]+\(.*\)|Caused by:.*|\.\.\. \d+ more)\s*$", re.MULTILINE
)
URL_PATTERN = re.compile(r"https?://\S+")
JIRA_LINK_PATTERN = re.compile(r"\[([^|\]]*)\|[^\]]*\]")
JIRA_MARKUP_PATTERN = re.compile(r"\{color[^}]*\}|\[~[^\]]*\]|^h\d\.\s*|[*_{}|\[\]#]", re.MULTILINE)
WHITESPACE_PATTERN = re.compile(r"\s+")


def strip_jira_markup(text: str) -> str:
    """Remove code blocks, stack traces, URLs and wiki markup from Jira text."""
    without_blocks = JIRA_BLOCK_PATTERN.sub(" ", text)
    without_traces = STACK_TRACE_LINE_PATTERN.sub(" ", without_blocks)
    without_urls = URL_PATTERN.sub(" ", without_traces)
    with_link_labels = JIRA_LINK_PATTERN.sub(r"\1", without_urls)
    without_markup = JIRA_MARKUP_PATTERN.sub(" ", with_link_labels)
    return WHITESPACE_PATTERN.sub(" ", without_markup).strip()


def build_issue_text(
    summary: str, description: str, max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS
) -> str:
    """Join the summary with the start of the cleaned description into one model input."""
    clean_summary = strip_jira_markup(summary)
    clean_description = strip_jira_markup(description)[:max_description_chars]
    if not clean_description:
        return clean_summary
    return f"{clean_summary}. {clean_description}"
