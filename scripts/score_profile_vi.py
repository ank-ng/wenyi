"""Score vi-daichung profile guidance against 11 Vietnamese literary criteria.

Offline: renders the real translator_system prompt for en->vi-daichung and
checks each criterion's regex anchors are present. Each anchor must match
in the correct context (no cross-criterion false hits). Each criterion
scores 0-10. Target: every criterion >= 9.
Usage: uv run python scripts/score_profile_vi.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from trans_novel.i18n import languages, prompts  # noqa: E402

# Each criterion: (name, [(anchor_label, regex_pattern), ...]).
# Patterns are case-sensitive to catch exact profile wording; use \s+ for
# whitespace so line wraps don't break matching.
CRITERIA: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "pronoun-i-we-ta",
        [
            ("i-is-toi", r"I\s+là\s+tôi"),
            ("we-default-exclusive", r"we\s+mặc\s+định\s+là\s+chúng\s+tôi"),
            ("we-inc-invitation", r"ta\s+chỉ\s+dùng\s+khi\s+rủ\s+bạn\s+đọc"),
            ("we-proper-noun", r"we\s+kèm\s+tên\s+riêng"),
            ("we-community", r"giới\s+nghiên\s+cứu\s+gọi"),
            ("you-always-ban", r"you\s+chung\s+luôn\s+là\s+bạn"),
            ("ban-i-to-ta", r"Cấm\s+I\s+thành\s+ta"),
        ],
    ),
    (
        "sentence-structure",
        [
            ("split-merge-reorder", r"Tách,\s+gộp\s+hoặc\s+đảo\s+câu"),
            ("drop-it-is", r"bỏ\s+It\s+is\s+X\s+that"),
            ("parallel-lists", r"liệt\s+kê\s+song\s+song"),
            ("short-closing-stands", r"câu\s+chốt\s+đứng\s+riêng"),
        ],
    ),
    (
        "rhythm-music",
        [
            ("short-long-mix", r"Xen\s+ngắn-dài"),
            ("read-aloud", r"đọc\s+to"),
            ("rewrite-on-stumble", r"vấp\s+thì\s+viết\s+lại"),
        ],
    ),
    (
        "reduplicative-onomatopoeia",
        [
            ("tu-lay", r"Từ\s+láy"),
            ("onomatopoeia", r"tượng\s+thanh\s+và\s+tượng\s+hình"),
            ("no-invention", r"không\s+bịa"),
        ],
    ),
    (
        "imagery-figures",
        [
            ("idiom-slang-proverb", r"Thành\s+ngữ,\s+slang\s+và\s+tục\s+ngữ"),
            ("vn-equivalent", r"tương\s+đương\s+Việt"),
            ("ban-raw", r"cấm\s+giữ\s+gốc"),
            ("ban-word-stack", r"cấm\s+xếp\s+chữ"),
        ],
    ),
    (
        "sino-vietnamese-balance",
        [
            ("han-viet-term", r"Hán-Việt"),
            ("native-everyday", r"thuần\s+Việt"),
            ("ban-overuse", r"cấm\s+quá\s+tay"),
        ],
    ),
    (
        "colloquial-idiom",
        [
            ("everyday-examples", r"Ví\s+dụ\s+đời\s+thường"),
            ("keep-question-voice", r"giữ\s+giọng\s+hỏi"),
        ],
    ),
    (
        "punctuation-presentation",
        [
            ("ellipsis-char", r"Ba\s+chấm\s+một\s+ký\s+tự"),
            ("double-quotes-child", r"ký\s+hiệu\s+lạ\s+giữ\s+vị\s+trí"),
            ("keep-symbol-place", r"ký\s+hiệu\s+lạ\s+giữ\s+vị\s+trí"),
        ],
    ),
    (
        "social-honorifics",
        [
            ("old-man-ong-ay", r"Ông\s+ấy\s+đủ\s+hai\s+chữ"),
            ("no-blood-inference", r"không\s+suy\s+huyết\s+thống"),
        ],
    ),
    (
        "genre-voice",
        [
            ("first-explain", r"giải\s+thích\s+lần\s+đầu"),
            ("consistent-use", r"nhất\s+quán"),
            ("plain-text", r"thuần\s+text"),
            ("no-markdown", r"không\s+markdown"),
        ],
    ),
    (
        "slang-proverb-localization",
        [
            ("slang-local", r"Thành\s+ngữ,\s+slang\s+và\s+tục\s+ngữ"),
            ("ban-keep-raw", r"cấm\s+giữ\s+gốc"),
        ],
    ),
    (
        "no-abbrev-slash-truncation",
        [
            ("ban-abbrev", r"Cấm\s+viết\s+tắt"),
            ("full-system-names", r"Hệ\s+thống\s+1\s+và\s+Hệ\s+thống\s+2"),
            ("words-not-slash", r"dấu\s+gạch\s+chéo"),
            ("full-translate", r"Dịch\s+đầy\s+đủ"),
            ("ban-ellipsis-trunc", r"cấm\s+tóm\s+tắt\s+bằng\s+ba\s+chấm"),
            ("psychopathy-term", r"rối\s+loạn\s+nhân\s+cách"),
            ("took-for-granted", r"đinh\s+ninh"),
            ("leading-authority", r"chuyên\s+gia\s+hàng\s+đầu"),
            ("sympathy-dong-cam", r"đồng\s+cảm"),
        ],
    ),
]
THRESHOLD = 9.0


def score_criterion(rendered: str, anchors: list[tuple[str, str]]) -> tuple[float, list[str]]:
    missing = [label for label, pat in anchors if not re.search(pat, rendered)]
    score = round(10.0 * (len(anchors) - len(missing)) / len(anchors), 1)
    return score, missing


def score_one(tgt: str) -> tuple[float, list[str]]:
    rendered = prompts.render("translator_system", src="en", tgt=tgt)
    child = languages.profile(tgt)
    print(f"== {tgt}: rendered={len(rendered)} guidance={len(child['target_guidance'])}")
    total = 0.0
    failed = []
    for name, anchors in CRITERIA:
        # voice criteria only apply to daichung; other genres have own voice
        if tgt != "vi-daichung" and name in (
            "slang-proverb-localization",
            "genre-voice",
            "sino-vietnamese-balance",
        ):
            continue
        # literary imagery only for fiction genres; technical writing is exempt
        if tgt == "vi-kythuat" and name in (
            "imagery-figures",
            "reduplicative-onomatopoeia",
        ):
            continue
        score, missing = score_criterion(rendered, anchors)
        total += score
        flag = "ok" if score >= THRESHOLD else "LOW"
        print(f"[{flag}] {name}: {score}/10 missing={missing}")
        if score < THRESHOLD:
            failed.append(name)
    exempt = ("slang-proverb-localization", "genre-voice", "sino-vietnamese-balance")
    if tgt == "vi-kythuat":
        exempt += ("imagery-figures", "reduplicative-onomatopoeia")
    n = len([c for c in CRITERIA if not (tgt != "vi-daichung" and c[0] in exempt)])
    avg = round(total / n, 1)
    print(f"AVERAGE {tgt}: {avg}/10  {'PASS' if not failed else 'FAIL ' + str(failed)}\n")
    return avg, failed


def main() -> int:
    all_failed: list[str] = []
    for tgt in ("vi-daichung", "vi-kythuat", "vi-vanhoc", "vi-hucau"):
        _, failed = score_one(tgt)
        all_failed.extend(f"{tgt}:{f}" for f in failed)
    print(f"OVERALL: {'PASS' if not all_failed else 'FAIL ' + str(all_failed)}")
    return 0 if not all_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
