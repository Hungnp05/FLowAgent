# FlowAgent

Trợ lý AI quản lý công việc bằng tiếng Việt: thêm, sửa, tìm việc bằng câu nói tự nhiên, gợi ý nên làm gì hôm nay, và chia nhỏ mục tiêu lớn thành kế hoạch có biểu đồ Gantt.

## Tính năng

- Quản lý công việc bằng hội thoại, hiểu mốc thời gian tương đối ("thứ 6 tuần sau", "chiều mai").
- "Hôm nay tôi nên làm gì?": xếp việc theo độ ưu tiên, hạn chót và thời gian rảnh.
- Lập kế hoạch dự án: agent chia mục tiêu thành các bước, tự xếp lịch và hiển thị Gantt.
- Hỏi xác nhận trước thao tác nguy hiểm (xoá).
- Bảng Kanban và cảnh báo việc quá hạn, sắp đến hạn.

## Công nghệ

Python 3.12 · LangChain/LangGraph (tool-calling agent) · Gemini / Groq · SQLModel (SQLite) · Streamlit · Plotly · pytest · ruff · GitHub Actions

## Kiến trúc

```
Streamlit UI (app/)  ──►  FlowAgent service  ──►  LLM (Gemini/Groq)
                               │
                               ▼ tool calls (validated by Pydantic)
                     tools ──► crud ──► SQLite
                       │
                       └──► planning/scheduler (deterministic ranking & timeline)
```

## Chạy dự án

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # rồi điền GEMINI_API_KEY hoặc GROQ_API_KEY
streamlit run app/streamlit_app.py
```

Không có API key thì bảng công việc và Gantt vẫn chạy, chỉ trang Trợ lý bị tắt.

## Kiểm thử

```bash
pytest
ruff check . && ruff format --check .
```
