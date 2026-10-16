# FlowAgent

Trợ lý AI quản lý công việc bằng tiếng Việt: thêm, sửa, tìm việc bằng câu nói tự nhiên, gợi ý nên làm gì hôm nay, và chia nhỏ mục tiêu lớn thành kế hoạch có biểu đồ Gantt.

## Tính năng

- Quản lý công việc bằng hội thoại, hiểu mốc thời gian tương đối ("thứ 6 tuần sau", "chiều mai").
- "Hôm nay tôi nên làm gì?": xếp việc theo độ ưu tiên, hạn chót và thời gian rảnh.
- Lập kế hoạch dự án: agent chia mục tiêu thành các bước, tự xếp lịch quanh các lịch đã bận, cố kịp thời hạn người dùng đặt ("xong trước thứ 6") và hiển thị Gantt.
- Dán biên bản họp: agent trích các việc cần làm (người phụ trách, hạn chót) và tóm tắt các quyết định.
- Tự xếp lại lịch khi có việc trễ hạn hoặc việc phát sinh chen vào (hỏi xác nhận trước khi áp dụng).
- Cảnh báo lịch trùng giờ và việc có nguy cơ trễ hạn; báo cáo tiến độ ngày/tuần, tải về hoặc soạn email.
- Trí nhớ: lịch sử trò chuyện được lưu lại sau khi tắt app; trợ lý ghi nhớ lâu dài thói quen của người dùng.
- Xuất lịch `.ics` (Google Calendar, Outlook) và công việc `.csv` (Excel, Sheets, Notion, Trello).
- Lịch tuần/tháng/năm/ngày với lịch trình lặp lại (hằng ngày, hằng tuần...); trợ lý tạo được lịch lặp, ví dụ "tập gym 18h–20h hằng ngày".
- Hỏi xác nhận trước thao tác nguy hiểm (xoá).
- Bảng Kanban và cảnh báo việc quá hạn, sắp đến hạn.
- Tự động đổi model khi model chính lỗi (Gemini → Gemini dự phòng → Groq).
- Trang Cài đặt API bảo vệ bằng mã PIN; API key được mã hoá trước khi lưu.
- Mô hình học máy gợi ý độ ưu tiên khi người dùng không nói rõ, huấn luyện trên 36.000 issue thật của Apache cộng 603 công việc tiếng Việt tổng hợp.

## Công nghệ

Python 3.12 · LangChain/LangGraph (tool-calling agent) · Gemini / Groq · scikit-learn · fastembed (multilingual embeddings) · SQLModel (SQLite) · Streamlit · Plotly · cryptography · pytest · ruff · GitHub Actions

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

1. Mở trang **Cài đặt API** ở thanh bên.
2. **Tạo mã PIN** (4 đến 8 chữ số). Những lần sau phải nhập PIN mới vào được trang này.
3. Nhập **Gemini API key** và/hoặc **Groq API key**, bấm **Lưu cài đặt**. Nút con mắt trong ô nhập dùng để ẩn/hiện key.
4. Bấm **Kiểm tra kết nối** để thử từng model trong thứ tự dự phòng.

Thay vì nhập trên trang, bạn có thể điền key vào file `.env`. Key nhập trên trang được ưu tiên hơn; để trống ô thì app dùng key trong `.env`.

> Nên có cả key Gemini lẫn Groq: khi Gemini quá tải, app tự chuyển sang Groq.

## Bản demo công khai

Bản online: **https://flowagent123.streamlit.app**

Bản này chạy ở **chế độ công khai** (`PUBLIC_MODE=true`):

