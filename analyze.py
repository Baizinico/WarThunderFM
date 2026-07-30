"""War Thunder 加速度分析工具 CLI 主入口。

提供五个子命令：
  - download: 下载飞机飞行模型 .blkx 文件
  - compute:  计算单架飞机的加速度网格与最优剖面
  - run:      串行执行 download + compute，并刷新 manifest
  - serve:    启动本地 HTTP 服务器预览网页
  - list:     列出已计算的数据集
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import sys
import webbrowser
from pathlib import Path

from lib.compute import compute_accel_grid, compute_climb_route, compute_optimal
from lib.downloader import DEFAULT_RAW_DIR, download_fm
from lib.schema import build_record, load_json, save_json

# ============================================================
# 路径常量（均基于项目根，避免依赖 cwd）
# ============================================================
# 项目根目录（本脚本所在目录）
PROJECT_ROOT: Path = Path(__file__).resolve().parent
# 原始数据目录
RAW_DIR: Path = PROJECT_ROOT / "data" / "raw"
# 计算结果目录
COMPUTED_DIR: Path = PROJECT_ROOT / "data" / "computed"
# Manifest 路径
MANIFEST_PATH: Path = PROJECT_ROOT / "web" / "manifest.json"
# 国家归属映射路径
NATIONS_PATH: Path = PROJECT_ROOT / "data" / "_nations.json"

# 用户要求的 9 国分类（其余国家归入 "other"）
SUPPORTED_NATIONS: dict[str, str] = {
    "usa":     "美国",
    "ussr":    "苏联",
    "germany": "德国",
    "china":   "中国",
    "france":  "法国",
    "italy":   "意大利",
    "britain": "英国",
    "japan":   "日本",
    "israel":  "以色列",
}


def _load_nations_map() -> dict[str, str]:
    """加载 data/_nations.json，返回 {aircraft: nation_code}。

    若文件不存在则返回空 dict。

    说明:
        - 仅保留 SUPPORTED_NATIONS 中的国家；其余国家（如 sweden）归入 "other"。
        - 未在 _nations.json 中出现的飞机也归入 "other"。
    """
    if not NATIONS_PATH.exists():
        return {}
    try:
        with open(NATIONS_PATH, "r", encoding="utf-8") as fp:
            raw_map = json.load(fp)
    except Exception:  # noqa: BLE001
        return {}

    result: dict[str, str] = {}
    for ac, nat in raw_map.items():
        if nat in SUPPORTED_NATIONS:
            result[ac] = nat
        else:
            result[ac] = "other"
    return result


# ============================================================
# update_manifest
# ============================================================
def update_manifest() -> dict:
    """扫描 data/raw/*.blkx，构建并写入 web/manifest.json。

    服务器只提供原始 .blkx 数据，加速度网格由浏览器端实时计算，
    因此 manifest 直接列出原始数据文件（path 指向 .blkx）。

    每个数据集附加 ``nation``（国家代号）字段，并生成国家分组统计。

    返回:
        manifest dict，结构为
        ``{"datasets": [{"name", "path", "nation"}, ...],
           "nations": [{"code", "label", "count"}, ...]}``。
    """
    nations_map = _load_nations_map()
    datasets: list[dict] = []
    nation_counts: dict[str, int] = {}

    # 扫描原始 .blkx 文件（服务器只提供原始数据）
    for blkx_path in sorted(RAW_DIR.glob("*.blkx")):
        ac_name = blkx_path.stem
        nation = nations_map.get(ac_name, "other")
        datasets.append({
            "name": ac_name,
            "path": f"data/raw/{blkx_path.name}",
            "nation": nation,
        })
        nation_counts[nation] = nation_counts.get(nation, 0) + 1

    # 按 SUPPORTED_NATIONS 顺序构建国家列表，"other" 放最后
    nations_list: list[dict] = []
    for code in list(SUPPORTED_NATIONS.keys()) + ["other"]:
        if nation_counts.get(code, 0) > 0:
            label = SUPPORTED_NATIONS.get(code, "其他")
            nations_list.append({
                "code": code,
                "label": label,
                "count": nation_counts.get(code, 0),
            })

    manifest = {"datasets": datasets, "nations": nations_list}
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)
    return manifest


# ============================================================
# _compute_one：单架飞机的计算流程（供 compute / run 复用）
# ============================================================
def _compute_one(aircraft: str, no_afterburner: bool = False,
                 fuel_pct: float = 0.5,
                 mass: float | None = None) -> int:
    """对单架飞机执行计算流程并保存结果。

    参数:
        aircraft: 飞机代号。
        no_afterburner: 是否仅计算军用推力（True=禁用加力）。
        fuel_pct: 燃油比例（0-1），当 ``mass`` 为 None 时使用。
        mass: 自定义飞行质量 kg；非 None 时覆盖 fuel_pct 计算。

    返回:
        0 表示成功，1 表示失败。
    """
    fm_path = RAW_DIR / f"{aircraft}.blkx"
    if not fm_path.exists():
        print(f"✗ 找不到原始数据: {fm_path}", file=sys.stderr)
        return 1

    # 1. 读取 .blkx JSON
    try:
        with open(fm_path, "r", encoding="utf-8") as fp:
            fm = json.load(fp)
    except Exception as e:  # noqa: BLE001
        print(f"✗ 读取 {fm_path} 失败: {e}", file=sys.stderr)
        return 1

    # 2. 提取质量信息
    mass_node = fm.get("Mass", {}) if isinstance(fm, dict) else {}
    if not isinstance(mass_node, dict):
        mass_node = {}
    empty_mass = float(mass_node.get("EmptyMass", 0.0))
    max_fuel = float(mass_node.get("MaxFuelMass0", 0.0))

    # 3. 计算飞行质量
    if mass is not None:
        mass_kg = float(mass)
    else:
        mass_kg = empty_mass + fuel_pct * max_fuel

    afterburner = not no_afterburner

    try:
        # 4. 计算加速度网格
        samples, grid = compute_accel_grid(fm, mass_kg, afterburner=afterburner)
        # 5. 计算最优剖面
        optimal = compute_optimal(samples, grid)
        # 5.5 计算最佳爬升速度程序（基于剩余功率 SEP）
        climb_route = compute_climb_route(samples, grid)
        # 6. 组装参数
        params = {
            "afterburner": afterburner,
            "fuel_pct": fuel_pct,
            "wt_fm_version": "datamine-master",
        }
        # 7. 构建 record
        record = build_record(aircraft, fm, samples, grid, optimal, params, climb_route)
        # 8. 保存
        COMPUTED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = COMPUTED_DIR / f"{aircraft}.json"
        save_json(record, out_path)
    except Exception as e:  # noqa: BLE001
        print(f"✗ {aircraft} 计算失败: {e}", file=sys.stderr)
        return 1

    # 9. 打印完成信息（路径用 spec 约定的相对形式）
    print(f"✓ 计算完成: data/computed/{aircraft}.json (samples={len(samples)})")
    return 0


# ============================================================
# 子命令实现
# ============================================================
def cmd_download(args: argparse.Namespace) -> int:
    """download 子命令：下载一架或多架飞机的飞行模型。

    单架失败不中断其它飞机。
    """
    exit_code = 0
    for aircraft in args.aircraft:
        try:
            # download_fm 内部会打印 "已缓存" / "已下载" 详情
            path = download_fm(aircraft, DEFAULT_RAW_DIR)
            print(f"✓ {aircraft}: {path}")
        except Exception as e:  # noqa: BLE001 - 单架失败不中断
            print(f"✗ {aircraft} 下载失败: {e}", file=sys.stderr)
            exit_code = 1
    return exit_code


def cmd_compute(args: argparse.Namespace) -> int:
    """compute 子命令：计算单架飞机的加速度。"""
    return _compute_one(
        args.aircraft,
        no_afterburner=args.no_afterburner,
        fuel_pct=args.fuel_pct,
        mass=args.mass,
    )


def cmd_run(args: argparse.Namespace) -> int:
    """run 子命令：串行执行 download + compute（默认参数），最后刷新 manifest。"""
    exit_code = 0
    success_count = 0
    fail_count = 0

    for aircraft in args.aircraft:
        # 下载阶段
        try:
            download_fm(aircraft, DEFAULT_RAW_DIR)
        except Exception as e:  # noqa: BLE001 - 单架失败不中断
            print(f"✗ {aircraft} 下载失败: {e}", file=sys.stderr)
            fail_count += 1
            exit_code = 1
            continue
        # 计算阶段
        rc = _compute_one(aircraft)
        if rc == 0:
            success_count += 1
        else:
            fail_count += 1
            exit_code = 1

    # 刷新 manifest
    manifest = update_manifest()

    # 汇总信息
    print("\n=== 汇总 ===")
    print(f"成功: {success_count}，失败: {fail_count}")
    print(f"manifest 数据集数: {len(manifest['datasets'])}")
    return exit_code


def cmd_serve(args: argparse.Namespace) -> int:
    """serve 子命令：启动本地 HTTP 服务器预览网页。"""
    port = args.port
    # 切换到项目根目录，使 http.server 能正确服务 web/ 等静态资源
    os.chdir(PROJECT_ROOT)

    # 自定义 handler：禁用缓存，确保开发时始终加载最新文件
    class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
        """为所有响应添加 no-cache 头，防止浏览器缓存开发文件。"""

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

    server = http.server.HTTPServer(("", port), NoCacheHandler)
    url = f"http://localhost:{port}/web/index.html"
    print(f"服务已启动: {url}")
    print(f"项目根: {PROJECT_ROOT}")
    print("按 Ctrl+C 停止")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """list 子命令：列出 manifest 中所有已计算的数据集。"""
    manifest = update_manifest()
    datasets = manifest.get("datasets", [])
    if not datasets:
        print("（暂无数据集）")
        return 0

    print(f"共 {len(datasets)} 个数据集：")
    for ds in datasets:
        name = ds.get("name", "?")
        path = ds.get("path", "?")
        meta = ds.get("metadata", {})
        flight_mass = meta.get("flight_mass_kg", "?")
        afterburner = meta.get("afterburner", "?")
        print(f"  - {name}  (path={path}, mass={flight_mass} kg, afterburner={afterburner})")
    return 0


# ============================================================
# argparse 解析器构建
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 顶层解析器（带子命令 subparsers）。"""
    parser = argparse.ArgumentParser(
        prog="analyze.py",
        description="War Thunder 加速度分析工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # download：下载一架或多架飞机
    p_download = subparsers.add_parser(
        "download", help="下载飞机飞行模型 .blkx 文件")
    p_download.add_argument("aircraft", nargs="+", help="飞机代号（可多个）")
    p_download.set_defaults(func=cmd_download)

    # compute：计算单架飞机
    p_compute = subparsers.add_parser(
        "compute", help="计算单架飞机的加速度网格与最优剖面")
    p_compute.add_argument("aircraft", help="飞机代号")
    p_compute.add_argument(
        "--no-afterburner", action="store_true",
        help="仅计算军用推力（禁用加力）")
    p_compute.add_argument(
        "--fuel-pct", type=float, default=0.5,
        help="燃油比例（默认 0.5）")
    p_compute.add_argument(
        "--mass", type=float, default=None,
        help="自定义飞行质量 kg（覆盖 fuel-pct 计算）")
    p_compute.set_defaults(func=cmd_compute)

    # run：串行 download + compute
    p_run = subparsers.add_parser(
        "run", help="串行执行 download + compute，并刷新 manifest")
    p_run.add_argument("aircraft", nargs="+", help="飞机代号（可多个）")
    p_run.set_defaults(func=cmd_run)

    # serve：启动本地 HTTP 服务器
    p_serve = subparsers.add_parser(
        "serve", help="启动本地 HTTP 服务器预览网页")
    p_serve.add_argument("--port", type=int, default=8000, help="端口号（默认 8000）")
    p_serve.add_argument(
        "--no-browser", action="store_true", help="不自动打开浏览器")
    p_serve.set_defaults(func=cmd_serve)

    # list：列出已计算的数据集
    p_list = subparsers.add_parser(
        "list", help="列出 manifest 中所有已计算的数据集")
    p_list.set_defaults(func=cmd_list)

    return parser


# ============================================================
# main
# ============================================================
def main(argv: list[str]) -> int:
    """CLI 主入口。

    参数:
        argv: 命令行参数列表（不含脚本名）。

    返回:
        进程退出码，0 表示成功，非 0 表示失败。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
