"""War Thunder 飞行模型加速度计算模块。

基于 wt-fm-analysis 算法，解析 WT .blkx 飞行模型 JSON 数据，计算：
  - ISA 国际标准大气（温度、气压、密度）
  - 推力双线性插值（军用推力 + 加力推力，含冲压效应）
  - 修正马赫倍增器的跨/超声速阻力（仅累加阻力增长通道）
  - 高度 × 马赫网格上的加速度
  - 最优飞行剖面（各高度最大速度、各马赫数最佳高度）

物理常量与节点定义与 wt-fm-analysis skill 一致。依赖 numpy。
"""

import math

import numpy as np

# ============================================================
# 物理常量与节点定义
# ============================================================
G = 9.80665              # 重力加速度 m/s^2
R_AIR = 287.05           # 空气气体常数 J/(kg·K)
GAMMA = 1.4              # 空气比热比
T0 = 288.15              # 海平面温度 K
P0 = 101325.0            # 海平面气压 Pa
LAPSE_RATE = 0.0065      # 对流层温度递减率 K/m
TROPO_EXP = 5.2561       # 对流层气压公式指数（≈ g/(R·L)）
TROPOPAUSE_M = 11000.0   # 对流层顶高度 m
T_TROPO = T0 - LAPSE_RATE * TROPOPAUSE_M            # 对流层顶温度 ≈ 216.65 K
P_TROPO = P0 * (T_TROPO / T0) ** TROPO_EXP          # 对流层顶气压 Pa

# 推力系数插值网格节点（匹配 .blkx 数据格式：7 高度 × 12 速度）
ALT_NODES = [0, 2000, 5000, 8000, 11000, 15000, 25000]                            # m
VEL_NODES = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2400]     # km/h TAS
N_ALT = len(ALT_NODES)   # 7
N_VEL = len(VEL_NODES)   # 12

# 输出加速度网格的高度节点（可自定义粒度，独立于 .blkx 数据格式）
OUTPUT_ALT_NODES = [0, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000, 15000]  # m


# ============================================================
# 1. ISA 大气模型
# ============================================================
def isa_atmosphere(altitude_m: float) -> tuple[float, float, float]:
    """国际标准大气模型（ISA）。

    参数:
        altitude_m: 海拔高度（米）。

    返回:
        (T_K, P_pa, rho_kg_m3)：温度(K)、气压(Pa)、密度(kg/m³)。

    说明:
        - 对流层（0-11000m）：T = T0 - L·h, P = P0·(T/T0)^5.2561
        - 同温层（11000-25000m）：T 恒为 216.65K, P = P11·exp(-g·(h-11000)/(R·T))
        - 密度 ρ = P/(R·T)
    """
    h = float(altitude_m)
    if h <= TROPOPAUSE_M:
        # 对流层
        T = T0 - LAPSE_RATE * h
        P = P0 * (T / T0) ** TROPO_EXP
    else:
        # 同温层（等温层）
        T = T_TROPO
        P = P_TROPO * math.exp(-G * (h - TROPOPAUSE_M) / (R_AIR * T))
    rho = P / (R_AIR * T)
    return T, P, rho


# ============================================================
# 2. 推力双线性插值
# ============================================================
def _get_thrust_data(fm: dict) -> dict:
    """从 fm 中提取推力数据字典。

    兼容 EngineType0 / EngineType / EngineType1 等命名变体
    （fm 中可能缺少 EngineType0 而使用其它键名）。
    """
    if not isinstance(fm, dict):
        return {}
    for key in ("EngineType0", "EngineType", "EngineType1"):
        eng = fm.get(key)
        if isinstance(eng, dict):
            main = eng.get("Main", {})
            if isinstance(main, dict) and isinstance(main.get("ThrustMax"), dict):
                return main["ThrustMax"]
    return {}


