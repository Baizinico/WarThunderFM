import json

for aircraft in ['j_10c', 'su_27']:
    d = json.load(open(f'data/computed/{aircraft}.json', 'r', encoding='utf-8'))
    s = d['samples']
    accels = [x['accel_mps2'] for x in s]
    print(f"=== {aircraft} ===")
    print(f"  加速度范围: min={min(accels):.2f} max={max(accels):.2f}")
    print(f"  样本数: {len(s)}")
    print(f"  高度: {d['grid']['altitudes_m']}")
    print(f"  马赫: {d['grid']['machs'][0]:.2f} - {d['grid']['machs'][-1]:.2f}")

    # 打印关键点
    print(f"  关键点 (加力):")
    for alt in [0, 5000, 11000]:
        print(f"    alt={alt}m:")
        for x in s:
            if x['altitude_m'] == alt and abs(x['mach'] - round(x['mach']*2)/2) < 0.001:
                if x['mach'] in [0.5, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0]:
                    print(f"      M{x['mach']:.1f}: accel={x['accel_mps2']:>8.2f} m/s²  "
                          f"thrust_ab={x['thrust_ab_n']/9.80665:>7.0f}kgf  "
                          f"drag={x['drag_n']/9.80665:>7.0f}kgf")

    # 最优剖面
    opt = d['optimal']
    print(f"  各高度最大速度:")
    for item in opt['max_speed_per_alt']:
        if item['mach_max'] is not None:
            print(f"    alt={item['altitude_m']:>6}m: M{item['mach_max']:.3f} ({item['tas_max_kmh']:.0f} km/h)")
        else:
            print(f"    alt={item['altitude_m']:>6}m: 无法维持平飞")
    print()