- Mỗi người dùng **API key miễn phí của chính mình**: mở trang **Cài đặt API**, dán key Gemini (lấy ở [Google AI Studio](https://aistudio.google.com/apikey)) hoặc Groq (lấy ở [Groq Console](https://console.groq.com/keys)). Key chỉ nằm trong phiên trình duyệt đó, không lưu lên máy chủ và mất khi đóng tab.
- Mỗi phiên có **dữ liệu mẫu riêng** (việc cá nhân, một dự án đã lập kế hoạch, lịch lặp, ghi nhớ) để thử ngay. Không ai thấy dữ liệu của ai; dữ liệu mất khi đóng tab.
- Không có mã PIN, vì không có key nào được lưu.

Để tự triển khai bản công khai trên Streamlit Community Cloud: đặt `PUBLIC_MODE = "true"` trong **Settings → Secrets** và không cần đặt API key nào. Khi chạy ở máy cá nhân, để `PUBLIC_MODE=false` (mặc định) thì app dùng CSDL thật, key trong `.env` hoặc trang Cài đặt API có mã PIN.

> Sau mỗi lần push có thay đổi trong `src/`, vào **Manage app → Reboot app**. Streamlit Cloud chỉ tự nạp lại mã trong `app/`; gói `flowagent` trong `src/` vẫn là bản cũ trong bộ nhớ cho tới khi app khởi động lại, gây lỗi `ImportError: cannot import name ...`.

## Hướng dẫn sử dụng

### Trợ lý

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
| Biên bản họp → việc | Dán biên bản: "Lan làm slide trước thứ 5 tuần sau; Minh viết báo cáo trước thứ 2..." |
| Xếp lại lịch | "Mấy việc trễ hạn rồi, xếp lại lịch giúp tôi", "Có việc gấp sửa server 9h mai, dời các việc khác ra sau" |
| Kiểm tra lịch | "Tuần này lịch có bị trùng không?", "Việc nào sắp trễ hạn?" |
| Báo cáo | "Tóm tắt tiến độ tuần này", "Viết standup hôm nay" |
| Ghi nhớ thói quen | "Tôi làm việc hiệu quả nhất buổi sáng, hãy nhớ điều đó" |

- Chỉ nói ngày mà không nói giờ: hạn chót tính đến **23:59**, ngày bắt đầu tính từ **09:00**.
- Độ ưu tiên: "gấp" là khẩn cấp, "quan trọng" là cao, "thấp" là thấp, còn lại là trung bình.
- Dòng "Trả lời bởi …" dưới mỗi câu trả lời cho biết model nào đã xử lý.
- Cuộc trò chuyện được lưu trong `data/chat_history.db`; nút **Cuộc trò chuyện mới** ở thanh bên bắt đầu lại từ đầu.
- Mục **Trí nhớ dài hạn** ở thanh bên liệt kê những điều trợ lý đã ghi nhớ; bấm nút thùng rác để quên một điều, hoặc tự thêm.

### Bảng công việc

- Ba cột **Cần làm**, **Đang làm**, **Hoàn thành**. Bấm **Về …** hoặc **Sang …** để chuyển việc giữa các cột, nút mũi tên lên / xuống để tăng hoặc giảm độ ưu tiên.
- Banner đỏ báo việc quá hạn, banner vàng báo việc đến hạn trong 24 giờ.
- **Thêm công việc** để nhập tay, chọn được ngày giờ bắt đầu, hạn chót và thời lượng. Ngày bắt đầu phải trước hoặc bằng hạn chót.

### Báo cáo & Xuất

- Báo cáo **Hôm nay** / **Tuần này**: việc đã xong (đúng hạn hay không), đang làm, trễ hạn, sắp đến hạn.
- **Tải báo cáo (.md)** hoặc **Soạn email báo cáo**: mở ứng dụng email với nội dung điền sẵn (app không tự gửi thư).
- **Lịch (.ics)**: nhập vào Google Calendar (Cài đặt → Nhập và xuất) hoặc Outlook (Thêm lịch → Tải lên từ tệp); giữ nguyên lịch lặp và nhắc nhở.
- **Công việc (.csv)**: mở bằng Excel, Google Sheets hoặc nhập vào Notion/Trello.

### Gantt

- Chọn **Tất cả công việc** hoặc một dự án.
- Chỉ việc có **ngày bắt đầu** mới hiện trên biểu đồ. Việc tạo bằng lệnh lập kế hoạch dự án luôn có sẵn ngày bắt đầu.

## Mô hình học máy: dự đoán độ ưu tiên

- **Dữ liệu thật:** 36.000 issue đã xử lý của 12 dự án Apache (Kafka, Spark, Hadoop…), thu thập qua REST API công khai của Apache Jira. Độ ưu tiên gốc được quy về 4 mức `low`, `medium`, `high`, `urgent`. Dữ liệu mất cân bằng mạnh: `medium` chiếm 74,5%.
- **Dữ liệu tổng hợp (thích nghi miền):** 603 công việc tiếng Việt (cá nhân và phần mềm) do Gemini sinh theo định nghĩa từng mức ưu tiên. Dữ liệu được lọc trùng, lọc câu chứa từ lộ nhãn, và lọc mọi câu giống bộ kiểm tra (cosine ≥ 0,75). Sau đó 48 nhãn sai được sửa lại sau khi rà soát; nhật ký sửa nằm ở `datasets/vietnamese_tasks_synthetic_relabels.csv`.
- **Mô hình:** embedding đa ngôn ngữ (`paraphrase-multilingual-MiniLM-L12-v2`) + Logistic Regression, trọng số cân bằng theo nguồn dữ liệu. Phần so sánh với baseline và TF-IDF nằm trong [notebooks/priority_model.ipynb](notebooks/priority_model.ipynb).

| Mô hình / dữ liệu huấn luyện | Apache (tiếng Anh) | 64 việc tiếng Việt | Việc cá nhân |
|---|---|---|---|
| Baseline (lớp đông nhất) | 0,21 | – | – |
| TF-IDF + LR, Apache | **0,41** | 0,20 | 0,10 |
| Embedding + LR, Apache | 0,31 | 0,29 | 0,19 |
| **Embedding + LR, Apache + tổng hợp đã rà soát (dùng trong app)** | 0,31 | **0,70** | **0,69** |

*(macro-F1; đoán ngẫu nhiên khoảng 0,25)*

App chỉ dùng kết quả như **gợi ý kèm độ tin cậy**: khi độ tin cậy dưới **0,55** (ngưỡng chọn trên tập kiểm định riêng), app để mức trung bình. Độ ưu tiên do người dùng nói rõ luôn được ưu tiên. Bộ kiểm tra tiếng Việt nhỏ (64 câu, tự gán nhãn), nên các con số mang tính tham khảo. Biểu đồ nằm trong [docs/figures/](docs/figures/).

Tái tạo kết quả:

```bash
pip install -e ".[dev,notebook]"
flowagent-collect-jira        # tải dữ liệu Apache (~1 phút)
flowagent-generate-tasks      # sinh lại dữ liệu tổng hợp (cần GEMINI_API_KEY; đã có sẵn trong datasets/)
flowagent-train-priority      # huấn luyện và lưu models/priority_classifier.joblib
```

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