def _count_engines(fm: dict) -> int:
    """统计飞机的引擎实例数量。

    WT FM 中 Engine0 / Engine1 / ... 为引擎实例，每个实例引用 EngineType0
    的推力曲线。双发战机（如 Su-27）有两个实例，总推力 = 单发推力 × 实例数。
    若无 Engine0/Engine1 键，默认 1 发。
    """
    if not isinstance(fm, dict):
        return 1
    count = 0
    for i in range(16):  # 最多检查 16 个引擎槽位
        if f"Engine{i}" in fm:
            count += 1
    return max(1, count)  # 至少 1 发


def _build_coeff_grid(thrust_data: dict, field_prefix: str, default: float) -> np.ndarray:
    """构建 7×12 系数网格。

    参数:
        thrust_data: ThrustMax 字典。
        field_prefix: 字段前缀，如 "ThrustMaxCoeff" 或 "ThrAftMaxCoeff"。
        default: 字段缺失时的默认值。

    返回:
        shape=(N_ALT, N_VEL) 的 numpy 数组，axis0=高度索引，axis1=速度索引。
    """
    grid = np.full((N_ALT, N_VEL), default, dtype=float)
    for a in range(N_ALT):
        for v in range(N_VEL):
            val = thrust_data.get(f"{field_prefix}_{a}_{v}")
            if val is not None:
                grid[a, v] = float(val)
    return grid


def _bilinear_interp(grid: np.ndarray, x_nodes: list[float], y_nodes: list[float],
                     x: float, y: float) -> float:
    """对二维网格做双线性插值。

    参数:
        grid: shape=(len(x_nodes), len(y_nodes)) 的二维数组，
              axis0 对应 x（高度），axis1 对应 y（速度）。
        x_nodes: x 轴节点（升序）。
        y_nodes: y 轴节点（升序）。
        x, y: 待插值点。

    返回:
        插值结果（float）。超出节点范围的输入会被钳制到端点。
    """
    x_arr = np.asarray(x_nodes, dtype=float)
    y_arr = np.asarray(y_nodes, dtype=float)
    # 钳制到节点范围
    xq = min(max(x, x_arr[0]), x_arr[-1])
    yq = min(max(y, y_arr[0]), y_arr[-1])
    # 定位下端索引（searchsorted 返回插入位置，减 1 得左端）
    xi = int(np.searchsorted(x_arr, xq) - 1)
    xi = max(0, min(xi, len(x_arr) - 2))
    yi = int(np.searchsorted(y_arr, yq) - 1)
    yi = max(0, min(yi, len(y_arr) - 2))
    x0, x1 = x_arr[xi], x_arr[xi + 1]
    y0, y1 = y_arr[yi], y_arr[yi + 1]
    fx = (xq - x0) / (x1 - x0) if x1 > x0 else 0.0
    fy = (yq - y0) / (y1 - y0) if y1 > y0 else 0.0
    q00 = grid[xi, yi]
    q01 = grid[xi, yi + 1]
    q10 = grid[xi + 1, yi]
    q11 = grid[xi + 1, yi + 1]
    return float(q00 * (1 - fx) * (1 - fy)
                 + q01 * (1 - fx) * fy
                 + q10 * fx * (1 - fy)
                 + q11 * fx * fy)


