"""ISA 国际标准大气模型单元测试。"""

import math

import pytest

from lib.compute import (
    G,
    LAPSE_RATE,
    P0,
    R_AIR,
    T0,
    TROPOPAUSE_M,
    isa_atmosphere,
)

RHO_SEA = P0 / (R_AIR * T0)  # ≈ 1.2250


def test_sea_level():
    t, p, rho = isa_atmosphere(0.0)
    assert t == pytest.approx(T0, rel=1e-9)
    assert p == pytest.approx(P0, rel=1e-9)
    assert rho == pytest.approx(RHO_SEA, rel=1e-6)


def test_troposphere_pressure_formula():
    # 5000 m：T = 288.15 - 0.0065*5000，P 按幂律
    h = 5000.0
    t, p, _ = isa_atmosphere(h)
    expected_t = T0 - LAPSE_RATE * h
    expected_p = P0 * (expected_t / T0) ** 5.2561
    assert t == pytest.approx(expected_t, rel=1e-9)
    assert p == pytest.approx(expected_p, rel=1e-9)


def test_tropopause():
    # 公认值：11000 m → 216.65 K, 22632 Pa, 0.3639 kg/m³
    t, p, rho = isa_atmosphere(TROPOPAUSE_M)
    assert t == pytest.approx(216.65, rel=1e-6)
    assert p == pytest.approx(22632.1, rel=1e-4)
    assert rho == pytest.approx(0.36392, rel=1e-4)


def test_stratosphere_isothermal():
    # 20000 m：温度保持 216.65 K
    t, _, rho = isa_atmosphere(20000.0)
    assert t == pytest.approx(216.65, rel=1e-9)
    # 密度应继续下降
    _, _, rho_tropo = isa_atmosphere(TROPOPAUSE_M)
    assert rho < rho_tropo


def test_density_monotonic_decreasing():
    prev = math.inf
    for h in (0, 2000, 5000, 8000, 11000, 15000, 25000, 40000):
        _, _, rho = isa_atmosphere(h)
        assert rho < prev
        prev = rho


def test_stratosphere_pressure_exponential():
    # P(20000) = P(11000) · exp(-g·(h-11000)/(R·T))
    _, p, _ = isa_atmosphere(20000.0)
    _, p_tropo, _ = isa_atmosphere(TROPOPAUSE_M)
    expected = p_tropo * math.exp(-G * (20000.0 - TROPOPAUSE_M) / (R_AIR * 216.65))
    assert p == pytest.approx(expected, rel=1e-9)
