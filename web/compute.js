// War Thunder 飞行模型加速度计算 - 浏览器端实现
// 移植自 lib/compute.py + lib/schema.py 的 build_record
// 使用 War Thunder 官方 .blkx 推力字段 + 社区逆向阻力模型计算加速度

// ============================================================
// 物理常量与节点定义
// ============================================================
const G = 9.80665;              // 重力加速度 m/s^2
const R_AIR = 287.05;           // 空气气体常数 J/(kg·K)
const GAMMA = 1.4;              // 空气比热比
const T0 = 288.15;              // 海平面温度 K
const P0 = 101325.0;            // 海平面气压 Pa
const LAPSE_RATE = 0.0065;      // 对流层温度递减率 K/m
const TROPO_EXP = 5.2561;       // 对流层气压公式指数（≈ g/(R·L)）
const TROPOPAUSE_M = 11000.0;   // 对流层顶高度 m
const T_TROPO = T0 - LAPSE_RATE * TROPOPAUSE_M;            // 对流层顶温度 ≈ 216.65 K
const P_TROPO = P0 * Math.pow(T_TROPO / T0, TROPO_EXP);    // 对流层顶气压 Pa

// 推力系数网格节点（7 高度 × 12 速度）
const ALT_NODES = [0, 2000, 5000, 8000, 11000, 15000, 25000];                            // m
const VEL_NODES = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2400];     // km/h TAS
const N_ALT = ALT_NODES.length;   // 7
const N_VEL = VEL_NODES.length;   // 12

// ============================================================
// 1. ISA 大气模型
// ============================================================
function isaAtmosphere(altitudeM) {
  const h = float(altitudeM);
  let T, P;
  if (h <= TROPOPAUSE_M) {
    // 对流层
    T = T0 - LAPSE_RATE * h;
    P = P0 * Math.pow(T / T0, TROPO_EXP);
  } else {
    // 同温层（等温层）
    T = T_TROPO;
    P = P_TROPO * Math.exp(-G * (h - TROPOPAUSE_M) / (R_AIR * T));
  }
  const rho = P / (R_AIR * T);
  return [T, P, rho];
}

// ============================================================
// 2. 推力双线性插值
// ============================================================
function getThrustData(fm) {
  if (!isObject(fm)) return {};
  for (const key of ['EngineType0', 'EngineType', 'EngineType1']) {
    const eng = fm[key];
    if (isObject(eng)) {
      const main = eng.Main;
      if (isObject(main) && isObject(main.ThrustMax)) {
        return main.ThrustMax;
      }
    }
  }
  return {};
}

function countEngines(fm) {
  if (!isObject(fm)) return 1;
  let count = 0;
  for (let i = 0; i < 16; i++) {
    if (`Engine${i}` in fm) count++;
  }
  return Math.max(1, count);
}

function buildCoeffGrid(thrustData, fieldPrefix, defaultValue) {
  const grid = [];
  for (let a = 0; a < N_ALT; a++) {
    const row = new Array(N_VEL).fill(defaultValue);
    for (let v = 0; v < N_VEL; v++) {
      const val = thrustData[`${fieldPrefix}_${a}_${v}`];
      if (val != null) row[v] = float(val);
    }
    grid.push(row);
  }
  return grid;
}

function bilinearInterp(grid, xNodes, yNodes, x, y) {
  // 钳制到节点范围
  const xq = Math.min(Math.max(x, xNodes[0]), xNodes[xNodes.length - 1]);
  const yq = Math.min(Math.max(y, yNodes[0]), yNodes[yNodes.length - 1]);
  // 定位下端索引
  let xi = lowerBound(xNodes, xq) - 1;
  xi = Math.max(0, Math.min(xi, xNodes.length - 2));
  let yi = lowerBound(yNodes, yq) - 1;
  yi = Math.max(0, Math.min(yi, yNodes.length - 2));
  const x0 = xNodes[xi], x1 = xNodes[xi + 1];
  const y0 = yNodes[yi], y1 = yNodes[yi + 1];
  const fx = x1 > x0 ? (xq - x0) / (x1 - x0) : 0.0;
  const fy = y1 > y0 ? (yq - y0) / (y1 - y0) : 0.0;
  const q00 = grid[xi][yi];
  const q01 = grid[xi][yi + 1];
  const q10 = grid[xi + 1][yi];
  const q11 = grid[xi + 1][yi + 1];
  return q00 * (1 - fx) * (1 - fy)
       + q01 * (1 - fx) * fy
       + q10 * fx * (1 - fy)
       + q11 * fx * fy;
}

