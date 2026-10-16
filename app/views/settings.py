import streamlit as st

from flowagent.agent.llm import check_model_connection, plan_model_chain
from flowagent.agent.llm_config import LlmConfig, read_stored_value, save_llm_config
from flowagent.clock import now_local
from flowagent.config import get_settings
from flowagent.db.app_settings import SettingKey
from flowagent.db.session import session_scope
from flowagent.errors import InvalidPinError, MissingApiKeyError, SecretDecryptionError
from flowagent.security.pin_guard import attempt_unlock, change_pin, create_pin, has_pin
from views.shared import (
    get_engine,
    get_secret_box,
    get_visitor_keys,
    is_public_mode,
    load_current_llm_config,
    set_visitor_keys,
)

UNLOCKED_STATE_KEY = "settings_unlocked"
PIN_MAX_LENGTH = 8
PROVIDER_LABELS = {"gemini": "Google Gemini", "groq": "Groq"}
ENV_KEY_PLACEHOLDER = "Để trống để dùng key trong file .env"
VISITOR_KEY_NOTICE = (
    "Đây là bản demo công khai: mỗi người dùng API key miễn phí của chính mình. Key chỉ được "
    "giữ trong phiên trình duyệt này, không lưu lên máy chủ và mất khi bạn đóng tab. Dữ liệu "
    "công việc của bạn cũng là dữ liệu mẫu riêng cho phiên này."
)
FREE_KEY_LINKS = (
    "Lấy key miễn phí: [Google AI Studio](https://aistudio.google.com/apikey) · "
    "[Groq Console](https://console.groq.com/keys)"
)


def pin_input(label: str, key: str) -> str:
    """Render a masked PIN field with a show/hide toggle."""
    return st.text_input(label, type="password", max_chars=PIN_MAX_LENGTH, key=key)


def mark_unlocked() -> None:
    """Unlock the settings page for this browser session and refresh it."""
    st.session_state[UNLOCKED_STATE_KEY] = True
    st.rerun()


def render_create_pin_form() -> None:
    """Ask a first-time user to create the PIN that guards this page."""
    st.info("Lần đầu sử dụng: hãy tạo mã PIN (4 đến 8 chữ số) để bảo vệ trang cài đặt API key.")
    with st.form("create_pin"):
        pin = pin_input("Mã PIN mới", "new-pin")
        confirmation = pin_input("Nhập lại mã PIN", "new-pin-confirm")
        is_submitted = st.form_submit_button("Tạo mã PIN", type="primary")
    if not is_submitted:
        return
    try:
        with session_scope(get_engine()) as session:
            create_pin(session, pin, confirmation)
    except InvalidPinError as error:
        st.error(str(error))
        return
    mark_unlocked()


def render_unlock_form() -> None:
    """Ask for the PIN before showing stored API keys."""
    with st.form("unlock"):
        pin = pin_input("Nhập mã PIN để mở trang cài đặt", "unlock-pin")
        is_submitted = st.form_submit_button("Mở khoá", icon=":material/lock_open:", type="primary")
    if not is_submitted:
        return
    with session_scope(get_engine()) as session:
        result = attempt_unlock(session, pin, now_local())
    if not result.is_unlocked:
        st.error(result.message)
        return
    mark_unlocked()


def load_saved_api_keys() -> tuple[str, str]:
    """Return the Gemini and Groq keys saved in the app, blank when .env is used instead."""
    box = get_secret_box()
    with session_scope(get_engine()) as session:
        gemini_key = read_stored_value(session, SettingKey.GEMINI_API_KEY, box) or ""
        groq_key = read_stored_value(session, SettingKey.GROQ_API_KEY, box) or ""
    return gemini_key, groq_key


def render_api_key_form(config: LlmConfig) -> None:
    """Edit API keys and model names; keys are encrypted before they are saved."""
    saved_gemini_key, saved_groq_key = load_saved_api_keys()
    with st.form("api_keys"):
        provider = st.radio(
            "Nhà cung cấp chính",
            list(PROVIDER_LABELS),
            index=list(PROVIDER_LABELS).index(config.llm_provider),
            format_func=PROVIDER_LABELS.get,
            horizontal=True,
        )
        st.markdown("**Google Gemini**")
        gemini_api_key = st.text_input(
            "Gemini API key", saved_gemini_key, type="password", placeholder=ENV_KEY_PLACEHOLDER
        )
        gemini_model = st.text_input("Model chính", config.gemini_model)
        gemini_fallback_model = st.text_input("Model dự phòng", config.gemini_fallback_model)
        st.markdown("**Groq**")
        groq_api_key = st.text_input(
            "Groq API key", saved_groq_key, type="password", placeholder=ENV_KEY_PLACEHOLDER
        )
        groq_model = st.text_input("Model Groq", config.groq_model)
        is_submitted = st.form_submit_button("Lưu cài đặt", icon=":material/save:", type="primary")
    if not is_submitted:
        return
    new_config = LlmConfig(
        llm_provider=provider,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_fallback_model=gemini_fallback_model,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
    )
    with session_scope(get_engine()) as session:
        save_llm_config(session, new_config, get_secret_box())
    st.success("Đã lưu. Trợ lý sẽ dùng cấu hình mới từ tin nhắn tiếp theo.")


