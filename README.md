# Vietnamica-Alignment

Trích xuất văn bia từ PDF Vietnamica thành JSONL UTF-8 có cấu trúc, giữ liên kết
giữa metadata của văn bia, các mặt bia và từng chuyên mục văn bản.

## Ý tưởng và giới hạn

Nhiều PDF nguồn nhúng font CID nhưng không có (hoặc có sai) bảng ánh xạ Unicode.
Vì vậy không dùng OCR: chương trình đối chiếu hình dạng glyph trong PDF với
glyph của font tham chiếu để giải mã một cách xác định (deterministic). Cách này
tránh sai khác giữa các lần chạy và không tự suy đoán ký tự.

PDF vẫn là nguồn có thể có lỗi đánh máy, marker bị thiếu, chú thích bị ngắt dòng
hoặc glyph không giải mã được. Chương trình dừng khi dữ liệu không thể trích xuất
an toàn; các bất thường về cấu trúc nhưng còn bảo toàn được dữ liệu sẽ được in ra
thành `warning` để người dùng đối chiếu PDF.

## Flow: xử lý PDF không copy được chữ

Áp dụng flow này khi mở PDF thấy chữ bình thường nhưng chọn/copy ra ký tự lạ,
trống, `U+0001` hoặc `�`. Nguyên nhân thường là font CID subset không có bảng
`ToUnicode` đáng tin cậy: PDF biết cách vẽ glyph nhưng không biết glyph đó là mã
Unicode nào.

```text
PDF nguồn không copy được
        │
        ├─► 1. Kiểm tra font nhúng và raw text/CID
        │       └─ Có ToUnicode đúng? Có thể extract Unicode trực tiếp.
        │       └─ Không/sai ToUnicode? Dùng glyph-profile flow bên dưới.
        │
        ├─► 2. Chuẩn bị font tham chiếu TTF có Unicode
        │       └─ NomNaTong: Nôm/tiếng Việt; PMingLiU-ExtB: Hán tự mở rộng;
        │          Palatino: Latin và dấu câu.
        │
        ├─► 3. Tạo glyph profile
        │       └─ Outline glyph PDF + outline font tham chiếu
        │          → signature → Unicode.
        │
        ├─► 4. Extract PDF theo config
        │       └─ CID → glyph signature → Unicode → line/marker/section
        │          → JSONL + warning/error có ngữ cảnh.
        │
        ├─► 5. Review và sửa dữ liệu nguồn/config nếu cần
        │       └─ Kiểm tra missing signature, marker sai, marker thiếu,
        │          control character và các warning cấu trúc.
        │
        └─► 6. Tuỳ chọn: export searchable PDF mới
                └─ Render trang gốc làm nền + Unicode text layer vô hình
                   → mở PDF có thể search/copy Unicode.
```

Các đầu ra được tách riêng để không làm mất PDF gốc:

| Đầu ra | Mục đích |
| --- | --- |
| `data/glyph_profiles/*.json` | Bảng ánh xạ xác định glyph outline sang Unicode. |
| `output/*.jsonl` | Dữ liệu máy đọc được, mỗi văn bia một JSON object trên một dòng. |
| `output/*_review.json` | Bản JSON có indent để con người kiểm tra. |
| `output/*_searchable.pdf` | PDF mới để search/copy; PDF đầu vào không bị sửa. |

## Vì sao cần font reference?

Font subset nhúng trong PDF thường chỉ đủ để **vẽ** chữ: nó chứa glyph outline
nhưng tên glyph là CID cục bộ như `cid123`, không phải `U+4E00` hay `U+1EA1`.
Khi bảng `ToUnicode` thiếu hoặc sai, không thể suy ra Unicode chỉ từ PDF. Font
reference là bản font có `cmap` chuẩn, cung cấp quan hệ `Unicode → glyph` để
so sánh outline và đảo chiều thành `glyph PDF → Unicode`.

Reference font không được dùng để thay đổi hình ảnh của JSONL hoặc PDF nguồn.
Nó chỉ có hai vai trò:

1. **Tạo glyph profile:** đối chiếu outline của glyph subset với outline trong
   font reference để tạo `signature → Unicode`.
2. **Xuất searchable PDF:** nhúng font Unicode mới trong text layer vô hình để
   viewer có thể search/copy chữ đã decode.