function interpolateThrust(fm, altM, velKmh, afterburner) {
  const thrustData = getThrustData(fm);
  const nEngines = countEngines(fm);
  const t0Kgf = float(thrustData.ThrustMax0 != null ? thrustData.ThrustMax0 : 0.0);
  const t0N = t0Kgf * G * nEngines;
  const coeff = buildCoeffGrid(thrustData, 'ThrustMaxCoeff', 0.0);
  const aft = buildCoeffGrid(thrustData, 'ThrAftMaxCoeff', 1.0);
  const c = bilinearInterp(coeff, ALT_NODES, VEL_NODES, altM, velKmh);
  const a = bilinearInterp(aft, ALT_NODES, VEL_NODES, altM, velKmh);
  const milN = t0N * c;
  const abN = milN * a;
  return [milN, abN];
}

// ============================================================
// 3. 马赫倍增器
// ============================================================
function machDragMultiplier(polar, mach) {
  const m = float(mach);
  const machFactor = float(polar.MachFactor != null ? polar.MachFactor : 3);
  let totalMult = 1.0;

  // WT FM 的马赫通道索引为 1-7
  for (let i = 1; i <= 7; i++) {
    let multMax = polar[`MultMachMax${i}`];
    multMax = float(multMax != null ? multMax : 1.0);

    // 跳过削减通道（MultMachMax < 1.0）
    if (multMax < 1.0) continue;

    const machCrit = float(polar[`MachCrit${i}`] != null ? polar[`MachCrit${i}`] : 0);
    const machMax = float(polar[`MachMax${i}`] != null ? polar[`MachMax${i}`] : 0);
    if (machCrit <= 0 || machMax <= 0) continue;

    const multLimit = float(polar[`MultLimit${i}`] != null ? polar[`MultLimit${i}`] : 1.0);
    const lineCoeff = float(polar[`MultLineCoeff${i}`] != null ? polar[`MultLineCoeff${i}`] : 0.0);

    // 跳过 LineCoeff > 0 的通道：原始公式产生负倍率
    if (lineCoeff > 0) continue;

    let mult;
    if (m < machCrit) {
      mult = 1.0;
    } else if (m <= machMax) {
      const denom = Math.max(machMax - machCrit, 1e-6);
      const t = (m - machCrit) / denom;
      mult = 1.0 + (multMax - 1.0) * Math.pow(t, machFactor);
    } else {  // m > machMax
      mult = multMax + (multLimit - multMax) * (1.0 - Math.exp(lineCoeff * (m - machMax)));
    }
    totalMult *= mult;
  }
  return totalMult;
}

// ============================================================
// 4. 阻力计算
// ============================================================
function sumAreas(areas) {
  if (areas == null) return 0.0;
  if (typeof areas === 'number') return float(areas);
  if (Array.isArray(areas)) {
    return areas.filter(v => typeof v === 'number').reduce((s, v) => s + float(v), 0.0);
  }
  if (isObject(areas)) {
    let s = 0.0;
    for (const k in areas) {
      if (typeof areas[k] === 'number') s += float(areas[k]);
    }
    return s;
  }
  return 0.0;
}

function extractDragComponents(fm) {
  const aero = fm.Aerodynamics;
  if (!isObject(aero)) return [];
  const comps = [];

  // 机翼
  const wingPlane = aero.WingPlane;
  if (isObject(wingPlane)) {
    const wingPolar = wingPlane.FlapsPolar0;
    if (isObject(wingPolar) && Object.keys(wingPolar).length > 0) {
      let area = sumAreas(wingPlane.Areas);
      if (area <= 0) area = float(wingPolar.Area != null ? wingPolar.Area : 0.0);
      comps.push([wingPolar, area]);
    }
  }

  // 机身 / 平尾 / 垂尾
  for (const planeKey of ['FuselagePlane', 'HorStabPlane', 'VerStabPlane']) {
    const plane = aero[planeKey];
    if (!isObject(plane)) continue;
    const polar = plane.Polar;
    if (isObject(polar) && Object.keys(polar).length > 0) {
      let area = sumAreas(plane.Areas);
      if (area <= 0) area = float(polar.Area != null ? polar.Area : 0.0);
      comps.push([polar, area]);
    }
  }
  return comps;
}

