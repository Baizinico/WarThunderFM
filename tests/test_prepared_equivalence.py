"""预编译模型（热路径）与逐点参考实现的一致性回归测试。

compute_accel_grid 现在先调用 _build_drag_model / _build_thrust_model 预编译，
再逐点用 _drag_from_model / _thrust_from_model 求值。本测试确保热路径与公开的
逐点接口 calculate_drag / interpolate_thrust / mach_drag_multiplier 数值一致，
防止未来修改时双路径失同步。
"""

from __future__ import annotations

from lib.compute import (
    _build_drag_model,
    _build_thrust_model,
    _compile_mach_channels,
    _drag_from_model,
    _eval_mach_channels,
    _thrust_from_model,
    calculate_drag,
    interpolate_thrust,
    mach_drag_multiplier,
)
from tests.fixtures import make_flat_jet_fm, make_jet_fm, make_prop_fm

FMS = {
    "jet": make_jet_fm(),
    "jet2": make_jet_fm(n_engines=2),
    "prop": make_prop_fm(),
    "flat": make_flat_jet_fm(),
}


def test_drag_hot_path_matches_reference():
    for fm in FMS.values():
        model = _build_drag_model(fm)
        for mach in (0.1, 0.5, 0.85, 1.0, 1.1, 1.6, 2.5):
            for mass in (0.0, 1000.0, 12000.0):
                rho = 1.225
                tas = mach * 340.0
                assert _drag_from_model(model, mach, tas, rho, mass) == \
                    calculate_drag(fm, mach, tas, rho, mass)


def test_thrust_hot_path_matches_reference():
    for fm in FMS.values():
        model = _build_thrust_model(fm)
        for alt in (0, 5000, 11000, 15000):
            for vel in (0, 400, 1000, 2400):
                assert _thrust_from_model(model, alt, vel) == \
                    interpolate_thrust(fm, alt, vel, True)


def test_mach_channel_eval_matches_reference():
    polars = [
        {"MachFactor": 3, "MultMachMax1": 5.0, "MachCrit1": 0.85,
         "MachMax1": 1.1, "MultLimit1": 8.0, "MultLineCoeff1": -0.5},
        {"MultMachMax1": 0.1},                                    # 削减通道，应跳过
        {"MultMachMax1": 2.0, "MachCrit1": 0.8, "MachMax1": 1.0,
         "MultLineCoeff1": 0.1},                                  # 正 LineCoeff，应跳过
        {"MultMachMax7": [6.0, 2.1], "MachCrit7": [0.96, 0.9]},   # 数组通道，应跳过
    ]
    for polar in polars:
        channels = _compile_mach_channels(polar)
        for mach in (0.1, 0.8, 1.0, 1.5, 2.5):
            assert _eval_mach_channels(channels, mach) == \
                mach_drag_multiplier(polar, mach)
