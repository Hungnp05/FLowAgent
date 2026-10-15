from datetime import datetime
from urllib.parse import quote

import streamlit as st

from flowagent.agent.formatting import format_progress_report
from flowagent.clock import now_local
from flowagent.config import get_settings
from flowagent.db import crud
from flowagent.db.session import session_scope
from flowagent.exports import build_ics, build_tasks_csv
from flowagent.planning.progress import ProgressReport, ReportPeriod, build_progress_report
from views.shared import get_engine, load_tasks

PERIOD_LABELS = {ReportPeriod.DAY: "Hôm nay", ReportPeriod.WEEK: "Tuần này"}
MAILTO_BODY_LIMIT = 1500
TRUNCATED_NOTE = "\n...(bản đầy đủ nằm trong file báo cáo tải về)"
RECIPIENT_SAFE_CHARACTERS = "@,"


def build_mailto_link(recipients: str, subject: str, body: str) -> str:
    """Build a mailto link that opens the user's mail app with the report filled in."""
    short_body = (
        body if len(body) <= MAILTO_BODY_LIMIT else body[:MAILTO_BODY_LIMIT] + TRUNCATED_NOTE
    )
    address = quote(recipients.replace(" ", ""), safe=RECIPIENT_SAFE_CHARACTERS)
    return f"mailto:{address}?subject={quote(subject)}&body={quote(short_body)}"


def render_report_metrics(report: ProgressReport) -> None:
    """Show the headline counts of a progress report."""
    counts = {
        "Đã hoàn thành": len(report.completed),
        "Đúng hạn": report.on_time_count,
        "Đang làm": len(report.in_progress),
        "Trễ hạn": len(report.overdue),
        "Đến hạn 7 ngày tới": len(report.upcoming),
    }
    for column, (label, value) in zip(st.columns(len(counts)), counts.items(), strict=True):
        column.metric(label, value)


def render_share_buttons(markdown: str, period: ReportPeriod, now: datetime) -> None:
    """Offer the report as a Markdown download and as a pre-filled email draft."""
    download_column, email_column = st.columns(2, vertical_alignment="bottom")
    download_column.download_button(
        "Tải báo cáo (.md)",
        markdown,
        icon=":material/download:",
        file_name=f"bao-cao-{period.value}-{now:%Y%m%d}.md",
        mime="text/markdown",
        width="stretch",
    )
    recipients = email_column.text_input("Gửi tới (email, cách nhau bởi dấu phẩy)")
    subject = f"Báo cáo tiến độ {PERIOD_LABELS[period].lower()} {now:%d/%m/%Y}"
    st.link_button(
        "Soạn email báo cáo",
        build_mailto_link(recipients, subject, markdown),
        icon=":material/mail:",
        width="stretch",
    )
    st.caption(
        "Nút này mở ứng dụng email của bạn với nội dung điền sẵn; FlowAgent không tự gửi thư."
    )


def render_report_section() -> None:
    """Show the daily or weekly progress report with sharing options."""
    st.subheader("Báo cáo tiến độ")
    period = st.segmented_control(
        "Kỳ báo cáo", list(ReportPeriod), default=ReportPeriod.WEEK, format_func=PERIOD_LABELS.get
    )
    period = period or ReportPeriod.WEEK
    now = now_local()
    report = build_progress_report(load_tasks(), period, now)
    render_report_metrics(report)
    markdown = format_progress_report(report)
    with st.container(border=True):
        st.markdown(markdown)
    render_share_buttons(markdown, period, now)
    st.caption("Muốn bản tóm tắt bằng lời? Hỏi Trợ lý: “Tóm tắt tiến độ tuần này”.")


def render_export_section() -> None:
    """Offer calendar (.ics) and task (.csv) files for other apps to import."""
    st.subheader("Xuất sang ứng dụng khác")
    with session_scope(get_engine()) as session:
        events, projects = list(crud.list_events(session)), list(crud.list_projects(session))
    tasks = load_tasks()
    ics_column, csv_column = st.columns(2)
    ics_column.download_button(
        "Lịch (.ics) cho Google Calendar / Outlook",
        build_ics(events, tasks, now_local(), get_settings().timezone).encode("utf-8"),
        icon=":material/event:",
        file_name="flowagent.ics",
        mime="text/calendar",
        width="stretch",
    )
    csv_column.download_button(
        "Công việc (.csv) cho Excel / Sheets / Notion / Trello",
        build_tasks_csv(tasks, projects),
        icon=":material/table_view:",
        file_name="flowagent-tasks.csv",
        mime="text/csv",
        width="stretch",
    )
    st.caption(
        "Google Calendar: Cài đặt → Nhập và xuất → Nhập. Outlook: Thêm lịch → Tải lên từ tệp. "
        "Notion/Trello/Sheets: dùng chức năng Import CSV. Lịch lặp lại và nhắc nhở được giữ nguyên."
    )


def render_report_page() -> None:
    """Render the progress report and export page."""
    st.title("Báo cáo & Xuất dữ liệu")
    render_report_section()
    st.divider()
    render_export_section()