def interpolate_thrust(fm: dict, alt_m: float, vel_kmh: float,
                       afterburner: bool) -> tuple[float, float]:
    """推力双线性插值。

    参数:
        fm: 飞行模型 JSON 字典。
        alt_m: 高度（米）。
        vel_kmh: 真空速（km/h TAS）。
        afterburner: 是否启用加力（保留参数；函数始终同时返回军用与加力推力，
                     由调用方按该标志选用）。

    返回:
        (military_thrust_n, afterburner_thrust_n)，单位牛顿(N)。
        - 军用推力 = ThrustMax0(kgf) × 9.80665 × ThrustMaxCoeff[alt][vel] × 引擎数
        - 加力推力 = 军用推力 × ThrAftMaxCoeff[alt][vel]（缺省系数视为 1.0）

    说明:
        多发战机（如 Su-27 有 Engine0 + Engine1 两个实例）的总推力 = 单发推力 ×
        引擎实例数。_count_engines 统计 Engine0/Engine1/... 键的数量。
    """
    thrust_data = _get_thrust_data(fm)
    n_engines = _count_engines(fm)
    t0_kgf = float(thrust_data.get("ThrustMax0", 0.0))
    t0_n = t0_kgf * G * n_engines  # 总基础推力 = 单发 × 引擎数
    # 军用推力系数缺省 0.0；加力倍增系数缺省 1.0
    coeff = _build_coeff_grid(thrust_data, "ThrustMaxCoeff", default=0.0)
    aft = _build_coeff_grid(thrust_data, "ThrAftMaxCoeff", default=1.0)
    c = _bilinear_interp(coeff, ALT_NODES, VEL_NODES, alt_m, vel_kmh)
    a = _bilinear_interp(aft, ALT_NODES, VEL_NODES, alt_m, vel_kmh)
    mil_n = t0_n * c
    ab_n = mil_n * a
    return mil_n, ab_n


# ============================================================
# 3. 修正马赫倍增器
# ============================================================
def mach_drag_multiplier(polar: dict, mach: float) -> float:
    """计算单个阻力极曲线的马赫阻力倍增器。

    使用 WT .blkx 中的增长通道（MultMachMax >= 1.0）模拟跨音速阻力墙，
    跳过削减通道（MultMachMax < 1.0）和 LineCoeff > 0 的异常通道。

    削减通道（如 ch6: MultMachMax=0.1）直接相乘会让超声速阻力接近 0，
    导致低空也能轻松超音速，与 WT 实际表现不符。WT 引擎对这些通道的组合
    逻辑并非简单相乘，跳过它们能得到与 WT 实际最大速度吻合的结果：
    - 低空卡在 M1.0-1.05（跨音速墙厚）
    - 高空可突破到 M1.5-1.8（墙薄 + 推力衰减慢）

    每通道插值：
        Mach < MachCrit              → multiplier = 1.0
        MachCrit <= Mach <= MachMax  → multiplier = 1 + (MultMachMax-1)·t^MachFactor
        Mach > MachMax               → multiplier = MultMachMax + (MultLimit-MultMachMax)
                                              ·(1 - exp(MultLineCoeff·(Mach-MachMax)))
    """
    m = float(mach)
    mach_factor = float(polar.get("MachFactor", 3))
    total_mult = 1.0

    # WT FM 的马赫通道索引为 1-7
    for i in range(1, 8):
        mult_max = polar.get(f"MultMachMax{i}", 1.0)
        mult_max = float(mult_max)

        # 跳过削减通道（MultMachMax < 1.0）
        if mult_max < 1.0:
            continue

        mach_crit = polar.get(f"MachCrit{i}", 0)
        mach_max = polar.get(f"MachMax{i}", 0)
        if mach_crit <= 0 or mach_max <= 0:
            continue

        mult_limit = float(polar.get(f"MultLimit{i}", 1.0))
        line_coeff = float(polar.get(f"MultLineCoeff{i}", 0.0))

        # 跳过 LineCoeff > 0 的通道：原始公式产生负倍率
        if line_coeff > 0:
            continue

        if m < mach_crit:
            mult = 1.0
        elif m <= mach_max:
            denom = max(mach_max - mach_crit, 1e-6)
            t = (m - mach_crit) / denom
            mult = 1.0 + (mult_max - 1.0) * (t ** mach_factor)
        else:  # m > mach_max
            mult = mult_max + (mult_limit - mult_max) * (
                1.0 - math.exp(line_coeff * (m - mach_max)))

        total_mult *= mult

    return total_mult