| Font reference trong `fonts/reference/` | Dùng ở đâu | Vai trò |
| --- | --- | --- |
| `NomNaTong.ttf` | `tools/build_glyph_profiles.py`, `export_searchable_pdf.py` | Nguồn chính cho chữ Nôm, Hán Nôm và tiếng Việt; ưu tiên đầu tiên trong lớp Unicode. |
| `Palatino-Regular.ttf` | `tools/build_glyph_profiles.py`, `export_searchable_pdf.py` | Đối chiếu Palatino Latin thường; fallback cho Latin/dấu câu, gồm một số ký tự như `U+2012`. |
| `Palatino-Bold.ttf` | `tools/build_glyph_profiles.py` | Đối chiếu glyph của subset Palatino bold trong PDF. |
| `Palatino-Italic.ttf` | `tools/build_glyph_profiles.py` | Đối chiếu glyph của subset Palatino italic trong PDF. |
| `Palatino-BoldItalic.ttf` | `tools/build_glyph_profiles.py` | Đối chiếu glyph của subset Palatino bold-italic trong PDF. |
| `PMingLiU-ExtB.ttf` | `tools/build_glyph_profiles.py`, `export_searchable_pdf.py` | Bổ sung Hán tự mở rộng mà NomNaTong không có; fallback thứ hai trong lớp Unicode. |
| `PMingLiU-ExtB.ttc` | Chỉ là nguồn để chạy `tools/extract_ttc_face.py` một lần | Không dùng trực tiếp trong pipeline; face `1` được tách thành `PMingLiU-ExtB.ttf`. |

Thứ tự `--font` trong lệnh export có ý nghĩa: exporter chọn font **đầu tiên**
có glyph cho ký tự đó. Dùng theo thứ tự `NomNaTong → PMingLiU-ExtB → Palatino`
để ưu tiên glyph phù hợp corpus trước, rồi mới dùng fallback.

Các font reference có thể bị giới hạn giấy phép nên nằm local và không nên được
commit vào Git. Khi thay font reference, phải tạo lại glyph profile và chạy test
trên PDF tương ứng; cùng một Unicode có thể có outline khác giữa các font.

## Cài đặt

```bash
uv sync --frozen
```

## Cấu trúc mã nguồn

`extract_pdf.py` là CLI chính, còn toàn bộ logic nằm trong package
`extraction/`. Không còn module `extract_support.py` ở root; code mới import
trực tiếp module có trách nhiệm phù hợp.

| File | Vai trò |
| --- | --- |
| `extract_pdf.py` | CLI extract JSONL; điều phối config, extract, cleanup và ghi output. |
| `export_searchable_pdf.py` | CLI tạo PDF mới có nền trang gốc và text layer Unicode vô hình. |
| `extraction/models.py` | Dataclass (`ExtractConfig`, `TextLine`, …), hằng số mặc định và `ExtractionError`. |
| `extraction/config.py` | Đọc/validate JSON config, resolve path và đọc glyph profile. |
| `extraction/text.py` | Nhận diện Unicode lỗi, loại control/replacement character, chuẩn hoá dòng. |
| `extraction/decoder.py` | Đọc raw PDF spans, font resource/CID, đối chiếu glyph profile và giữ toạ độ text. |
| `extraction/records.py` | Tách tiêu đề văn bia, metadata, mặt bia, chuyên mục và tạo warning có ngữ cảnh. |
| `extraction/jsonl.py` | Validate Unicode, JSONL compact, JSON review có indent, cleanup `van_ban`, atomic write. |
| `extraction/service.py` | API `extract_document()` nối decoder và parser, không ghi file. |
| `extraction/searchable_pdf.py` | Render nền PDF và nhúng Unicode text layer; kiểm tra coverage của font TTF. |
| `tools/build_glyph_profiles.py` | Tạo ánh xạ `glyph signature → Unicode` từ PDF/font tham chiếu. |
| `tools/extract_ttc_face.py` | Utility một lần để tách một face TTC thành TTF cho pipeline. |

Các hàm public và các hàm nội bộ có logic quan trọng đều có docstring ngay tại
nguồn; docstring nêu input, trách nhiệm và lý do kiểm tra an toàn khi phù hợp.

## Workflow

### 1. Chuẩn bị cấu hình cho một PDF

Mỗi PDF dùng một file JSON trong `configs/`. Các đường dẫn trong config được
hiểu tương đối so với thư mục chứa config. Những phần quan trọng là:

