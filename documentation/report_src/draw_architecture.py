import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

COLORS = {"ui": "#D6EAF8", "agent": "#FDEBD0", "llm": "#E8DAEF", "core": "#D5F5E3", "data": "#F2F3F4", "ml": "#FADBD8"}
fig, ax = plt.subplots(figsize=(12, 8.4))
ax.set_xlim(0, 12)
ax.set_ylim(0, 8.4)
ax.axis("off")


def box(x, y, w, h, title, lines, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12", fc=color, ec="#566573", lw=1.2))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=10.5, fontweight="bold", color="#1B2631")
    ax.text(x + w / 2, y + h - 0.6, "\n".join(lines), ha="center", va="top", fontsize=8.7, color="#283747", linespacing=1.35)


def arrow(start, end, label="", both=False, label_offset=(0.1, 0)):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="<|-|>" if both else "-|>", mutation_scale=13, color="#34495E", lw=1.3))
    if label:
        ax.text((start[0] + end[0]) / 2 + label_offset[0], (start[1] + end[1]) / 2 + label_offset[1], label,
                fontsize=8.2, color="#34495E", ha="left", va="center", style="italic")


box(0.3, 7.0, 11.4, 1.05, "Giao diện Streamlit (app/)", ["Trợ lý chat  ·  Bảng công việc (Kanban)  ·  Lịch  ·  Gantt  ·  Báo cáo & Xuất (.ics/.csv)  ·  Cài đặt API (mã PIN)"], COLORS["ui"])
box(0.3, 4.55, 5.6, 1.95, "FlowAgent service (LangChain create_agent)", ["Middleware: dynamic prompt (ngày giờ + bảng lịch 14 ngày)", "ToolErrorMiddleware · ModelCallLimit (≤ 8 lượt gọi)", "ModelFallback: Gemini → Gemini dự phòng → Groq", "Human-in-the-loop: hỏi trước khi xoá, tạo loạt, dời lịch", "Trí nhớ: lịch sử hội thoại (SQLite) + ghi nhớ dài hạn"], COLORS["agent"])
box(6.5, 4.85, 4.7, 1.35, "Mô hình ngôn ngữ lớn (API miễn phí)", ["Gemini 3.1 Flash-Lite (chính)", "Gemini 3.5 Flash-Lite · Groq gpt-oss-120b (dự phòng)"], COLORS["llm"])
box(0.3, 2.55, 10.9, 1.5, "17 công cụ (tools) — tham số được kiểm tra bằng Pydantic, LLM không ghi trực tiếp vào CSDL", ["Công việc: create / list / update / delete_task · plan_my_day · create_project_plan · predict_priority · list_projects", "Lịch trình (có lặp lại): create_event · list_events · update_event · delete_event", "Quy trình: create_tasks_from_notes · reschedule_tasks · check_schedule · progress_report · remember_fact"], COLORS["core"])
box(0.3, 0.3, 3.4, 1.95, "Lập lịch (planning/)", ["Xếp hạng: độ ưu tiên × độ gấp của hạn", "Xếp lịch tránh giờ bận, cố kịp hạn", "Cảnh báo trùng lịch, nguy cơ trễ hạn", "Báo cáo tiến độ ngày/tuần"], COLORS["core"])
box(4.1, 0.3, 3.4, 1.95, "Mô hình học máy", ["Dự đoán độ ưu tiên", "Embedding đa ngôn ngữ", "+ Logistic Regression", "Dữ liệu: Apache Jira + tiếng Việt"], COLORS["ml"])
box(7.9, 0.3, 3.3, 1.95, "Lưu trữ (SQLModel)", ["SQLite (local) / Postgres (deploy)", "Công việc, dự án, lịch trình, trí nhớ", "API key mã hoá Fernet · PIN scrypt"], COLORS["data"])

arrow((3.1, 7.0), (3.1, 6.5), "câu lệnh / câu trả lời", both=True)
arrow((5.9, 5.5), (6.5, 5.5), "", both=True)
arrow((3.1, 4.55), (3.1, 4.05), "gọi tool / kết quả", both=True)
arrow((2.0, 2.55), (2.0, 2.25))
arrow((5.8, 2.55), (5.8, 2.25))
arrow((9.55, 2.55), (9.55, 2.25), "CRUD")
ax.add_patch(FancyArrowPatch((11.55, 7.0), (11.22, 1.3), connectionstyle="angle,angleA=-90,angleB=0,rad=0", arrowstyle="-|>", mutation_scale=13, color="#34495E", lw=1.3))
ax.text(11.45, 4.45, "đọc / sửa trực tiếp\n(Kanban, Lịch, Gantt)", fontsize=8.2, color="#34495E", ha="right", va="center", style="italic")
plt.title("Kiến trúc hệ thống FlowAgent", fontsize=13, fontweight="bold", pad=6)
plt.savefig("docs/figures/architecture.png", dpi=170, bbox_inches="tight")
print("saved")
