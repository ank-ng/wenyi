"""Cham ban dich Viet that theo 9 tieu chi van hoc (0-10 moi tieu chi).

Khac score_profile_vi.py (cham marker trong prompt), script nay cham VAN
BAN DICH THAT: doc file dich + file goc, cho diem tung tieu chi.
Usage: uv run python scripts/score_translation_vi.py <src.txt> <tgt.txt>
Threshold: trung binh >= 9.0
"""

from __future__ import annotations

import re
import sys

CRITERIA = [
    ("nhac-tinh", "Xen cau ngan dai, van lung, diep am co chu y; doc to khong vap."),
    (
        "tu-lay-tuong-hinh",
        "Tu lay, tuong thanh/hinh dung sac thai goc; khong bia khi goc trung tinh.",
    ),
    (
        "han-viet-can-bang",
        "Khaniem truu tuong dung Han-Viet; doi thuong dung thuan Viet; khong qua tay.",
    ),
    (
        "thanh-ngu-tuc-ngu",
        "Thanh ngu/tuc ngu/slang co tuong duong Viet; khong xep chu, khong giu goc.",
    ),
    (
        "dai-tu-xung-ho",
        "I=toi; we mac dinh chung toi; ta chi khi ru doc; you theo tuoi; so huu dung chu the.",
    ),
    (
        "an-du-hinh-anh",
        "An du giu hinh; dien tich Tay giai thich 1 dong; don vi doi he met khi can.",
    ),
    (
        "nhip-luan-diem",
        "Doan mo-than-chot; 1 doan 1 y; cau chot dung rieng; hoi tu tu tach, khong don.",
    ),
    ("giong-dai-chung", "Gan gui, khau ngu co kiem soat; vi du doi thuong; khong hoc thuat kho."),
    (
        "trung-thanh-nguon",
        "Khong them/bot/sua so lieu, ten, y; so sanh/phu dinh du ca 2 ve; thuat ngu theo glossary.",
    ),
]


def auto_checks(src: str, tgt: str) -> dict[str, tuple[float, str]]:
    """Kiem tra may lam duoc: tra ve {tieu_chi: (diem, ghi_chu)}."""
    out: dict[str, tuple[float, str]] = {}
    out["trung-thanh-nguon"] = (
        (10.0, "khong thay ...")
        if "…" not in tgt and "..." not in tgt
        else (4.0, "co dau ba cham tom tat")
    )
    nums_src = re.findall(r"\d[\d,.]*", src)
    nums_tgt = re.findall(r"\d[\d,.]*", tgt)
    out["so-lieu-giu-nguyen"] = (
        (10.0, f"{len(nums_src)} so deu co mat")
        if len(nums_src) == 0 or all(n in tgt for n in nums_src)
        else (5.0, f"goc {nums_src} vs dich {nums_tgt}")
    )
    out["viet-tat-he-thong"] = (
        (10.0, "Hệ thống 1/2 day du")
        if "Hệ thống 1" in tgt or "Hệ thống" in tgt
        else (7.0, "khong thay He thong")
    )
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src = open(sys.argv[1], encoding="utf-8").read()
    tgt = open(sys.argv[2], encoding="utf-8").read()
    print(f"SRC chars={len(src)} TGT chars={len(tgt)} ratio={len(tgt) / max(len(src), 1):.2f}")
    if len(tgt) < len(src) * 0.5:
        print("CANH BAO: ban dich qua ngan so voi goc, nghi tom tat.")
    for name, desc in CRITERIA:
        print(f"\n[{name}] {desc}")
        print("  -> cham tay (doc doan dich roi cho diem 0-10).")
    print("\n--- KIEM TRA MAY ---")
    for k, (s, note) in auto_checks(src, tgt).items():
        print(f"[{k}] {s}/10 ({note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
