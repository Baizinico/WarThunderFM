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

// 推力系数插值网格节点（匹配 .blkx 数据格式：7 高度 × 12 速度）
const ALT_NODES = [0, 2000, 5000, 8000, 11000, 15000, 25000];                            // m
const VEL_NODES = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2400];     // km/h TAS
const N_ALT = ALT_NODES.length;   // 7
const N_VEL = VEL_NODES.length;   // 12

// 输出加速度网格的高度节点（可自定义粒度，独立于 .blkx 数据格式）
const OUTPUT_ALT_NODES = [0, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000, 15000];  // m

// ============================================================
// 0. UI 让步工具（让浏览器在计算间隙更新 DOM）
// ============================================================
function yieldToUI() {
  return new Promise(r => setTimeout(r, 0));
}

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

// --- 螺旋桨飞机推力常量 ---
const HP_TO_WATT = 745.7;          // 英美马力 → 瓦特
const ETA_PROP = 0.82;             // 巡航螺旋桨效率
const ETA_STATIC = 0.75;           // 静推力致动盘修正系数

function isPropAircraft(fm) {
  if (!isObject(fm)) return false;
  // 条件 1：有螺旋桨
  let hasPropeller = false;
  if (isObject(fm.PropellerType0) && Object.keys(fm.PropellerType0).length > 0) {
    hasPropeller = true;
  } else if (isObject(fm.Propeller0) && Object.keys(fm.Propeller0).length > 0) {
    hasPropeller = true;
  } else {
    for (let i = 0; i < 16; i++) {
      const eng = fm[`Engine${i}`];
      if (isObject(eng) && isObject(eng.Propellor) && Object.keys(eng.Propellor).length > 0) {
        hasPropeller = true;
        break;
      }
    }
  }
  if (!hasPropeller) return false;
  // 条件 2：缺少 ThrustMaxCoeff 网格（抽查 6 个节点）
  const thrustData = getThrustData(fm);
  const sampleNodes = [[0, 0], [0, 6], [3, 0], [3, 6], [6, 0], [6, 11]];
  for (const [a, v] of sampleNodes) {
    if (thrustData[`ThrustMaxCoeff_${a}_${v}`] != null) return false;
  }
  return true;
}

function findEngineDict(fm) {
  // 定位引擎定义字典（EngineType0 / EngineType / EngineType1 / Engine0...）
  for (const key of ['EngineType0', 'EngineType', 'EngineType1']) {
    const e = fm[key];
    if (isObject(e) && Object.keys(e).length > 0) return e;
  }
  for (let i = 0; i < 16; i++) {
    const e = fm[`Engine${i}`];
    if (isObject(e) && Object.keys(e).length > 0) return e;
  }
  return null;
}

function compileEnginePower(fm) {
  // 把多级增压器曲线预编译为纯数值数组，供逐高度快速求值。
  // stages 每项：[powerStage, altCrit, ceilingOrNull, powerAtCeiling, slope]
  const eng = findEngineDict(fm);
  if (eng === null) return { stages: [], basePower: 0.0 };

  const main = eng.Main || {};
  const basePower = float(main.Power != null ? main.Power : 0.0);

  const comp = eng.Compressor;
  if (!isObject(comp) || Object.keys(comp).length === 0) {
    return { stages: [], basePower };
  }

  const stages = [];
  for (let stage = 0; stage < 4; stage++) {
    const pkey = `Power${stage}`;
    if (comp[pkey] == null) continue;
    const powerStage = float(comp[pkey]);
    const altCrit = float(comp[`Altitude${stage}`] != null ? comp[`Altitude${stage}`] : 0.0);
    const ceilingRaw = comp[`Ceiling${stage}`];
    if (ceilingRaw == null || float(ceilingRaw) <= 0) {
      stages.push([powerStage, altCrit, null, 0.0, 0.0]);
      continue;
    }
    const ceiling = float(ceilingRaw);
    const powerAtCeiling = float(comp[`PowerAtCeiling${stage}`] != null
      ? comp[`PowerAtCeiling${stage}`] : powerStage * 0.5);
    const slope = (ceiling > altCrit && altCrit > 0)
      ? (powerStage - powerAtCeiling) / (ceiling - altCrit) : 0.0;
    stages.push([powerStage, altCrit, ceiling, powerAtCeiling, slope]);
  }
  return { stages, basePower };
}

