# Quy trình dịch sách EN→VI chuẩn (wenyi + profile vi)

> Nguyên tắc thép rút ra từ thực tế: **prepare → duyệt glossary → mới translate**.
> Bỏ qua bước duyệt là ngộ độc toàn sách (analyzer seed sai từ gốc, first-wins khóa lại).

## 0. Yêu cầu

- Gateway LLM sống ở `http://localhost:10100/v1` (opencodex) + key trong `$env:OCX_API_KEY`.
- File EPUB tiếng Anh nguồn. Không mở/sửa file nguồn bằng Calibre giữa chừng
  (đổi hash → state mismatch, phải migrate manifest).

## 1. Tạo config riêng cho từng sách (không dùng chung config.yaml)

```yaml
language: {source: en, target: vi-daichung}   # vi-kythuat / vi-vanhoc / vi-hucau tùy thể loại
llm:
  provider: openai-compatible
  base_url: http://localhost:10100/v1
  api_key_env: OCX_API_KEY
  reasoning_style: none
  timeout: 300
  max_retries: 2
  tiers:
    strong: {model: kenari/agnes-2-5-flash:free}
    cheap: {model: kilo/nex-agi/nex-n2.5-pro:free}
    fast: {model: kenari/hy3:free}
pipeline: {polish: true, review: false, book_understanding: true}
paths: {state_dir: <sach>_state}   # state riêng mỗi sách
```

Dự phòng khi 429: cheap → `kenari/mistral-medium-3-5:free`.

## 2. Prepare

```powershell
uv run trans-novel --config <sach>.yaml prepare "Tên-sách.epub"
```

Verify: `Preparation complete`, state ở `<state>/<slug>/targets/vi-daichung/`.

## 3. DUYỆT GLOSSARY SEED (bắt buộc, không bỏ qua)

```powershell
uv run trans-novel --config <sach>.yaml glossary list "Tên-sách.epub"
```

Đọc từng term, sửa những lỗi analyzer hay mắc:
- Thêm sắc thái không có trong gốc (`lucky fool → kẻ may mắn ngạo mạn`): resolve về trung thành.
- Gạch chéo trong term (`xác suất / tỷ lệ trúng`): chọn 1.
- Dịch thoát ở tầng glossary (`at the helm → chỉ huy con tàu`): trả về trung thành,
  để thoát cho translator trong câu.
- Tên sách: verify đã seed keep-as-is (`glossary list` phải có tên sách → target = source).

```powershell
# CLI hiện chỉ list/conflicts; resolve/sửa trực tiếp qua python:
uv run python -c "
from trans_novel.pipeline.runstore import RunStore
from trans_novel.glossary.store import GlossaryStore
import glob
rd = sorted(glob.glob('<state>/*/targets/vi-daichung'))[0]
g = GlossaryStore(RunStore(rd).glossary_path)
g.resolve_term('<source>', '<target-đúng>')
g.mark_conflicts_resolved('<source>')
g.close()"
```

## 4. Dịch thử 1 chương + đọc + chấm

```powershell
uv run trans-novel --config <sach>.yaml translate "Tên-sách.epub" --chapter N
uv run trans-novel --config <sach>.yaml assemble "Tên-sách.epub" --format txt --out sample.txt
```

Đọc `sample.txt`, chấm 10 điểm (mỗi điểm 1): tên riêng giữ, thoại ngoặc kép,
`…` đúng, xưng hô tôn trọng, idiom thoát, không EN sót, số/tiền viết chữ,
không bịa thêm, nhịp tự nhiên, không CJK lẫn. **Dưới 8 → sửa profile/glossary,
không chạy full.**

## 5. Chạy full (resume tự động)

```powershell
uv run trans-novel --config <sach>.yaml translate "Tên-sách.epub"
```

Gateway free 429/502 là bình thường: pipeline retry + checkpoint, chạy lại cùng
lệnh để nối tiếp. Kiểm tra tiến độ:

```powershell
uv run trans-novel --config <sach>.yaml status "Tên-sách.epub"
```

## 6. Duyệt conflicts + quét CJK + assemble cuối

```powershell
uv run trans-novel --config <sach>.yaml glossary conflicts "Tên-sách.epub"
# resolve theo quy tắc: HOA→thường, We→Chúng ta, hư từ giữ bản có hư từ,
# nghĩa thật quyết tay từng cái, xong mark resolved
uv run trans-novel --config <sach>.yaml assemble "Tên-sách.epub" --format epub --bilingual
```

Quét CJK lẫn trong output:

```powershell
uv run python scripts/fix_cjk.py   # quét + dịch lại segments nhiễm qua gateway
```

Verify file cuối: đếm blocks VI/EN, 0 EN, 0 CJK (trừ rác source).

## 7. Review (tùy chọn, cần model khỏe)

Reviewer model free mù với lỗi Việt → chỉ chạy khi tier cheap là model trả phí.
Không cố chạy cho có.

## 8. Không làm

- Không mở/sửa EPUB nguồn giữa chừng (vỡ hash state).
- Không `ruff format` lên file JSON data (thêm trailing comma hỏng file).
- Không repolish mù toàn sách (tốn ~2M tokens + tạo lỗi mới): polish theo chương,
  đọc diff (`target_before_polish`), sửa tay chỗ sai.
- Không commit `config.yaml` local, state, output, EPUB vào git.
