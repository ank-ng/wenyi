"""Repolish finished chapters with the current profile via Polisher + RunStore API.

Usage: uv run python scripts/repolish.py --chapter N [--all] [--config fooled.yaml]
Keeps target_before_polish chain: previous target becomes the new pre-polish
snapshot only when it differs, so rollback stays possible.
"""

import argparse
import glob
import sys

sys.path.insert(0, ".")

from trans_novel.agents.polisher import Polisher
from trans_novel.config import Config
from trans_novel.glossary.store import GlossaryStore
from trans_novel.llm.factory import build_client
from trans_novel.pipeline.runstore import RunStore


def repolish_chapter(store: RunStore, polisher: Polisher, ci: int) -> dict:
    ch = store.load_chapter(ci)
    segs = ch.text_segments
    targets = []
    for s in segs:
        t = s.get("target", "") if isinstance(s, dict) else getattr(s, "target", "")
        targets.append(t or "")
    gloss = GlossaryStore(store.glossary_path)
    try:
        terms = gloss.all_terms()
    finally:
        gloss.close()
    polished = polisher.polish(targets, glossary_terms=terms)
    assert len(polished) == len(targets), f"count mismatch ch{ci}"
    changed = 0
    for s, old, new in zip(segs, targets, polished):
        if not isinstance(new, str) or not new.strip() or new == old:
            continue
        if isinstance(s, dict):
            if not s.get("target_before_polish"):
                s["target_before_polish"] = old
            s["target"] = new
        else:
            if not getattr(s, "target_before_polish", ""):
                s.target_before_polish = old
            s.target = new
        changed += 1
    store.save_chapter(ch)
    return {"chapter": ci, "segments": len(segs), "changed": changed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="fooled.yaml")
    ap.add_argument("--chapter", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--book", default=None)
    args = ap.parse_args()
    cfg = Config.load(args.config)
    client = build_client(cfg)
    polisher = Polisher(client, cfg)
    if args.book:
        pattern = args.book
    else:
        pattern = "fooled_state/*/targets/vi-daichung"
    rd = sorted(glob.glob(pattern))[0]
    store = RunStore(rd)
    manifest = store.load_manifest()
    indices = (
        [c["index"] for c in manifest.get("chapters", [])]
        if args.all
        else [args.chapter if args.chapter is not None else 4]
    )
    for ci in indices:
        print(f"repolish ch{ci} ...", flush=True)
        print(repolish_chapter(store, polisher, ci), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