function enginePowerFromCompiled(stages, basePower, altM) {
  if (stages.length === 0) return basePower;
  let bestPower = 0.0;
  for (const s of stages) {
    const powerStage = s[0], altCrit = s[1], ceiling = s[2];
    const powerAtCeiling = s[3], slope = s[4];
    let stagePower;
    if (ceiling === null) {
      if (altM <= altCrit || altCrit <= 0) {
        stagePower = powerStage;
      } else {
        const falloff = powerStage * 0.12 * Math.max(0.0, (altM - altCrit) / 1000.0);
        stagePower = Math.max(0.0, powerStage - falloff);
      }
    } else if (altM <= altCrit) {
      stagePower = powerStage;
    } else if (altM <= ceiling) {
      const frac = (altM - altCrit) / (ceiling - altCrit);
      stagePower = powerStage + frac * (powerAtCeiling - powerStage);
    } else {
      stagePower = Math.max(0.0, powerAtCeiling - slope * (altM - ceiling));
    }
    if (stagePower > bestPower) bestPower = stagePower;
  }
  return bestPower;
}

function getEnginePower(fm, altM) {
  // 逐点参考接口；网格计算使用 compileEnginePower 预编译后复用。
  const c = compileEnginePower(fm);
  return enginePowerFromCompiled(c.stages, c.basePower, altM);
}

function getPropRadius(fm) {
  // 路径 1：PropellerType0
  const pt0 = fm.PropellerType0;
  if (isObject(pt0)) {
    const geo = pt0.Geometry;
    if (isObject(geo) && geo.Radius != null) return float(geo.Radius);
  }

  // 路径 2：Propeller0
  const p0 = fm.Propeller0;
  if (isObject(p0)) {
    const geo = p0.Geometry;
    if (isObject(geo) && geo.Radius != null) return float(geo.Radius);
  }

  // 路径 3：Engine.Propellor.Diameter
  for (let i = 0; i < 16; i++) {
    const eng = fm[`Engine${i}`];
    if (isObject(eng)) {
      const prop = eng.Propellor;
      if (isObject(prop) && prop.Diameter != null) return float(prop.Diameter) / 2.0;
    }
  }

  // 路径 4：Propeller.Mass.Diameter
  for (let i = 0; i < 16; i++) {
    const p = fm[`Propeller${i}`];
    if (isObject(p)) {
      const mass = p.Mass;
      if (isObject(mass) && mass.Diameter != null) return float(mass.Diameter) / 2.0;
    }
  }

  // 路径 5：按功率估算 R ≈ 0.06 × P^0.25
  let power = 1000.0;
  let eng = null;
  for (const key of ['EngineType0', 'EngineType', 'EngineType1']) {
    const e = fm[key];
    if (isObject(e) && Object.keys(e).length > 0) { eng = e; break; }
  }
  if (eng === null) {
    for (let i = 0; i < 16; i++) {
      const e = fm[`Engine${i}`];
      if (isObject(e) && Object.keys(e).length > 0) { eng = e; break; }
    }
  }
  if (isObject(eng)) {
    const main = eng.Main;
    if (isObject(main) && main.Power != null) power = Math.max(power, float(main.Power));
  }
  return 0.06 * Math.pow(power, 0.25);
}

