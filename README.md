# Vietnamica-Alignment

Trích xuất văn bia từ PDF Vietnamica thành **JSONL UTF-8 có cấu trúc**, đồng thời giữ liên kết giữa metadata, mặt bia và các chuyên mục văn bản.

## 1. Tổng quan

Một số PDF Vietnamica sử dụng **font CID subset** nhưng không có hoặc có bảng `ToUnicode` không chính xác. Khi đó PDF vẫn hiển thị chữ đúng trên màn hình, nhưng khi copy hoặc extract text có thể nhận được ký tự lạ như `U+0001`, `�` hoặc ký tự không đúng.

Dự án không sử dụng OCR. Thay vào đó, hệ thống dựa trên **hình dạng glyph trong font nhúng** để xác định Unicode một cách xác định (deterministic).

Ý tưởng chính:

```text
PDF
 │
 ├─ Font thường
 │    └─► dùng Unicode do PyMuPDF cung cấp
 │
 └─ Font mã hóa
      └─► CID
           └─► glyph trong font nhúng
                └─► glyph signature
                     └─► glyph_profile
                          └─► Unicode
                               │
                               ▼
                         Văn bản đã decode
                               │
                               ▼
                    Metadata / mặt bia / chuyên mục
                               │
                               ▼
                             JSONL
```

PDF vẫn được xem là nguồn dữ liệu có thể chứa lỗi đánh máy, marker thiếu, chú thích bị ngắt dòng hoặc glyph chưa thể giải mã. Chương trình **không tự đoán** trong những trường hợp không an toàn:

* Bất thường có thể bảo toàn dữ liệu → ghi `warning`.
* Không thể xác định dữ liệu một cách đáng tin cậy → `error` và dừng.

---

## 2. Vì sao cần font tham chiếu?

Font được nhúng trong PDF có thể chứa đầy đủ **glyph outline** để vẽ chữ, nhưng mã CID bên trong font không nhất thiết tương ứng trực tiếp với Unicode.

Ví dụ:

```text
PDF:
CID 123
  ↓
glyph outline của chữ "東"
```

Nhưng PDF không nhất thiết cho biết:

```text
CID 123 → U+6771
```

Do đó cần một font tham chiếu có Unicode chuẩn, ví dụ `NomNaTong.ttf`.

Từ font tham chiếu:

```text
Unicode
   ↓
glyph
   ↓
outline
   ↓
signature
```

Hệ thống tạo bảng:

```text
glyph signature → Unicode
```

Bảng này được lưu thành `glyph_profile`.

Khi extract PDF:

```text
CID
 ↓
glyph outline trong PDF
 ↓
signature
 ↓
glyph_profile
 ↓
Unicode
```

**Font tham chiếu chỉ được dùng để xác định Unicode và tạo text layer khi xuất searchable PDF; không thay đổi hình ảnh hoặc nội dung PDF gốc.**

---

## 3. Font tham chiếu

Các font tham chiếu được đặt trong `fonts/reference/`:

| Font                      | Vai trò                                        |
| ------------------------- | ---------------------------------------------- |
| `NomNaTong.ttf`           | Nguồn chính cho chữ Nôm, Hán Nôm và tiếng Việt |
| `Palatino-Regular.ttf`    | Latin và dấu câu                               |
| `Palatino-Bold.ttf`       | Glyph Palatino bold                            |
| `Palatino-Italic.ttf`     | Glyph Palatino italic                          |
| `Palatino-BoldItalic.ttf` | Glyph Palatino bold-italic                     |
| `PMingLiU-ExtB.ttf`       | Bổ sung Hán tự mở rộng                         |

Thứ tự `--font` khi export searchable PDF có ý nghĩa: hệ thống chọn **font đầu tiên có glyph phù hợp**.

Với corpus này, thứ tự khuyến nghị là:

```text
NomNaTong → PMingLiU-ExtB → Palatino
```

Các font reference có thể có giới hạn giấy phép nên được giữ local và không commit vào Git.

Nếu thay đổi font reference, cần **tạo lại glyph profile và chạy lại test**.

---

## 4. Cài đặt

Từ thư mục `Vietnamica-Alignment`, kiểm tra `uv`:

```bash
uv --version
```

Nếu chưa có `uv`, cài theo hướng dẫn chính thức tại [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/).

Dự án yêu cầu Python 3.10 trở lên.

Đồng bộ môi trường:

```bash
uv sync --frozen
```

Sau đó sử dụng `uv run` để chạy Python:

