# Debug Fooled by Randomness Prologue (19 segments, vi-daichung, agnes-2-5)

Ngày: 2026-09-12. Chunk: `fooled_chunks/prologue.txt`. State: `fooled_state/`.

## Lỗi hệ thống tìm thấy (9)

1. **CJK lẫn** P.3 `某天` — model đa ngữ. Fix: reviewer template thêm check `script` (đã vá `reviewer_system.txt`).
2. **Title P.1 bịa** `VẪN CÓ NHỮNG NHÀ THỜ TRÊN MÂY MÙ` cho MOSQUES IN THE CLOUDS. Title translator thiếu context. Chưa vá (cần title brief, backlog).
3. **CJK lẫn** P.7 `bi又可 hài`. Cùng fix #1.
4. **Tên sách dịch từng chữ** P.16 `Đụng dối bởi Sự Ngẫu nhiên`. Fix: `_seed_title_glossary` trong `preparation.py` (đã vá + 2 tests).
5. **Sót EN** P.8 `Armed với siêu máy tính`. Translator bỏ sót từ đầu câu. Chưa vá (cần coverage check, backlog).
6. **Ngoặc đơn đôi** `''thơ ca`, `''nhà phê bình.''` — rule ngoặc kép chưa ăn với model này. Ghi nhận.
7. **`bọn` cho nhóm triết gia** P.17 (Wittgenstein/Descartes phe). Rule cấm nó/hắn có nhưng `bọn` lọt. Chưa vá — bổ sung vào vi gốc: `bọn` chỉ dùng cho khinh miệt có chủ ý, nhóm trung lập dùng phe/nhóm.
8. **`ngạo mạn` thêm sắc thái** cho lucky fool P.2 (fool=khờ, không ngạo mạn). Bịa sắc thái — cùng họ L4 (đã có rule cấm bịa).
9. **Segment cụt** P.18 `(…`. Nghi truncation. Chưa vá (cần sentence-complete check, backlog).

## Điểm tốt (giữ)
- `gán công`, `tia sáng xuyên qua tiếng ồn`, `thiên nga đen`, `đấu kỵ`, `Utopia`, `ta suy ngẫm`.
- Triết ngữ xử lý tốt hơn mong đợi với model free.
