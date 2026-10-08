"""把 data/raw/*.blkx 同步到上游 War-Thunder-Datamine 的 master 分支。

比对方式
--------
把每个本地文件的 **规范化内容**（即 git 在 core.autocrlf 下 clean 后的 LF 形式）
算出 git blob SHA，与上游 tree 中同名的 blob SHA 逐一比对。这样：

  - 只有真正变更 / 新增的模型才会被下载，未变的文件不会因 Windows 换行而误判；
  - 下载后可以用同一个 SHA 做完整性校验。

用法
----
    python scripts/_sync_upstream.py              # 只报告差异（dry-run，默认）
    python scripts/_sync_upstream.py --apply      # 下载差异文件并刷新清单
    python scripts/_sync_upstream.py --apply --workers 16

``--apply`` 会写出：
  - data/raw/<name>.blkx      变更 / 新增的模型（未变的文件保持原样，不重写）
  - data/_all_aircraft.txt    data/raw 下全部机型代号（排序）
  - data/_upstream.json       本次同步的上游 commit / 版本 / 时间与差异清单
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.downloader import CDN_BASE  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
LIST_FILE = PROJECT_ROOT / "data" / "_all_aircraft.txt"
UPSTREAM_FILE = PROJECT_ROOT / "data" / "_upstream.json"

REPO = "gszabi99/War-Thunder-Datamine"
# 上游仓库中 flightmodels/fm 所在的多级路径
FM_PATH_PARTS = ("aces.vromfs.bin_u", "gamedata", "flightmodels", "fm")
API = "https://api.github.com"
HEADERS = {"User-Agent": "WarThunderFM-Sync/1.0", "Accept": "application/vnd.github+json"}
FETCH_HEADERS = {"User-Agent": "WarThunderFM-Sync/1.0"}


# ============================================================
# 网络
# ============================================================
def api_get(url: str) -> dict:
    """读取 GitHub API 的 JSON 响应（单次请求，失败直接抛出）。"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def resolve_fm_tree() -> tuple[str, str, str, dict[str, str]]:
    """定位上游 master 的 fm 目录。

    返回:
        (commit_sha, version_label, commit_date, {机型代号: blob_sha})
    """
    branch = api_get(f"{API}/repos/{REPO}/branches/master")
    commit = branch["commit"]
    commit_sha = commit["sha"]
    commit_date = commit["commit"]["committer"]["date"]
    version = commit["commit"]["message"].strip()

    tree_sha = commit["commit"]["tree"]["sha"]
    for part in FM_PATH_PARTS:
        tree = api_get(f"{API}/repos/{REPO}/git/trees/{tree_sha}")
        entry = next((e for e in tree.get("tree", []) if e["path"] == part), None)
        if entry is None:
            raise RuntimeError(f"上游路径缺少 {part}（{REPO} 目录结构可能已变化）")
        tree_sha = entry["sha"]

    tree = api_get(f"{API}/repos/{REPO}/git/trees/{tree_sha}?recursive=1")
    upstream = {
        e["path"][: -len(".blkx")]: e["sha"]
        for e in tree.get("tree", [])
        if e.get("type") == "blob" and e["path"].endswith(".blkx")
    }
    return commit_sha, version, commit_date, upstream