```bash
uv run python --version

uv run python -m unittest discover -s tests -v
```

---

# 5. Quy trình xử lý

Toàn bộ pipeline gồm 4 bước chính:

```text
Font reference
      │
      ▼
1. Build glyph profile
      │
      ▼
2. Extract PDF
      │
      ▼
3. Parse metadata / sections / markers
      │
      ▼
4. Validate → JSONL
      │
      └────► Review / Searchable PDF (tuỳ chọn)
```

## Bước 1 — Tạo glyph profile

`glyph_profile` là bảng:

```text
glyph signature → Unicode
```

Profile được tạo từ font tham chiếu và glyph trong PDF.

Chạy:

```bash
uv run python tools/build_glyph_profiles.py \
  --pdf input/Tap-1_Bia-Hau-the-ki-XVII_760-trang.pdf \
  --nomna fonts/reference/NomNaTong.ttf \
  --palatino fonts/reference/Palatino-Regular.ttf \
  --palatino-bold fonts/reference/Palatino-Bold.ttf \
  --palatino-italic fonts/reference/Palatino-Italic.ttf \
  --palatino-bold-italic fonts/reference/Palatino-BoldItalic.ttf \
  --pmingliu fonts/reference/PMingLiU-ExtB.ttf \
  --output data/glyph_profiles/tap_1.json
```

Nếu PDF không sử dụng `PMingLiU-ExtB` thì có thể bỏ `--pmingliu`.

Nếu chỉ có file `.ttc`, tách face cần dùng thành `.ttf`:

```bash
uv run python tools/extract_ttc_face.py \
  --input fonts/reference/PMingLiU-ExtB.ttc \
  --font-number 1 \
  --output fonts/reference/PMingLiU-ExtB.ttf
```

### Glyph profile hoạt động như thế nào?

Với font lỗi trong PDF:

```text
CID → glyph outline → signature
```

Với font tham chiếu:

```text
Unicode → glyph outline → signature
```

Hai phía được đối chiếu bằng signature để tạo:

```text
signature → Unicode
```

Trong quá trình này, hệ thống có thể sử dụng kích thước glyph, bounding box và rasterized outline để giảm và đánh giá các ứng viên.

Nếu một glyph không có signature tương ứng hoặc có nhiều ứng viên không thể phân biệt an toàn, chương trình không tự đoán mà báo lỗi.

---

## Bước 2 — Extract PDF

Mỗi PDF có một file config riêng trong `configs/`.

Các trường quan trọng:

* `input_pdf`: PDF đầu vào.
* `glyph_profile`: profile dùng để decode glyph.
* `output_jsonl`: JSONL đầu ra.
* `metadata`: các trường metadata cần đọc.
* `title_pattern`: nhận diện đầu mỗi văn bia.
* `content_start`: mốc bắt đầu nội dung.
* `content_sections`: các chuyên mục văn bản.
* `marker_pattern`: nhận diện marker mặt bia.
* `encoded_fonts`: các font cần giải mã bằng glyph profile.
* `page_margins`: loại header/footer hoặc vùng ngoài nội dung.
* `expected_record_count`: số lượng bản ghi kỳ vọng.

Chạy extraction:

```bash
uv run python extract_pdf.py --config configs/tap_1.json
```

Hoặc tạo thêm JSON có indent để review:

```bash
uv run python extract_pdf.py \
  --config configs/tap_1.json \
  --pretty-output output/tap_1_review.json
```
Flow extract

PDF → PyMuPDF → Kiểm tra font → Giải mã text → Chuẩn hóa → Ghép dòng → Tách văn bia → Validate → JSONL / Issues

Quy trình bắt đầu bằng việc đọc nội dung PDF bằng PyMuPDF và duyệt văn bản theo từng trang. Với mỗi đoạn text, hệ thống kiểm tra font: font thông thường sử dụng trực tiếp Unicode do PyMuPDF cung cấp; với encoded font, hệ thống giải mã theo chuỗi CID → glyph → signature → glyph profile → Unicode.

Sau khi giải mã, text được chuẩn hóa và ghép thành các dòng hoàn chỉnh. Hệ thống tiếp tục nhận diện cấu trúc văn bia, bao gồm metadata, chuyên mục và marker mặt bia, sau đó thực hiện các bước kiểm tra và validate. Kết quả cuối cùng được xuất thành JSONL, đồng thời ghi nhận các bản ghi hoặc vấn đề cần review vào issues.

