"""逐层导航 git tree 获取 wpcost.blkx blob SHA，然后通过 blob API 下载。"""
import urllib.request
import json
import ssl
import base64
import time
from pathlib import Path
from collections import Counter

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
HEADERS = {"User-Agent": "WT", "Accept": "application/vnd.github+json"}


def get_tree(tree_sha):
    """获取指定 SHA 的 tree（非递归）。"""
    url = f"https://api.github.com/repos/gszabi99/War-Thunder-Datamine/git/trees/{tree_sha}"
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    return json.loads(resp.read())


def get_root_commit_sha():
    """获取 master 分支最新 commit SHA。"""
    url = "https://api.github.com/repos/gszabi99/War-Thunder-Datamine/branches/master"
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    data = json.loads(resp.read())
    return data["commit"]["sha"]


def find_entry(tree, name):
    """在 tree 中查找指定名称的条目，返回 (sha, type)。"""
    for item in tree.get("tree", []):
        if item["path"] == name:
            return item["sha"], item["type"]
    return None, None


def get_blob(blob_sha):
    """通过 SHA 下载 git blob（base64 编码）。"""
    url = f"https://api.github.com/repos/gszabi99/War-Thunder-Datamine/git/blobs/{blob_sha}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=180, context=ctx)
            blob = json.loads(resp.read())
            return base64.b64decode(blob["content"])
        except Exception as e:
            print(f"  blob 下载尝试 {attempt+1}/3 失败: {e}")
            if attempt < 2:
                time.sleep(5)
    return None


# 步骤1: 逐层导航
print("步骤1: 逐层导航到 wpcost.blkx...")

# 获取 root commit
commit_sha = get_root_commit_sha()
print(f"  master commit: {commit_sha[:12]}...")

# 获取 root tree
root_tree = get_tree(commit_sha)
sha, typ = find_entry(root_tree, "char.vromfs.bin_u")
print(f"  char.vromfs.bin_u: sha={sha[:12]}... type={typ}")

# 进入 char.vromfs.bin_u
tree1 = get_tree(sha)
sha, typ = find_entry(tree1, "config")
print(f"  config: sha={sha[:12]}... type={typ}")

# 进入 config
tree2 = get_tree(sha)
sha, typ = find_entry(tree2, "wpcost.blkx")
print(f"  wpcost.blkx: sha={sha[:12]}... type={typ} (blob)")

wpcost_blob_sha = sha

# 步骤2: 下载 blob
print(f"\n步骤2: 通过 blob API 下载 wpcost.blkx (30MB)...")
content = get_blob(wpcost_blob_sha)
if not content:
    print("✗ 下载失败")
    exit(1)
print(f"下载成功: {len(content)/1024/1024:.1f} MB")
Path("data/_wpcost.blkx").write_bytes(content)

# 步骤3: 解析
print("\n步骤3: 解析国家归属...")
obj = json.loads(content)
print(f"wpcost 总条目: {len(obj)}")

# 读取飞机列表
aircraft_list = Path("data/_all_aircraft.txt").read_text(encoding="utf-8").strip().split("\n")
aircraft_set = set(aircraft_list)

# 检查 j_10c 条目结构
for test_ac in ("j_10c", "su_27", "f-16a", "a-10c"):
    if test_ac in obj:
        entry = obj[test_ac]
        if isinstance(entry, dict):
            print(f"\n{test_ac} 字段: {list(entry.keys())}")
            for k, v in entry.items():
                print(f"  {k} = {v}")
        break

# 找国家字段
sample_fields = set()
for k, v in list(obj.items())[:500]:
    if isinstance(v, dict):
        sample_fields.update(v.keys())

print(f"\n前500条目字段: {sorted(sample_fields)[:30]}")

# 找国家字段
nation_field = None
for field in ("country", "nation", "unitClass"):
    if field in sample_fields:
        nation_field = field
        break

if not nation_field:
    # 检查含 country/nation 的字段
    matches = [f for f in sample_fields if "count" in f.lower() or "nation" in f.lower()]
    print(f"含 country/nation 的字段: {matches}")
    if matches:
        nation_field = matches[0]

print(f"国家字段: {nation_field}")

# 提取国家
nation_map = {}
if nation_field:
    for ac in aircraft_list:
        if ac in obj and isinstance(obj[ac], dict):
            nation_map[ac] = obj[ac].get(nation_field)

# 统计
dist = Counter(v for v in nation_map.values() if v is not None)
NATION_CN = {
    "usa": "美", "ussr": "苏", "germany": "德", "china": "中",
    "france": "法", "italy": "意", "britain": "英", "japan": "日",
    "israel": "以", "sweden": "瑞",
}
print(f"\n匹配: {len(nation_map)} / {len(aircraft_list)}")
print(f"国家分布:")
for nat, count in dist.most_common():
    cn = NATION_CN.get(nat, nat)
    print(f"  {cn}({nat}): {count} 架")

not_found = [ac for ac in aircraft_list if ac not in nation_map or nation_map.get(ac) is None]
print(f"未匹配: {len(not_found)}")
if not_found[:10]:
    print(f"示例: {not_found[:10]}")

Path("data/_nations.json").write_text(
    json.dumps(nation_map, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"已保存 data/_nations.json")
