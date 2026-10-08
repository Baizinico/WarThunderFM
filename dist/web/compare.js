// War Thunder 飞行模型对比 - 前端对比数据构建
// 与 lib/compare.py 逐字段等价（tests/test_compare_cross_js.py 用 Node.js 交叉验证），
// 修改任意一侧都必须同步另一侧。
//
// 输出结构（buildComparison 返回值）：
//   {
//     aircraft: ["j_10c", ...],          参与对比的机型名（顺序即表格列序）
//     generated_at: "…+08:00",           生成时间（北京时间）
//     metrics: [ {key,label,unit,decimals,higher_is_better} ... ],
//     radar_indicators: [ {key,label,unit} ... ],
//     entries: [ {name,nation,fuel_pct,payload_kg,flight_mass_kg,afterburner,
//                 metrics:{key:number|null}, radar:[number|null]} ... ],
//     best: { metric_key: [机型名...] },  各指标取得最优值的机型（并列全部列出）
//     profiles: [ {altitude_m, series:[{name,mach:[],accel_mps2:[]}]} ],
//     climb_routes: [ {name, altitude_m:[], mach:[], sep_mps:[]} ]
//   }

// ===== 指标定义（顺序即表格行序）=====
// higher_is_better=false 表示该指标越小越好（飞行质量）
const COMPARE_METRICS = [
  { key: 'flight_mass_kg', label: '飞行质量', unit: 'kg', decimals: 0, higher_is_better: false },
  { key: 'thrust_max0_kgf', label: '静推力', unit: 'kgf', decimals: 0, higher_is_better: true },
  { key: 'twr', label: '推重比', unit: '', decimals: 2, higher_is_better: true },
  { key: 'max_accel_mps2', label: '最大加速度', unit: 'm/s²', decimals: 2, higher_is_better: true },
  { key: 'max_climb_mps', label: '最大爬升率', unit: 'm/s', decimals: 1, higher_is_better: true },
  { key: 'ceiling_m', label: '实用升限', unit: 'm', decimals: 0, higher_is_better: true },
  { key: 'top_mach', label: '极速马赫', unit: 'Mach', decimals: 2, higher_is_better: true },
  { key: 'top_tas_kmh', label: '极速 TAS', unit: 'km/h', decimals: 0, higher_is_better: true }
];

// 雷达图使用的指标（均按「越大越好」归一化）
const RADAR_METRIC_KEYS = ['twr', 'max_accel_mps2', 'max_climb_mps', 'ceiling_m', 'top_mach', 'top_tas_kmh'];

// 「定高加速剖面」优先使用的高度层（m）；缺失时按网格均匀取样
const PROFILE_PREFERRED_ALTITUDES = [0, 5000, 10000, 15000];
// 剖面最多保留的高度层数
const PROFILE_MAX_LAYERS = 4;
// 一次性参与对比的最大机型数（受图表可读性限制）
const MAX_COMPARE_AIRCRAFT = 4;

// ===== 辅助函数（对应 lib/compare.py 中的 _cmp_* ）=====
/** 转为有限数值；null/undefined/bool/NaN/Inf/非数值 返回 null */
function cmpNumber(value) {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  if (typeof value !== 'number') return null;
  return isFinite(value) ? value : null;
}

/** 按 key 查找指标定义 */
function cmpMetricDef(key) {
  for (const m of COMPARE_METRICS) {
    if (m.key === key) return m;
  }
  return null;
}

// ===== 1. 单条记录 → 可对比指标 =====
/**
 * 从一条分析记录提取可对比指标。
 * 口径与元数据面板一致：最大加速度取网格峰值，爬升指标取最佳爬升路线，
 * 极速取 optimal.max_speed_per_alt 中平飞可加速的最高马赫及其 TAS。
 * @param {object} record analyzeAircraft 返回的记录
 * @returns {object} {metric_key: number|null}
 */
