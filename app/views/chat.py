import logging

import streamlit as st

from flowagent.agent.llm import describe_llm_error
from flowagent.agent.service import ChatMessage, FlowAgent
from flowagent.db.models import MAX_MEMORY_LENGTH
from flowagent.errors import MissingApiKeyError, SecretDecryptionError
from views.shared import (
    add_memory,
    forget_memory,
    get_agent,
    get_chat_thread_id,
    load_memories,
    start_new_chat_thread,
)

logger = logging.getLogger(__name__)

CHAT_EXAMPLES = (
    "Thêm việc nộp báo cáo vào thứ 6 tuần sau, ưu tiên cao",
    "Hôm nay tôi nên làm gì?",
    "Tôi muốn làm website bán hàng trong 2 tuần, lập kế hoạch giúp tôi",
    "Tóm tắt tiến độ tuần này",
    "Lịch tuần này có bị trùng không?",
)
NOTICES_KEY = "chat_notices"
CONFIRMATION_TEXTS = {
    "delete_task": ("Xác nhận xoá công việc?", "Xác nhận xoá"),
    "delete_event": ("Xác nhận xoá lịch trình?", "Xác nhận xoá"),
    "create_tasks_from_notes": ("Tạo các việc sau từ biên bản?", "Tạo công việc"),
    "reschedule_tasks": ("Áp dụng lịch mới cho các việc sau?", "Áp dụng"),
}
DEFAULT_CONFIRMATION = ("Xác nhận thao tác?", "Đồng ý")


def run_agent_safely(agent: FlowAgent, action: str, **kwargs: object) -> None:
    """Call an agent method and surface LLM or network failures in the UI instead of crashing."""
    st.session_state[NOTICES_KEY] = []
    try:
        with st.spinner("FlowAgent đang xử lý..."):
            getattr(agent, action)(get_chat_thread_id(), **kwargs)
    except Exception as error:
        logger.exception("Agent call failed")
        st.session_state[NOTICES_KEY] = [describe_llm_error(error)]


def render_message(message: ChatMessage) -> None:
    """Show one chat message, noting which model wrote an assistant reply."""
    with st.chat_message(message.role):
        st.markdown(message.text)
        if message.model_name:
            st.caption(f"Trả lời bởi {message.model_name}")


def render_confirmation(agent: FlowAgent, pending: dict) -> None:
    """Show the pending action with approve and cancel buttons."""
    question, approve_label = CONFIRMATION_TEXTS.get(pending.get("action"), DEFAULT_CONFIRMATION)
    st.warning(f"{question}\n\n{pending['summary']}", icon=":material/help:")
    approve_column, cancel_column = st.columns(2)
    if approve_column.button(
        approve_label, icon=":material/check:", type="primary", width="stretch"
    ):
        run_agent_safely(agent, "resolve_confirmation", is_approved=True)
        st.rerun()
    if cancel_column.button("Huỷ", icon=":material/close:", width="stretch"):
        run_agent_safely(agent, "resolve_confirmation", is_approved=False)
        st.rerun()


def render_memory_panel() -> None:
    """List remembered facts in the sidebar with delete buttons and a field to add one."""
    with st.sidebar.expander("Trí nhớ dài hạn", icon=":material/psychology:"):
        memories = load_memories()
        if not memories:
            st.caption("Trợ lý chưa ghi nhớ điều gì. Hãy kể về thói quen làm việc của bạn.")
        for memory in memories:
            text_column, delete_column = st.columns([5, 1], vertical_alignment="center")
            text_column.markdown(memory.content)
            if delete_column.button(
                "", icon=":material/delete:", key=f"forget-{memory.id}", help="Quên điều này"
            ):
                forget_memory(memory.id)
                st.rerun()
        with st.form("add-memory", clear_on_submit=True, border=False):
            new_fact = st.text_input("Thêm điều cần nhớ", max_chars=MAX_MEMORY_LENGTH)
            if (
                st.form_submit_button("Ghi nhớ", icon=":material/bookmark_add:")
                and new_fact.strip()
            ):
                add_memory(new_fact)
                st.rerun()


def render_chat_sidebar() -> None:
    """Show the new-conversation button and the memory panel."""
    if st.sidebar.button("Cuộc trò chuyện mới", icon=":material/add_comment:", width="stretch"):
        start_new_chat_thread()
        st.session_state[NOTICES_KEY] = []
        st.rerun()
    render_memory_panel()


def render_chat_page() -> None:
    """Render the conversational assistant page."""
    st.title("Trợ lý FlowAgent")
    render_chat_sidebar()
    try:
        agent = get_agent()
    except (MissingApiKeyError, SecretDecryptionError) as error:
        st.warning(f"{error} Mở trang **Cài đặt API** ở thanh bên để thêm key.")
        return
    thread_id = get_chat_thread_id()
    history = agent.history(thread_id)
    if not history:
        st.caption("Ví dụ: " + " · ".join(f"“{example}”" for example in CHAT_EXAMPLES))
    for message in history:
        render_message(message)
    for notice in st.session_state.get(NOTICES_KEY, []):
        st.error(notice, icon=":material/error:")
    if pending := agent.pending_confirmation(thread_id):
        render_confirmation(agent, pending)
        return
    if user_text := st.chat_input("Nhập yêu cầu hoặc dán biên bản họp..."):
        render_message(ChatMessage(role="user", text=user_text))
        run_agent_safely(agent, "send", user_text=user_text)
        st.rerun()
