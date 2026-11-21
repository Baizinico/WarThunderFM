#!/usr/bin/env python3
"""用 War Thunder Wiki 数据卡核对 data/computed 的极速。

用法:
    python scripts/audit_wiki.py                  # 抓取/复用缓存并输出 CSV
    python scripts/audit_wiki.py --offline        # 只用已有缓存
    python scripts/audit_wiki.py --cache /tmp/wt_wiki --out data/audit_wiki_43.csv

Wiki 数据卡里同一行有四个数: RB 完全体 / RB 白板 / AB 完全体 / AB 白板,
按 span 的 class 取, 不能按位置猜。本脚本以 RB 完全体 (rb_ref) 为基准。

注意: 本机 Python 的 SSL CA 不可用, 因此用 curl 抓取。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")

CLASSES = (
    "show-char-rb-mod-ref",
    "show-char-rb-mod-basic",
    "show-char-ab-mod-ref",
    "show-char-ab-mod-basic",
)

DEFAULT_NAMES = """a2d a5m4 a6m5_zero a_4n ah_64d arado-234c-3 b-17e b-29 b_66b
bf-109f-4 bi f-4e f-80 f-86a-5 f-86f-25 f4u-1a f9f-2 fr_1_fireball fw-190a-5
he-162a-2 hunter_f1 il_28 j_10c ka_50 la-7 me-163b me-262a-1a me_264 mi_24a
mig-15 mig-17 mig-21_bis mig-9 mig_29_9_12g mirage_3c mirage_f1c
p-51d-30_usaaf_korea su_27 tu_14t vampire_fb5 wyvern_s4 yak-3 yak_141""".split()


def fetch(name: str, cache: Path, offline: bool) -> str:
    path = cache / f"{name}.html"
    if path.exists() and path.stat().st_size > 50_000:
        return path.read_text(encoding="utf-8", errors="ignore")
    if offline:
        raise FileNotFoundError(f"缓存缺失: {path}")
    cache.mkdir(parents=True, exist_ok=True)
    url = f"https://wiki.warthunder.com/unit/{name}"
    subprocess.run(
        ["curl", "-fsSL", "-A", UA, "-o", str(path), url],
        check=False, timeout=90,
    )
    if not path.exists() or path.stat().st_size < 50_000:
        raise RuntimeError(f"抓取失败: {url}")
    time.sleep(0.6)
    return path.read_text(encoding="utf-8", errors="ignore")


def chars_block(html: str, header: str) -> str:
    """截取从 header 到下一个 game-unit_chars-block 之间的片段。"""
    i = html.find(header)
    if i < 0:
        return ""
    j = html.find("game-unit_chars-block", i + len(header))
    return html[i:j] if j > 0 else html[i:i + 3000]


def four_values(seg: str) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for cls in CLASSES:
        m = re.search(r'class="%s[^"]*">([\d.,]+)</span>' % cls, seg)
        out[cls] = float(m.group(1).replace(",", "")) if m else None
    return out


def parse_card(html: str) -> dict:
    speed_seg = chars_block(html, "Max speed")
    speed = four_values(speed_seg)
    alt = re.search(r"at\s*<span>([\d,]+)</span>\s*m", speed_seg)
    # 部分早期机型的速度块没有四个 span, 只有单个数值。
    if all(v is None for v in speed.values()):
        m = re.search(r'game-unit_chars-value">\s*(?:<span>)?([\d.,]+)', speed_seg)
        if m:
            speed["show-char-rb-mod-ref"] = float(m.group(1).replace(",", ""))
    climb = four_values(chars_block(html, "Rate of Climb"))
    ceiling = None
    i = html.find("Max altitude")
    if i >= 0:
        m = re.search(r'game-unit_chars-value">\s*([\d,.]+)\s*m', html[i:i + 600])
        if m:
            ceiling = float(m.group(1).replace(",", ""))
    return {
        "speed": speed,
        "speed_alt_m": float(alt.group(1).replace(",", "")) if alt else None,
        "climb": climb,
        "ceiling_m": ceiling,
    }


def computed_top(name: str) -> tuple[float, dict]:
    d = json.loads((ROOT / "data" / "computed" / f"{name}.json").read_text(encoding="utf-8"))
    vals = [x["tas_max_kmh"] for x in d["optimal"]["max_speed_per_alt"]
            if x.get("tas_max_kmh") is not None]
    return (max(vals) if vals else 0.0), d.get("metadata", {})


def model_info(name: str) -> tuple[str, str, float]:
    """返回 (模型 kind, 主引擎类型, thrust_max0_kgf)。"""
    try:
        import lib.compute as C
        fm = json.loads((ROOT / "data" / "raw" / f"{name}.blkx").read_text(encoding="utf-8"))
        kind = C._build_thrust_model(fm).get("kind", "?")
        main = None
        for i in range(16):
            e = fm.get(f"EngineType{i}")
            if isinstance(e, dict) and e.get("Main"):
                main = e["Main"].get("Type")
                break
        if main is None:
            for i in range(16):
                e = fm.get(f"Engine{i}")
                if isinstance(e, dict) and e.get("Main"):
                    main = e["Main"].get("Type")
                    break
        return kind, str(main), float(C._build_thrust_model(fm).get("t0_n", 0.0) / C.G)
    except Exception:
        return "?", "?", 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path("/tmp/wt_wiki"))
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "audit_wiki_43.csv")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--names", nargs="*", default=None)
    args = ap.parse_args()

    names = args.names or DEFAULT_NAMES
    rows = []
    for name in names:
        try:
            html = fetch(name, args.cache, args.offline)
            card = parse_card(html)
        except Exception as e:
            print(f"跳过 {name}: {e}", file=sys.stderr)
            continue
        ref = card["speed"].get("show-char-rb-mod-ref")
        if not ref:
            print(f"跳过 {name}: 无 RB 极速", file=sys.stderr)
            continue
        top, md = computed_top(name)
        kind, main, t0 = model_info(name)
        err = (top - ref) / ref * 100.0
        rows.append({
            "name": name,
            "wiki_rb_kmh": round(ref, 1),
            "wiki_alt_m": card["speed_alt_m"],
            "computed_kmh": round(top, 1),
            "error_pct": round(err, 2),
            "model_kind": kind,
            "main_type": main,
            "thrust_max0_kgf": round(t0, 1),
            "empty_mass_kg": md.get("empty_mass_kg"),
        })

    rows.sort(key=lambda r: r["name"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    errs = [r["error_pct"] for r in rows]
    within10 = sum(abs(e) <= 10 for e in errs)
    within20 = sum(abs(e) <= 20 for e in errs)
    print(f"写入 {args.out} ({len(rows)} 架)")
    print(f"≤10%: {within10}/{len(rows)}  ≤20%: {within20}/{len(rows)}  "
          f"中位数 {statistics.median(errs):+.1f}%  均值 {statistics.mean(errs):+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
