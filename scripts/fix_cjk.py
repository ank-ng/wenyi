"""Batch-retranslate script-contaminated segments via gateway, verify, save via RunStore."""

import glob
import json
import re
import time
import urllib.request

KEY = "ocx_data_45386309b90af4e6b263fa445496c8f0d08398db"
BASE = "http://localhost:10100/v1"
MODEL = "kenari/agnes-2-5-flash:free"
PAT = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04FF]")
STATE = sorted(glob.glob("fooled_state/*/targets/vi-daichung"))[0]

import sys

sys.path.insert(0, ".")
from trans_novel.i18n import prompts
from trans_novel.pipeline.runstore import RunStore

SYS = prompts.render("translator_system", src="en", tgt="vi-daichung")


def translate_one(source: str, retries: int = 3) -> str | None:
    for _ in range(retries):
        body = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYS},
                {"role": "user", "content": "[0] " + source + "\nReturn ONLY the JSON object."},
            ],
            "max_tokens": 2000,
        }
        req = urllib.request.Request(
            BASE + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        )
        time.sleep(2)
        try:
            r = json.load(urllib.request.urlopen(req, timeout=180))
            content = r["choices"][0]["message"].get("content") or ""
            data = json.loads(content[content.find("{") : content.rfind("}") + 1])
            t = data["translations"][0]
            if t and t.strip() and not PAT.search(t):
                return t
        except Exception as e:  # noqa: BLE001
            print("  retry:", str(e)[:100])
    return None


def main():
    store = RunStore(STATE)
    fixed, failed = 0, []
    for f in sorted(glob.glob(f"{STATE}/chapters/ch*.json")):
        ci = int(f.rsplit("ch", 1)[1].split(".")[0])
        ch = store.load_chapter(ci)
        dirty = False
        for idx, seg in enumerate(ch.text_segments):
            g = lambda k: seg.get(k, "") if isinstance(seg, dict) else getattr(seg, k, "")
            t, src = g("target") or "", g("source") or ""
            if t and PAT.search(t) and not PAT.search(src or ""):
                print(f"fix {f.split('/')[-1]} seg{idx} ...")
                new = translate_one(src)
                if new:
                    if isinstance(seg, dict):
                        seg["target"] = new
                    else:
                        seg.target = new
                    dirty = True
                    fixed += 1
                    print("  FIXED")
                else:
                    failed.append((f, idx))
        if dirty:
            store.save_chapter(ch)
    print(f"\nFIXED {fixed}, FAILED {len(failed)}: {failed}")


if __name__ == "__main__":
    raise SystemExit(main())