- `input_pdf`, `glyph_profile`, `output_jsonl`: PDF đầu vào, bảng glyph và file
  JSONL đầu ra.
- `metadata`: nhãn xuất hiện trong PDF và tên trường JSON ổn định; trường có
  `type: "identifiers"` đọc các marker như `<1234>`.
- `title_pattern`, `content_start`, `content_sections`, `marker_pattern`: quy
  tắc nhận biết biên văn bia, chuyên mục và mặt bia.
- `encoded_fonts`: các font CID cần giải mã bằng glyph profile.
- `page_margins`, `expected_record_count`, `require_consecutive_numbers`: các
  kiểm tra và giới hạn riêng của tập PDF.

### 2. Tạo glyph profile

Chạy một lần cho mỗi bộ PDF/font tham chiếu. Script đọc outline glyph trong PDF
và font tham chiếu, tạo ánh xạ `glyph signature → Unicode` trong JSON. Profile
được tái sử dụng ở bước trích xuất.

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

`--pmingliu` chỉ cần khi font này có trong PDF. Font tham chiếu nằm tại
`fonts/reference/` và không được Git theo dõi vì có thể bị giới hạn giấy phép.
Nếu chỉ có bản collection `.ttc`, tạo TTF một lần rồi dùng TTF đó cho toàn bộ
pipeline:

```bash
uv run python tools/extract_ttc_face.py \
  --input fonts/reference/PMingLiU-ExtB.ttc \
  --font-number 1 \
  --output fonts/reference/PMingLiU-ExtB.ttf
```

#### Cách so sánh glyph hoạt động

PDF lỗi trong tập này thường không lưu chuỗi Unicode. Thay vào đó, content
stream nói "vẽ glyph số 1" (CID 1), còn font subset nhúng trong PDF chứa outline
của glyph đó. Nếu font thiếu bảng `ToUnicode`, số CID không cho biết đó là chữ
gì; PyMuPDF có thể trả nó về một control character như `U+0001`.

`build_glyph_profiles.py` tạo profile theo các bước sau:

1. Lấy font CFF subset nhúng từ PDF theo `xref`. Với mỗi glyph `cidNNN`, đọc
   outline Bézier và chuẩn hoá nó thành chuỗi SVG path commands.
2. Từ font tham chiếu có Unicode (NomNaTong, Palatino hoặc PMingLiU), lấy
   `cmap` để có tập ứng viên `code point → glyph` và lấy outline tương ứng.
3. Giảm ứng viên trước khi so sánh ảnh: Palatino/PMingLiU lọc theo advance
   width; NomNaTong ưu tiên cặp `(width, bounding box)` trùng khớp, nếu chưa đủ
   thì chọn các bbox gần nhất có width tương thích.
4. Rasterize hai outline về cùng canvas xám `72×101`, tính tổng sai khác tuyệt
   đối từng pixel, chọn ứng viên có điểm thấp nhất. Nếu bằng điểm, ưu tiên mã
   tiếng Việt `Đ/đ`, sau đó Hán tự phổ biến, rồi các vùng Unicode khác.
5. SHA-256 rút gọn của SVG path là `glyph signature`; profile lưu
   `signature → Unicode`. Do chữ ký dựa trên outline chứ không phải CID, cùng
   một hình glyph trong các subset khác nhau dùng lại được profile.

Khi extract, `decoder.py` lấy CID từ raw text, tìm glyph `cidNNN` trong font
nhúng, tạo đúng signature và tra profile. Một trang có thể có nhiều subset font
cùng base name nhưng CID table khác nhau; decoder đọc thêm content stream để lấy
font resource (`C10`, `C13`, …) và gán CID vào đúng `xref`. Nếu vẫn không thể
phân biệt, chương trình dừng thay vì đoán chữ.

Đây là so khớp hình dạng có kiểm soát, không phải OCR. Nó đáng tin cậy khi PDF
và font tham chiếu dùng cùng thiết kế glyph, nhưng không thể tự giải quyết hai
ký tự thật sự có outline giống nhau hoặc một glyph không có trong font tham
chiếu. Các trường hợp đó phải được profile/font tham chiếu xử lý và được báo lỗi
`missing signature` hoặc `cannot disambiguate`.

#### Vì sao có Unicode lỗi và cách chương trình xử lý

