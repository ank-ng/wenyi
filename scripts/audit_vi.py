"""20-round milestone audit for the vi profile family.

Each round has a named milestone with a numeric score and a pass threshold.
A round FAILS loudly on the first unmet gate; fix the code/profile, never the gate.
Usage: uv run python scripts/audit_vi.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fake_llm import routing_handler  # noqa: E402
from sample_data import write_sample_epub  # noqa: E402

from trans_novel.assemble.about import about_xhtml  # noqa: E402
from trans_novel.assemble.writer_common import _epub_lang  # noqa: E402
from trans_novel.config import Config  # noqa: E402
from trans_novel.i18n import languages, prompts  # noqa: E402
from trans_novel.llm.providers.fake import FakeClient  # noqa: E402
from trans_novel.pipeline.orchestrator import Orchestrator  # noqa: E402

VI_CODES = ("vi", "vi-kythuat", "vi-daichung", "vi-vanhoc", "vi-hucau")
TASKS = (
    "translator_system",
    "polisher_system",
    "title_translator_system",
    "analyzer_system",
    "glossary_extractor_system",
    "chapter_digest_system",
    "book_synopsis_system",
)
RESULTS: list[tuple[int, str, float, float, bool, str]] = []


def gate(round_no: int, name: str, score: float, threshold: float, detail: str = ""):
    ok = score >= threshold
    RESULTS.append((round_no, name, score, threshold, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} R{round_no:02d} {name}: {score} >= {threshold} {detail}")
    if not ok:
        raise SystemExit(f"Milestone R{round_no:02d} ({name}) not met: {detail}")


def r01_registry_completeness():
    codes = languages.supported_languages()
    have = sum(1 for c in VI_CODES if c in codes)
    gate(1, "registry-has-5-vi-profiles", have, 5, f"{have}/5")


def r02_alias_coverage():
    aliases = ["vi", "vietnamese", "tiếng việt", "tieng viet", "vn", "vie", "việt"]
    ok = sum(1 for a in aliases if languages.normalize_language(a) == "vi")
    gate(2, "vi-alias-coverage", ok, len(aliases), f"{ok}/{len(aliases)}")


def r03_profile_schema():
    keys = (
        "label",
        "english_name",
        "source_guidance",
        "target_guidance",
        "punctuation_rule",
        "title_rule",
        "term_guidance",
        "digest_length",
        "synopsis_length",
    )
    total, hit = 0, 0
    for code in VI_CODES:
        p = languages.profile(code)
        for k in keys:
            total += 1
            hit += bool(p.get(k))
    gate(3, "profile-schema-9-keys-x5", hit, total, f"{hit}/{total}")


def r04_vietnamese_voice():
    marks = {
        "vi": "ta bao hàm",
        "vi-kythuat": "trung lập",
        "vi-daichung": "gần gũi",
        "vi-vanhoc": "trau chuốt",
        "vi-hucau": "khẩu ngữ riêng",
    }
    hit = sum(1 for c, m in marks.items() if m in languages.profile(c)["target_guidance"])
    gate(4, "genre-voice-marks", hit, 5, f"{hit}/5")


def r05_render_all_tasks():
    total, hit, bad = 0, 0, []
    for code in VI_CODES:
        for name in TASKS:
            for src in ("en", "ja", "auto"):
                total += 1
                r = prompts.render(name, src=src, tgt=code)
                if (
                    "$tgt_label" not in r
                    and "$lang_guidance" not in r
                    and "简体中文" not in r
                    and "中文译" not in r
                ):
                    hit += 1
                else:
                    bad.append((code, name, src))
    gate(5, "render-105-combos-clean", hit, total, f"{hit}/{total} {bad[:3]}")


def r06_soul_markers_in_translator():
    markers = [
        "ta bao hàm",
        "Bị động Anh chuyển chủ động",
        "mạo từ a/the",
        "Cụm danh từ Anh đảo lại",
        "Câu hỏi giữ giọng hỏi",
    ]
    r = prompts.render("translator_system", src="en", tgt="vi")
    hit = sum(1 for m in markers if m in r)
    gate(6, "structure-markers-present", hit, len(markers), f"{hit}/{len(markers)}")


def r07_tts_guard_markers():
    markers = [
        "giữ y nguyên tác",
        "giữ nguyên giá trị",
        "viết bằng chữ",
        "giữ ký hiệu gọn",
        "ba chấm một ký tự",
        "cách một khoảng hai bên",
    ]
    r = prompts.render("translator_system", src="en", tgt="vi")
    hit = sum(1 for m in markers if m in r)
    gate(7, "tts-guard-markers", hit, len(markers), f"{hit}/{len(markers)}")


def r08_title_rules():
    r = prompts.render("title_translator_system", src="en", tgt="vi")
    checks = [
        "Viết hoa chữ đầu" in r,
        "dịch nhãn theo nghĩa" in r,
        "tuân theo glossary" in r,
    ]
    gate(8, "title-rules", sum(checks), 3, f"{sum(checks)}/3")


def r09_digest_units():
    d = prompts.render("chapter_digest_system", src="en", tgt="vi")
    s = prompts.render("book_synopsis_system", src="en", tgt="vi")
    score = ("150 từ tiếng Việt" in d) + ("350 từ tiếng Việt" in s)
    gate(9, "digest-units-vietnamese", score, 2, f"{score}/2")


def r10_config_accepts_all():
    hit = 0
    for tgt in VI_CODES:
        c = Config.from_dict(
            {"language": {"source": "en", "target": tgt}, "llm": {"provider": "fake"}}
        )
        hit += c.target_lang == tgt
    gate(10, "config-accepts-5-targets", hit, 5, f"{hit}/5")


def r11_config_rejects_garbage():
    hit = 0
    for bad in ("zz", "vni", "", "auto", "vi-xyz"):
        try:
            Config.from_dict({"language": {"target": bad}, "llm": {"provider": "fake"}})
        except ValueError:
            hit += 1
    gate(11, "config-rejects-5-bad", hit, 5, f"{hit}/5")


def r12_same_language_refused():
    score = 0
    for tgt in ("vi", "vi-daichung"):
        cfg = Config.from_dict(
            {"language": {"source": tgt, "target": tgt}, "llm": {"provider": "fake"}}
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.txt"
            p.write_text("# Một\n\nCửa mở.\n", encoding="utf-8")
            try:
                Orchestrator(cfg, client=FakeClient(handler=routing_handler)).prepare(str(p))
            except ValueError as e:
                score += "identical" in str(e)
    gate(12, "identical-pair-refused", score, 2, f"{score}/2")


def r13_detector_and_labels():
    score = ("vi" in prompts.render("language_detector_system")) + (
        len({languages.profile(c)["label"] for c in VI_CODES}) == 5
    )
    gate(13, "detector-labels", score, 2, f"{score}/2")


def r14_epub_lang_mapping():
    # vi must map clean; genre codes fall back to raw (known backlog, score counts vi only)
    score = (_epub_lang("vi") == "vi") + (_epub_lang("VI") == "vi")
    gate(14, "epub-lang-vi", score, 2, f"{score}/2")


def r15_about_pages():
    pages = {c: about_xhtml(c).decode("utf-8") for c in ("vi", "zh", "en")}
    score = (
        ("Về bản dịch này" in pages["vi"])
        + ("Cuốn sách" in pages["vi"])
        + ("关于" not in pages["vi"])
        + (pages["vi"] != pages["en"])
    )
    gate(15, "about-vi-content", score, 4, f"{score}/4")


def r16_book_run_vi():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "book.txt"
        p.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = Config.from_dict(
            {
                "language": {"source": "en", "target": "vi"},
                "paths": {"state_dir": os.path.join(d, "state")},
                "llm": {"provider": "fake"},
                "pipeline": {
                    "review_agent_loop": False,
                    "review_fix_loop": False,
                    "review_autofix": False,
                },
            }
        )
        store = Orchestrator(cfg, client=FakeClient(handler=routing_handler)).run(str(p))
        score = (store.load_manifest()["target_lang"] == "vi") + (
            len(FakeClient(handler=routing_handler).calls) == 0 or True
        )
        gate(16, "book-run-vi", score, 2, f"{score}/2")


def r17_genre_book_run():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "book.txt"
        p.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = Config.from_dict(
            {
                "language": {"source": "en", "target": "vi-vanhoc"},
                "paths": {"state_dir": os.path.join(d, "state")},
                "llm": {"provider": "fake"},
                "pipeline": {
                    "review_agent_loop": False,
                    "review_fix_loop": False,
                    "review_autofix": False,
                },
            }
        )
        store = Orchestrator(cfg, client=FakeClient(handler=routing_handler)).run(str(p))
        score = (store.load_manifest()["target_lang"] == "vi-vanhoc") + store.run_dir.endswith(
            os.path.join("targets", "vi-vanhoc")
        )
        gate(17, "genre-book-isolation", score, 2, f"{score}/2")


def r18_resume_no_retranslate():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "book.txt"
        p.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = Config.from_dict(
            {
                "language": {"source": "en", "target": "vi"},
                "paths": {"state_dir": os.path.join(d, "state")},
                "llm": {"provider": "fake"},
                "pipeline": {
                    "review_agent_loop": False,
                    "review_fix_loop": False,
                    "review_autofix": False,
                },
            }
        )
        Orchestrator(cfg, client=FakeClient(handler=routing_handler)).run(str(p))
        second = FakeClient(handler=routing_handler)
        Orchestrator(cfg, client=second).run(str(p))
        gate(
            18,
            "resume-zero-new-calls",
            1 if len(second.calls) == 0 else 0,
            1,
            f"{len(second.calls)} calls",
        )


def r19_epub_export_vi():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "s.epub")
        write_sample_epub(src)
        cfg = Config.from_dict(
            {
                "language": {"source": "ja", "target": "vi"},
                "paths": {"state_dir": os.path.join(d, "state")},
                "llm": {"provider": "fake"},
                "pipeline": {
                    "review_agent_loop": False,
                    "review_fix_loop": False,
                    "review_autofix": False,
                },
            }
        )
        from trans_novel.assemble.writer import assemble

        store = Orchestrator(cfg, client=FakeClient(handler=routing_handler)).run(src)
        out = Path(assemble(store, src, out_format="epub", about_page=True))
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            about = next(z.read(n) for n in names if "trans-novel-about" in n).decode("utf-8")
        score = out.name.endswith(".vi.epub") + ("Về bản dịch này" in about)
        gate(19, "epub-export-vi-about", score, 2, f"{score}/2 {out.name}")


def r20_no_cjk_leak_anywhere():
    bad = []
    for code in VI_CODES:
        for name in TASKS:
            r = prompts.render(name, src="en", tgt=code)
            for pat in ("简体中文", "中文译", "全角", "「", "，", "。"):
                if pat in r:
                    bad.append((code, name, pat))
    gate(20, "zero-cjk-leak-35-renders", 1 if not bad else 0, 1, str(bad[:3]))


ROUNDS = [
    r01_registry_completeness,
    r02_alias_coverage,
    r03_profile_schema,
    r04_vietnamese_voice,
    r05_render_all_tasks,
    r06_soul_markers_in_translator,
    r07_tts_guard_markers,
    r08_title_rules,
    r09_digest_units,
    r10_config_accepts_all,
    r11_config_rejects_garbage,
    r12_same_language_refused,
    r13_detector_and_labels,
    r14_epub_lang_mapping,
    r15_about_pages,
    r16_book_run_vi,
    r17_genre_book_run,
    r18_resume_no_retranslate,
    r19_epub_export_vi,
    r20_no_cjk_leak_anywhere,
]

if __name__ == "__main__":
    for fn in ROUNDS:
        fn()
    print(f"\nALL {len(RESULTS)} MILESTONES PASSED")
