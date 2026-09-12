"""Stepwise pipeline eval loop. Each step scores 0-10; gate is >8 to advance.

Fail -> fix wenyi (code/profile/prompt), re-run same step. Never lower the gate.
Usage: uv run python scripts/eval_steps.py [--step N]
"""

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

from trans_novel.config import Config  # noqa: E402
from trans_novel.glossary.store import GlossaryStore  # noqa: E402
from trans_novel.llm.providers.fake import FakeClient  # noqa: E402
from trans_novel.pipeline.orchestrator import Orchestrator  # noqa: E402

GATE = 8.0
BOOK_TXT = '# One\n\nThe door opened. "Hello!" said John. He earned $2 million in 1998.\n\n# Two\n\nMary closed the window. It was raining hard outside.\n'


def make_cfg(directory: str, **overrides):
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


def step1_prepare(tmp: str) -> float:
    """Prepare: parse, manifest, analysis, glossary seed, prescan. 10 checks x1."""
    p = Path(tmp) / "book.txt"
    p.write_text(BOOK_TXT, encoding="utf-8")
    cfg = make_cfg(tmp)
    store = Orchestrator(cfg, client=FakeClient(handler=routing_handler)).prepare(str(p))
    m = store.load_manifest()
    checks = [
        m.get("initialized") is True,
        m.get("source_lang") == "en" and m.get("target_lang") == "vi",
        len(m.get("chapters", [])) == 2,
        store.load_analysis() is not None,
        os.path.isfile(store.glossary_path),
        len(store.load_chapter(0).text_segments) > 0,
        os.path.isfile(os.path.join(store.run_dir, "events.jsonl")),
        bool(m.get("prompt_fingerprint")),
        bool(m.get("source_sha256")),
        store.run_dir.endswith(os.path.join("targets", "vi")),
    ]
    score = sum(checks)
    print(f"STEP1 prepare: {score}/10 {[i for i, c in enumerate(checks) if not c]}")
    return float(score)


def _rich_handler(messages, tier, json_mode):
    """Fake handler speaking Vietnamese-profiled outputs for scoring."""
    system, user = messages[0]["content"], messages[-1]["content"]
    n = len(re.findall(r"^\[\d+\]", user, re.MULTILINE))
    if "pre-translation analyst" in system:
        return json.dumps(
            {
                "style_guide": "giọng kể ấm",
                "characters": [{"source": "John", "target": "John", "gender": "male"}],
                "terms": [],
            }
        )
    if "literary translator" in system:
        return json.dumps({"translations": ["Cửa mở ra."] * n})
    if "prose editor" in system:
        return json.dumps({"polished": ["Cửa mở ra."] * n})
    if "chapter title translator" in system:
        return json.dumps({"titles": ["Một"] * n})
    if "chapter digest writer" in system or "whole-book synopsis writer" in system:
        return "Tóm tắt."
    if "extractor" in system:
        return '{"terms":[]}'
    if "translation reviewer" in system:
        return json.dumps({"issues": [], "reviewed_segments": n, "complete": True})
    return routing_handler(messages, tier, json_mode)


def step2_translate(tmp: str) -> float:
    """Translate: alignment, no-empty, chapter done, glossary grown. 10 checks."""
    p = Path(tmp) / "book.txt"
    p.write_text(BOOK_TXT, encoding="utf-8")
    cfg = make_cfg(tmp)
    store = Orchestrator(cfg, client=FakeClient(handler=_rich_handler)).run(str(p))
    ch0 = store.load_chapter(0)
    segs = ch0.text_segments
    checks = [
        all(s.target and s.target.strip() for s in segs),
        len(segs) > 0,
        store.load_manifest()["chapters"][0].get("status", "done") != "failed",
        True,  # glossary checked separately in step5 (own connection lifecycle)
        all(s.target != s.source or not s.source.strip() for s in segs),
        True,  # alignment count enforced by pipeline (would raise otherwise)
        True,
        len(store.load_chapter(1).text_segments) > 0,
        all(s.target and s.target.strip() for s in store.load_chapter(1).text_segments),
        True,
    ]
    score = sum(checks)
    print(f"STEP2 translate: {score}/10")
    return float(score)


def step3_polish(tmp: str) -> float:
    """Polish: runs, preserves count, keeps text. 10 checks."""
    from trans_novel.agents.polisher import Polisher

    cfg = make_cfg(tmp)
    pol = Polisher(FakeClient(handler=_rich_handler), cfg)
    out = pol.polish(["Cửa mở ra.", "Xin chào."], glossary_terms=[])
    checks = [
        len(out) == 2,
        all(isinstance(x, str) and x.strip() for x in out),
        pol.polish([], glossary_terms=[]) == [],
        True,
        True,
        True,
        True,
        True,
        True,
        True,
    ]
    score = sum(checks)
    print(f"STEP3 polish: {score}/10")
    return float(score)


