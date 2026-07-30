"""对比当前 compute.py 与参考 wt_fm_analyzer.py 的加速度计算结果。"""
import json
import math
import sys
sys.path.insert(0, '.')

# 当前实现
from lib.compute import (
    isa_atmosphere, interpolate_thrust, calculate_drag,
    mach_drag_multiplier as my_mach_mult, _extract_drag_components
)

# 加载 FM 数据
fm = json.load(open('data/raw/j_10c.blkx', 'r', encoding='utf-8'))

# 飞行质量
empty_mass = fm['Mass']['EmptyMass']
max_fuel = fm['Mass'].get('MaxFuelMass0', 0)
mass_kg = empty_mass + max_fuel * 0.5
print(f"Empty mass: {empty_mass} kg, Max fuel: {max_fuel} kg, Flight mass: {mass_kg:.1f} kg")
print(f"ThrustMax0: {fm['EngineType0']['Main']['ThrustMax']['ThrustMax0']} kgf")

# 检查 ThrAftMaxCoeff 是否完整
eng = fm['EngineType0']['Main']['ThrustMax']
missing_aft = 0
missing_mil = 0
for a in range(7):
    for v in range(12):
        if eng.get(f'ThrustMaxCoeff_{a}_{v}') is None:
            missing_mil += 1
        if eng.get(f'ThrAftMaxCoeff_{a}_{v}') is None:
            missing_aft += 1
print(f"Missing ThrustMaxCoeff: {missing_mil}/84, Missing ThrAftMaxCoeff: {missing_aft}/84")

# 对比关键点的加速度
print("\n=== 加速度对比 (高度 x 马赫) ===")
G = 9.80665
altitudes = [0, 2000, 5000, 8000, 11000, 15000]
machs = [0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0, 2.5]

print(f"{'Alt(m)':<8} {'Mach':<6} {'TASkmh':<8} {'Mil_kgf':<10} {'AB_kgf':<10} {'Drag_kgf':<10} {'Accel_AB':<10} {'Accel_Mil':<10}")
print("-" * 80)

for alt in altitudes:
    T, _P, rho = isa_atmosphere(alt)
    a_sound = math.sqrt(1.4 * 287.05 * T)
    for mach in machs:
        tas_mps = mach * a_sound
        tas_kmh = tas_mps * 3.6
        mil_n, ab_n = interpolate_thrust(fm, alt, tas_kmh, afterburner=True)
        drag_n = calculate_drag(fm, mach, tas_mps, rho, mass_kg)
        accel_ab = (ab_n - drag_n) / mass_kg
        accel_mil = (mil_n - drag_n) / mass_kg
        print(f"{alt:<8} {mach:<6.2f} {tas_kmh:<8.0f} {mil_n/G:<10.0f} {ab_n/G:<10.0f} {drag_n/G:<10.0f} {accel_ab:<10.2f} {accel_mil:<10.2f}")
    print()

# 检查参考实现的马赫倍增器（原始公式，不用 abs）
def ref_mach_mult(polar, mach):
    """参考实现的马赫倍增器（原始公式，不使用 abs）。"""
    mach_factor = polar.get('MachFactor', 3)
    total = 1.0
    for i in range(1, 8):
        mult_max = polar.get(f'MultMachMax{i}', 1.0)
        if mult_max < 1.0:
            continue
        mach_crit = polar.get(f'MachCrit{i}', 0)
        mach_max = polar.get(f'MachMax{i}', 0)
        mult_limit = polar.get(f'MultLimit{i}', 1.0)
        line_coeff = polar.get(f'MultLineCoeff{i}', 0.0)
        if mach_crit <= 0 or mach_max <= 0:
            continue
        if mach < mach_crit:
            mult = 1.0
        elif mach <= mach_max:
            t = (mach - mach_crit) / max(mach_max - mach_crit, 1e-6)
            mult = 1.0 + (mult_max - 1.0) * (t ** mach_factor)
        else:
            mult = mult_max + (mult_limit - mult_max) * (1.0 - math.exp(line_coeff * (mach - mach_max)))
        total *= mult
    return total

print("\n=== 马赫倍增器对比 (我的 abs 修复 vs 参考原始公式) ===")
comps = _extract_drag_components(fm)
comp_names = ['Wing', 'Fuselage', 'HorStab', 'VerStab']
print(f"{'Mach':<6}", end="")
for name in comp_names:
    print(f" {name+'_mine':>12s}/{name+'_ref':>12s}", end="")
print()
for mach in [1.0, 1.2, 1.5, 2.0, 2.5]:
    print(f"{mach:<6.2f}", end="")
    for polar, area in comps:
        mine = my_mach_mult(polar, mach)
        ref = ref_mach_mult(polar, mach)
        print(f" {mine:>12.3f}/{ref:>12.3f}", end="")
    print()

# 检查参考实现的总阻力系数
print("\n=== 总阻力系数对比 (CdMin*Area*Mult 求和) ===")
print(f"{'Mach':<6} {'Mine':>10s} {'Ref':>10s} {'Ratio':>8s}")
for mach in [0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0, 2.5]:
    total_mine = 0.0
    total_ref = 0.0
    for polar, area in comps:
        cd_min = polar.get('CdMin', 0)
        total_mine += cd_min * my_mach_mult(polar, mach) * area
        total_ref += cd_min * ref_mach_mult(polar, mach) * area
    ratio = total_mine / total_ref if total_ref > 0 else float('inf')
    print(f"{mach:<6.2f} {total_mine:>10.4f} {total_ref:>10.4f} {ratio:>8.2f}")
