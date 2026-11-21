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


# ============================================================
# FIX_SPEC §8.1 新增夹具（新引擎布局：老格式 / 多类型 / 垂直升力等）
# ============================================================
def _small_coeff_grid(n_alt: int, n_vel: int, value: float = 1.0,
                      prefix: str = "ThrustMaxCoeff") -> dict:
    """生成 n_alt×n_vel 恒定值系数网格（新夹具用的占位网格）。"""
    return {f"{prefix}_{a}_{v}": value for a in range(n_alt) for v in range(n_vel)}


def make_old_format_jet_fm() -> dict:
    """老格式双发喷气（me-262a-1a 型）：无 EngineType，Engine0/1 自带完整 Main。

    每台 Main.Type="Jet"、Power=1200（占位）、ThrustMax0=910 + 6×7 恒定系数网格；
    另有占位 Propellor 字段（不得影响“喷气”判定）。总推力应为 2×910=1820 kgf。
    """
    engine = {
        "Main": {
            "Type": "Jet",
            "Power": 1200.0,
            "ThrustMax": {
                "ThrustMax0": 910.0,
                **_small_coeff_grid(6, 7),
            },
        },
        # 老格式里常见的占位螺旋桨字段：有 Type=Jet 时必须判为喷气
        "Propellor": {"Diameter": 3.0},
    }
    fm = make_jet_fm()
    fm.pop("EngineType0", None)
    fm["Mass"] = {"EmptyMass": 7000.0, "MaxFuelMass0": 2000.0}
    fm["Engine0"] = engine
    fm["Engine1"] = {
        "Main": {
            "Type": "Jet",
            "Power": 1200.0,
            "ThrustMax": {
                "ThrustMax0": 910.0,
                **_small_coeff_grid(6, 7),
            },
        },
        "Propellor": {"Diameter": 3.0},
    }
    return fm


def make_multi_type_jet_fm() -> dict:
    """多发动机类型：EngineType0=Jet(4590)、EngineType1=Rocket(453)。

    Engine0/1 引用 Type=0 共 2 台，Engine2..13 引用 Type=1 共 12 台。
    Rocket 类型应被喷气统计排除 → count=2、总推力 2×4590=9180 kgf。
    """
    fm = make_jet_fm()
    fm["Mass"] = {"EmptyMass": 20000.0, "MaxFuelMass0": 5000.0}
    fm["EngineType0"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 4590.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["EngineType1"] = {
        "Main": {
            "Type": "Rocket",
            "ThrustMax": {
                "ThrustMax0": 453.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm.pop("Engine0", None)
    for i in range(14):
        fm[f"Engine{i}"] = {"Type": 0 if i < 2 else 1}
    return fm


def make_vertical_lift_fm() -> dict:
    """垂直起降（Yak-141 型）：主升力发动机 + 2 台升力发动机。

    EngineType0=Jet(10960)，EngineType1=Jet(4260)；
    Engine0 引用 Type0 俯仰 0°，Engine1/2 引用 Type1 俯仰 76°（>45° 应排除）。
    → count=1、总推力 10960 kgf。
    """
    fm = make_jet_fm()
    fm["Mass"] = {"EmptyMass": 15000.0, "MaxFuelMass0": 4000.0}
    fm["EngineType0"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 10960.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["EngineType1"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 4260.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["Engine0"] = {
        "Type": 0,
        "Nozzle0": {"Direction": [0.0, 0.0, -1.0]},   # 俯仰 0°
    }
    for i in (1, 2):
        fm[f"Engine{i}"] = {
            "Type": 1,
            "Nozzle0": {"Direction": [0.0, 76.0, 0.0]},  # 俯仰 76°（垂直升力）
        }
    return fm


def make_typed_prop_fm() -> dict:
    """带 Type 的螺旋桨（a5m4 型）：EngineType0.Main.Type="Radial"。

    Power=619、占位 ThrustMax0=2700 + 4×5 系数网格、PropellerType0；
    1 台 Type=0 实例 → 螺旋桨、count=1。
    """
    fm = make_prop_fm()
    fm["EngineType0"] = {
        "Main": {
            "Type": "Radial",
            "Power": 619.0,
            "ThrustMax": {
                "ThrustMax0": 2700.0,
                **_small_coeff_grid(4, 5),
            },
        },
    }
    fm["Engine0"] = {"Type": 0}
    return fm


def make_old_format_prop_fm() -> dict:
    """老格式双发螺旋桨（a2d 型）：无 EngineType，Engine0/1 自带 Main。

    每台 Main.Type="TurboProp"、Power=256（占位）、ThrustMax0=256；
    顶层 Propeller0 → 螺旋桨、count=2。
    """
    fm = make_prop_fm()
    fm.pop("EngineType0", None)
    fm.pop("PropellerType0", None)
    for i in (0, 1):
        fm[f"Engine{i}"] = {
            "Main": {
                "Type": "TurboProp",
                "Power": 256.0,
                "ThrustMax": {"ThrustMax0": 256.0},
            },
        }
    fm["Propeller0"] = {"Geometry": {"Radius": 1.5}}
    return fm


def make_multi_jet_type_fm() -> dict:
    """两个 Jet 类型各 1 台：EngineType0(1652) + EngineType1(821)。

    总推力应为 1652+821=2473 kgf（不能只取主类型 × 台数）。
    """
    fm = make_jet_fm()
    fm["Mass"] = {"EmptyMass": 8000.0, "MaxFuelMass0": 2500.0}
    fm["EngineType0"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 1652.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["EngineType1"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 821.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["Engine0"] = {"Type": 0}
    fm["Engine1"] = {"Type": 1}
    return fm


def make_orphan_type_jet_fm() -> dict:
    """孤儿类型：仅 Engine0 引用 Type=0，另有未被引用的 EngineType1(9999)。

    未被引用的类型不得计入 → count=1、总推力 1200 kgf。
    """
    fm = make_jet_fm()
    fm["Mass"] = {"EmptyMass": 9000.0, "MaxFuelMass0": 3000.0}
    fm["EngineType0"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 1200.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["EngineType1"] = {
        "Main": {
            "Type": "Jet",
            "ThrustMax": {
                "ThrustMax0": 9999.0,
                **_small_coeff_grid(7, 12),
                **_small_coeff_grid(7, 12, 1.5, "ThrAftMaxCoeff"),
            },
        }
    }
    fm["Engine0"] = {"Type": 0}
    return fm
