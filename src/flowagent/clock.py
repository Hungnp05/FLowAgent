from datetime import datetime
from zoneinfo import ZoneInfo

from flowagent.config import get_settings


def now_local() -> datetime:
    """Return the current wall-clock time in the configured timezone, without tzinfo."""
    return datetime.now(ZoneInfo(get_settings().timezone)).replace(tzinfo=None, microsecond=0)
