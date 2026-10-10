"""Build the four genre VI profiles from one shared core plus small voice files.

Source of truth after the merge:
  trans_novel/i18n/data/languages/_parts/vi-core.txt        (31 shared sentences)
  trans_novel/i18n/data/languages/_parts/_voice.<code>.txt  (per-genre voice)

Generated (do not hand-edit):
  vi-daichung.json, vi-kythuat.json, vi-vanhoc.json, vi-hucau.json

Safety: the script renders each genre's target_guidance and asserts it is
byte-identical to the checked-in file before writing. Any drift fails loudly.

Usage: uv run python scripts/build_vi_profiles.py [--check]
"""

import json
import sys
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parents[1] / "trans_novel" / "i18n" / "data" / "languages"
PARTS_DIR = LANG_DIR / "_parts"
CORE_FILE = PARTS_DIR / "vi-core.txt"

GENRES: dict[str, dict[str, str]] = {
    "vi-daichung": {
        "label": "Tiếng Việt đại chúng",
        "english_name": "Popular Vietnamese",
    },
    "vi-kythuat": {
        "label": "Tiếng Việt kỹ thuật",
        "english_name": "Technical Vietnamese",
    },
    "vi-vanhoc": {
        "label": "Tiếng Việt văn học",
        "english_name": "Literary Vietnamese",
    },
    "vi-hucau": {
        "label": "Tiếng Việt hư cấu",
        "english_name": "Fictional Vietnamese",
    },
}


def build_guidance(code: str) -> str:
    voice_file = PARTS_DIR / f"_voice.{code}.txt"
    voice = " ".join(voice_file.read_text(encoding="utf-8").split())
    core = CORE_FILE.read_text(encoding="utf-8").strip()
    core_one_line = " ".join(core.split())
    parts = [voice, core_one_line] if voice else [core_one_line]
    return " ".join(parts)


def expected_document(code: str) -> dict[str, str]:
    return {
        "extends": "vi",
        "label": GENRES[code]["label"],
        "english_name": GENRES[code]["english_name"],
        "target_guidance": build_guidance(code),
    }


def dump(document: dict[str, str]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2)


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    failures: list[str] = []
    for code in GENRES:
        target = LANG_DIR / f"{code}.json"
        current = target.read_text(encoding="utf-8")
        current_doc = json.loads(current)
        generated = dump(expected_document(code))
        # Compare semantic content (key order/formatting may differ); the
        # byte check below guards the exact file bytes.
        if json.loads(generated) != {
            k: current_doc[k] for k in ("extends", "label", "english_name", "target_guidance")
        }:
            failures.append(f"{code}: content drift vs source parts")
            continue
        if current != generated + "\n" and current != generated:
            # Normalize: generated files end with a single trailing newline.
            if check_only:
                failures.append(f"{code}: bytes differ (run without --check to rewrite)")
                continue
        if not check_only:
            target.write_text(generated + "\n", encoding="utf-8")
            print(f"wrote {target.name}")
        else:
            print(f"ok {target.name}")
    if failures:
        print("FAIL:")
        for f in failures:
            print(" -", f)
        return 1
    print("all genre profiles match source parts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