function computeCompareMetrics(record) {
  const metrics = {};
  const rec = (record && typeof record === 'object') ? record : {};
  const metadata = (rec.metadata && typeof rec.metadata === 'object') ? rec.metadata : {};

  const flightMass = cmpNumber(metadata.flight_mass_kg);
  const thrustKgf = cmpNumber(metadata.thrust_max0_kgf);
  metrics.flight_mass_kg = flightMass;
  metrics.thrust_max0_kgf = thrustKgf;
  metrics.twr = (flightMass !== null && flightMass > 0 && thrustKgf !== null)
    ? thrustKgf / flightMass
    : null;

  // 最大加速度：网格内峰值
  let maxAccel = null;
  const samples = Array.isArray(rec.samples) ? rec.samples : [];
  for (const s of samples) {
    if (!s || typeof s !== 'object') continue;
    const v = cmpNumber(s.accel_mps2);
    if (v === null) continue;
    if (maxAccel === null || v > maxAccel) maxAccel = v;
  }
  metrics.max_accel_mps2 = maxAccel;

  // 爬升：SEP 峰值 + 最高可用高度层
  let maxSep = null;
  let ceiling = null;
  const climbRoute = Array.isArray(rec.climb_route) ? rec.climb_route : [];
  for (const p of climbRoute) {
    if (!p || typeof p !== 'object') continue;
    const sep = cmpNumber(p.sep_mps);
    if (sep !== null && (maxSep === null || sep > maxSep)) maxSep = sep;
    const alt = cmpNumber(p.altitude_m);
    if (alt !== null && (ceiling === null || alt > ceiling)) ceiling = alt;
  }
  metrics.max_climb_mps = maxSep;
  metrics.ceiling_m = ceiling;

  // 极速：平飞可加速的最高马赫（及其 TAS）
  const optimal = (rec.optimal && typeof rec.optimal === 'object') ? rec.optimal : {};
  const rows = Array.isArray(optimal.max_speed_per_alt) ? optimal.max_speed_per_alt : [];
  let topMach = null;
  let topTas = null;
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    const mach = cmpNumber(row.mach_max);
    if (mach === null) continue;
    if (topMach === null || mach > topMach) {
      topMach = mach;
      topTas = cmpNumber(row.tas_max_kmh);
    }
  }
  metrics.top_mach = topMach;
  metrics.top_tas_kmh = topTas;

  return metrics;
}

// ===== 2. 剖面高度层选取 =====
/**
 * 选取定高加速剖面的高度层：优先命中 PROFILE_PREFERRED_ALTITUDES，
 * 命中不足 2 层时在网格上均匀取 PROFILE_MAX_LAYERS 层
 * （下标 = floor(i*(n-1)/3 + 0.5)，与 lib/compare.py 逐位一致）。
 * @param {number[]} altitudes 网格高度层
 * @returns {number[]} 选中的高度层（升序）
 */
function pickProfileAltitudes(altitudes) {
  const grid = [];
  for (const a of (altitudes || [])) {
    const v = cmpNumber(a);
    if (v !== null && grid.indexOf(v) < 0) grid.push(v);
  }
  if (grid.length === 0) return [];
  const picked = PROFILE_PREFERRED_ALTITUDES.filter(a => grid.indexOf(a) >= 0);
  if (picked.length >= 2) return picked.slice().sort((a, b) => a - b);

  const n = grid.length;
  if (n <= PROFILE_MAX_LAYERS) return grid.slice();
  const idx = [];
  for (let i = 0; i < PROFILE_MAX_LAYERS; i++) {
    const j = Math.floor(i * (n - 1) / 3 + 0.5);
    if (idx.indexOf(j) < 0) idx.push(j);
  }
  return idx.map(j => grid[j]).sort((a, b) => a - b)
    .filter((v, i, arr) => arr.indexOf(v) === i);
}

// ===== 3. 指标归一化（雷达图）=====
/**
 * 把一组指标值归一化到 0-100。
 * - 仅用非 null 值确定上下界，null 保持 null；
 * - 全部相等（或只有一个有效值）时有效值记为 100；
 * - higherIsBetter=false 时取反（越小越好）。
 * @param {Array<number|null>} values 指标值
 * @param {boolean} higherIsBetter 是否越大越好
 * @returns {Array<number|null>} 0-100 的分数
 */
function normalizeMetric(values, higherIsBetter = true) {
  const list = values || [];
  const present = list.filter(v => v !== null && v !== undefined);
  if (present.length === 0) return list.map(() => null);
  const lo = Math.min(...present);
  const hi = Math.max(...present);
  return list.map(v => {
    if (v === null || v === undefined) return null;
    if (hi === lo) return 100;
    let t = (v - lo) / (hi - lo);
    if (!higherIsBetter) t = 1 - t;
    return t * 100;
  });
}

/** 北京时间（UTC+8）ISO 8601 字符串 */
function cmpBeijingNowIso() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().replace('Z', '+08:00');
}

