"""获取 War Thunder Datamine 仓库中所有 .blkx 飞行模型文件列表。

使用 GitHub git trees API (recursive=1) 获取完整文件树，
提取 flightmodels/fm 目录下的所有 .blkx 文件名。
"""
import urllib.request
import json
import sys
import time

REPO = "gszabi99/War-Thunder-Datamine"
BRANCH = "master"
TARGET_PREFIX = "aces.vromfs.bin_u/gamedata/flightmodels/fm/"
OUTPUT_FILE = "data/_all_aircraft.txt"


def fetch_tree():
    """获取完整 git tree（带重试）。"""
    url = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
    headers = {
        "User-Agent": "WarThunderFM",
        "Accept": "application/vnd.github+json",
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            if data.get("truncated"):
                print("⚠ 警告: tree 被截断，列表可能不完整", file=sys.stderr)
            return data
        except Exception as e:
            print(f"尝试 {attempt+1}/3 失败: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(3)
    return None


def main():
    print(f"正在获取 {REPO} 的完整文件树...")
    data = fetch_tree()
    if not data:
        print("✗ 无法获取文件树", file=sys.stderr)
        return 1

    tree = data.get("tree", [])
    print(f"文件树总条目数: {len(tree)}")

    # 提取 flightmodels/fm 目录下的 .blkx 文件
    blkx_names = []
    for item in tree:
        path = item.get("path", "")
        if path.startswith(TARGET_PREFIX) and path.endswith(".blkx"):
            # 只取直接子文件（不再有子目录）
            remainder = path[len(TARGET_PREFIX):]
            if "/" not in remainder and remainder:
                blkx_names.append(remainder.replace(".blkx", ""))

    blkx_names.sort()
    print(f"\n找到 {len(blkx_names)} 个 .blkx 飞行模型文件")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(blkx_names))
    print(f"已保存到 {OUTPUT_FILE}")

    print(f"\n前 10 个: {blkx_names[:10]}")
    print(f"后 10 个: {blkx_names[-10:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