function propellerThrustArea(area, tasMps, rho, powerHp) {
  // 由螺旋桨盘面积与轴功率计算推力（N）。
  if (powerHp <= 0) return 0.0;

  const pWatts = powerHp * HP_TO_WATT;

  // 静推力（致动盘理论）：T = (2·rho·A·P^2)^(1/3) x eta_static
  const tStatic = Math.pow(2.0 * rho * area * pWatts * pWatts, 1.0 / 3.0) * ETA_STATIC;

  // 极低速 -> 静推力
  if (tasMps < 5.0) return tStatic;

  // 飞行推力：T = P x eta / V，钳制不超过静推力
  const tDynamic = pWatts * ETA_PROP / tasMps;
  return Math.min(tDynamic, tStatic);
}

function propellerThrust(fm, altM, tasMps, rho, powerHp) {
  // 逐点参考实现：由轴功率计算单台螺旋桨推力（N）。
  const radius = getPropRadius(fm);
  return propellerThrustArea(Math.PI * radius * radius, tasMps, rho, powerHp);
}

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

function getThrustAxes(thrustData) {
  const alts = [];
  let i = 0;
  while (`Altitude_${i}` in thrustData) {
    const v = thrustData[`Altitude_${i}`];
    if (typeof v === 'number' && !Number.isNaN(v)) alts.push(float(v));
    i++;
  }
  const vels = [];
  i = 0;
  while (`Velocity_${i}` in thrustData) {
    const v = thrustData[`Velocity_${i}`];
    if (typeof v === 'number' && !Number.isNaN(v)) vels.push(float(v));
    i++;
  }
  if (alts.length >= 2 && vels.length >= 2) return [alts, vels];
  return null;
}

function buildCoeffGrid(thrustData, fieldPrefix, defaultValue, nAlt = N_ALT, nVel = N_VEL) {
  const grid = [];
  for (let a = 0; a < nAlt; a++) {
    const row = new Array(nVel).fill(defaultValue);
    for (let v = 0; v < nVel; v++) {
      const val = thrustData[`${fieldPrefix}_${a}_${v}`];
      if (val != null) row[v] = float(val);
    }
    grid.push(row);
  }
  return grid;
}

