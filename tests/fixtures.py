"""合成飞行模型夹具（自包含，不依赖 data/raw）。"""

from __future__ import annotations


def make_coeff_grid(value: float = 1.0, prefix: str = "ThrustMaxCoeff") -> dict:
    """生成 7×12 恒定值系数网格。"""
    return {f"{prefix}_{a}_{v}": value for a in range(7) for v in range(12)}


def make_jet_fm(*, n_engines: int = 1, coeff_value: float = 1.0) -> dict:
    """合成单/双发喷气战斗机 FM。

    推力基础值 5000 kgf，加力倍增系数 1.5，全网格恒定。
    机翼：面积 40 m²、展长 10 m、CdMin 0.02、e=0.8。
    """
    fm = {
        "Mass": {"EmptyMass": 10000.0, "MaxFuelMass0": 3000.0},
        "Engine0": {},
        "EngineType0": {
            "Main": {
                "ThrustMax": {
                    "ThrustMax0": 5000.0,
                    **make_coeff_grid(coeff_value),
                    **make_coeff_grid(1.5, "ThrAftMaxCoeff"),
                }
            }
        },
        "Aerodynamics": {
            "WingPlane": {
                "Areas": {"LeftIn": 20.0, "RightIn": 20.0},
                "Span": 10.0,
                "FlapsPolar0": {
                    "CdMin": 0.02,
                    "OswaldsEfficiencyNumber": 0.8,
                    "MachFactor": 3,
                    "MultMachMax1": 5.0,
                    "MachCrit1": 0.85,
                    "MachMax1": 1.1,
                    "MultLimit1": 8.0,
                    "MultLineCoeff1": -0.5,
                },
            },
            "FuselagePlane": {
                "Areas": 5.0,
                "Polar": {"CdMin": 0.1},
            },
        },
    }
    for i in range(1, n_engines):
        fm[f"Engine{i}"] = {}
    return fm


def make_axes_grid(value: float = 1.0, prefix: str = "ThrustMaxCoeff",
                   n_alt: int = 9, n_vel: int = 13) -> dict:
    """生成带显式轴的 n_alt×n_vel 系数网格（datamine 新格式）。

    Velocity_0 是类型标记（如 "TAS"），不参与网格取值。
    """
    grid = {
        f"Altitude_{a}": float(a * 4000) for a in range(n_alt)
    }
    grid["Velocity_0"] = "TAS"
    for v in range(1, n_vel):
        grid[f"Velocity_{v}"] = float((v - 1) * 100)
    for a in range(n_alt):
        for v in range(n_vel):
            grid[f"{prefix}_{a}_{v}"] = value
    return grid


def make_flat_jet_fm() -> dict:
    """合成平坦格式喷气 FM（老 datamine 结构）。

    机翼极曲线在 NoFlaps，面积在顶层 Areas（Wing* 键），展长在顶层
    Wingspan；机身/平尾/垂尾在 Fuselage/Stab/Fin 子节点各带面积。
    推力网格为 9×13 带显式轴，(8,11) 处系数为 2.0 以便验证旧硬编码
    7×12 网格读不到高位节点。
    """
    grid = make_axes_grid(1.0)
    grid["ThrustMaxCoeff_8_11"] = 2.0
    return {
        "Mass": {"EmptyMass": 10000.0, "MaxFuelMass0": 3000.0},
        "Engine0": {},
        "EngineType0": {
            "Main": {
                "ThrustMax": {
                    "ThrustMax0": 5000.0,
                    **grid,
                    **make_axes_grid(1.5, "ThrAftMaxCoeff"),
                }
            }
        },
        "Wingspan": 10.0,
        "Areas": {"WingLeftIn": 8.0, "WingRightIn": 8.0},
        "Aerodynamics": {
            "NoFlaps": {
                "CdMin": 0.02,
                "OswaldsEfficiencyNumber": 0.8,
                "MachFactor": 3,
                "MultMachMax1": 5.0,
                "MachCrit1": 0.85,
                "MachMax1": 1.1,
                "MultLimit1": 8.0,
                "MultLineCoeff1": -0.5,
            },
            "Fuselage": {
                "Areas": 5.0,
                "CdMin": 0.1,
            },
            "Stab": {
                "Areas": 2.0,
                "CdMin": 0.1,
            },
            "Fin": {
                "Areas": 2.0,
                "CdMin": 0.1,
            },
        },
    }


def make_prop_fm() -> dict:
    """合成二战螺旋桨战斗机 FM。

    单发 1000 HP，单级增压（临界 3000m、天花板 6000m、天花板功率 700HP），
    桨叶半径 1.5 m。
    """
    return {
        "Mass": {"EmptyMass": 3000.0, "MaxFuelMass0": 500.0},
        "Engine0": {"Propellor": {"Diameter": 3.0}},
        "PropellerType0": {"Geometry": {"Radius": 1.5}},
        "EngineType0": {
            "Main": {"Power": 1000.0},
            "Compressor": {
                "Power0": 1000.0,
                "Altitude0": 3000.0,
                "Ceiling0": 6000.0,
                "PowerAtCeiling0": 700.0,
            },
        },
        "Aerodynamics": {
            "WingPlane": {
                "Areas": 17.0,
                "Span": 10.0,
                "FlapsPolar0": {
                    "CdMin": 0.02,
                    "OswaldsEfficiencyNumber": 0.75,
                    "MachFactor": 3,
                    "MultMachMax1": 3.0,
                    "MachCrit1": 0.6,
                    "MachMax1": 0.8,
                },
            },
            "FuselagePlane": {
                "Areas": 3.0,
                "Polar": {"CdMin": 0.1},
            },
        },
    }