def render_connection_check(config: LlmConfig) -> None:
    """Show the fallback order and let the user test every model in it."""
    st.subheader("Thứ tự tự động đổi model")
    try:
        chain = plan_model_chain(config)
    except MissingApiKeyError as error:
        st.warning(str(error))
        return
    st.caption(" → ".join(spec.label for spec in chain))
    if not st.button("Kiểm tra kết nối", icon=":material/network_check:"):
        return
    for spec in chain:
        with st.spinner(f"Đang thử {spec.label}..."):
            error_hint = check_model_connection(spec, get_settings())
        if error_hint:
            st.error(f"{spec.label}: {error_hint}")
        else:
            st.success(f"{spec.label}: hoạt động tốt")


def render_change_pin_form() -> None:
    """Let an unlocked user replace the PIN after confirming the current one."""
    with st.expander("Đổi mã PIN", icon=":material/password:"), st.form("change_pin"):
        current_pin = pin_input("Mã PIN hiện tại", "current-pin")
        new_pin = pin_input("Mã PIN mới", "changed-pin")
        confirmation = pin_input("Nhập lại mã PIN mới", "changed-pin-confirm")
        if not st.form_submit_button("Đổi mã PIN"):
            return
        try:
            with session_scope(get_engine()) as session:
                result = change_pin(session, current_pin, new_pin, confirmation, now_local())
        except InvalidPinError as error:
            st.error(str(error))
            return
        if result.is_unlocked:
            st.success("Đã đổi mã PIN.")
        else:
            st.error(result.message)


def render_unlocked_settings() -> None:
    """Render the API settings, connection check and PIN management for an unlocked session."""
    if st.button("Khoá lại", icon=":material/lock:"):
        st.session_state[UNLOCKED_STATE_KEY] = False
        st.rerun()
    st.caption("API key được mã hoá trước khi lưu và được ưu tiên hơn file .env.")
    try:
        config = load_current_llm_config()
    except SecretDecryptionError as error:
        st.error(str(error))
        return
    render_api_key_form(config)
    render_connection_check(load_current_llm_config())
    render_change_pin_form()


def render_visitor_key_form() -> None:
    """Let a public visitor enter their own keys, kept only in this browser session."""
    provider, gemini_key, groq_key = get_visitor_keys()
    with st.form("visitor_keys"):
        new_provider = st.radio(
            "Nhà cung cấp chính",
            list(PROVIDER_LABELS),
            index=list(PROVIDER_LABELS).index(provider),
            format_func=PROVIDER_LABELS.get,
            horizontal=True,
        )
        new_gemini_key = st.text_input("Gemini API key", gemini_key, type="password")
        new_groq_key = st.text_input("Groq API key", groq_key, type="password")
        is_submitted = st.form_submit_button("Dùng key này", icon=":material/key:", type="primary")
    if is_submitted:
        set_visitor_keys(new_provider, new_gemini_key, new_groq_key)
        st.success("Đã lưu key cho phiên này. Mở trang Trợ lý để bắt đầu trò chuyện.")


def render_visitor_settings() -> None:
    """Show the bring-your-own-key form used by the public demo instead of the PIN flow."""
    st.info(VISITOR_KEY_NOTICE, icon=":material/info:")
    st.markdown(FREE_KEY_LINKS)
    render_visitor_key_form()
    if st.button("Xoá key khỏi phiên", icon=":material/delete:"):
        set_visitor_keys("gemini", "", "")
        st.rerun()
    render_connection_check(load_current_llm_config())


def render_settings_page() -> None:
    """Guard the API settings behind a PIN, creating one on first visit."""
    st.title("Cài đặt API")
    if is_public_mode():
        render_visitor_settings()
        return
    with session_scope(get_engine()) as session:
        is_pin_created = has_pin(session)
    if not is_pin_created:
        render_create_pin_form()
    elif not st.session_state.get(UNLOCKED_STATE_KEY):
        render_unlock_form()
    else:
        render_unlocked_settings()