| Dấu hiệu | Nguồn gốc trong PDF | Xử lý hiện tại |
| --- | --- | --- |
| `U+0001`, `U+0002`, … | CID bị PyMuPDF diễn giải như mã control vì font không có/sai `ToUnicode`; cũng có thể là glyph không xác định của font thường. | Loại khỏi text trước khi tạo JSONL. |
| `U+FFFD` | Thư viện PDF báo "replacement character": không giải mã được glyph/encoding. | Loại khỏi text; không thay bằng ký tự đoán. |
| Control character khác (`Cc`) | Dữ liệu text stream bất thường hoặc mapping hỏng. | Loại khỏi text. |
| Surrogate (`Cs`) | Chuỗi Unicode không hợp lệ từ dữ liệu nguồn/thư viện. | Loại khỏi text và validator vẫn chặn nếu lọt vào serializer. |

Việc lọc giúp một glyph hỏng không làm hỏng toàn bộ lần extract, nhưng có nghĩa
glyph đó không xuất hiện trong JSONL. Nếu ký tự mang nghĩa, cần bổ sung profile
hoặc sửa PDF nguồn; không nên coi việc lọc là khôi phục văn bản.

#### PDF có thể search/copy Unicode không?

Có thể, nhưng đó là một bước xuất PDF riêng, không phải chỉ ghi JSONL. Có hai
hướng kỹ thuật:

1. **Khuyến nghị để tạo PDF truy cập được:** render từng trang gốc làm nền và
   đặt một text layer Unicode vô hình, theo toạ độ span/line đã extract, với font
   có đủ Latin + Hán Nôm. Người đọc nhìn thấy bản gốc, còn search/copy đọc lớp
   Unicode. Cần kiểm tra trực quan từng trang và kiểm tra copy/search vì thứ tự
   text, ligature, line break và vùng chọn phụ thuộc viewer. Đổi lại PDF sẽ có
   nền raster (không còn vector gốc) và dung lượng lớn hơn.
2. **Giữ nguyên vector gốc:** thay/thêm `ToUnicode CMap` đúng cho từng font
   subset, hoặc thay toàn bộ text operator bằng font Unicode mới. Cách này giữ
   chất lượng in nhưng phức tạp: phải map chính xác resource → CID → Unicode,
   xử lý nhiều subset, metric/kerning và tránh hai text layer cùng được copy.
   Nên chỉ làm khi cần PDF archival chất lượng cao và có bộ kiểm thử trực quan.

Không nên chỉ overlay text vô hình lên PDF gốc mà không loại text layer cũ: nhiều
viewer sẽ copy cả mapping cũ lẫn mapping mới, gây ký tự lặp hoặc control
character. Nếu bạn muốn triển khai, hướng 1 có thể được thêm thành một command
riêng (ví dụ `export_searchable_pdf.py`) với output mới, không sửa PDF gốc.

### Xuất PDF có thể search/copy Unicode

`export_searchable_pdf.py` tạo PDF mới: mỗi trang gốc được render làm nền, sau
đó text đã decode được nhúng vô hình ở toạ độ tương ứng. PDF nguồn không bị sửa.

```bash
uv run python export_searchable_pdf.py \
  --config configs/tap_1.json \
  --output output/tap_1_searchable.pdf \
  --font fonts/reference/NomNaTong.ttf \
  --font fonts/reference/PMingLiU-ExtB.ttf \
  --font fonts/reference/Palatino-Regular.ttf \
  --dpi 150
```

`--font` có thể lặp lại: exporter chọn font đầu tiên có glyph tương ứng. Với tập
mẫu, NomNaTong bao phủ tiếng Việt và phần lớn Hán Nôm; PMingLiU-ExtB là fallback
cho Hán tự mở rộng; Palatino bổ sung dấu câu như `U+2012`. Exporter chỉ nhận TTF
và dừng trước khi ghi output nếu bất kỳ ký tự nào không có trong các font đã đưa
vào, để tránh tạo lớp copy/search bị mất chữ.

`--dpi` quyết định chất lượng nền ảnh và dung lượng file; `150` phù hợp để đọc,
`300` phù hợp hơn để in nhưng file lớn hơn nhiều. Có thể kiểm tra nhanh một số
trang trước khi xuất cả volume:

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

`--pages` chỉ dành cho QA và tạo PDF chứa đúng các trang được chỉ định; bỏ tham
số này để xuất toàn bộ PDF. Sau khi export, kiểm tra bằng một PDF viewer: tìm một
cụm Hán Nôm/Vietnamese, chọn text qua nhiều dòng rồi copy sang editor Unicode.