function getWingData(fm) {
  const aero = fm.Aerodynamics;
  if (!isObject(aero)) return [{}, 0.0, 0.0];
  const wingPlane = aero.WingPlane;
  if (!isObject(wingPlane)) return [{}, 0.0, 0.0];
  let wingPolar = wingPlane.FlapsPolar0;
  if (!isObject(wingPolar)) wingPolar = {};
  let area = sumAreas(wingPlane.Areas);
  if (area <= 0) area = float(wingPolar.Area != null ? wingPolar.Area : 0.0);
  const span = float(wingPlane.Span != null ? wingPlane.Span : 0.0);
  return [wingPolar, area, span];
}

function calculateDrag(fm, mach, tasMps, rho, massKg) {
  const q = 0.5 * rho * tasMps * tasMps;  // 动压

  // 寄生阻力：累加各部件
  let parasite = 0.0;
  for (const [polar, area] of extractDragComponents(fm)) {
    const cdMin = float(polar.CdMin != null ? polar.CdMin : 0.0);
    const cd = cdMin * machDragMultiplier(polar, mach);
    parasite += q * cd * area;
  }

  // 诱导阻力：使用机翼极曲线
  const [wingPolar, wingArea, wingSpan] = getWingData(fm);
  const e = isObject(wingPolar) ? float(wingPolar.OswaldsEfficiencyNumber != null ? wingPolar.OswaldsEfficiencyNumber : 0.75) : 0.75;

  // 展弦比 AR = Span² / S
  let ar;
  if (wingArea > 0 && wingSpan > 0) {
    ar = (wingSpan * wingSpan) / wingArea;
  } else {
    ar = 8.0;
  }

  // 升力系数 CL = m·g / (q·S)（平飞假设），上限 1.5
  let cl = 0.0;
  if (q > 0 && wingArea > 0) {
    cl = (massKg * G) / (q * wingArea);
    cl = Math.min(cl, 1.5);
  }

  let cdInduced = 0.0;
  if (e > 0 && ar > 0) {
    cdInduced = (cl * cl) / (Math.PI * ar * e);
  }
  const induced = q * wingArea * cdInduced;

  return Math.max(0.0, parasite + induced);
}

// ============================================================
// 5. 加速度网格
// ============================================================
function computeAccelGrid(fm, massKg, afterburner,
                          machMin = 0.1, machMax = 2.5, machStep = 0.05) {
  const altitudes = ALT_NODES.slice();
  const machs = [];
  for (let m = machMin; m <= machMax + 0.001; m += machStep) {
    machs.push(float(m));
  }

  const samples = [];
  for (const alt of altitudes) {
    const [T, _P, rho] = isaAtmosphere(alt);
    const aSound = Math.sqrt(GAMMA * R_AIR * T);
    for (const mach of machs) {
      const machF = float(mach);
      const tasMps = machF * aSound;
      const tasKmh = tasMps * 3.6;
      const [milN, abN] = interpolateThrust(fm, alt, tasKmh, afterburner);
      const dragN = calculateDrag(fm, machF, tasMps, rho, massKg);
      const thrustN = afterburner ? abN : milN;
      const netForceN = thrustN - dragN;
      const accelMps2 = massKg > 0 ? netForceN / massKg : 0.0;
      samples.push({
        altitude_m: alt,
        mach: machF,
        tas_mps: tasMps,
        thrust_mil_n: milN,
        thrust_ab_n: abN,
        drag_n: dragN,
        net_force_n: netForceN,
        accel_mps2: accelMps2,
      });
    }
  }

  const grid = { altitudes_m: altitudes, machs: machs };
  return [samples, grid];
}