Sau khi PyMuPDF đọc text từ PDF, hệ thống kiểm tra font của từng đoạn text:
- Font thường → sử dụng trực tiếp Unicode mà PyMuPDF trích xuất được.
- Encoded font → không sử dụng trực tiếp Unicode của PyMuPDF mà thực hiện giải mã thông qua glyph trong font PDF và `glyph_profile`.

### Xử lý từng trang

Trang PDF chỉ là **đơn vị đọc**, không phải đơn vị bản ghi.

Một văn bia có thể bắt đầu ở trang này và tiếp tục sang trang kế tiếp.

Sau khi đọc text:

1. Lọc vùng ngoài margin.
2. Decode glyph.
3. Chuẩn hóa Unicode và khoảng trắng.
4. Sắp xếp line theo vị trí `(y, x)`.
5. Nối các line giữa các trang.
6. Dùng `title_pattern` để xác định văn bia.
7. Đọc metadata.
8. Từ `content_start`, phân chia chuyên mục.
9. Dùng marker để xác định mặt bia.
10. Validate và tạo JSONL.

Nếu marker bị thiếu, hệ thống không tự gán nội dung sang một mặt bia khác nếu không đủ cơ sở. Trường hợp này được đưa vào warning/review.

---

## Bước 3 — Review dữ liệu

JSONL chính chứa các bản ghi hợp lệ.

Các vấn đề cần con người kiểm tra được ghi riêng vào:

```text
output/<tên>_invalid.json
```

Hoặc chỉ định file:

```bash
--issues-output
```

Các bất thường thường gặp:

| Warning                            | Ý nghĩa                                   |
| ---------------------------------- | ----------------------------------------- |
| Marker không có trong metadata     | Marker có thể sai hoặc thừa               |
| Không tìm thấy nội dung cho marker | Marker có nhưng không có text được gán    |
| Có nội dung không thuộc marker     | Thiếu marker hoặc cấu trúc PDF bất thường |
| Bỏ qua dòng trước metadata         | Có text bất thường trước phần metadata    |

Các trường hợp không thể đảm bảo kết quả:

* Không mở được PDF.
* Không đọc được glyph profile.
* Không resolve được font nhúng.
* Không decode được CID.
* Không thể phân biệt nhiều font subset.
* Unicode không hợp lệ.
* Cấu trúc văn bia không đáp ứng các điều kiện bắt buộc.

→ chương trình dừng và báo `error`.

---

# 6. Xử lý ký tự Unicode lỗi

Một số PDF có thể trả về:

* `U+0001`, `U+0002`, ...
* `U+FFFD` (`�`)
* control characters
* surrogate

Đây thường là dấu hiệu mapping Unicode của font không đáng tin cậy.

Hệ thống **không tự thay thế bằng ký tự phỏng đoán**.

Các ký tự không hợp lệ được loại khỏi text trước khi ghi JSONL. Nếu ký tự đó có ý nghĩa thực tế, cần bổ sung font reference/glyph profile hoặc xử lý lại nguồn PDF.

---

# 7. Xuất PDF searchable

JSONL là output chính. Nếu cần một PDF có thể search/copy Unicode, có thể tạo một PDF mới với:

```text
PDF gốc
   ↓
render thành nền
   +
Unicode text layer vô hình
   ↓
searchable PDF
```

PDF gốc không bị sửa.

Chạy:

```bash
uv run python export_searchable_pdf.py \
  --config configs/tap_1.json \
  --output output/tap_1_searchable.pdf \
  --font fonts/reference/NomNaTong.ttf \
  --font fonts/reference/PMingLiU-ExtB.ttf \
  --font fonts/reference/Palatino-Regular.ttf \
  --dpi 150
```

`--font` có thể lặp lại. Font được chọn theo thứ tự xuất hiện trong command.

Có thể kiểm tra một số trang trước:

```bash
uv run python export_searchable_pdf.py \
  --config configs/tap_1.json \
  --output /private/tmp/tap_1_qa.pdf \
  --font fonts/reference/NomNaTong.ttf \
  --font fonts/reference/PMingLiU-ExtB.ttf \
  --font fonts/reference/Palatino-Regular.ttf \
  --dpi 100 \
  --pages 5,121-122
```

`--dpi` quyết định chất lượng ảnh nền và dung lượng PDF:

* `150`: phù hợp để đọc.
* `300`: phù hợp hơn để in nhưng file lớn hơn.

Exporter sẽ dừng nếu có ký tự không được hỗ trợ bởi các font được cung cấp, thay vì tạo một text layer bị mất chữ.