### 3. Trích xuất PDF

```bash
uv run python extract_pdf.py --config configs/tap_1.json
```

Giữ JSONL cho pipeline và tạo thêm JSON có xuống dòng để kiểm tra thủ công:

```bash
uv run python extract_pdf.py \
  --config configs/tap_1.json \
  --pretty-output output/tap_1_review.json
```

`output_jsonl` vẫn là JSONL chuẩn (một record một dòng). File `--pretty-output`
là một JSON array có indent, thuận tiện mở bằng editor; không dùng nó như JSONL.

Mặc định `van_ban` giữ line break do PDF. Khi cần file dễ đọc hoặc dễ so sánh,
có thể gộp các line break thành khoảng trắng và bỏ ký tự backslash thật sự:

```bash
uv run python extract_pdf.py \
  --config configs/tap_1.json \
  --pretty-output output/tap_1_review.json \
  --content-layout space \
  --strip-literal-backslashes
```

`--content-layout preserve` (mặc định) giữ `\n`; `space` thay newline trong
`van_ban` bằng khoảng trắng. `--strip-literal-backslashes` chỉ bỏ ký tự `\\`
thật sự trong nội dung; `\n` hiển thị trong JSON là cách JSON mã hoá newline,
không phải backslash cần xoá. Dùng các cờ này chỉ khi cần bản review/cleaned
output, vì chúng thay đổi cách trình bày văn bản gốc.

Các bước nội bộ:

1. Đọc raw text, font và toạ độ từng span bằng PyMuPDF; bỏ phần đầu/cuối trang
   theo margin cấu hình.
2. Với font trong `encoded_fonts`, giải mã CID bằng glyph profile. Font thường
   (ví dụ `TimesNewRoman`) dùng Unicode do PyMuPDF trả về.
3. Loại bỏ ký tự không thể đưa vào corpus (`U+FFFD`, control characters như
   `U+0001`, và surrogate), chuẩn hoá NFC và khoảng trắng.
4. Tách các văn bia theo tiêu đề; đọc metadata; sau mốc `content_start`, gán
   từng dòng vào chuyên mục và marker mặt bia.
5. Kiểm tra cấu trúc, kiểm tra Unicode lần cuối, rồi ghi JSONL UTF-8 theo kiểu
   atomic write để không tạo file đầu ra dở dang.

### 4. Logic extract dữ liệu và tách trang

Extractor không coi một trang PDF là một bản ghi. Trang chỉ là đơn vị đọc đầu
vào; một văn bia, metadata hoặc chuyên mục có thể bắt đầu ở trang này và tiếp tục
ở trang kế tiếp.

1. Với từng trang, PyMuPDF trả về các block, line, span và ký tự thô kèm toạ độ.
   Chương trình bỏ line có phần trên `page_margins.top` hoặc phần dưới
   `page_margins.bottom`. Việc này nhằm loại số trang, running header/footer;
   margin phải được chỉnh theo từng tập PDF nếu chúng chứa nội dung thật.
2. Các span trên cùng một line được ghép lại theo thứ tự PDF, sau đó chuẩn hoá
   Unicode/khoảng trắng. Các line còn lại được sắp xếp theo toạ độ dọc `y`, rồi
   toạ độ ngang `x`; mỗi line vẫn lưu `page_number` và `y0` để truy vết nguồn.
3. Danh sách line của tất cả trang được nối liên tục. `title_pattern` xác định
   đầu một văn bia; bản ghi kết thúc ngay trước tiêu đề văn bia kế tiếp. Vì vậy
   nội dung qua ngắt trang vẫn thuộc cùng một bản ghi, không cần ghép thủ công.
4. Bên trong một bản ghi, các line trước `content_start` được đọc thành metadata.
   Từ `content_start` trở đi, tiêu đề trong `content_sections` đổi chuyên mục;
   một line khớp `marker_pattern` (ví dụ `<4296>`) đổi mặt bia hiện hành. Text
   sau marker trên cùng line vẫn được giữ lại.
5. Khi gặp tiêu đề chuyên mục mới, mặt bia hiện hành được xoá để tránh vô tình
   gán nội dung của mặt trước vào mặt sau. Do đó PDF cần lặp marker ở đầu mỗi
   phần/mặt; nếu thiếu, text được giữ với `ky_hieu: null` và tạo warning thay vì
   bị gán đoán.

