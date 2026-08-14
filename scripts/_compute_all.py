"""批量计算全部飞机的加速度数据。

读取 data/raw/*.blkx，计算每架飞机的加速度网格与最优剖面，
保存到 data/computed/<aircraft>.json。
已计算的自动跳过（断点续传）。失败的记录到错误日志。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from lib.compute import compute_accel_grid, compute_optimal
from lib.schema import build_record, save_json

RAW_DIR = Path("data/raw")
COMPUTED_DIR = Path("data/computed")
COMPUTED_DIR.mkdir(parents=True, exist_ok=True)


def compute_one(aircraft: str) -> tuple[str, bool, str]:
    """计算单架飞机。返回 (aircraft, success, message)。"""
    out_path = COMPUTED_DIR / f"{aircraft}.json"
    if out_path.exists():
        return aircraft, True, "cached"

    fm_path = RAW_DIR / f"{aircraft}.blkx"
    if not fm_path.exists():
        return aircraft, False, f"raw file not found: {fm_path}"

    try:
        fm = json.loads(fm_path.read_text(encoding="utf-8"))
    except Exception as e:
        return aircraft, False, f"read error: {e}"

    # 提取质量
    mass_node = fm.get("Mass", {})
    if not isinstance(mass_node, dict):
        mass_node = {}
    empty_mass = float(mass_node.get("EmptyMass", 0.0))
    max_fuel = float(mass_node.get("MaxFuelMass0", 0.0))
    if empty_mass <= 0:
        return aircraft, False, "no mass data"
    mass_kg = empty_mass + 0.5 * max_fuel

    afterburner = True

    try:
        samples, grid = compute_accel_grid(fm, mass_kg, afterburner=afterburner)
        optimal = compute_optimal(samples, grid)
        params = {
            "afterburner": afterburner,
            "fuel_pct": 0.5,
            "wt_fm_version": "datamine-master",
        }
        record = build_record(aircraft, fm, samples, grid, optimal, params)
        save_json(record, out_path)
        return aircraft, True, f"ok ({len(samples)} samples)"
    except Exception as e:
        return aircraft, False, f"compute error: {e}"


def main():
    # 读取飞机列表
    aircraft_list = sorted(
        p.stem for p in RAW_DIR.glob("*.blkx")
    )
    total = len(aircraft_list)
    print(f"共 {total} 架飞机待计算")
    print(f"已计算: {sum(1 for a in aircraft_list if (COMPUTED_DIR / f'{a}.json').exists())}")
    print()

    success_count = 0
    fail_count = 0
    cache_count = 0
    fail_list = []
    start_time = time.time()

    for i, aircraft in enumerate(aircraft_list):
        ac, ok, msg = compute_one(aircraft)

        if ok:
            success_count += 1
            if msg == "cached":
                cache_count += 1
        else:
            fail_count += 1
            fail_list.append((aircraft, msg))

        # 进度报告
        done = i + 1
        if done % 50 == 0 or done == total:
            elapsed = time.time() - start_time
            computed = done - cache_count
            rate = computed / elapsed if elapsed > 0 and computed > 0 else 0
            remaining = total - done
            eta = remaining / rate if rate > 0 else 0
            print(f"进度: {done}/{total} ({done*100//total}%)  "
                  f"成功={success_count}(缓存={cache_count}) 失败={fail_count}  "
                  f"速率={rate:.1f}/s 剩余≈{eta:.0f}s")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"计算完成！耗时 {elapsed:.1f}s")
    print(f"成功: {success_count} (其中缓存 {cache_count})")
    print(f"失败: {fail_count}")
    print(f"总计: {total}")

    if fail_list:
        print(f"\n失败列表（前 30 个）:")
        for name, msg in fail_list[:30]:
            print(f"  ✗ {name}: {msg}")
        # 保存失败列表
        Path("data/_compute_failures.txt").write_text(
            "\n".join(f"{name}: {msg}" for name, msg in fail_list),
            encoding="utf-8")
        print(f"失败列表已保存到 data/_compute_failures.txt")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