# ============================================================
# 4. 阻力计算
# ============================================================
def _sum_areas(areas) -> float:
    """从 Areas 字典/列表中求和得到部件参考面积。

    WT FM 中各 plane 的 Areas 字段为 dict（如 {'LeftIn':7.0, 'LeftMid':6.0, ...}）
    或数值。此处统一求和。
    """
    if areas is None:
        return 0.0
    if isinstance(areas, (int, float)):
        return float(areas)
    if isinstance(areas, dict):
        return sum(float(v) for v in areas.values() if isinstance(v, (int, float)))
    if isinstance(areas, list):
        return sum(float(v) for v in areas if isinstance(v, (int, float)))
    return 0.0


def _extract_drag_components(fm: dict) -> list[tuple[dict, float]]:
    """提取四个阻力部件的 (polar, area) 列表。

    部件：机翼(WingPlane.FlapsPolar0)、机身(FuselagePlane.Polar)、
          平尾(HorStabPlane.Polar)、垂尾(VerStabPlane.Polar)。

    面积取值优先级：plane 的 Areas 字典求和 → polar 的 Area → 缺省 0.0。
    """
    aero = fm.get("Aerodynamics", {})
    if not isinstance(aero, dict):
        return []
    comps: list[tuple[dict, float]] = []

    # 机翼
    wing_plane = aero.get("WingPlane", {})
    if isinstance(wing_plane, dict):
        wing_polar = wing_plane.get("FlapsPolar0", {})
        if isinstance(wing_polar, dict) and wing_polar:
            area = _sum_areas(wing_plane.get("Areas"))
            if area <= 0:
                area = float(wing_polar.get("Area", 0.0))
            comps.append((wing_polar, area))

    # 机身 / 平尾 / 垂尾
    for plane_key in ("FuselagePlane", "HorStabPlane", "VerStabPlane"):
        plane = aero.get(plane_key, {})
        if not isinstance(plane, dict):
            continue
        polar = plane.get("Polar", {})
        if isinstance(polar, dict) and polar:
            area = _sum_areas(plane.get("Areas"))
            if area <= 0:
                area = float(polar.get("Area", 0.0))
            comps.append((polar, area))
    return comps


def _get_wing_data(fm: dict) -> tuple[dict, float, float]:
    """取机翼极曲线、面积、展长，用于诱导阻力计算。

    返回:
        (wing_polar, wing_area, wing_span)
    """
    aero = fm.get("Aerodynamics", {})
    if not isinstance(aero, dict):
        return {}, 0.0, 0.0
    wing_plane = aero.get("WingPlane", {})
    if not isinstance(wing_plane, dict):
        return {}, 0.0, 0.0
    wing_polar = wing_plane.get("FlapsPolar0", {})
    if not isinstance(wing_polar, dict):
        wing_polar = {}
    area = _sum_areas(wing_plane.get("Areas"))
    if area <= 0:
        area = float(wing_polar.get("Area", 0.0))
    span = float(wing_plane.get("Span", 0.0))
    return wing_polar, area, span


def calculate_drag(fm: dict, mach: float, tas_mps: float, rho: float,
                   mass_kg: float) -> float:
    """计算总阻力（N）。

    参数:
        fm: 飞行模型 JSON 字典。
        mach: 马赫数。
        tas_mps: 真空速（m/s）。
        rho: 空气密度（kg/m³）。
        mass_kg: 飞行质量（kg）——用于诱导阻力 CL 计算。

    返回:
        总阻力（N）= 寄生阻力 + 诱导阻力。

    寄生阻力 = Σ 0.5·ρ·v²·Cd_i·area_i，
              其中 Cd_i = CdMin_i · mach_drag_multiplier(polar_i, mach)。
    诱导阻力 = 0.5·ρ·v²·S_wing·CL²/(π·AR·e)，
              CL = m·g / (q·S_wing)（平飞假设：升力=重力），上限 CL_max=1.5，
              AR = Span²/S_wing（从 FM 数据计算），e 取机翼 polar 的 OswaldsEfficiencyNumber。
    """
    q = 0.5 * rho * tas_mps * tas_mps  # 动压

    # 寄生阻力：累加各部件
    parasite = 0.0
    for polar, area in _extract_drag_components(fm):
        cd_min = float(polar.get("CdMin", 0.0))
        cd = cd_min * mach_drag_multiplier(polar, mach)
        parasite += q * cd * area

    # 诱导阻力：使用机翼极曲线
    wing_polar, wing_area, wing_span = _get_wing_data(fm)
    e = float(wing_polar.get("OswaldsEfficiencyNumber", 0.75)) if wing_polar else 0.75

    # 展弦比 AR = Span² / S
    if wing_area > 0 and wing_span > 0:
        ar = (wing_span * wing_span) / wing_area
    else:
        ar = 8.0  # 兜底

    # 升力系数 CL = m·g / (q·S)（平飞假设），上限 1.5 防止低速失速区发散
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

    # 钳制为非负值：高马赫数下 Mach 倍增器近似公式可能产生负倍率，
    # 但物理上阻力始终 >= 0。这是 wt-fm-analysis 算法的已知限制。
    return max(0.0, parasite + induced)


