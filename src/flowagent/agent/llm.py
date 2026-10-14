from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from flowagent.agent.llm_config import LlmConfig
from flowagent.config import LlmProvider, Settings
from flowagent.errors import MissingApiKeyError

CONNECTION_CHECK_PROMPT = "Trả lời đúng 1 từ: OK"
LLM_ERROR_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("NOT_FOUND", "404", "model_not_found"),
        "Tên model không tồn tại hoặc đã ngừng hỗ trợ, hãy kiểm tra tên model trong Cài đặt API.",
    ),
    (
        ("RESOURCE_EXHAUSTED", "429", "rate limit", "quota"),
        "Đã hết lượt gọi miễn phí trong lúc này, hãy đợi khoảng 1 phút rồi thử lại.",
    ),
    (
        ("API_KEY_INVALID", "PERMISSION_DENIED", "401", "403", "invalid api key"),
        "API key không hợp lệ hoặc không có quyền, hãy kiểm tra lại key trong Cài đặt API.",
    ),
    (
        ("UNAVAILABLE", "503", "high demand", "overloaded"),
        "Máy chủ AI đang quá tải, hãy thử lại sau ít phút hoặc đổi sang model khác.",
    ),
    (("timeout", "timed out", "DEADLINE_EXCEEDED"), "Mô hình phản hồi quá lâu, hãy thử lại."),
)


@dataclass(frozen=True)
class ModelSpec:
    provider: LlmProvider
    model_name: str
    api_key: str

    @property
    def label(self) -> str:
        """Return a short human-readable name like 'gemini / gemini-3.1-flash-lite'."""
        return f"{self.provider} / {self.model_name}"


def plan_model_chain(config: LlmConfig) -> list[ModelSpec]:
    """Order usable models: primary provider first, then its fallback, then the other provider."""
    gemini_specs = [
        ModelSpec("gemini", config.gemini_model, config.gemini_api_key),
        ModelSpec("gemini", config.gemini_fallback_model, config.gemini_api_key),
    ]
    groq_specs = [ModelSpec("groq", config.groq_model, config.groq_api_key)]
    is_gemini_primary = config.llm_provider == "gemini"
    ordered = gemini_specs + groq_specs if is_gemini_primary else groq_specs + gemini_specs
    usable: list[ModelSpec] = []
    for spec in ordered:
        if spec.api_key and spec.model_name and spec not in usable:
            usable.append(spec)
    if not usable:
        raise MissingApiKeyError("Chưa có API key nào, hãy thêm key ở trang Cài đặt API.")
    return usable


def build_chat_model(spec: ModelSpec, settings: Settings) -> BaseChatModel:
    """Create the LangChain chat model for one provider and model name."""
    if spec.provider == "groq":
        return ChatGroq(
            model=spec.model_name,
            api_key=spec.api_key,
            temperature=settings.llm_temperature,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
        )
    return ChatGoogleGenerativeAI(
        model=spec.model_name,
        api_key=spec.api_key,
        temperature=settings.llm_temperature,
        retries=settings.llm_max_retries,
        request_timeout=settings.llm_timeout_seconds,
    )


def check_model_connection(spec: ModelSpec, settings: Settings) -> str | None:
    """Send a tiny prompt to one model and return an error hint, or None when it answers."""
    try:
        build_chat_model(spec, settings).invoke(CONNECTION_CHECK_PROMPT)
    except Exception as error:
        return describe_llm_error(error)
    return None


def describe_llm_error(error: Exception) -> str:
    """Translate a provider exception into a short Vietnamese hint the user can act on."""
    error_text = f"{type(error).__name__} {error}".lower()
    for markers, hint in LLM_ERROR_HINTS:
        if any(marker.lower() in error_text for marker in markers):
            return hint
    return f"Lỗi không xác định khi gọi mô hình AI ({type(error).__name__})."
