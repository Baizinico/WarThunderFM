"""验证引擎数量修复后的最大速度。"""
import json
import math
import sys
sys.path.insert(0, '.')
from lib.compute import isa_atmosphere, interpolate_thrust, calculate_drag, _count_engines

G = 9.80665

for aircraft in ['j_10c', 'su_27']:
    fm = json.load(open(f'data/raw/{aircraft}.blkx', 'r', encoding='utf-8'))
    empty_mass = fm['Mass']['EmptyMass']
    max_fuel = fm['Mass'].get('MaxFuelMass0', 0)
    mass_kg = empty_mass + max_fuel * 0.5
    n_eng = _count_engines(fm)
    t0 = fm['EngineType0']['Main']['ThrustMax']['ThrustMax0']
    print(f"=== {aircraft} ===")
    print(f"  引擎数: {n_eng}, 单发推力: {t0} kgf, 总推力: {t0*n_eng} kgf")
    print(f"  飞行质量: {mass_kg:.0f} kg, TWR: {t0*n_eng/mass_kg:.3f}")

    print(f"  各高度最大速度 (加力, 当前阻力模型):")
    print(f"  {'Alt(m)':<8} {'MaxMach':<10} {'TASkmh':<10} {'Thrust_kgf':<12} {'Drag_kgf':<12} {'Accel':<10}")
    for alt in [0, 2000, 5000, 8000, 11000, 15000]:
        T, _P, rho = isa_atmosphere(alt)
        a_sound = math.sqrt(1.4 * 287.05 * T)
        best_mach = 0
        best_data = None
        for mi in range(10, 501):
            mach = mi / 100.0
            tas_mps = mach * a_sound
            tas_kmh = tas_mps * 3.6
            _mil, ab = interpolate_thrust(fm, alt, tas_kmh, afterburner=True)
            drag = calculate_drag(fm, mach, tas_mps, rho, mass_kg)
            accel = (ab - drag) / mass_kg
            if accel > 0:
                best_mach = mach
                best_data = (ab/G, drag/G, accel, tas_kmh)
        if best_mach > 0:
            ab_kgf, drag_kgf, accel, tas_kmh = best_data
            print(f"  {alt:<8} M{best_mach:<9.2f} {tas_kmh:<10.0f} {ab_kgf:<12.0f} {drag_kgf:<12.0f} {accel:<10.2f}")
        else:
            print(f"  {alt:<8} {'N/A':<10}")
    print()

print("参考: J-10C 实际最大速度 ~M1.8-2.0 (高空), Su-27 ~M2.35 (高空)")