# ============================================================
# 5. 加速度网格
# ============================================================
def compute_accel_grid(fm: dict, mass_kg: float, afterburner: bool,
                       mach_min: float = 0.1, mach_max: float = 2.5,
                       mach_step: float = 0.05) -> tuple[list[dict], dict]:
    """在高度 × 马赫网格上计算加速度。

    参数:
        fm: 飞行模型 JSON 字典。
        mass_kg: 飞行质量（kg）。
        afterburner: 是否使用加力推力（True=加力，False=军用）。
        mach_min: 马赫数下限（默认 0.1）。
        mach_max: 马赫数上限（默认 2.5）。
        mach_step: 马赫数步长（默认 0.05）。

    返回:
        (samples, grid)：
        - samples: 每个网格点的字典列表，字段含
          altitude_m / mach / tas_mps / thrust_mil_n / thrust_ab_n /
          drag_n / net_force_n / accel_mps2。
        - grid: {"altitudes_m": [...], "machs": [...]}。
    """
    altitudes = list(OUTPUT_ALT_NODES)
    machs = np.arange(mach_min, mach_max + 0.001, mach_step)

    samples: list[dict] = []
    for alt in altitudes:
        T, _P, rho = isa_atmosphere(alt)
        a_sound = math.sqrt(GAMMA * R_AIR * T)  # 当地声速
        for mach in machs:
            mach_f = float(mach)
            tas_mps = mach_f * a_sound
            tas_kmh = tas_mps * 3.6
            mil_n, ab_n = interpolate_thrust(fm, alt, tas_kmh, afterburner)
            drag_n = calculate_drag(fm, mach_f, tas_mps, rho, mass_kg)
            thrust_n = ab_n if afterburner else mil_n
            net_force_n = thrust_n - drag_n
            accel_mps2 = net_force_n / mass_kg if mass_kg > 0 else 0.0
            samples.append({
                "altitude_m": alt,
                "mach": mach_f,
                "tas_mps": tas_mps,
                "thrust_mil_n": mil_n,
                "thrust_ab_n": ab_n,
                "drag_n": drag_n,
                "net_force_n": net_force_n,
                "accel_mps2": accel_mps2,
            })

    grid = {
        "altitudes_m": altitudes,
        "machs": [float(m) for m in machs],
    }
    return samples, grid


