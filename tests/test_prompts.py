from datetime import date

from flowagent.agent.prompts import build_calendar, build_system_prompt, describe_relative_day
from tests.conftest import FIXED_NOW

TODAY = FIXED_NOW.date()


def test_describe_relative_day_names_weeks_from_monday() -> None:
    """With today Wednesday 14/10, Friday 16/10 is this week and Friday 23/10 is next week."""
    assert describe_relative_day(date(2026, 10, 14), TODAY) == "hôm nay, thứ 4 tuần này"
    assert describe_relative_day(date(2026, 10, 15), TODAY) == "ngày mai, thứ 5 tuần này"
    assert describe_relative_day(date(2026, 10, 16), TODAY) == "ngày kia, thứ 6 tuần này"
    assert describe_relative_day(date(2026, 10, 18), TODAY) == "chủ nhật tuần này"
    assert describe_relative_day(date(2026, 10, 19), TODAY) == "thứ 2 tuần sau"
    assert describe_relative_day(date(2026, 10, 23), TODAY) == "thứ 6 tuần sau"


def test_build_calendar_covers_two_weeks_and_month_end() -> None:
    """The calendar lists 14 days and the last day of the month."""
    lines = build_calendar(TODAY).splitlines()
    assert len(lines) == 15
    assert "2026-10-23 (Thứ Sáu): thứ 6 tuần sau" in lines[9]
    assert lines[-1] == "- Cuối tháng này: 2026-10-31"


def test_system_prompt_contains_calendar() -> None:
    """The system prompt embeds the calendar so the model can look dates up."""
    assert "2026-10-19 (Thứ Hai): thứ 2 tuần sau" in build_system_prompt(FIXED_NOW)