// ===== 4. buildComparison =====
/**
 * 把多架飞机的分析记录组装为完整对比数据。
 * @param {Array<object>} records 分析记录；可附带 nation / fuel_pct / payload_kg
 * @returns {object} 对比数据（见文件头注释）
 */
function buildComparison(records) {
  const list = (records || []).filter(r => r && typeof r === 'object');

  const entries = list.map(record => {
    const metadata = (record.metadata && typeof record.metadata === 'object') ? record.metadata : {};
    const name = (typeof record.aircraft === 'string' && record.aircraft) ? record.aircraft : 'unknown';
    return {
      name: name,
      nation: typeof record.nation === 'string' ? record.nation : '',
      fuel_pct: cmpNumber(record.fuel_pct),
      payload_kg: cmpNumber(record.payload_kg),
      flight_mass_kg: cmpNumber(metadata.flight_mass_kg),
      afterburner: !!metadata.afterburner,
      metrics: computeCompareMetrics(record),
      radar: []
    };
  });

  // ---- 最优值判定（并列时列出全部机型）----
  const best = {};
  for (const m of COMPARE_METRICS) {
    const key = m.key;
    const candidates = [];
    for (const e of entries) {
      const v = e.metrics[key];
      if (v === null || v === undefined) continue;
      candidates.push([e.name, v]);
    }
    if (candidates.length === 0) { best[key] = []; continue; }
    const values = candidates.map(c => c[1]);
    const target = m.higher_is_better ? Math.max(...values) : Math.min(...values);
    best[key] = candidates.filter(c => c[1] === target).map(c => c[0]);
  }

  // ---- 雷达图：逐指标在本次对比集合内归一化 ----
  const radarIndicators = [];
  const radarColumns = [];
  for (const key of RADAR_METRIC_KEYS) {
    const def = cmpMetricDef(key);
    if (!def) continue;
    radarIndicators.push({ key: def.key, label: def.label, unit: def.unit });
    radarColumns.push(normalizeMetric(entries.map(e => e.metrics[key]), def.higher_is_better));
  }
  entries.forEach((e, i) => {
    e.radar = radarColumns.map(col => col[i]);
  });

  // ---- 定高加速剖面 ----
  const altitudeSource = [];
  for (const record of list) {
    const grid = (record.grid && typeof record.grid === 'object') ? record.grid : {};
    const alts = Array.isArray(grid.altitudes_m) ? grid.altitudes_m : [];
    for (const a of alts) {
      const v = cmpNumber(a);
      if (v !== null && altitudeSource.indexOf(v) < 0) altitudeSource.push(v);
    }
  }
  altitudeSource.sort((a, b) => a - b);
  const profileAlts = pickProfileAltitudes(altitudeSource);

  const profiles = profileAlts.map(alt => {
    const series = list.map(record => {
      const name = (typeof record.aircraft === 'string' && record.aircraft) ? record.aircraft : 'unknown';
      const machs = [];
      const accels = [];
      const samples = Array.isArray(record.samples) ? record.samples : [];
      for (const s of samples) {
        if (!s || typeof s !== 'object') continue;
        if (cmpNumber(s.altitude_m) !== alt) continue;
        const mach = cmpNumber(s.mach);
        if (mach === null) continue;
        machs.push(mach);
        accels.push(cmpNumber(s.accel_mps2));
      }
      return { name: name, mach: machs, accel_mps2: accels };
    });
    return { altitude_m: alt, series: series };
  });

  // ---- 最佳爬升路线（叠加用）----
  const climbRoutes = list.map(record => {
    const name = (typeof record.aircraft === 'string' && record.aircraft) ? record.aircraft : 'unknown';
    const alts = [];
    const machs = [];
    const seps = [];
    const route = Array.isArray(record.climb_route) ? record.climb_route : [];
    for (const p of route) {
      if (!p || typeof p !== 'object') continue;
      const alt = cmpNumber(p.altitude_m);
      const mach = cmpNumber(p.mach);
      if (alt === null || mach === null) continue;
      alts.push(alt);
      machs.push(mach);
      seps.push(cmpNumber(p.sep_mps));
    }
    return { name: name, altitude_m: alts, mach: machs, sep_mps: seps };
  });

  return {
    aircraft: entries.map(e => e.name),
    generated_at: cmpBeijingNowIso(),
    metrics: COMPARE_METRICS.map(m => Object.assign({}, m)),
    radar_indicators: radarIndicators,
    entries: entries,
    best: best,
    profiles: profiles,
    climb_routes: climbRoutes
  };
}
