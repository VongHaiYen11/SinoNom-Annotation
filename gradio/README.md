# Vietnamica Gradio MVP

Ứng dụng annotation mới, chỉ dùng module nền `text_detection` để phát hiện box. Source JSON là kết quả của `text_extraction`; app không chạy lại extraction khi mở ảnh.

## Cài đặt

Python 3.11+, từ repository root:

```bash
pip install -r gradio/requirements.txt
```

Hoặc dùng virtualenv hiện có:

```bash
uv pip install --python .venv/bin/python -r gradio/requirements.txt
```

Detection trực tiếp cần runtime và model trong `../text_detection/README.md`: Torch, OpenCV, Shapely, MMDetection/MMCV/MMEngine tương thích với DINO config; OCR executable phải chạy được trên hệ điều hành hiện tại. UI và các test state không yêu cầu ML runtime.

## Chạy

Từ repository root:

```bash
python gradio/app.py \
  --image-dir /absolute/path/images \
  --source-json /absolute/path/source.json \
  --output-dir /absolute/path/annotations \
  --vague-det-config /absolute/path/damage_detect.py \
  --vague-det-weights /absolute/path/damage_detect.pth \
  --ocr-det-executable /absolute/path/det_model
```

Hoặc `cd gradio && python app.py` với dữ liệu tại các đường dẫn mặc định tương đối với working directory: `data/images`, `data/source_json/source.json`, `data/annotations`. Nếu thiếu input, app vẫn mở và hiển thị lỗi; khởi động lại với parameter đúng. App bind localhost; mặc định port 7860, đổi bằng `--port`.

Input folder phẳng, tên ảnh không extension phải trùng chính xác `ky_hieu`, ví dụ `12305.jpg`. Không có upload ảnh. Không cho hai ảnh cùng stem vì sẽ trùng output filename.

Source schema được adapter kiểm tra dựa trên output hiện tại:

```json
[{"so_van_bia":1,"noi_dung":[{"ky_hieu":"12305","chuyen_muc":[{"tieu_de":"Nguyên văn chữ Hán Nôm","van_ban":"永寺樂"}]}]}]
```

Toàn bộ record và các field thêm được giữ nguyên. Annotation chỉ dùng `van_ban` thuộc đúng mặt `ky_hieu`, đúng chuyên mục. Không tìm thấy/trùng mã hoặc chuyên mục sẽ báo lỗi. Muốn hỗ trợ schema khác, thêm adapter tại `annotation/text_extraction.py`.

## Workflow

1. **Image:** chọn ảnh, bấm Mở ảnh. Nạp annotation cũ nếu có; giữ draft từng ảnh trong session.
2. **Content:** xem toàn bộ record; chọn field, sửa, bấm **Áp dụng field**, rồi **Save content** để ghi source JSON và xác nhận. Editor hiển thị chuỗi normalized. Undo quay về lần Save gần nhất; khôi phục bản ban đầu chỉ đưa snapshot vào draft, cần Save để ghi xuống file.
3. **BBox:** lần đầu vào bước này tự gọi `text_detection`. Nếu model không chạy được, lỗi hiện rõ, vẫn có thể thêm box thủ công. Kéo vùng trống để thêm; kéo trong box để move; kéo bốn góc để resize. Chọn ID để sửa tọa độ/xóa. Chạy lại detection yêu cầu checkbox vì thay toàn bộ boxes và mapping.
4. **Alignment:** kiểm tra temporary one-to-one mapping. Count mismatch chặn bước này.
5. **Status:** chọn ID hoặc click box, chọn intact/damaged, cập nhật. Next xác nhận tất cả status.
6. **Reading Order:** kéo thẻ đến trước thẻ đích, hoặc nhập JSON ID order. Next xác nhận.
7. **Review:** kiểm tra ảnh, order, bảng, final text, JSON preview; bấm Save annotation.
8. **Crop:** sau Save, Next mở module crop. Kéo frame/bốn góc hoặc nhập tọa độ rồi Save crop.

Back/Next dùng cùng state; không tự chạy lại detection. **Reset draft / nạp lại file** bỏ draft của ảnh được chọn và nạp bản đã lưu. Reload trình duyệt tạo session mới; chỉ dữ liệu đã Save được khôi phục.

## State architecture

- `box_id = identity`; `bbox = location`; `status = condition`.
- `annotations[str(box_id)] = character`; `reading_order = sequence of IDs`.
- Một `gr.State` chứa active state và draft cache từng ảnh. JavaScript chỉ gửi action; Python validate và trả snapshot chính thức.
- `temporary_order` độc lập với `reading_order`. Reorder không sửa mapping.
- ID tăng đơn điệu trong state; sidecar giữ high-water mark khi Save. Xóa không renumber; chạy detection lại cấp ID mới.
- Text thay đổi: bỏ mapping cũ, invalidate alignment/status confirmation/reading order. Add/delete/move/resize box cũng invalidate dependency. Nếu count khớp, tạo mapping mới theo temporary order, vẫn cần xác nhận lại status/order.
- Sửa status không đổi bbox, ID, mapping hay order.
- Mọi callback thay đổi state chạy tuần tự; event canvas/card mang image + revision, event cũ bị từ chối.

## Text verification / Unicode

Raw record → draft → Save source → verified content → annotation text → count validation → temporary alignment.

Normalization NFC; bỏ whitespace và mọi ký tự Unicode category P (punctuation), giữ chữ trong ngoặc và các symbol ngoài category P. Dùng `regex` grapheme `\X` để không đếm dấu kết hợp/variation selector riêng. Text nguồn giữ nguyên dấu câu. Thay rule tại `text_alignment.py`; counting và mapping dùng chung rule.

## Files / persistence

```text
annotations/
├── 12305.json          # image, bounding_boxes, reading_order, annotations
├── .state/12305.json   # temporary order, next ID, source/document hashes
└── crops/12305.json    # image, crop với đủ bốn góc
```

Annotation và crop lưu UTF-8, `ensure_ascii=False`, `indent=2`, ghi file nguyên tử. Sidecar chỉ được tin khi hash khớp final document. Không có sidecar/source đổi: giữ dữ liệu đã load để review, rồi tạo lại alignment khi xác nhận content; yêu cầu xác nhận status/order lại.

Source Save kiểm tra record baseline dưới process lock trước khi patch, tránh session trong cùng server ghi đè thay đổi của nhau. File ghi lỗi thì state không báo thành công. Không triển khai khóa liên-process: MVP dành cho một server instance. Annotation cùng ảnh dùng last-save-wins; tránh hai người sửa cùng ảnh đồng thời.

Crop chỉ lưu tọa độ trên ảnh input, không cắt file ảnh hoặc biến đổi annotation coordinates.

## Kiểm thử

```bash
python -m unittest discover -s gradio/tests -v
```

Test dùng ảnh/source tạm và detector mock; không cần model và không sửa dataset thật. Ví dụ final JSON tại `examples/bia_001.json`.

## Bố cục

`app.py`: CLI, Gradio components/callbacks. `annotation/`: state, workflow, source adapter, bbox/status/order/alignment và persistence. `ui/editor.py` và `ui/assets/editor.js`: SVG canvas/cards. `crop/crop.py`: crop độc lập. Không thêm `gradio/__init__.py` vì trùng tên thư viện Gradio.