---

# 8. Kiểm tra ký tự không được hỗ trợ

Sau khi extract, có thể kiểm tra các ký tự không có trong các font reference:

```bash
uv run python tools/filter_unsupported_characters.py \
  --input output/tap_1_review.json \
  --output output/tap_1_unsupported_characters.json \
  --font fonts/reference/NomNaTong.ttf \
  --font fonts/reference/PMingLiU-ExtB.ttf \
  --font fonts/reference/Palatino-Regular.ttf
```

Tool giữ nguyên record gốc và bổ sung thông tin:

```text
unsupported_character
```

bao gồm ký tự, Unicode, số lần xuất hiện và vị trí trong dữ liệu.

---

# 9. Output

Pipeline tạo các file chính:

| File                         | Mục đích                                   |
| ---------------------------- | ------------------------------------------ |
| `data/glyph_profiles/*.json` | Bảng `glyph signature → Unicode`           |
| `output/*.jsonl`             | Dữ liệu chính, mỗi văn bia một JSON object |
| `output/*_review.json`       | JSON có indent để review                   |
| `output/*_invalid.json`      | Record/warning cần kiểm tra                |
| `output/*_searchable.pdf`    | PDF mới có Unicode text layer              |

PDF nguồn luôn được giữ nguyên.

---

# 10. Cấu trúc mã nguồn

| File                                     | Vai trò                            |
| ---------------------------------------- | ---------------------------------- |
| `extract_pdf.py`                         | CLI chính cho extraction           |
| `export_searchable_pdf.py`               | Tạo searchable PDF                 |
| `extraction/models.py`                   | Dataclass, config và exception     |
| `extraction/config.py`                   | Đọc và validate config             |
| `extraction/text.py`                     | Làm sạch và chuẩn hóa text         |
| `extraction/decoder.py`                  | Đọc PDF, CID, font và decode glyph |
| `extraction/records.py`                  | Parse metadata, section và marker  |
| `extraction/jsonl.py`                    | Validate và ghi JSONL/JSON         |
| `extraction/service.py`                  | Điều phối extraction               |
| `extraction/searchable_pdf.py`           | Tạo Unicode text layer             |
| `tools/build_glyph_profiles.py`          | Tạo glyph profile                  |
| `tools/extract_ttc_face.py`              | Tách face từ TTC                   |
| `tools/filter_unsupported_characters.py` | Tìm ký tự không có glyph           |

---

# 11. Các nguyên tắc quan trọng

### Không dùng OCR

Giải mã dựa trên cấu trúc font và glyph outline, nên kết quả deterministic và có thể tái lập giữa các lần chạy.

### Không đoán Unicode

Nếu không thể xác định glyph một cách an toàn, chương trình báo lỗi thay vì tự chọn ký tự gần nhất.

### Không sửa PDF nguồn

Mọi output đều được ghi thành file mới.

### Font reference không phải font của PDF

Font reference cung cấp **Unicode chuẩn để xây dựng profile**.

Font nhúng trong PDF cung cấp **glyph thực tế cần giải mã**.

### CID không phải Unicode

```text
CID → glyph
```

không đồng nghĩa với:

```text
CID → Unicode
```

Do đó pipeline sử dụng:

```text
CID → glyph → signature → Unicode
```

### Một PDF có thể chứa nhiều subset của cùng một font

Ví dụ:

```text
AAAAAT+NomNaTong
AAAABA+NomNaTong
AAAABG+NomNaTong
...
```

Các subset có thể dùng CID table khác nhau. Decoder vì vậy không chỉ dựa vào tên font mà còn kiểm tra resource và `xref` để xác định đúng font nhúng.

---

# 12. Kiểm thử

Chạy toàn bộ test:

```bash
uv run python -m unittest discover -s tests -v
```

Integration test sẽ chạy khi PDF mẫu và glyph profile tương ứng đã có. Nếu thiếu dữ liệu test bên ngoài, test đó có thể được bỏ qua.

# To-do
* [ ] Phân loại font theo PDF font resource: font TrueType dùng trực tiếp Unicode từ PyMuPDF, font CID/Type0 giải mã thông qua `glyph_profile`.
* [ ] Rà soát toàn bộ font resource trong PDF và đảm bảo các font CID có `glyph_profile` tương ứng.
* [ ] Xem lại các trường hợp kí tự có mã unicode đặc biệt có thể gây lỗi (lúc trước bỏ qua thẳng).