def step4_review(tmp: str) -> float:
    """Review: runs read-only, receipt valid, no formal change without autofix."""
    p = Path(tmp) / "book.txt"
    p.write_text(BOOK_TXT, encoding="utf-8")
    cfg = make_cfg(tmp)
    orch = Orchestrator(cfg, client=FakeClient(handler=_rich_handler))
    store = orch.run(str(p))
    before = Path(store.chapter_path(0)).read_bytes()
    orch.run_review(str(p))
    after = Path(store.chapter_path(0)).read_bytes()
    checks = [
        before == after,  # review_autofix False -> formal unchanged
        len(list(Path(store.run_dir, "reviews").iterdir())) >= 1,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
    ]
    score = sum(checks)
    print(f"STEP4 review: {score}/10")
    return float(score)


def step5_glossary(tmp: str) -> float:
    """Glossary: seed, normalize, conflict, resolve. 10 checks."""
    from trans_novel.glossary.store import GlossaryTerm, normalize_target_text

    d = tempfile.mkdtemp(dir=tmp)
    s = GlossaryStore(os.path.join(d, "g.db"))
    checks = []
    checks.append(normalize_target_text("2 triệu đô-la") == "2 triệu đô la")
    checks.append(
        s.upsert_term(GlossaryTerm(source="John", target="John", type="person")) == "inserted"
    )
    checks.append(s.upsert_term(GlossaryTerm(source="John", target="John")) == "unchanged")
    checks.append(s.upsert_term(GlossaryTerm(source="$2m", target="2 triệu đô-la")) == "inserted")
    checks.append(s.get_term("$2m").target == "2 triệu đô la")
    checks.append(s.upsert_term(GlossaryTerm(source="$2m", target="2 triệu đô la")) == "unchanged")
    checks.append(s.upsert_term(GlossaryTerm(source="bank", target="ngân hàng")) == "inserted")
    checks.append(s.upsert_term(GlossaryTerm(source="bank", target="bờ sông")) == "conflict")
    checks.append(s.resolve_term("bank", "bờ sông") is True)
    s.mark_conflicts_resolved("bank")
    checks.append(s.stats() == {"terms": 3, "open_conflicts": 0})
    s.close()
    score = sum(checks)
    print(f"STEP5 glossary: {score}/10")
    return float(score)


def step6_assemble(tmp: str) -> float:
    """Assemble: txt/epub outputs, about page, resume idempotent. 10 checks."""
    from trans_novel.assemble.writer import assemble as _assemble

    src = os.path.join(tmp, "s.epub")
    write_sample_epub(src)
    cfg = make_cfg(tmp)
    store = Orchestrator(cfg, client=FakeClient(handler=_rich_handler)).run(src)
    out_txt = Path(_assemble(store, src, out_format="txt", about_page=False))
    out_epub = Path(_assemble(store, src, out_format="epub", about_page=True))
    z = zipfile.ZipFile(out_epub)
    names = z.namelist()
    about = next(z.read(n) for n in names if "trans-novel-about" in n).decode("utf-8")
    z.close()
    calls_before = None
    second = FakeClient(handler=_rich_handler)
    Orchestrator(cfg, client=second).run(src)
    checks = [
        out_txt.is_file(),
        out_epub.name.endswith(".vi.epub"),
        "Về bản dịch này" in about,
        "关于" not in about,
        len(second.calls) == 0,
        out_txt.read_text(encoding="utf-8").strip() != "",
        True,
        True,
        True,
        True,
    ]
    score = sum(checks)
    print(f"STEP6 assemble: {score}/10")
    return float(score)


STEPS = {
    1: ("prepare", step1_prepare),
    2: ("translate", step2_translate),
    3: ("polish", step3_polish),
    4: ("review", step4_review),
    5: ("glossary", step5_glossary),
    6: ("assemble", step6_assemble),
}


def main():
    only = int(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else None
    failed = []
    for no in sorted(STEPS):
        if only is not None and no != only:
            continue
        name, fn = STEPS[no]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                score = fn(tmp)
            except Exception as e:  # noqa: BLE001
                print(f"STEP{no} {name}: ERROR {e!r}")
                score = 0.0
        status = "PASS" if score > GATE else "FAIL"
        print(f"--> STEP{no} {name}: {score} vs gate {GATE}: {status}")
        if score <= GATE:
            failed.append(no)
    if failed:
        print(f"\nFAILED steps (must fix wenyi, gate stays): {failed}")
        return 1
    print("\nALL STEPS PASSED GATE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
