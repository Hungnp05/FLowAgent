import pytest

from flowagent.agent.llm import describe_llm_error


@pytest.mark.parametrize(
    ("error_message", "expected_fragment"),
    [
        ("404 NOT_FOUND. models/gemini-2.5-flash is no longer available", "Tên model"),
        ("429 RESOURCE_EXHAUSTED. Quota exceeded", "hết lượt"),
        ("400 API_KEY_INVALID", "API key"),
        ("503 UNAVAILABLE. This model is currently experiencing high demand", "quá tải"),
        ("504 DEADLINE_EXCEEDED", "quá lâu"),
    ],
)
def test_describe_llm_error_maps_known_failures(error_message: str, expected_fragment: str) -> None:
    """Known provider failures map to an actionable Vietnamese hint."""
    assert expected_fragment in describe_llm_error(RuntimeError(error_message))


def test_describe_llm_error_falls_back_to_exception_type() -> None:
    """Unknown failures still name the exception type for debugging."""
    assert "ValueError" in describe_llm_error(ValueError("something odd"))
