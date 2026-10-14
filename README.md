# FlowAgent

Trợ lý AI quản lý công việc bằng tiếng Việt: thêm, sửa, tìm việc bằng câu nói tự nhiên, gợi ý nên làm gì hôm nay, và chia nhỏ mục tiêu lớn thành kế hoạch có biểu đồ Gantt.

## Tính năng

- Quản lý công việc bằng hội thoại, hiểu mốc thời gian tương đối ("thứ 6 tuần sau", "chiều mai").
- "Hôm nay tôi nên làm gì?": xếp việc theo độ ưu tiên, hạn chót và thời gian rảnh.
- Lập kế hoạch dự án: agent chia mục tiêu thành các bước, tự xếp lịch và hiển thị Gantt.
- Hỏi xác nhận trước thao tác nguy hiểm (xoá).
- Bảng Kanban và cảnh báo việc quá hạn, sắp đến hạn.
- Tự động đổi model khi model chính lỗi (Gemini → Gemini dự phòng → Groq).
- Trang Cài đặt API bảo vệ bằng mã PIN; API key được mã hoá trước khi lưu.

## Công nghệ

Python 3.12 · LangChain/LangGraph (tool-calling agent) · Gemini / Groq · SQLModel (SQLite) · Streamlit · Plotly · cryptography · pytest · ruff · GitHub Actions

## Kiến trúc

```
Streamlit UI (app/)  ──►  FlowAgent service  ──►  LLM chính ─(lỗi)─► LLM dự phòng
                               │
                               ▼ tool calls (validated by Pydantic)
                     tools ──► crud ──► SQLite
                       │
                       └──► planning/scheduler (deterministic ranking & timeline)
```

## Cài đặt

Yêu cầu Python 3.12 và một API key miễn phí của [Google AI Studio](https://aistudio.google.com/apikey) hoặc [Groq](https://console.groq.com/keys).

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
streamlit run app/streamlit_app.py
```

Trình duyệt sẽ mở `http://localhost:8501`. Nhấn **Ctrl+C** trong terminal để tắt app.

## Thiết lập lần đầu

1. Mở trang **🔑 Cài đặt API** ở thanh bên.
2. **Tạo mã PIN** (4 đến 8 chữ số). Những lần sau phải nhập PIN mới vào được trang này.
3. Nhập **Gemini API key** và/hoặc **Groq API key**, bấm **Lưu cài đặt**. Nút con mắt trong ô nhập dùng để ẩn/hiện key.
4. Bấm **Kiểm tra kết nối** để thử từng model trong thứ tự dự phòng.

Thay vì nhập trên trang, bạn có thể điền key vào file `.env`. Key nhập trên trang được ưu tiên hơn; để trống ô thì app dùng key trong `.env`.

> Nên có cả key Gemini lẫn Groq: khi Gemini quá tải, app tự chuyển sang Groq.

## Hướng dẫn sử dụng

### 💬 Trợ lý

Ra lệnh bằng tiếng Việt tự nhiên:

| Mục đích | Ví dụ |
|---|---|
| Thêm việc | "Thêm việc nộp báo cáo vào thứ 6 tuần sau, ưu tiên cao" |
| Thêm việc có ngày bắt đầu | "Làm slide từ thứ 2, hạn thứ 4, khoảng 3 tiếng" |
| Xem việc | "Tuần này tôi có việc gì?", "Liệt kê việc ưu tiên cao" |
| Sửa việc | "Dời hạn việc nộp báo cáo sang chủ nhật" |
| Đánh dấu xong | "Tôi đã làm xong việc nộp báo cáo" |
| Xoá việc | "Xoá việc gọi điện cho mẹ" (app hỏi xác nhận trước khi xoá) |
| Gợi ý trong ngày | "Hôm nay tôi nên làm gì?", "Hôm nay tôi rảnh 3 tiếng, nên làm gì?" |
| Lập kế hoạch dự án | "Tôi muốn làm website bán hàng trong 2 tuần, lập kế hoạch giúp tôi" |

- Chỉ nói ngày mà không nói giờ: hạn chót tính đến **23:59**, ngày bắt đầu tính từ **09:00**.
- Độ ưu tiên: "gấp" là khẩn cấp, "quan trọng" là cao, "thấp" là thấp, còn lại là trung bình.
- Dòng "Trả lời bởi …" dưới mỗi câu trả lời cho biết model nào đã xử lý.

### 📋 Bảng công việc

- Ba cột **Cần làm**, **Đang làm**, **Hoàn thành**. Bấm ◀ hoặc ▶ để chuyển việc giữa các cột.
- Banner đỏ báo việc quá hạn, banner vàng báo việc đến hạn trong 24 giờ.
- **Thêm công việc** để nhập tay, chọn được ngày giờ bắt đầu, hạn chót và thời lượng. Ngày bắt đầu phải trước hoặc bằng hạn chót.

### 📅 Gantt

- Chọn **Tất cả công việc** hoặc một dự án.
- Chỉ việc có **ngày bắt đầu** mới hiện trên biểu đồ. Việc tạo bằng lệnh lập kế hoạch dự án luôn có sẵn ngày bắt đầu.

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| "Máy chủ AI đang quá tải" hoặc "hết lượt gọi miễn phí" | Đợi khoảng 1 phút rồi thử lại, hoặc thêm key Groq để có model dự phòng |
| "Tên model không tồn tại" | Vào Cài đặt API và đổi tên model, ví dụ `gemini-3.5-flash-lite` |
| Sửa `.env` nhưng app không nhận | Tắt app (Ctrl+C) và chạy lại |
| Quên mã PIN | Chạy `flowagent-reset-pin` (trong venv) và gõ `RESET`. Lệnh này xoá mã PIN và API key đã lưu trong app; công việc và dự án được giữ nguyên |
| Muốn xoá toàn bộ dữ liệu | Tắt app rồi xoá thư mục `data/`. Mọi công việc sẽ mất |

## Dữ liệu

| File | Nội dung |
|---|---|
| `data/flowagent.db` | Công việc, dự án, mã PIN (đã băm) và API key (đã mã hoá) |
| `data/secret.key` | Khoá giải mã API key. Mất file này thì phải nhập lại key |

Lịch sử chat chỉ lưu trong bộ nhớ và mất khi tắt app. Công việc vẫn được giữ trong database.

## Kiểm thử

```bash
pytest
ruff check . && ruff format --check .
```