function buildThrustTable(fm) {
  const thrustData = getThrustData(fm);
  if (Object.keys(thrustData).length === 0) return null;
  const axes = getThrustAxes(thrustData);
  let altNodes, velNodes;
  if (axes) {
    [altNodes, velNodes] = axes;
  } else {
    altNodes = ALT_NODES;
    velNodes = VEL_NODES;
  }
  const nAlt = altNodes.length, nVel = velNodes.length;
  const coeff = buildCoeffGrid(thrustData, 'ThrustMaxCoeff', 0.0, nAlt, nVel);
  const aft = buildCoeffGrid(thrustData, 'ThrAftMaxCoeff', 1.0, nAlt, nVel);
  return { altNodes, velNodes, coeff, aft };
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

function buildThrustModel(fm) {
  // 把 fm 的推力结构预编译为纯数值模型，供整网格逐点复用。
  if (isPropAircraft(fm)) {
    const cp = compileEnginePower(fm);
    const radius = getPropRadius(fm);
    return {
      kind: 'prop',
      nEngines: countEngines(fm),
      propArea: Math.PI * radius * radius,
      stages: cp.stages,
      basePower: cp.basePower,
    };
  }
  const thrustData = getThrustData(fm);
  const table = buildThrustTable(fm);
  const t0Kgf = float(thrustData.ThrustMax0 != null ? thrustData.ThrustMax0 : 0.0);
  return { kind: 'jet', t0N: t0Kgf * G * countEngines(fm), table };
}

function thrustFromModel(model, altM, velKmh, rho = null) {
  if (model.kind === 'prop') {
    const powerHp = enginePowerFromCompiled(model.stages, model.basePower, altM)
      * model.nEngines;
    if (rho == null) {
      const [_T, _P, r] = isaAtmosphere(altM);
      rho = r;
    }
    const thrustN = propellerThrustArea(model.propArea, velKmh / 3.6, rho, powerHp);
    // 螺旋桨无加力，军用和加力推力相同
    return [thrustN, thrustN];
  }

  const table = model.table;
  if (table == null) return [0.0, 0.0];
  const c = bilinearInterp(table.coeff, table.altNodes, table.velNodes, altM, velKmh);
  const a = bilinearInterp(table.aft, table.altNodes, table.velNodes, altM, velKmh);
  const milN = model.t0N * c;
  return [milN, milN * a];
}

function interpolateThrust(fm, altM, velKmh, afterburner, table = null) {
  // 逐点参考接口；网格计算请使用 buildThrustModel + thrustFromModel。
  let model = buildThrustModel(fm);
  if (table != null && model.kind === 'jet') {
    model = { kind: 'jet', t0N: model.t0N, table };
  }
  return thrustFromModel(model, altM, velKmh);
}

// ============================================================
// 3. 马赫倍增器
// ============================================================
function compileMachChannels(polar) {
  // 把一条极曲线的马赫倍增通道预编译为纯数值数组。
  // 编译期复现原逐点实现的 float 归一化与通道过滤，运行期只做算术。
  const channels = [];
  const machFactor = float(polar.MachFactor != null ? polar.MachFactor : 3);
  for (let i = 1; i <= 7; i++) {
    const multMax = float(polar[`MultMachMax${i}`] != null ? polar[`MultMachMax${i}`] : 1.0);
    // 跳过削减通道（MultMachMax < 1.0）
    if (multMax < 1.0) continue;
    const machCrit = float(polar[`MachCrit${i}`] != null ? polar[`MachCrit${i}`] : 0);
    const machMax = float(polar[`MachMax${i}`] != null ? polar[`MachMax${i}`] : 0);
    if (machCrit <= 0 || machMax <= 0) continue;
    const multLimit = float(polar[`MultLimit${i}`] != null ? polar[`MultLimit${i}`] : 1.0);
    const lineCoeff = float(polar[`MultLineCoeff${i}`] != null ? polar[`MultLineCoeff${i}`] : 0.0);
    // 跳过 LineCoeff > 0 的通道：原始公式产生负倍率
    if (lineCoeff > 0) continue;
    channels.push([multMax, machCrit, machMax, multLimit, lineCoeff, machFactor]);
  }
  return channels;
}

function evalMachChannels(channels, mach) {
  // 由预编译通道求马赫阻力倍增器（整网格计算的热路径）。
  const m = float(mach);
  let totalMult = 1.0;
  for (let k = 0; k < channels.length; k++) {
    const c = channels[k];
    const multMax = c[0], machCrit = c[1], machMax = c[2];
    const multLimit = c[3], lineCoeff = c[4], machFactor = c[5];
    let mult;
    if (m < machCrit) {
      mult = 1.0;
    } else if (m <= machMax) {
      const denom = Math.max(machMax - machCrit, 1e-6);
      const t = (m - machCrit) / denom;
      mult = 1.0 + (multMax - 1.0) * Math.pow(t, machFactor);
    } else {
      mult = multMax + (multLimit - multMax) * (1.0 - Math.exp(lineCoeff * (m - machMax)));
    }
    mult = Math.max(0.0, mult);
    totalMult *= mult;
    if (totalMult === 0.0) return 0.0;
  }
  return Math.max(0.0, totalMult);
}

function machDragMultiplier(polar, mach) {
  // 逐点参考接口；网格计算请使用 compileMachChannels + evalMachChannels。
  return evalMachChannels(compileMachChannels(polar), mach);
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

function flatWingArea(fm) {
  const areas = fm.Areas;
  if (!isObject(areas)) return 0.0;
  let total = 0.0;
  for (const k in areas) {
    if (k.startsWith('Wing') && typeof areas[k] === 'number') {
      total += float(areas[k]);
    }
  }
  return total;
}

function extractDragComponents(fm) {
  const aero = fm.Aerodynamics;
  if (!isObject(aero)) return [];
  const comps = [];

  // --- 机翼 ---
  const wingPlane = aero.WingPlane;
  if (isObject(wingPlane) && Object.keys(wingPlane).length > 0) {
    const wingPolar = wingPlane.FlapsPolar0;
    if (isObject(wingPolar) && Object.keys(wingPolar).length > 0) {
      let area = sumAreas(wingPlane.Areas);
      if (area <= 0) area = float(wingPolar.Area != null ? wingPolar.Area : 0.0);
      comps.push([wingPolar, area]);
    }
  }
  // 平坦格式机翼（NoFlaps 或 Wing）
  if (comps.length === 0) {
    for (const wingKey of ['NoFlaps', 'Wing']) {
      const wingPolar = aero[wingKey];
      if (isObject(wingPolar) && Object.keys(wingPolar).length > 0) {
        let area = sumAreas(aero.Areas);
        if (area <= 0) area = float(wingPolar.Area != null ? wingPolar.Area : 0.0);
        if (area <= 0) area = flatWingArea(fm);
        comps.push([wingPolar, area]);
        break;
      }
    }
  }

  // --- 机身 / 平尾 / 垂尾（嵌套格式优先）---
  let flatUsed = false;
  for (const planeKey of ['FuselagePlane', 'HorStabPlane', 'VerStabPlane']) {
    const plane = aero[planeKey];
    if (!isObject(plane)) continue;
    const polar = plane.Polar;
    if (isObject(polar) && Object.keys(polar).length > 0) {
      let area = sumAreas(plane.Areas);
      if (area <= 0) area = float(polar.Area != null ? polar.Area : 0.0);
      comps.push([polar, area]);
      flatUsed = true;
    }
  }

  // --- 平坦格式：Fuselage / Stab / Fin ---
  if (!flatUsed) {
    const areaPower = estimateAreaFromPower(fm);
    for (const subKey of ['Fuselage', 'Stab', 'Fin']) {
      const sub = aero[subKey];
      if (isObject(sub) && Object.keys(sub).length > 0) {
        let area = sumAreas(sub.Areas);
        if (area <= 0) area = float(sub.Area != null ? sub.Area : 0.0);
        if (area <= 0) area = areaPower * (subKey === 'Fuselage' ? 0.35 : 0.15);
        comps.push([sub, area]);
      }
    }
  }

  return comps;
}

function estimateAreaFromPower(fm) {
  const powerHp = getEnginePower(fm, 0.0);
  if (powerHp <= 0) return 15.0;
  return Math.max(10.0, 15.0 + (powerHp - 800.0) / 100.0);
}

function getWingData(fm) {
  const aero = fm.Aerodynamics;
  if (!isObject(aero)) return [{}, 0.0, 0.0];

  // 嵌套格式
  const wingPlane = aero.WingPlane;
  if (isObject(wingPlane) && Object.keys(wingPlane).length > 0) {
    let wingPolar = wingPlane.FlapsPolar0;
    if (!isObject(wingPolar)) wingPolar = {};
    let area = sumAreas(wingPlane.Areas);
    if (area <= 0) area = float(wingPolar.Area != null ? wingPolar.Area : 0.0);
    const span = float(wingPlane.Span != null ? wingPlane.Span : 0.0);
    if (area > 0 || span > 0) return [wingPolar, area, span];
  }

  // 平坦格式
  for (const wingKey of ['NoFlaps', 'Wing']) {
    const wingPolar = aero[wingKey];
    if (isObject(wingPolar) && Object.keys(wingPolar).length > 0) {
      let area = sumAreas(aero.Areas);
      if (area <= 0) area = float(wingPolar.Area != null ? wingPolar.Area : 0.0);
      if (area <= 0) area = flatWingArea(fm);
      let span = float(aero.Span != null ? aero.Span : 0.0);
      if (span <= 0) span = float(fm.Wingspan != null ? fm.Wingspan : 0.0);
      if (area <= 0) area = estimateAreaFromPower(fm);
      if (span <= 0 && area > 0) span = Math.sqrt(area * 6.0);
      return [wingPolar, area, span];
    }
  }

  // 完全兜底
  const area = estimateAreaFromPower(fm);
  const span = Math.sqrt(area * 6.0);
  return [{}, area, span];
}

function flatAircraftMachChannels(fm) {
  const aero = fm.Aerodynamics;
  if (!isObject(aero) || isObject(aero.WingPlane)) return {};
  const channels = {};
  for (const k in aero) {
    if (k.startsWith('Mach') || k.startsWith('Mult')) channels[k] = aero[k];
  }
  if (Object.keys(channels).some(k => k.startsWith('MachCrit'))) return channels;
  return {};
}

function flatFixedDragAreas(fm) {
  const aero = fm.Aerodynamics;
  if (!isObject(aero) || isObject(aero.WingPlane)) return 0.0;
  let total = 0.0;
  for (const key of ['RadiatorCd', 'OilRadiatorCd', 'CockpitDoorCd', 'FuseCd']) {
    const val = aero[key];
    if (typeof val === 'number') total += float(val);
  }
  return total;
}

function buildDragModel(fm) {
  // 把 fm 的阻力结构预编译为纯数值模型，供整网格逐点复用。
  const components = [];
  for (const [polar, area] of extractDragComponents(fm)) {
    const cdMin = float(polar.CdMin != null ? polar.CdMin : 0.0);
    components.push([cdMin, area, compileMachChannels(polar)]);
  }

  const aero = fm.Aerodynamics;
  const isFlat = isObject(aero) && !isObject(aero.WingPlane);
  const fixedArea = isFlat ? flatFixedDragAreas(fm) : 0.0;
  const aeroChannels = isFlat ? compileMachChannels(flatAircraftMachChannels(fm)) : [];

  // 机翼数据（用于诱导阻力）
  const [wingPolar, wingArea, wingSpan] = getWingData(fm);
  let e = isObject(wingPolar)
    ? float(wingPolar.OswaldsEfficiencyNumber != null
      ? wingPolar.OswaldsEfficiencyNumber : 0.75)
    : 0.75;
  if (e <= 0) e = 0.75;
  // 老格式：机翼 polar 无 e，取顶层 Aerodynamics 的整机 e
  if (!isObject(wingPolar) || wingPolar.OswaldsEfficiencyNumber == null
      || wingPolar.OswaldsEfficiencyNumber === 0) {
    if (isObject(aero)) {
      const eTop = aero.OswaldsEfficiencyNumber;
      if (typeof eTop === 'number' && eTop > 0) e = float(eTop);
    }
  }

  // 展弦比 AR = Span^2 / S
  const ar = (wingArea > 0 && wingSpan > 0) ? (wingSpan * wingSpan) / wingArea : 8.0;

  return { components, isFlat, fixedArea, aeroChannels, wingArea, ar, e };
}

function dragFromModel(model, mach, tasMps, rho, massKg) {
  const q = 0.5 * rho * tasMps * tasMps;
  const m = float(mach);

  // 寄生阻力：累加各部件
  let parasite = 0.0;
  for (const [cdMin, area, channels] of model.components) {
    const cd = cdMin * evalMachChannels(channels, m);
    parasite += q * cd * area;
  }

  // 老格式：整机马赫通道 x 全部寄生阻力，并计入固定阻力面积
  if (model.isFlat) {
    if (model.fixedArea > 0) parasite += q * model.fixedArea;
    parasite *= evalMachChannels(model.aeroChannels, m);
  }

  const wingArea = model.wingArea, e = model.e, ar = model.ar;

  // 升力系数 CL = m*g / (q*S)（平飞假设），上限 1.5
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

function calculateDrag(fm, mach, tasMps, rho, massKg) {
  // 逐点参考接口；网格计算请使用 buildDragModel + dragFromModel。
  return dragFromModel(buildDragModel(fm), mach, tasMps, rho, massKg);
}

// ============================================================
// 5. 加速度网格
// ============================================================
async function computeAccelGrid(fm, massKg, afterburner,
                          machMin = 0.1, machMax = 2.5, machStep = 0.05,
                          onProgress = null) {
  const altitudes = OUTPUT_ALT_NODES.slice();
  const machs = [];
  for (let m = machMin; m <= machMax + 0.001; m += machStep) {
    machs.push(float(m));
  }

  const samples = [];
  // 预编译一次，784 个网格点复用（避免逐点解析 fm）
  const dragModel = buildDragModel(fm);
  const thrustModel = buildThrustModel(fm);
  const totalAlts = altitudes.length;
  let lastYield = Date.now();
  for (let ai = 0; ai < totalAlts; ai++) {
    const alt = altitudes[ai];
    const [T, _P, rho] = isaAtmosphere(alt);
    const aSound = Math.sqrt(GAMMA * R_AIR * T);
    for (const mach of machs) {
      const machF = float(mach);
      const tasMps = machF * aSound;
      const tasKmh = tasMps * 3.6;
      const [milN, abN] = thrustFromModel(thrustModel, alt, tasKmh, rho);
      const dragN = dragFromModel(dragModel, machF, tasMps, rho, massKg);
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
    // 每完成一个高度层：报告进度值；按实际耗时自适应让步。
    // 计算很快时避免被固定次数的 setTimeout 开销拖慢；慢设备仍保持 UI 响应。
    if (onProgress) {
      onProgress(ai + 1, totalAlts);
    }
    if (Date.now() - lastYield >= 16 || ai === totalAlts - 1) {
      await yieldToUI();
      lastYield = Date.now();
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
// 7. 最佳爬升路线（基于剩余功率 SEP 的爬升速度程序）
// ============================================================
// 剩余功率（Specific Excess Power, SEP）= (T-D)·V / (m·g) = a·V / g
//   单位 m/s，即该状态下可达到的最大稳态爬升率。
// 机头向上角度 θ = arcsin(SEP / V) = arcsin(a / g)
//   单位 °，即稳定爬升时飞机纵轴与水平面的夹角。
// 最佳爬升路线：对每个高度，在 accel>0 的点中选取 SEP 最大的马赫数，
//   连接为一条「高度 → 最佳爬升马赫数」的速度程序曲线。
//   该曲线给出从海平面爬升到包线顶点应遵循的马赫数随高度变化规律。
function computeClimbRoute(samples, grid) {
  const altitudes = grid.altitudes_m || [];

  // 按高度分组
  const byAlt = new Map();
  for (const s of samples) {
    if (!byAlt.has(s.altitude_m)) byAlt.set(s.altitude_m, []);
    byAlt.get(s.altitude_m).push(s);
  }

  const route = [];
  for (const alt of altitudes) {
    let best = null;
    for (const s of (byAlt.get(alt) || [])) {
      if (s.accel_mps2 <= 0) continue;  // 仅在可加速区域选取
      const sep = s.tas_mps * s.accel_mps2 / G;  // m/s 爬升率
      if (best === null || sep > best.sep_mps) {
        // 机头向上角度：sin(θ) = SEP / V = a / g
        const angleRad = Math.asin(Math.min(s.accel_mps2 / G, 1.0));
        best = {
          altitude_m: alt,
          mach: s.mach,
          tas_kmh: s.tas_mps * 3.6,
          sep_mps: sep,
          climb_angle_deg: angleRad * 180.0 / Math.PI,
          accel_mps2: s.accel_mps2,
        };
      }
    }
    if (best !== null) route.push(best);
  }
  return route;
}

// ============================================================
// 8. analyzeAircraft：完整分析入口（对应 build_record + compute_accel_grid + compute_optimal）
// ============================================================
async function analyzeAircraft(aircraft, fm, params, onProgress = null) {
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

  // 计算加速度网格与最优剖面（传入进度回调）
  const [samples, grid] = await computeAccelGrid(fm, flightMassKg, afterburner,
                                                 0.1, 2.5, 0.05, onProgress);
  const optimal = computeOptimal(samples, grid);
  const climbRoute = computeClimbRoute(samples, grid);

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
    climb_route: climbRoute,
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