// ============================================================
// 6. 最优计算
// ============================================================
function computeOptimal(samples, grid) {
  const altitudes = grid.altitudes_m || [];
  const machs = grid.machs || [];

  const byAlt = new Map();
  const byMach = new Map();
  for (const s of samples) {
    if (!byAlt.has(s.altitude_m)) byAlt.set(s.altitude_m, []);
    byAlt.get(s.altitude_m).push(s);
    if (!byMach.has(s.mach)) byMach.set(s.mach, []);
    byMach.get(s.mach).push(s);
  }

  const maxSpeedPerAlt = [];
  for (const alt of altitudes) {
    let bestMach = null, bestTasKmh = null;
    for (const s of (byAlt.get(alt) || [])) {
      if (s.accel_mps2 > 0) {
        if (bestMach === null || s.mach > bestMach) {
          bestMach = s.mach;
          bestTasKmh = s.tas_mps * 3.6;
        }
      }
    }
    maxSpeedPerAlt.push({ altitude_m: alt, mach_max: bestMach, tas_max_kmh: bestTasKmh });
  }

  const bestAltPerMach = [];
  for (const mach of machs) {
    let bestAlt = null, bestAccel = null;
    for (const s of (byMach.get(mach) || [])) {
      if (s.accel_mps2 > 0) {
        if (bestAccel === null || s.accel_mps2 > bestAccel) {
          bestAccel = s.accel_mps2;
          bestAlt = s.altitude_m;
        }
      }
    }
    if (bestAlt !== null) {
      bestAltPerMach.push({ mach: mach, best_alt_m: bestAlt, accel_mps2: bestAccel });
    }
  }

  return { max_speed_per_alt: maxSpeedPerAlt, best_alt_per_mach: bestAltPerMach };
}

// ============================================================
// 7. analyzeAircraft：完整分析入口（对应 build_record + compute_accel_grid + compute_optimal）
// ============================================================
function analyzeAircraft(aircraft, fm, params) {
  const afterburner = !!params.afterburner;
  const fuelPct = float(params.fuel_pct != null ? params.fuel_pct : 0.0);
  const wtFmVersion = typeof params.wt_fm_version === 'string' ? params.wt_fm_version : String(params.wt_fm_version || '');

  // 从 fm 提取质量信息
  let mass = {};
  if (isObject(fm) && isObject(fm.Mass)) mass = fm.Mass;
  const emptyMass = safeFloat(mass.EmptyMass, 0.0);
  const maxFuelMass = safeFloat(mass.MaxFuelMass0, 0.0);

  // 从 fm 提取 ThrustMax0（兼容命名变体）
  let thrustMax0Kgf = 0.0;
  if (isObject(fm)) {
    for (const key of ['EngineType0', 'EngineType', 'EngineType1']) {
      const eng = fm[key];
      if (!isObject(eng)) continue;
      const main = eng.Main;
      if (!isObject(main)) continue;
      const tm = main.ThrustMax;
      if (isObject(tm) && tm.ThrustMax0 != null) {
        const singleThrust = safeFloat(tm.ThrustMax0, 0.0);
        let nEngines = 0;
        for (let i = 0; i < 16; i++) {
          if (`Engine${i}` in fm) nEngines++;
        }
        nEngines = Math.max(1, nEngines);
        thrustMax0Kgf = singleThrust * nEngines;
        break;
      }
    }
  }

  // 计算衍生质量
  const fuelMassKg = fuelPct * maxFuelMass;
  const flightMassKg = emptyMass + fuelMassKg;

  // 计算加速度网格与最优剖面
  const [samples, grid] = computeAccelGrid(fm, flightMassKg, afterburner);
  const optimal = computeOptimal(samples, grid);

  // 北京时间（UTC+8）ISO 8601 字符串
  const computedAt = new Date(Date.now() + 8 * 3600 * 1000)
    .toISOString().replace('Z', '+08:00');

  return {
    aircraft: aircraft,
    metadata: {
      empty_mass_kg: emptyMass,
      fuel_mass_kg: fuelMassKg,
      flight_mass_kg: flightMassKg,
      afterburner: afterburner,
      thrust_max0_kgf: thrustMax0Kgf,
      computed_at: computedAt,
      wt_fm_version: wtFmVersion,
    },
    grid: grid,
    samples: samples,
    optimal: optimal,
  };
}

// ============================================================
// 辅助函数
// ============================================================
function float(v) { return typeof v === 'number' ? v : Number(v) || 0.0; }
function safeFloat(v, def) {
  if (v == null) return def;
  try {
    const f = float(v);
    if (!isFinite(f)) return def;
    return f;
  } catch (e) { return def; }
}
function isObject(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
// 二分查找：返回第一个 >= x 的位置
function lowerBound(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
