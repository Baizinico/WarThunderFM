"""测试包含所有通道（含削减通道）的阻力模型效果。"""
import json
import math
import sys
sys.path.insert(0, '.')
from lib.compute import isa_atmosphere, interpolate_thrust, _extract_drag_components, _get_wing_data

G = 9.80665

def mach_mult_all_channels(polar, mach, abs_fix=True):
    """包含所有通道的马赫倍增器（不跳过 MultMachMax<1.0 的通道）。"""
    total = 1.0
    m = float(mach)
    mach_factor = float(polar.get("MachFactor", 3))
    for i in range(1, 8):
        mult_max = polar.get(f"MultMachMax{i}")
        if mult_max is None:
            continue
        mult_max = float(mult_max)
        mach_crit = polar.get(f"MachCrit{i}")
        mach_max = polar.get(f"MachMax{i}")
        if mach_crit is None or mach_max is None:
            continue
        mach_crit = float(mach_crit)
        mach_max = float(mach_max)
        if mach_crit <= 0 or mach_max <= 0:
            continue
        mult_limit = float(polar.get(f"MultLimit{i}", mult_max))
        line_coeff = float(polar.get(f"MultLineCoeff{i}", 0.0))

        if m < mach_crit:
            mult = 1.0
        elif m <= mach_max:
            denom = mach_max - mach_crit
            if denom <= 0:
                mult = mult_max
            else:
                t = (m - mach_crit) / denom
                mult = 1.0 + (mult_max - 1.0) * (t ** mach_factor)
        else:
            if abs_fix:
                mult = mult_max + (mult_limit - mult_max) * (
                    1.0 - math.exp(-abs(line_coeff) * (m - mach_max)))
            else:
                mult = mult_max + (mult_limit - mult_max) * (
                    1.0 - math.exp(line_coeff * (m - mach_max)))
        if mult < 0:
            mult = 0.0
        total *= mult
    return total

def calc_drag_all_channels(fm, mach, tas_mps, rho, mass_kg, floor=1.0):
    """使用所有通道计算阻力，可指定总倍率的下限 floor。"""
    q = 0.5 * rho * tas_mps * tas_mps
    parasite = 0.0
    for polar, area in _extract_drag_components(fm):
        cd_min = float(polar.get("CdMin", 0.0))
        mult = mach_mult_all_channels(polar, mach)
        mult = max(floor, mult)  # 应用下限
        cd = cd_min * mult
        parasite += q * cd * area

    wing_polar, wing_area, wing_span = _get_wing_data(fm)
    e = float(wing_polar.get("OswaldsEfficiencyNumber", 0.75)) if wing_polar else 0.75
    if wing_area > 0 and wing_span > 0:
        ar = (wing_span * wing_span) / wing_area
    else:
        ar = 8.0
    if q > 0 and wing_area > 0:
        cl = (mass_kg * G) / (q * wing_area)
        cl = min(cl, 1.5)
    else:
        cl = 0.0
    if e > 0 and ar > 0:
        cd_induced = (cl * cl) / (math.pi * ar * e)
    else:
        cd_induced = 0.0
    induced = q * wing_area * cd_induced
    return max(0.0, parasite + induced)

# 加载 FM 数据
fm = json.load(open('data/raw/j_10c.blkx', 'r', encoding='utf-8'))
empty_mass = fm['Mass']['EmptyMass']
max_fuel = fm['Mass'].get('MaxFuelMass0', 0)
mass_kg = empty_mass + max_fuel * 0.5

# 测试不同 floor 值
print("=== J-10C 各高度最大速度对比（加力） ===")
print(f"{'方案':<20}", end="")
for alt in [0, 5000, 8000, 11000, 15000]:
    print(f" alt={alt:<6}", end="")
print()

for floor, label in [(None, "跳过<1.0(当前)"), (1.0, "全通道+floor=1.0"),
                      (0.5, "全通道+floor=0.5"), (0.3, "全通道+floor=0.3"),
                      (0.0, "全通道无floor")]:
    print(f"{label:<20}", end="")
    for alt in [0, 5000, 8000, 11000, 15000]:
        T, _P, rho = isa_atmosphere(alt)
        a_sound = math.sqrt(1.4 * 287.05 * T)
        best_mach = 0
        for mi in range(10, 251):
            mach = mi / 100.0
            tas_mps = mach * a_sound
            tas_kmh = tas_mps * 3.6
            _mil, ab = interpolate_thrust(fm, alt, tas_kmh, afterburner=True)
            if floor is None:
                from lib.compute import calculate_drag
                drag = calculate_drag(fm, mach, tas_mps, rho, mass_kg)
            else:
                drag = calc_drag_all_channels(fm, mach, tas_mps, rho, mass_kg, floor=floor)
            accel = (ab - drag) / mass_kg
            if accel > 0:
                best_mach = mach  # 不 break，继续找更高的正加速度马赫数
        if best_mach > 0:
            print(f" M{best_mach:<5.2f}", end="")
        else:
            print(f" {'N/A':<6}", end="")
    print()

# 也测试 Su-27
print()
fm_su27 = json.load(open('data/raw/su_27.blkx', 'r', encoding='utf-8'))
empty_mass_s = fm_su27['Mass']['EmptyMass']
max_fuel_s = fm_su27['Mass'].get('MaxFuelMass0', 0)
mass_kg_s = empty_mass_s + max_fuel_s * 0.5
print(f"Su-27 mass: {mass_kg_s:.0f} kg, ThrustMax0: {fm_su27['EngineType0']['Main']['ThrustMax']['ThrustMax0']} kgf")

print("\n=== Su-27 各高度最大速度对比（加力） ===")
print(f"{'方案':<20}", end="")
for alt in [0, 5000, 8000, 11000, 15000]:
    print(f" alt={alt:<6}", end="")
print()

for floor, label in [(None, "跳过<1.0(当前)"), (1.0, "全通道+floor=1.0"),
                      (0.5, "全通道+floor=0.5"), (0.3, "全通道+floor=0.3"),
                      (0.0, "全通道无floor")]:
    print(f"{label:<20}", end="")
    for alt in [0, 5000, 8000, 11000, 15000]:
        T, _P, rho = isa_atmosphere(alt)
        a_sound = math.sqrt(1.4 * 287.05 * T)
        best_mach = 0
        for mi in range(10, 251):
            mach = mi / 100.0
            tas_mps = mach * a_sound
            tas_kmh = tas_mps * 3.6
            _mil, ab = interpolate_thrust(fm_su27, alt, tas_kmh, afterburner=True)
            if floor is None:
                from lib.compute import calculate_drag
                drag = calculate_drag(fm_su27, mach, tas_mps, rho, mass_kg_s)
            else:
                drag = calc_drag_all_channels(fm_su27, mach, tas_mps, rho, mass_kg_s, floor=floor)
            accel = (ab - drag) / mass_kg_s
            if accel > 0:
                best_mach = mach
        if best_mach > 0:
            print(f" M{best_mach:<5.2f}", end="")
        else:
            print(f" {'N/A':<6}", end="")
    print()

print("\n参考值: J-10C 实际最大速度 ~M1.8-2.0, Su-27 ~M2.35 (高空)")