Tóm tắt luồng:

```text
PDF pages → lọc margin → decode + chuẩn hoá span → sort line theo (y, x)
→ nối line xuyên trang → title chia văn bia → metadata / chuyên mục / marker
→ validate → JSONL
```

## Cảnh báo và lỗi có thể gặp

### `warning` — cần kiểm tra PDF, chương trình vẫn tạo output

| Cảnh báo | Ý nghĩa thường gặp | Cách xử lý |
| --- | --- | --- |
| `marker <…> không có trong metadata` | Marker trong nội dung không nằm trong danh sách `Kí hiệu VNCHN`; có thể là typo, marker thừa, hoặc số trong chú thích bị parser hiểu là marker. | Đối chiếu PDF; sửa nguồn/config hoặc thêm quy tắc xử lý ngoại lệ nếu đó là mặt bia thật. |
| `không tìm thấy nội dung cho <…>` | Metadata có marker nhưng không có nội dung được gán cho marker đó. | Kiểm tra marker có bị gõ sai (ví dụ `3672`/`1672`) hoặc bị mất không. |
| `có nội dung không thuộc marker mặt bia` | Sau một tiêu đề chuyên mục không có marker, nên nội dung không thể gán an toàn cho mặt nào. | Thêm/khôi phục marker trong nguồn, hoặc chỉ dùng quy tắc kế thừa marker sau khi đã xác minh bố cục PDF. |
| `bỏ qua dòng trước metadata` | Có text nằm giữa tiêu đề văn bia và metadata đầu tiên. | Đối chiếu phần đầu bản ghi; điều chỉnh nhãn metadata hay layout/margin nếu cần. |

Ví dụ thực tế: một chú thích bị ngắt thành `<3417>` và `<3418>)` có thể làm dòng
thứ hai trông giống marker; đây là lỗi bố cục/nguồn PDF, không phải lỗi font.

### `error` — chương trình dừng, không ghi output mới

| Nhóm lỗi / thông báo tiêu biểu | Nguyên nhân và hướng xử lý |
| --- | --- |
| `Cannot read config`, `Config field …`, `Invalid title_pattern` | Config không đọc được hoặc sai schema/regex. Kiểm tra JSON và các trường bắt buộc. |
| `Input PDF does not exist`, `Cannot open PDF` | Sai đường dẫn, thiếu file hoặc PDF hỏng/không đọc được. |
| `Cannot read glyph profile`, `Glyph profile is …` | Glyph profile thiếu, JSON hỏng hoặc sai định dạng. Tạo lại profile. |
| `Glyph profile is missing signature`, `Cannot decode embedded font`, `Missing CID mapping` | Glyph trong PDF không có ánh xạ đáng tin cậy. Bổ sung font tham chiếu/tạo lại profile; không nên thay bằng ký tự đoán mò. |
| `Cannot resolve embedded font`, `Cannot disambiguate CID mapping` | PDF có resource/font không khớp hoặc nhiều subset font không thể phân biệt an toàn. Kiểm tra font nhúng và content stream của trang lỗi. |
| `No inscription titles matched`, `Duplicate inscription numbers`, `not consecutive`, `Expected … records` | Tiêu đề không khớp pattern hoặc số lượng/thứ tự bản ghi trái với config. Kiểm tra PDF, margins, `title_pattern` và các kiểm tra số lượng. |
| `thiếu mốc …`, `thiếu metadata bắt buộc …`, `không đọc được ký hiệu …` | Một bản ghi thiếu mốc bắt đầu nội dung, nhãn metadata hay marker bắt buộc. Đối chiếu PDF và cấu hình metadata. |
| `Invalid Unicode character U+…` | Chỉ xảy ra nếu dữ liệu được đưa thẳng vào serializer mà chưa qua luồng làm sạch; luồng extract PDF thông thường đã lọc các ký tự này. |
| `Record … does not end with field 'noi_dung'` | Lỗi nội bộ hoặc caller tạo record sai thứ tự trường; `noi_dung` luôn phải là trường cuối để JSONL có cấu trúc ổn định. |

## Kiểm thử

```bash
uv run python -m unittest discover -s tests -v
```

Integration test sẽ chạy khi cả PDF mẫu (không track Git) và glyph profile đã có;
nếu thiếu một trong hai thì test đó được bỏ qua.
