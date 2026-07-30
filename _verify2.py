import json
d = json.load(open('data/computed/j_10c.json', 'r', encoding='utf-8'))
samples = d['samples']
altitudes = d['grid']['altitudes_m']
machs = d['grid']['machs']


def find(alt, mach):
    for s in samples:
        if s['altitude_m'] == alt and abs(s['mach'] - mach) < 0.001:
            return s
    return None


print('=== J-10C 加速度验证（修复后）===')
print(f'飞行质量: {d["metadata"]["flight_mass_kg"]} kg, 加力: {d["metadata"]["afterburner"]}')
print()

# 不同高度不同马赫数的加速度
print('高度 | M0.3  | M0.8  | M0.9  | M1.0  | M1.1  | M1.2  | M1.5  | M2.0')
print('-----|-------|-------|-------|-------|-------|-------|-------|------')
for alt in altitudes:
    row = f'{alt:>4d} |'
    for m in [0.3, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0]:
        s = find(alt, m)
        if s:
            row += f' {s["accel_mps2"]:>5.1f} |'
        else:
            row += '   N/A |'
    print(row)

print()
print('=== 阻力分解（海平面）===')
for m in [0.3, 0.8, 1.0, 1.2, 1.5, 2.0]:
    s = find(0, m)
    if s:
        print(f'M{m}: drag={s["drag_n"]:.0f}N, thrust_ab={s["thrust_ab_n"]:.0f}N, '
              f'thrust_mil={s["thrust_mil_n"]:.0f}N, accel={s["accel_mps2"]:.2f} m/s²')

print()
print('=== 跨音速墙检查（M0.9→M1.2 阻力增长）===')
for alt in [0, 5000, 11000]:
    s09 = find(alt, 0.9)
    s12 = find(alt, 1.2)
    if s09 and s12:
        drag_ratio = s12['drag_n'] / s09['drag_n'] if s09['drag_n'] > 0 else float('inf')
        print(f'高度 {alt}m: M0.9 drag={s09["drag_n"]:.0f}N → M1.2 drag={s12["drag_n"]:.0f}N '
              f'(×{drag_ratio:.2f})')

print()
print('=== 各高度最大速度 ===')
for item in d['optimal']['max_speed_per_alt']:
    if item['mach_max'] is not None:
        print(f'  {item["altitude_m"]:>5d}m: M{item["mach_max"]:.2f} ({item["tas_max_kmh"]:.0f} km/h)')
    else:
        print(f'  {item["altitude_m"]:>5d}m: 无法达到正加速度')