# ============================================================
# 6. 最优计算
# ============================================================
def compute_optimal(samples: list[dict], grid: dict) -> dict:
    """由加速度网格推导最优飞行剖面。

    参数:
        samples: compute_accel_grid 返回的样本列表。
        grid: compute_accel_grid 返回的网格描述。

    返回:
        {
          "max_speed_per_alt": [ {altitude_m, mach_max, tas_max_kmh}, ... ],
          "best_alt_per_mach": [ {mach, best_alt_m, accel_mps2}, ... ]
        }

    规则:
        - max_speed_per_alt: 每个高度中 accel>0 的最大马赫数视为该高度最大速度
          （含 tas_max_kmh = tas_mps·3.6）；若该高度所有点 accel<=0，
          则 mach_max 与 tas_max_kmh 均为 None。
        - best_alt_per_mach: 每个马赫数在 accel>0 的点中选加速度最大的高度；
          若该马赫数所有高度 accel<=0，则跳过该马赫数（不出现在结果中）。
    """
    altitudes = grid.get("altitudes_m", [])
    machs = grid.get("machs", [])

    # 按高度 / 马赫分组
    by_alt: dict[float, list[dict]] = {}
    by_mach: dict[float, list[dict]] = {}
    for s in samples:
        by_alt.setdefault(s["altitude_m"], []).append(s)
        by_mach.setdefault(s["mach"], []).append(s)

    # 各高度最大速度（accel>0 的最大马赫）
    max_speed_per_alt = []
    for alt in altitudes:
        best_mach = None
        best_tas_kmh = None
        for s in by_alt.get(alt, []):
            if s["accel_mps2"] > 0:
                if best_mach is None or s["mach"] > best_mach:
                    best_mach = s["mach"]
                    best_tas_kmh = s["tas_mps"] * 3.6
        max_speed_per_alt.append({
            "altitude_m": alt,
            "mach_max": best_mach,
            "tas_max_kmh": best_tas_kmh,
        })

    # 各马赫数最佳高度（accel>0 中加速度最大者）
    best_alt_per_mach = []
    for mach in machs:
        best_alt = None
        best_accel = None
        for s in by_mach.get(mach, []):
            if s["accel_mps2"] > 0:
                if best_accel is None or s["accel_mps2"] > best_accel:
                    best_accel = s["accel_mps2"]
                    best_alt = s["altitude_m"]
        if best_alt is not None:
            best_alt_per_mach.append({
                "mach": mach,
                "best_alt_m": best_alt,
                "accel_mps2": best_accel,
            })

    return {
        "max_speed_per_alt": max_speed_per_alt,
        "best_alt_per_mach": best_alt_per_mach,
    }


# ============================================================
# 7. 最佳爬升路线（基于剩余功率 SEP 的爬升速度程序）
# ============================================================
def compute_climb_route(samples: list[dict], grid: dict) -> list[dict]:
    """基于剩余功率（SEP）计算最佳爬升速度程序。

    SEP（Specific Excess Power）= (T-D)·V / (m·g) = a·V / g，
    单位 m/s，即该状态下可达到的最大稳态爬升率。

    对每个高度，在 accel>0 的点中选取 SEP 最大的马赫数，
    连接为一条「高度 → 最佳爬升马赫数」的速度程序曲线，
    给出从海平面爬升到包线顶点应遵循的马赫数随高度变化规律。

    参数:
        samples: compute_accel_grid 返回的样本列表。
        grid: compute_accel_grid 返回的网格描述。

    返回:
        [{"altitude_m", "mach", "tas_kmh", "sep_mps", "accel_mps2"}, ...]
        按高度升序排列；无 accel>0 点的高度被跳过。
    """
    altitudes = grid.get("altitudes_m", [])

    # 按高度分组
    by_alt: dict[float, list[dict]] = {}
    for s in samples:
        by_alt.setdefault(s["altitude_m"], []).append(s)

    route: list[dict] = []
    for alt in altitudes:
        best: dict | None = None
        for s in by_alt.get(alt, []):
            if s["accel_mps2"] <= 0:
                continue  # 仅在可加速区域选取
            sep = s["tas_mps"] * s["accel_mps2"] / G  # m/s 爬升率
            if best is None or sep > best["sep_mps"]:
                best = {
                    "altitude_m": alt,
                    "mach": s["mach"],
                    "tas_kmh": s["tas_mps"] * 3.6,
                    "sep_mps": sep,
                    "accel_mps2": s["accel_mps2"],
                }
        if best is not None:
            route.append(best)
    return route
