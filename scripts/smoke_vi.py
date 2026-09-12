"""Smoke test the vi language patch end-to-end with the offline fake provider."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fake_llm import routing_handler  # noqa: E402
from sample_data import write_sample_epub  # noqa: E402

from trans_novel.assemble.about import about_xhtml, append_about_page  # noqa: E402
from trans_novel.assemble.writer import assemble  # noqa: E402
from trans_novel.assemble.writer_common import _epub_lang  # noqa: E402
from trans_novel.config import Config  # noqa: E402
from trans_novel.glossary.store import GlossaryStore, GlossaryTerm  # noqa: E402
from trans_novel.i18n import languages, prompts  # noqa: E402
from trans_novel.i18n.resources import prompt_fingerprint  # noqa: E402
from trans_novel.llm.providers.fake import FakeClient  # noqa: E402
from trans_novel.pipeline.orchestrator import Orchestrator  # noqa: E402
from trans_novel.pipeline.runstore import translation_run_dir  # noqa: E402
from trans_novel.srt.translate import translate_srt  # noqa: E402

VI_SENTENCE = "Cánh cửa mở ra. “Xin chào!”"
PASS = []
FAIL = []


def check(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        FAIL.append((name, repr(exc)))
        print(f"FAIL {name}: {exc!r}")
    else:
        PASS.append(name)
        print(f"ok {name}")


def t_aliases():
    assert languages.normalize_language("vi") == "vi"
    assert languages.normalize_language("VI") == "vi"
    assert languages.normalize_language(" vietnamese ") == "vi"
    assert languages.normalize_language("Tiếng Việt") == "vi"
    assert languages.normalize_language("tieng viet") == "vi"
    assert languages.normalize_language("vn") == "vi"
    assert languages.require_language("vi") == "vi"
    assert "vi" in languages.supported_languages()


def t_alias_edge():
    # Underscore/diacritic/case variants must not sneak past the whitelist.
    assert languages.normalize_language("TIẾNG_VIỆT") == "vi"
    assert languages.normalize_language("việt") == "vi"
    assert languages.normalize_language("viet") == "vi"
    assert languages.normalize_language("zz") == ""
    assert languages.normalize_language("") == ""
    assert languages.normalize_language("auto") == ""
    assert languages.label("vi") == "Tiếng Việt"
    assert languages.label("zz") == "the source language"


def t_profile_keys():
    profile = languages.profile("vi")
    for key in (
        "label",
        "english_name",
        "source_guidance",
        "target_guidance",
        "punctuation_rule",
        "title_rule",
        "term_guidance",
        "digest_length",
        "synopsis_length",
    ):
        assert profile[key], key
    assert profile["english_name"] == "Vietnamese"


def t_render_core_tasks():
    for name in (
        "translator_system",
        "polisher_system",
        "title_translator_system",
        "analyzer_system",
        "glossary_extractor_system",
        "chapter_digest_system",
        "book_synopsis_system",
    ):
        for src in ("en", "ja", "auto"):
            rendered = prompts.render(name, src=src, tgt="vi")
            assert "$tgt_label" not in rendered, name
            assert "$lang_guidance" not in rendered, name
            assert "简体中文" not in rendered, name
            assert "中文译" not in rendered, name
            assert "Tiếng Việt" in rendered or "tiếng Việt" in rendered, name


def t_render_cjk_free():
    rendered = prompts.render("translator_system", src="en", tgt="vi")
    assert "dấu thanh" in rendered
    assert "全角" not in rendered
    assert "「" not in rendered
    # Full-width stops must never leak into the vi prompt.
    assert "，" not in rendered and "。" not in rendered
    assert "TTS đọc được" in rendered or "viết bằng chữ" in rendered


def t_tts_guard_renders_everywhere():
    # punct_rule fans out to translator, title and SRT prompts alike.
    title = prompts.render("title_translator_system", src="en", tgt="vi")
    assert "quy ước sách Việt" in title
    srt = prompts.render("srt_batch_system", src="en", tgt="vi")
    assert "giữ y nguyên tác" in srt or "viết bằng chữ" in srt
    body = prompts.render("translator_system", src="en", tgt="vi")
    for needle in (
        "giữ y nguyên tác",
        "giữ nguyên giá trị",
        "viết bằng chữ",
        "giữ ký hiệu gọn",
        "ba chấm một ký tự",
        "cách hai bên",
    ):
        assert needle in body, needle


def t_translate_guidance():
    guidance = languages.translate_guidance("en", tgt="vi")
    assert "tiếng Việt" in guidance or "Tiếng Việt" in guidance
    assert "dấu thanh" in guidance
    # Unknown source falls back to the shared generic guidance, still with vi target.
    generic = languages.translate_guidance("zz", tgt="vi")
    assert "tiếng Việt" in generic or "Tiếng Việt" in generic
    assert languages.term_guidance("en").strip()


def t_honorific_fallback():
    assert languages.honorific_rule("keep_style", src="en", tgt="vi")
    assert languages.honorific_rule("bogus-strategy", src="en", tgt="vi")


def t_config_accepts_vi():
    for target in ("vi", "VI", "vietnamese", "Tiếng Việt", "vn", "vie"):
        cfg = Config.from_dict(
            {
                "language": {"source": "en", "target": target},
                "llm": {"provider": "fake"},
            }
        )
        assert cfg.target_lang == "vi", target
    for source in ("vi", "vietnamese", "vn", "auto"):
        cfg = Config.from_dict(
            {"language": {"source": source, "target": "en"}, "llm": {"provider": "fake"}}
        )
        assert cfg.source_lang == ("auto" if source == "auto" else "vi"), source


def t_config_rejects_garbage():
    for bad in ("zz", "vni", "vnn", "", "auto"):
        try:
            Config.from_dict({"language": {"target": bad}, "llm": {"provider": "fake"}})
        except ValueError:
            pass
        else:
            raise AssertionError(f"target {bad!r} accepted")
    # ISO 639-2 vie is a valid alias for vi.
    assert (
        Config.from_dict({"language": {"target": "vie"}, "llm": {"provider": "fake"}}).target_lang
        == "vi"
    )


def t_same_lang_refused():
    cfg = Config.from_dict(
        {"language": {"source": "vi", "target": "VI"}, "llm": {"provider": "fake"}}
    )
    assert cfg.source_lang == cfg.target_lang == "vi"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "book.txt"
        path.write_text("# Một\n\nCánh cửa mở ra.\n", encoding="utf-8")
        try:
            Orchestrator(cfg, client=FakeClient(handler=routing_handler)).prepare(str(path))
        except ValueError as exc:
            assert "identical" in str(exc)
        else:
            raise AssertionError("vi→vi not refused")


def t_detector_mentions_vi():
    text = prompts.render("language_detector_system")
    assert "vi" in text


def t_epub_lang_code():
    assert _epub_lang("vi") == "vi"
    assert _epub_lang("VI") == "vi"
    assert _epub_lang("vietnamese") == "vi"


def t_about_vi():
    page = about_xhtml("vi").decode("utf-8")
    assert "Wenyi" in page
    assert "Cuốn sách" in page
    assert 'lang="vi"' in page
    assert "github.com/BigDawnGhost/wenyi" in page
    assert about_xhtml("en").decode("utf-8") != page


def t_append_about_vi_to_epub():
    with tempfile.TemporaryDirectory() as directory:
        src = os.path.join(directory, "sample.epub")
        write_sample_epub(src)
        out = os.path.join(directory, "sample.vi.epub")
        with open(src, "rb") as fin, open(out, "wb") as fout:
            fout.write(fin.read())
        assert append_about_page(out, "vi")
        with zipfile.ZipFile(out) as book:
            names = book.namelist()
            assert any("trans-novel-about" in name for name in names)
            blob = next(book.read(n) for n in names if "trans-novel-about" in n)
            assert "Cuốn sách" in blob.decode("utf-8")


def _vi_handler(messages, tier, json_mode):
    system, user = messages[0]["content"], messages[-1]["content"]
    n = len(re.findall(r"^\[\d+\]", user, re.MULTILINE))
    if "pre-translation analyst" in system:
        assert "Tiếng Việt" in system or "tiếng Việt" in system
        return json.dumps({"style_guide": "giọng kể nhất quán", "characters": [], "terms": []})
    if "literary translator" in system:
        assert "Tiếng Việt" in system or "tiếng Việt" in system
        return json.dumps({"translations": [VI_SENTENCE] * n})
    if "prose editor" in system:
        assert "Tiếng Việt" in system or "tiếng Việt" in system
        return json.dumps({"polished": [VI_SENTENCE] * n})
    if "chapter title translator" in system:
        assert "Tiếng Việt" in system or "tiếng Việt" in system
        return json.dumps({"titles": [VI_SENTENCE] * n})
    if "chapter digest writer" in system or "whole-book synopsis writer" in system:
        assert "tiếng Việt" in system or "Tiếng Việt" in system
        return VI_SENTENCE
    if "extractor" in system:
        assert "tiếng Việt" in system or "Tiếng Việt" in system
        return '{"terms":[]}'
    if "translation reviewer" in system:
        return json.dumps({"issues": [], "reviewed_segments": n, "complete": True})
    return routing_handler(messages, tier, json_mode)


def _vi_config(directory, **overrides):
    payload = {
        "language": {"source": "en", "target": "vi"},
        "paths": {"state_dir": os.path.join(directory, "state")},
        "llm": {"provider": "fake"},
        "pipeline": {
            "review_agent_loop": False,
            "review_fix_loop": False,
            "review_autofix": False,
        },
    }
    payload.update(overrides)
    return Config.from_dict(payload)


def t_book_en_vi_txt():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "book.txt"
        path.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = _vi_config(directory)
        store = Orchestrator(cfg, client=FakeClient(handler=_vi_handler)).run(str(path))
        assert store.load_manifest()["target_lang"] == "vi"
        assert store.load_manifest()["prompt_fingerprint"] == prompt_fingerprint()
        assert store.load_chapter(0).text_segments[0].target == VI_SENTENCE
        assert translation_run_dir(os.path.join(directory, "state"), "book", "vi") == store.run_dir
        out = Path(assemble(store, str(path), out_format="txt", about_page=False))
        assert out.name.endswith(".vi.txt")
        assert VI_SENTENCE in out.read_text(encoding="utf-8")


def t_book_en_vi_all_formats():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "book.txt"
        path.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = _vi_config(directory)
        store = Orchestrator(cfg, client=FakeClient(handler=_vi_handler)).run(str(path))
        for fmt in ("txt", "markdown", "html", "epub", "docx"):
            for bilingual in (False, True):
                output = Path(
                    assemble(
                        store,
                        str(path),
                        out_format=fmt,
                        bilingual=bilingual,
                        punctuation_normalize=True,
                    )
                )
                assert f".vi{'-bi' if bilingual else ''}." in output.name, output.name
                assert output.is_file()
                if fmt == "epub":
                    with zipfile.ZipFile(output) as book:
                        opf = next(n for n in book.namelist() if n.endswith(".opf"))
                        assert ">vi</" in book.read(opf).decode(), output.name


def t_epub_en_vi_about():
    with tempfile.TemporaryDirectory() as directory:
        src = os.path.join(directory, "sample.epub")
        write_sample_epub(src)
        cfg = _vi_config(directory)
        store = Orchestrator(cfg, client=FakeClient(handler=_vi_handler)).run(src)
        out = Path(assemble(store, src, out_format="epub", about_page=True))
        assert out.name.endswith(".vi.epub")
        with zipfile.ZipFile(out) as book:
            names = book.namelist()
            blob = next(book.read(n) for n in names if "trans-novel-about" in n)
            assert "Cuốn sách" in blob.decode("utf-8")


def t_docx_vi_no_song_font():
    from docx import Document

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "book.txt"
        path.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = _vi_config(directory)
        store = Orchestrator(cfg, client=FakeClient(handler=_vi_handler)).run(str(path))
        out = Path(assemble(store, str(path), out_format="docx"))
        assert out.name.endswith(".vi.docx")
        fonts = {(r.font.name or "") for p in Document(str(out)).paragraphs for r in p.runs}
        assert "宋体" not in fonts, fonts


def t_target_isolation_vi_vs_en():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "book.txt"
        source.write_text("# 一\n\n扉が開いた。\n", encoding="utf-8")
        dirs = {}
        for target in ("vi", "en"):
            cfg = Config.from_dict(
                {
                    "language": {"source": "ja", "target": target},
                    "paths": {"state_dir": str(root / "state")},
                    "llm": {"provider": "fake"},
                    "pipeline": {"book_understanding": False},
                }
            )
            store = Orchestrator(cfg, client=FakeClient(handler=routing_handler)).prepare(
                str(source)
            )
            dirs[target] = store.run_dir
        assert dirs["vi"] != dirs["en"]
        assert dirs["vi"].endswith(os.path.join("targets", "vi"))
        # Switching target on the same book must fail loudly, not mix state.
        cfg = Config.from_dict(
            {
                "language": {"source": "ja", "target": "vi"},
                "paths": {"state_dir": str(root / "state")},
                "llm": {"provider": "fake"},
            }
        )
        store = Orchestrator(cfg, client=FakeClient(handler=routing_handler)).prepare(str(source))
        try:
            languages.validate_run_languages(store.load_manifest(), "ja", "en")
        except ValueError:
            pass
        else:
            raise AssertionError("cross-target resume not refused")


def t_resume_no_retranslate():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "book.txt"
        path.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = _vi_config(directory)
        first = FakeClient(handler=_vi_handler)
        Orchestrator(cfg, client=first).run(str(path))
        calls_before = len(first.calls)
        assert calls_before > 0
        second = FakeClient(handler=_vi_handler)
        Orchestrator(cfg, client=second).run(str(path))
        assert len(second.calls) == 0, [c.get("stage") for c in second.calls]


def t_glossary_vi_terms():
    with tempfile.TemporaryDirectory() as directory:
        db = os.path.join(directory, "g.db")
        store = GlossaryStore(db)
        try:
            term = GlossaryTerm(
                source="John",
                target="Gio-an",
                type="person",
                aliases=["Johnny"],
                note="nhân vật chính",
            )
            assert store.upsert_term(term) == "inserted"
            assert store.upsert_term(term) == "unchanged"
            assert store.upsert_term(GlossaryTerm(source="John", target="Dôn")) == "conflict"
            conflicts = store.open_conflicts()
            assert len(conflicts) == 1
            assert conflicts[0]["existing_target"] == "Gio-an"
        finally:
            store.close()


def t_srt_en_vi():
    def handler(messages, tier, json_mode):
        if json_mode:
            return json.dumps(
                {"1": "Xin chào thế giới.", "2": "Bạn khỏe không?"},
                ensure_ascii=False,
            )
        return "Xin chào thế giới."

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "demo.srt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "1\n00:00:01,000 --> 00:00:02,000\nHello world.\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nHow are you?\n"
            )
        cfg = Config.from_dict(
            {
                "language": {"source": "en", "target": "vi"},
                "paths": {"state_dir": os.path.join(directory, "state")},
                "output": {"mono": True, "bilingual": True},
                "llm": {"provider": "fake"},
            }
        )
        result = translate_srt(path, cfg, client=FakeClient(handler=handler))
        assert result["cue_count"] == 2
        assert any(p.endswith(".vi.srt") for p in result["outputs"])
        assert any(p.endswith(".vi-bi.srt") for p in result["outputs"])
        mono = next(p for p in result["outputs"] if p.endswith(".vi.srt"))
        with open(mono, encoding="utf-8") as handle:
            assert "Xin chào thế giới." in handle.read()


def t_genre_profiles_render():
    voices = {
        "vi-kythuat": "trung lập",
        "vi-daichung": "gần gũi",
        "vi-vanhoc": "trau chuốt",
        "vi-hucau": "khẩu ngữ riêng",
    }
    for code, mark in voices.items():
        profile = languages.profile(code)
        assert profile["label"].startswith("Tiếng Việt"), code
        assert mark in profile["target_guidance"], code
        # extends merge: base keys survive
        for name in ("translator_system", "polisher_system"):
            rendered = prompts.render(name, src="en", tgt=code)
            assert mark in rendered, (code, name)
            assert "简体中文" not in rendered and "中文译" not in rendered, (code, name)
        title = prompts.render("title_translator_system", src="en", tgt=code)
        assert "Tiếng Việt" in title or "tiếng Việt" in title, (code, "title")
        assert "简体中文" not in title and "中文译" not in title, (code, "title")


def t_genre_profile_book_run():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "book.txt"
        path.write_text("# One\n\nThe door opened.\n", encoding="utf-8")
        cfg = Config.from_dict(
            {
                "language": {"source": "en", "target": "vi-daichung"},
                "paths": {"state_dir": os.path.join(directory, "state")},
                "llm": {"provider": "fake"},
                "pipeline": {
                    "review_agent_loop": False,
                    "review_fix_loop": False,
                    "review_autofix": False,
                },
            }
        )
        store = Orchestrator(cfg, client=FakeClient(handler=_vi_handler)).run(str(path))
        assert store.load_manifest()["target_lang"] == "vi-daichung"
        out = Path(assemble(store, str(path), out_format="txt", about_page=False))
        assert ".vi-daichung." in out.name, out.name


CHECKS = [
    ("aliases", t_aliases),
    ("alias-edge", t_alias_edge),
    ("profile-keys", t_profile_keys),
    ("render-core-tasks", t_render_core_tasks),
    ("render-cjk-free", t_render_cjk_free),
    ("tts-guard-renders", t_tts_guard_renders_everywhere),
    ("honorific-fallback", t_honorific_fallback),
    ("config-accepts-vi", t_config_accepts_vi),
    ("config-rejects-garbage", t_config_rejects_garbage),
    ("same-lang-refused", t_same_lang_refused),
    ("detector-mentions-vi", t_detector_mentions_vi),
    ("epub-lang-code", t_epub_lang_code),
    ("about-vi", t_about_vi),
    ("append-about-vi", t_append_about_vi_to_epub),
    ("book-en-vi-txt", t_book_en_vi_txt),
    ("book-en-vi-all-formats", t_book_en_vi_all_formats),
    ("epub-en-vi-about", t_epub_en_vi_about),
    ("docx-vi-no-song", t_docx_vi_no_song_font),
    ("resume-no-retranslate", t_resume_no_retranslate),
    ("target-isolation", t_target_isolation_vi_vs_en),
    ("glossary-vi-terms", t_glossary_vi_terms),
    ("srt-en-vi", t_srt_en_vi),
    ("genre-render", t_genre_profiles_render),
    ("genre-book-run", t_genre_profile_book_run),
]

if __name__ == "__main__":
    for name, fn in CHECKS:
        check(name, fn)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        raise SystemExit(1)
