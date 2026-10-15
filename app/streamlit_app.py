import streamlit as st
from views.board import render_board_page
from views.calendar_page import render_calendar_page
from views.chat import render_chat_page
from views.gantt import render_gantt_page
from views.report import render_report_page
from views.settings import render_settings_page

st.set_page_config(page_title="FlowAgent", page_icon="🗂️", layout="wide")
st.navigation(
    [
        st.Page(render_chat_page, title="Trợ lý", icon="💬", default=True),
        st.Page(render_board_page, title="Bảng công việc", icon="📋"),
        st.Page(render_calendar_page, title="Lịch", icon="🗓️"),
        st.Page(render_gantt_page, title="Gantt", icon="📅"),
        st.Page(render_report_page, title="Báo cáo & Xuất", icon="📊"),
        st.Page(render_settings_page, title="Cài đặt API", icon="🔑"),
    ]
).run()
