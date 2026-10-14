import logging
import uuid

import streamlit as st

from flowagent.agent.llm import describe_llm_error
from flowagent.agent.service import AgentReply, FlowAgent
from flowagent.errors import MissingApiKeyError, SecretDecryptionError
from views.shared import get_agent

logger = logging.getLogger(__name__)

CHAT_EXAMPLES = (
    "Thêm việc nộp báo cáo vào thứ 6 tuần sau, ưu tiên cao",
    "Hôm nay tôi nên làm gì?",
    "Tôi muốn làm website bán hàng trong 2 tuần, lập kế hoạch giúp tôi",
)


def init_chat_state() -> None:
    """Give each browser session its own conversation thread and history."""
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pending_confirmation", None)


def record_reply(reply: AgentReply) -> None:
    """Store the agent reply in the chat history and remember any pending confirmation."""
    st.session_state.chat_history.append(
        {"role": "assistant", "content": reply.text, "model": reply.model_name}
    )
    st.session_state.pending_confirmation = reply.pending_confirmation


def run_agent_safely(agent: FlowAgent, action: str, **kwargs: object) -> None:
    """Call an agent method and surface LLM or network failures in the UI instead of crashing."""
    try:
        with st.spinner("FlowAgent đang xử lý..."):
            record_reply(getattr(agent, action)(st.session_state.thread_id, **kwargs))
    except Exception as error:
        logger.exception("Agent call failed")
        st.session_state.chat_history.append(
            {"role": "assistant", "content": f"⚠️ {describe_llm_error(error)}"}
        )


def render_message(message: dict[str, str | None]) -> None:
    """Show one chat message, noting which model wrote an assistant reply."""
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("model"):
            st.caption(f"Trả lời bởi {message['model']}")


def render_confirmation(agent: FlowAgent) -> None:
    """Show the pending destructive action with approve and cancel buttons."""
    pending = st.session_state.pending_confirmation
    st.warning(f"Xác nhận xoá công việc?\n\n{pending['summary']}")
    approve_column, cancel_column = st.columns(2)
    if approve_column.button("Xác nhận xoá", type="primary", width="stretch"):
        run_agent_safely(agent, "resolve_confirmation", is_approved=True)
        st.rerun()
    if cancel_column.button("Huỷ", width="stretch"):
        run_agent_safely(agent, "resolve_confirmation", is_approved=False)
        st.rerun()


def render_chat_page() -> None:
    """Render the conversational assistant page."""
    st.title("💬 Trợ lý FlowAgent")
    init_chat_state()
    try:
        agent = get_agent()
    except (MissingApiKeyError, SecretDecryptionError) as error:
        st.warning(f"{error} Mở trang **Cài đặt API** ở thanh bên để thêm key.")
        return
    if not st.session_state.chat_history:
        st.caption("Ví dụ: " + " · ".join(f"“{example}”" for example in CHAT_EXAMPLES))
    for message in st.session_state.chat_history:
        render_message(message)
    if st.session_state.pending_confirmation:
        render_confirmation(agent)
        return
    if user_text := st.chat_input("Nhập yêu cầu của bạn..."):
        st.session_state.chat_history.append({"role": "user", "content": user_text})
        run_agent_safely(agent, "send", user_text=user_text)
        st.rerun()
