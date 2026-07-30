import json
d = json.load(open('data/computed/j_10c.json', 'r', encoding='utf-8'))
s = d['samples']
print("=== 当前计算文件中的值 (alt=0) ===")
for x in s:
    if x['altitude_m'] == 0 and x['mach'] in [0.5, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0, 2.5]:
        print(f"  mach={x['mach']:.2f}  accel={x['accel_mps2']:>8.2f}  "
              f"thrust_ab={x['thrust_ab_n']/9.80665:>8.0f}kgf  "
              f"drag={x['drag_n']/9.80665:>8.0f}kgf")

print("\n=== 当前计算文件中的值 (alt=11000) ===")
for x in s:
    if x['altitude_m'] == 11000 and x['mach'] in [0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0, 2.5]:
        print(f"  mach={x['mach']:.2f}  accel={x['accel_mps2']:>8.2f}  "
              f"thrust_ab={x['thrust_ab_n']/9.80665:>8.0f}kgf  "
              f"drag={x['drag_n']/9.80665:>8.0f}kgf")

# 加速度范围
accels = [x['accel_mps2'] for x in s]
print(f"\n加速度范围: min={min(accels):.2f} max={max(accels):.2f}")
print(f"计算时间: {d['metadata']['computed_at']}")
