import json

fm = json.load(open('data/raw/su_27.blkx', 'r', encoding='utf-8'))

print("=== Su-27 Engine0 结构 ===")
eng0 = fm.get('Engine0', {})
print(f"类型: {type(eng0)}")
if isinstance(eng0, dict):
    print(f"键: {sorted(eng0.keys())}")
    for k, v in eng0.items():
        if isinstance(v, dict):
            print(f"  {k}: dict with keys {sorted(v.keys())[:10]}")
        elif isinstance(v, (int, float, str)):
            print(f"  {k}: {v}")

print("\n=== Su-27 Engine1 结构 ===")
eng1 = fm.get('Engine1', {})
print(f"类型: {type(eng1)}")
if isinstance(eng1, dict):
    print(f"键: {sorted(eng1.keys())}")
    for k, v in eng1.items():
        if isinstance(v, dict):
            print(f"  {k}: dict with keys {sorted(v.keys())[:10]}")
        elif isinstance(v, (int, float, str)):
            print(f"  {k}: {v}")

# J-10C 对比
print("\n=== J-10C Engine0 结构 ===")
fm_j10 = json.load(open('data/raw/j_10c.blkx', 'r', encoding='utf-8'))
eng0_j = fm_j10.get('Engine0', {})
if isinstance(eng0_j, dict):
    print(f"键: {sorted(eng0_j.keys())}")
    for k, v in eng0_j.items():
        if isinstance(v, (int, float, str)):
            print(f"  {k}: {v}")

# 检查 MaxSpeedAtAltitude 和 MaxSpeedNearGround（官方最大速度数据）
print("\n=== Su-27 官方速度数据 ===")
print(f"MaxSpeedAtAltitude: {fm.get('MaxSpeedAtAltitude')}")
print(f"MaxSpeedNearGround: {fm.get('MaxSpeedNearGround')}")

print("\n=== J-10C 官方速度数据 ===")
print(f"MaxSpeedAtAltitude: {fm_j10.get('MaxSpeedAtAltitude')}")
print(f"MaxSpeedNearGround: {fm_j10.get('MaxSpeedNearGround')}")