def fetch_bytes(url: str, attempts: int = 3) -> bytes:
    """下载 URL 内容，失败重试 attempts 次（每次间隔递增）。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=FETCH_HEADERS)
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:  # noqa: PERF203
            last = e
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    raise RuntimeError(f"下载失败（已重试 {attempts} 次）: {url}: {last}")


# ============================================================
# 本地 blob SHA
# ============================================================
def blob_sha_of_bytes(data: bytes) -> str:
    """按 git 的对象格式计算 blob SHA：sha1("blob <len>\\0" + data)。"""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def local_blob_shas(paths: list[Path]) -> dict[str, str]:
    """用 ``git hash-object --stdin-paths`` 批量读取本地文件的规范化 blob SHA。

    这样得到的 SHA 与 git 提交时会存入的对象完全一致（自动处理 core.autocrlf），
    因此可以直接和上游 tree 里的 blob SHA 比较。

    参数:
        paths: 待计算的文件路径列表。

    返回:
        {机型代号: blob_sha}，机型代号为文件名去掉 ``.blkx`` 后缀。
    """
    if not paths:
        return {}
    # 统一用相对项目根的 POSIX 形式，避免中文/空格路径与 git 的解析差异
    rel = [p.relative_to(PROJECT_ROOT).as_posix() for p in paths]
    proc = subprocess.run(
        ["git", "hash-object", "--stdin-paths"],
        input="\n".join(rel),
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=True,
    )
    shas = proc.stdout.split()
    if len(shas) != len(rel):
        raise RuntimeError(
            f"git hash-object 返回 {len(shas)} 个 SHA，期望 {len(rel)} 个")
    return {p.stem: sha for p, sha in zip(paths, shas)}


# ============================================================
# 同步
# ============================================================
def download_one(name: str, expected_sha: str) -> tuple[str, bool, str]:
    """下载单个模型并校验 blob SHA。返回 (name, ok, message)。"""
    url = f"{CDN_BASE}/{name}.blkx"
    try:
        data = fetch_bytes(url)
    except Exception as e:  # noqa: BLE001 - 单文件失败不中断整体
        return name, False, str(e)

    actual = blob_sha_of_bytes(data)
    if actual != expected_sha:
        return name, False, f"SHA 不匹配（期望 {expected_sha[:12]}，实际 {actual[:12]}）"

    tmp = RAW_DIR / f".{name}.blkx.tmp"
    tmp.write_bytes(data)
    tmp.replace(RAW_DIR / f"{name}.blkx")
    return name, True, f"{len(data) / 1024:.1f} KB"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="同步上游飞行模型数据")
    parser.add_argument("--apply", action="store_true",
                        help="实际下载差异文件并刷新清单（默认只报告差异）")
    parser.add_argument("--workers", type=int, default=16,
                        help="并发下载数（默认 16）")
    args = parser.parse_args(argv)

    print(f"上游: {REPO}@master")
    commit_sha, version, commit_date, upstream = resolve_fm_tree()
    print(f"  commit = {commit_sha[:12]}  版本 = {version}  时间 = {commit_date}")
    print(f"  上游 .blkx 数量 = {len(upstream)}")

    local_paths = sorted(RAW_DIR.glob("*.blkx"))
    local = local_blob_shas(local_paths)
    print(f"  本地 .blkx 数量 = {len(local)}")

    new = sorted(set(upstream) - set(local))
    removed = sorted(set(local) - set(upstream))
    changed = sorted(n for n in set(upstream) & set(local) if upstream[n] != local[n])
    unchanged = len(set(upstream) & set(local)) - len(changed)

    print(f"\n未变 = {unchanged}，变更 = {len(changed)}，新增 = {len(new)}，上游已移除 = {len(removed)}")
    if new:
        print(f"新增: {new}")
    if removed:
        print(f"上游已移除（本地保留）: {removed}")

    todo = [(n, upstream[n]) for n in new + changed]

    if not args.apply:
        print("\n（dry-run：加 --apply 才会下载）")
        return 0

    if not todo:
        print("\n无需下载，数据已是最新。")
    else:
        print(f"\n开始下载 {len(todo)} 个文件（并发 {args.workers}）...")
        done = 0
        failures: list[tuple[str, str]] = []
        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(download_one, n, s) for n, s in todo]
            for fut in concurrent.futures.as_completed(futures):
                name, ok, msg = fut.result()
                done += 1
                if not ok:
                    failures.append((name, msg))
                if done % 25 == 0 or done == len(todo):
                    rate = done / max(time.time() - start, 1e-6)
                    print(f"  进度: {done}/{len(todo)}  失败={len(failures)}  {rate:.1f}/s")
        print(f"下载完成，耗时 {time.time() - start:.1f}s，失败 {len(failures)} 个")
        for name, msg in failures[:20]:
            print(f"  ✗ {name}: {msg}")
        if failures:
            print("存在下载失败，未刷新清单。请重试。")
            return 1

    # 刷新机型清单（以本地实际文件为准）
    names = sorted(p.stem for p in RAW_DIR.glob("*.blkx"))
    LIST_FILE.write_text("\n".join(names) + "\n", encoding="utf-8")
    print(f"已写出 {LIST_FILE.relative_to(PROJECT_ROOT)}（{len(names)} 个机型）")

    UPSTREAM_FILE.write_text(json.dumps({
        "repo": REPO,
        "commit": commit_sha,
        "version": version,
        "commit_date": commit_date,
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "counts": {
            "upstream": len(upstream),
            "local": len(names),
            "unchanged": unchanged,
            "changed": len(changed),
            "new": len(new),
            "removed_upstream": len(removed),
        },
        "new": new,
        "changed": changed,
        "removed_upstream": removed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 {UPSTREAM_FILE.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
