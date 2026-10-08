// War Thunder 飞行模型 3D 加速度分析 - 前端逻辑
// 依赖：Plotly.js（懒加载，仅在首次渲染 3D 曲面时从 CDN 动态加载）

// ===== 全局变量 =====
let currentData = null;         // 当前加载的数据
let currentMatrix = null;       // 当前 Z 矩阵（供悬停查询）
let currentDatasets = [];       // 全部数据集（来自 manifest）
let currentNations = [];        // 国家分组列表（来自 manifest）
let currentNationFilter = '__all__';  // 当前国家筛选
let currentAircraftList = [];   // 当前筛选下的飞机列表（供搜索过滤）
let highlightedIndex = -1;      // 下拉列表中当前高亮项索引
let renderToken = 0;            // 渲染竞态令牌（丢弃过时的 Plotly 渲染）
let renderQueue = Promise.resolve();  // 渲染队列（串行化，避免并发 WebGL 操作）
let plotlyPromise = null;       // Plotly.js 懒加载 Promise（首次渲染 3D 时才加载）
let currentFuelPct = 0.5;       // 当前燃油比例（0.30-1.00，由滑动条控制）
let currentPayloadKg = 0;       // 当前挂载质量 kg（由数字输入框控制）
let currentFm = null;           // 当前飞机的原始 .blkx 数据（供燃油调整时重算）
let currentAircraftName = null; // 当前飞机代号
let currentAircraftNation = null;  // 当前飞机国家

// 主题色（与 style.css 中的 CSS 变量保持一致）
const COLOR_ACCENT = '#ff8b4d';   // 橙色强调（高加速度）
const COLOR_BLUE = '#4ec5f1';     // 冷色低值（低/负加速度）
const COLOR_CREAM = '#f7ece1';    // 中性暖白（零加速度）
const COLOR_GREEN = '#8fd07a';    // 爬升路线绿
const COLOR_TEXT = '#eaf2fb';     // 主文字
const COLOR_TEXT_DIM = '#9fb0c3'; // 次要文字
const COLOR_GRID = 'rgba(148,170,196,0.16)';   // 网格线
const COLOR_AXIS_BG = 'rgba(8,12,17,0.55)';    // 坐标轴背景
const FONT_UI = "'Inter', system-ui, -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif";
const FONT_MONO = "'JetBrains Mono', ui-monospace, Consolas, monospace";
// 色阶：仅显示加速度 ≥ 0 的区域
//   暖白(零加速) → 浅橙 → 橙(中等加速) → 深橙红(强加速)
// 负加速度区域通过 z=null 过滤，不渲染曲面
const COLORSCALE = [
  [0.00, COLOR_CREAM],
  [0.35, '#f3ab7c'],
  [0.65, COLOR_ACCENT],
  [1.00, '#c2461f']
];
// 色阶映射范围：0 m/s² 到 6 m/s²（典型最大加速度）
const COLOR_MIN = 0;
const COLOR_MAX = 6;

// ===== 1. 状态栏更新 =====
/**
 * 更新顶部状态指示灯。
 * @param {string} msg 显示文案
 * @param {boolean} isError 是否为错误状态（等价于 state='error'）
 * @param {'idle'|'busy'|'ready'|'error'} [state] 指示灯状态，省略时按 isError 推断
 */
function setStatus(msg, isError = false, state) {
  const bar = document.getElementById('status-bar');
  if (!bar) return;
  const textEl = bar.querySelector('.status-text');
  if (textEl) textEl.textContent = msg;
  else bar.textContent = msg;
  bar.dataset.state = state || (isError ? 'error' : 'idle');
  bar.classList.toggle('error', !!isError);
}

// ===== 1.5 进度条控制 =====
function showProgress(label) {
  const container = document.getElementById('compute-progress');
  const bar = document.getElementById('progress-bar');
  const lbl = document.getElementById('progress-label');
  if (!container || !bar) return;
  container.style.display = 'flex';
  bar.value = 0;
  if (lbl && label) lbl.textContent = label;
}

function updateProgress(done, total) {
  const bar = document.getElementById('progress-bar');
  const lbl = document.getElementById('progress-label');
  if (!bar) return;
  bar.value = total > 0 ? done / total : 0;
  if (lbl) lbl.textContent = `计算加速度网格... (${done}/${total})`;
}

function hideProgress() {
  const container = document.getElementById('compute-progress');
  if (!container) return;
  container.style.display = 'none';
}

// ===== 2a. 填充国家筛选器 =====
function populateNationSelect(nations) {
  const sel = document.getElementById('nation-select');
  if (!sel) return;
  sel.innerHTML = '';
  // "全部" 选项
  const allOpt = document.createElement('option');
  allOpt.value = '__all__';
  allOpt.textContent = `全部 (${nations.reduce((s, n) => s + n.count, 0)})`;
  sel.appendChild(allOpt);
  // 各国家
  nations.forEach(n => {
    const opt = document.createElement('option');
    opt.value = n.code;
    opt.textContent = `${n.label} (${n.count})`;
    sel.appendChild(opt);
  });
}

// ===== 2b. 飞机搜索框 + 下拉列表（支持模糊搜索） =====

// 单次渲染下拉列表的最大项数：超过此值时只渲染前 N 项并提示用户细化搜索，
// 避免一次性创建上千个 DOM 节点导致页面卡顿。
const MAX_DROPDOWN_ITEMS = 100;

/** 更新当前国家筛选下的飞机列表（不渲染 DOM，只更新数据） */
function updateAircraftList(datasets, nations, nationCode) {
  currentNationFilter = nationCode;
  currentAircraftList = nationCode === '__all__'
    ? datasets.slice()
    : datasets.filter(ds => ds.nation === nationCode);
  // 清空搜索框，但不主动渲染下拉（延迟到用户聚焦搜索框时才渲染，避免初始化慢）
  const searchInput = document.getElementById('aircraft-search');
  if (searchInput) searchInput.value = '';
  // 清空下拉列表（若已显示），等用户聚焦时再渲染
  const dropdown = document.getElementById('aircraft-dropdown');
  if (dropdown) dropdown.innerHTML = '';
}

/** 查找国家标签 */
function getNationLabel(code) {
  const n = currentNations.find(x => x.code === code);
  return n ? n.label : code;
}

/**
 * 渲染下拉列表：根据搜索词过滤飞机并按国家分组显示。
 * 搜索时连字符（-）与下划线（_）等价，且忽略分隔符差异，
 * 例如 "f-16" 可匹配 "f_16a"，"mig21" 可匹配 "mig-21"。
 * @param {string} query 搜索词。空字符串表示显示全部。
 */
function renderAircraftDropdown(query) {
  const dropdown = document.getElementById('aircraft-dropdown');
  if (!dropdown) return;
  dropdown.innerHTML = '';
  highlightedIndex = -1;

  const qRaw = (query || '').trim();
  const q = qRaw.toLowerCase();
  // 归一化：移除 - 和 _ 用于模糊匹配
  const qNorm = q.replace(/[-_]/g, '');
  // 过滤匹配的飞机
  const matched = q === ''
    ? currentAircraftList
    : currentAircraftList.filter(ds => {
        const nameNorm = ds.name.toLowerCase().replace(/[-_]/g, '');
        // 同时支持归一化匹配和原始子串匹配
        return nameNorm.includes(qNorm) || ds.name.toLowerCase().includes(q);
      });

  if (matched.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'ac-empty';
    empty.textContent = `未找到匹配 "${query}" 的飞机`;
    dropdown.appendChild(empty);
    return;
  }

  // 按国家分组（与原 optgroup 行为一致）
  const groups = new Map();
  matched.forEach(ds => {
    if (!groups.has(ds.nation)) groups.set(ds.nation, []);
    groups.get(ds.nation).push(ds);
  });

  // 按当前 nations 顺序输出，"other" 放最后
  // 分页限制：单次最多渲染 MAX_DROPDOWN_ITEMS 项，超出部分提示用户细化搜索
  let renderedCount = 0;
  const truncated = matched.length > MAX_DROPDOWN_ITEMS;
  const orderedCodes = currentNations.map(n => n.code).concat(['other']);
  orderedCodes.forEach(code => {
    const list = groups.get(code);
    if (!list || list.length === 0) return;
    // 计算本组可渲染数量（受全局上限约束）
    const remain = MAX_DROPDOWN_ITEMS - renderedCount;
    if (remain <= 0) return;
    const showCount = Math.min(list.length, remain);
    // 分组标题
    const header = document.createElement('div');
    header.className = 'ac-group-header';
    header.textContent = `${getNationLabel(code)} (${list.length})`;
    dropdown.appendChild(header);
    // 选项（仅渲染前 showCount 个）
    for (let i = 0; i < showCount; i++) {
      const ds = list[i];
      const item = document.createElement('div');
      item.className = 'ac-option';
      item.setAttribute('data-path', ds.path);
      item.setAttribute('data-name', ds.name);
      item.setAttribute('data-nation', ds.nation);
      item.setAttribute('role', 'option');
      // 高亮匹配子串（基于归一化匹配，映射回原字符串位置）
      if (q !== '') {
        const html = highlightMatch(ds.name, q);
        item.innerHTML = html;
      } else {
        item.textContent = ds.name;
      }
      item.addEventListener('mousedown', (e) => {
        e.preventDefault();  // 防止输入框失焦
        selectAircraft(ds);
      });
      dropdown.appendChild(item);
      renderedCount++;
    }
  });

  // 若结果被截断，在末尾显示提示，引导用户细化搜索
  if (truncated) {
    const more = document.createElement('div');
    more.className = 'ac-truncated';
    more.textContent = `仅显示前 ${MAX_DROPDOWN_ITEMS} 项（共 ${matched.length} 项），请输入更具体的关键词以缩小范围`;
    dropdown.appendChild(more);
  }
}

/**
 * 高亮飞机代号中匹配搜索词的子串。
 * 归一化匹配（忽略 - 和 _ 差异），将匹配范围映射回原字符串并高亮。
 * @param {string} name 飞机代号（原样）
 * @param {string} query 搜索词（小写）
 * @returns {string} 带 <span class="ac-match"> 的 HTML
 */
function highlightMatch(name, query) {
  const qNorm = query.replace(/[-_]/g, '');
  const nameLower = name.toLowerCase();
  const nameNorm = nameLower.replace(/[-_]/g, '');
  const normIdx = nameNorm.indexOf(qNorm);
  if (normIdx < 0) return name;
  // 把归一化字符串中的索引映射回原字符串的位置
  let count = 0;
  let origStart = -1;
  let origEnd = -1;
  for (let i = 0; i < nameLower.length; i++) {
    const c = nameLower[i];
    if (c === '-' || c === '_') continue;
    if (count === normIdx) origStart = i;
    if (count === normIdx + qNorm.length - 1) {
      origEnd = i + 1;
      break;
    }
    count++;
  }
  if (origStart < 0) return name;
  return name.substring(0, origStart) +
    '<span class="ac-match">' + name.substring(origStart, origEnd) + '</span>' +
    name.substring(origEnd);
}

/** 选中一架飞机：更新搜索框文字、关闭下拉、加载数据 */
function selectAircraft(ds) {
  const searchInput = document.getElementById('aircraft-search');
  if (searchInput) {
    searchInput.value = ds.name;
  }
  hideDropdown();
  loadAircraft(ds.name, ds.path, ds.nation);
}

/** 显示下拉列表 */
function showDropdown() {
  const dropdown = document.getElementById('aircraft-dropdown');
  if (dropdown) dropdown.classList.add('show');
}

/** 隐藏下拉列表 */
function hideDropdown() {
  const dropdown = document.getElementById('aircraft-dropdown');
  if (dropdown) dropdown.classList.remove('show');
  highlightedIndex = -1;
}

/** 获取当前下拉中所有可选项 */
function getDropdownOptions() {
  const dropdown = document.getElementById('aircraft-dropdown');
  if (!dropdown) return [];
  return Array.from(dropdown.querySelectorAll('.ac-option'));
}

/** 高亮指定索引的选项 */
function highlightOption(idx) {
  const opts = getDropdownOptions();
  if (opts.length === 0) return;
  opts.forEach(o => o.classList.remove('highlighted'));
  if (idx >= 0 && idx < opts.length) {
    opts[idx].classList.add('highlighted');
    // 确保高亮项可见
    opts[idx].scrollIntoView({ block: 'nearest' });
    highlightedIndex = idx;
  } else {
    highlightedIndex = -1;
  }
}

/** 初始化搜索框事件 */
function initAircraftSearch() {
  const searchInput = document.getElementById('aircraft-search');
  const dropdown = document.getElementById('aircraft-dropdown');
  if (!searchInput || !dropdown) return;

  // 输入时过滤
  searchInput.addEventListener('input', () => {
    renderAircraftDropdown(searchInput.value);
    showDropdown();
  });

  // 聚焦时显示下拉
  searchInput.addEventListener('focus', () => {
    renderAircraftDropdown(searchInput.value);
    showDropdown();
  });

  // 点击时也显示下拉（确保鼠标点击触发）
  searchInput.addEventListener('click', () => {
    renderAircraftDropdown(searchInput.value);
    showDropdown();
  });

  // 失焦时延迟关闭（让 mousedown 事件先触发）
  searchInput.addEventListener('blur', () => {
    setTimeout(hideDropdown, 150);
  });

  // 键盘导航：上下箭头选择，回车确认，Esc 关闭
  searchInput.addEventListener('keydown', (e) => {
    const opts = getDropdownOptions();
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = highlightedIndex < opts.length - 1 ? highlightedIndex + 1 : 0;
      highlightOption(next);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = highlightedIndex > 0 ? highlightedIndex - 1 : opts.length - 1;
      highlightOption(prev);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (highlightedIndex >= 0 && highlightedIndex < opts.length) {
        const opt = opts[highlightedIndex];
        const ds = currentDatasets.find(d => d.path === opt.getAttribute('data-path'));
        if (ds) selectAircraft(ds);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hideDropdown();
    }
  });
}

// ===== 3. 渲染元数据卡片 =====
// 卡片图标（内联 SVG，24×24 视框，线条由 CSS 统一设色）
const META_ICONS = {
  plane: '<path d="M3 11l18-8-8 18-2-7-8-3z"/>',
  mass: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7"/>',
  fuel: '<path d="M12 3.5c3 3.9 5.5 6.6 5.5 9.5a5.5 5.5 0 1 1-11 0c0-2.9 2.5-5.6 5.5-9.5z"/>',
  payload: '<path d="M12 3v9m0 0 3.5-3.5M12 12 8.5 8.5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  thrust: '<path d="M12 22c4 0 6-2.9 6-6.2C18 11.5 12 2 12 2S6 11.5 6 15.8C6 19.1 8 22 12 22z"/><path d="M12 18.5c1.3 0 2-1.1 2-2.3 0-1.3-2-3.7-2-3.7s-2 2.4-2 3.7c0 1.2.7 2.3 2 2.3z"/>',
  gauge: '<path d="M4.5 19a9 9 0 1 1 15 0"/><path d="M12 15.5 15.5 10"/><circle cx="12" cy="16.5" r="1.6"/>',
  climb: '<path d="M3 18l5.5-6 4 3.5L21 6"/><path d="M21 11V6h-5"/>',
  ceiling: '<path d="M4 5h16"/><path d="M12 20V9"/><path d="m7.5 13.5 4.5-4.5 4.5 4.5"/>',
  speed: '<path d="M4 9h9a2.5 2.5 0 1 0-2.5-2.5"/><path d="M3 13h13a2.5 2.5 0 1 1-2.5 2.5"/><path d="M5 17h5"/>'
};

/** 生成单个元数据卡片 HTML */
function metaCard({ label, value, sub, icon, tone, className }) {
  const iconSvg = icon && META_ICONS[icon]
    ? `<svg class="meta-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${META_ICONS[icon]}</svg>`
    : '';
  return `<div class="meta-item${className ? ' ' + className : ''}"${tone ? ` style="--tone:${tone}"` : ''}>` +
    `<div class="meta-label">${iconSvg}${label}</div>` +
    `<div class="meta-value">${value}</div>` +
    (sub ? `<div class="meta-sub">${sub}</div>` : '') +
    `</div>`;
}

/**
 * 渲染参数面板：平台参数（质量/推力）+ 性能包线（加速度/爬升/升限/极速）。
 * @param {object} metadata analyzeAircraft 返回的 metadata
 * @param {string} nation 国家代码
 * @param {object} [data] 完整分析结果，用于提取性能包线指标
 */
function renderMetadata(metadata, nation, data) {
  const panel = document.getElementById('metadata-panel');
  if (!panel) return;
  if (!metadata) {
    panel.innerHTML = '';
    return;
  }
  const fmtNum = v => (v === undefined || v === null) ? '—' : Number(v).toLocaleString('zh-CN');
  const fmt1 = v => (v === undefined || v === null || !isFinite(v)) ? '—' : Number(v).toFixed(1);
  const fmt2 = v => (v === undefined || v === null || !isFinite(v)) ? '—' : Number(v).toFixed(2);
  const kg = v => (v === undefined || v === null) ? '—' : `${fmtNum(v)} kg`;

  // ---- 性能包线：由 samples / climb_route / optimal 提取关键指标 ----
  const samples = (data && data.samples) || [];
  const climbRoute = (data && data.climb_route) || [];
  let maxAccel = null;
  for (const s of samples) {
    if (s.accel_mps2 != null && (maxAccel === null || s.accel_mps2 > maxAccel)) maxAccel = s.accel_mps2;
  }
  let maxSep = null, ceiling = null;
  for (const p of climbRoute) {
    if (p.sep_mps != null && (maxSep === null || p.sep_mps > maxSep)) maxSep = p.sep_mps;
    if (p.altitude_m != null && (ceiling === null || p.altitude_m > ceiling)) ceiling = p.altitude_m;
  }
  let topMach = null, topTas = null;
  const maxSpeedPerAlt = (data && data.optimal && data.optimal.max_speed_per_alt) || [];
  for (const row of maxSpeedPerAlt) {
    if (row.mach_max != null && (topMach === null || row.mach_max > topMach)) {
      topMach = row.mach_max;
      topTas = row.tas_max_kmh;
    }
  }

  const nationLabel = nation ? getNationLabel(nation) : '';
  const identity = metaCard({
    label: '机型',
    value: `${currentAircraftName ? currentAircraftName.toUpperCase() : '—'}` +
      (nationLabel ? `<span class="meta-chip">${nationLabel}</span>` : ''),
    sub: `飞行质量 ${fmtNum(metadata.flight_mass_kg)} kg · 燃油 ${Math.round(currentFuelPct * 100)}%`,
    icon: 'plane',
    className: 'meta-item-identity'
  });

  const platformCards = [
    identity,
    metaCard({ label: '空重', value: kg(metadata.empty_mass_kg), sub: '机体 + 固定设备', icon: 'mass', tone: '#9fb0c3' }),
    metaCard({ label: '燃油质量', value: kg(metadata.fuel_mass_kg), sub: `${Math.round(currentFuelPct * 100)}% 内油`, icon: 'fuel', tone: '#4ec5f1' }),
    metaCard({ label: '挂载质量', value: kg(currentPayloadKg), sub: '外挂载荷', icon: 'payload', tone: '#ffab76' }),
    metaCard({ label: '飞行质量', value: kg(metadata.flight_mass_kg), sub: '含燃油与挂载', icon: 'gauge', tone: '#ff8b4d' }),
    metaCard({
      label: '加力推力',
      value: metadata.thrust_max0_kgf ? `${fmtNum(metadata.thrust_max0_kgf)} kgf` : '—',
      sub: metadata.afterburner === false ? '军用推力' : '全加力静推力',
      icon: 'thrust',
      tone: '#ff8b4d'
    })
  ].join('');

  const envelopeCards = [
    metaCard({ label: '最大加速度', value: maxAccel == null ? '—' : `${fmt2(maxAccel)} m/s²`, sub: '网格内峰值', icon: 'gauge', tone: '#ff8b4d' }),
    metaCard({ label: '最大爬升率', value: maxSep == null ? '—' : `${fmt1(maxSep)} m/s`, sub: 'SEP 峰值', icon: 'climb', tone: '#8fd07a' }),
    metaCard({ label: '实用升限', value: ceiling == null ? '—' : `${fmtNum(ceiling)} m`, sub: 'SEP > 0 的最高层', icon: 'ceiling', tone: '#4ec5f1' }),
    metaCard({
      label: '极速',
      value: topMach == null ? '—' : `Mach ${fmt2(topMach)}`,
      sub: topTas == null ? '平飞可加速上限' : `TAS ${fmtNum(Math.round(topTas))} km/h`,
      icon: 'speed',
      tone: '#ffab76'
    })
  ].join('');

  panel.innerHTML =
    `<div class="meta-section">` +
      `<h3 class="meta-section-title">平台参数</h3>` +
      `<div class="meta-grid">${platformCards}</div>` +
    `</div>` +
    `<div class="meta-section">` +
      `<h3 class="meta-section-title">性能包线</h3>` +
      `<div class="meta-grid">${envelopeCards}</div>` +
    `</div>`;

  // 同步图表卡片副标题与页面标题
  const sub3d = document.getElementById('plot-sub-3d');
  if (sub3d) {
    sub3d.textContent = `${currentAircraftName ? currentAircraftName.toUpperCase() : '—'}` +
      ` · 燃油 ${Math.round(currentFuelPct * 100)}% · 飞行质量 ${fmtNum(metadata.flight_mass_kg)} kg`;
  }
  const subClimb = document.getElementById('plot-sub-climb');
  if (subClimb) {
    subClimb.textContent = maxSep == null
      ? '该参数下无可用爬升状态'
      : `最佳爬升率 ${fmt1(maxSep)} m/s · 升限 ${fmtNum(ceiling)} m`;
  }
  if (currentAircraftName) {
    document.title = `${currentAircraftName.toUpperCase()} · WT 飞行模型加速度分析`;
  }
}

// ===== 4. 扁平 samples 转 Z 矩阵 =====
function samplesToMatrix(samples, grid) {
  const altitudes = grid.altitudes_m;
  const machs = grid.machs;
  const altIdxMap = new Map();
  altitudes.forEach((a, i) => altIdxMap.set(a, i));
  const machIdxMap = new Map();
  machs.forEach((m, i) => machIdxMap.set(m, i));
  const rows = altitudes.length;
  const cols = machs.length;
  const z = Array.from({ length: rows }, () => new Array(cols).fill(null));
  const samplesGrid = Array.from({ length: rows }, () => new Array(cols).fill(null));
  (samples || []).forEach(s => {
    const ai = altIdxMap.get(s.altitude_m);
    const mi = machIdxMap.get(s.mach);
    if (ai === undefined || mi === undefined) return;
    z[ai][mi] = s.accel_mps2;
    samplesGrid[ai][mi] = s;
  });
  return { z, x: machs, y: altitudes, samplesGrid };
}

// ===== 5. 渲染 3D 曲面（唯一图表） =====

/**
 * 平滑 Z 矩阵：将负值替换为 null，并用邻域插值填充正加速度区域之间的"洞"，
 * 使曲面在正加速度区域之间平滑过渡连接，避免突然中断形成的"缺口"。
 *
 * 原理：负值过滤为 null 后，两个正加速度区域之间若存在负值"洞"（如某高度
 * 在低马赫端为正、高马赫端为正，但相邻高度的同马赫点为负），曲面会断开。
 * 通过迭代式邻域插值：对每个 null 点，若其 4 邻域中有 ≥2 个非 null 值，
 * 则用这些邻居的平均值填充。迭代多次让插值从边界向洞内逐层扩散。
 *
 * 这样：
 *   - 正加速度区域之间被正值插值"架桥"连接（过渡曲面，非 0）
 *   - 远离正值的纯负值区域保持 null（不显示，也不填 0）
 *   - 不在任何点显示固定的 0 值
 *
 * @param {Array<Array<number|null>>} z 原始 Z 矩阵
 * @param {number} iterations 插值迭代次数（默认 8），次数越多洞填充越深
 * @returns {Array<Array<number|null>>} 平滑后的 Z 矩阵
 */
function smoothZMatrix(z, iterations = 8) {
  const rows = z.length;
  if (rows === 0) return z;
  const cols = z[0].length;
  // 第一步：负值与非有限值替换为 null（保留 ≥ 0 的数据点）
  let result = z.map(row => row.map(v => (v == null || !isFinite(v) || v < 0) ? null : v));
  // 第二步：迭代式邻域插值，填充正加速度区域之间的"洞"
  // 每次迭代基于上一次快照，对 null 点用 ≥2 个非 null 邻居的平均值填充
  for (let iter = 0; iter < iterations; iter++) {
    const snapshot = result.map(row => row.slice());
    let filled = false;
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        if (snapshot[i][j] != null) continue;  // 已有值，跳过
        // 收集 4 邻域的非 null 值
        const neighbors = [];
        if (i > 0 && snapshot[i - 1][j] != null) neighbors.push(snapshot[i - 1][j]);
        if (i < rows - 1 && snapshot[i + 1][j] != null) neighbors.push(snapshot[i + 1][j]);
        if (j > 0 && snapshot[i][j - 1] != null) neighbors.push(snapshot[i][j - 1]);
        if (j < cols - 1 && snapshot[i][j + 1] != null) neighbors.push(snapshot[i][j + 1]);
        // 至少 2 个非 null 邻居才插值（避免在边缘外无限扩展）
        if (neighbors.length >= 2) {
          const avg = neighbors.reduce((s, v) => s + v, 0) / neighbors.length;
          result[i][j] = avg;
          filled = true;
        }
      }
    }
    if (!filled) break;  // 没有新填充点，提前结束
  }
  return result;
}

/**
 * 懒加载 Plotly.js：进入网页时不加载（约 3.5MB），
 * 仅在首次需要渲染 3D 曲面时才从 CDN 动态加载。
 * 后续调用复用同一 Promise，避免重复加载。
 * @returns {Promise<void>} 加载完成后 resolve；加载失败 reject。
 */
function loadPlotlyOnce() {
  if (window.Plotly) return Promise.resolve();
  if (plotlyPromise) return plotlyPromise;
  plotlyPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.plot.ly/plotly-2.27.0.min.js';
    s.charset = 'utf-8';
    s.onload = () => resolve();
    s.onerror = () => {
      plotlyPromise = null;  // 失败后允许重试
      reject(new Error('Plotly.js 加载失败'));
    };
    document.head.appendChild(s);
  });
  return plotlyPromise;
}

async function render3DSurface(samples, grid, climbRoute) {
  const { z, x, y, samplesGrid } = samplesToMatrix(samples, grid);
  // 平滑 Z 矩阵：负值→null，并用邻域插值填充正加速度区域之间的"洞"，
  // 使曲面在正加速度区域之间平滑过渡连接，不显示 0，纯负值区域保持 null
  const zFiltered = smoothZMatrix(z, 8);
  currentMatrix = { z: zFiltered, x, y, samplesGrid };
  // 构建 customdata：[tas_kmh, thrust_mil_n, thrust_ab_n, drag_n, altitude_m, mach]
  const customdata = y.map((alt, ai) => x.map((mach, mi) => {
    const s = samplesGrid[ai][mi];
    if (!s) return [null, null, null, null, alt, mach];
    return [
      s.tas_mps != null ? s.tas_mps * 3.6 : null,
      s.thrust_mil_n != null ? s.thrust_mil_n : null,
      s.thrust_ab_n != null ? s.thrust_ab_n : null,
      s.drag_n != null ? s.drag_n : null,
      alt,
      mach
    ];
  }));
  const trace = {
    type: 'surface',
    x: x,
    y: y,
    z: zFiltered,
    customdata: customdata,
    colorscale: COLORSCALE,
    cmin: COLOR_MIN,
    cmax: COLOR_MAX,
    // 曲面光照：略偏漫反射，突出坡度
    lighting: { ambient: 0.72, diffuse: 0.9, specular: 0.12, roughness: 0.85 },
    lightposition: { x: 800, y: 1200, z: 2200 },
    // 等高线增强可读性：在曲面表面绘制等值线
    contours: {
      z: {
        show: true,
        usecolormap: true,
        highlightcolor: '#ffffff',
        project: { z: true }
      }
    },
    colorbar: {
      thickness: 12,
      len: 0.72,
      outlinewidth: 0,
      tickfont: { family: FONT_MONO, color: COLOR_TEXT_DIM, size: 11 },
      title: { text: 'm/s²', side: 'right', font: { family: FONT_MONO, color: COLOR_TEXT_DIM, size: 11 } }
    },
    hovertemplate:
      '<b>高度 %{y} m · 马赫 %{x}</b><br>' +
      '加速度: <b>%{z:.2f} m/s²</b><extra></extra>'
  };
  // 最佳爬升路线叠加层：scatter3d 线+点，悬浮于曲面之上
  // z 轴为加速度，叠加 +0.5 m/s² 偏移使曲线脱离曲面可见
  const traces = [trace];
  if (climbRoute && climbRoute.length > 0) {
    const cX = climbRoute.map(p => p.mach);
    const cY = climbRoute.map(p => p.altitude_m);
    const cZ = climbRoute.map(p => (p.accel_mps2 != null ? p.accel_mps2 : 0) + 0.5);
    const cCustom = climbRoute.map(p => [
      p.tas_kmh != null ? p.tas_kmh : null,
      p.climb_angle_deg != null ? p.climb_angle_deg : null,
      p.altitude_m,
      p.mach
    ]);
    traces.push({
      type: 'scatter3d',
      mode: 'lines+markers',
      x: cX,
      y: cY,
      z: cZ,
      customdata: cCustom,
      line: {
        color: COLOR_GREEN,
        width: 6,
        dash: 'solid'
      },
      marker: {
        size: 6,
        color: COLOR_GREEN,
        symbol: 'circle',
        line: { color: '#faf9f5', width: 1 }
      },
      name: '最佳爬升路线',
      hovertemplate:
        '<b>爬升路线</b><br>' +
        '高度 %{y} m · 马赫 %{x}<br>' +
        '加速度: %{customdata[3]:.2f} m/s²<br>' +
        'TAS: %{customdata[0]:.0f} km/h<br>' +
        '机头向上: <b>%{customdata[1]:.1f}°</b><extra></extra>'
    });
  }
  // 窄屏（手机）时相机拉远并降低俯角，避免 3D 场景被容器裁切
  const narrowView = typeof window !== 'undefined' && window.innerWidth < 768;
  const layout = {
    autosize: true,
    margin: { l: 0, r: 0, b: 0, t: 8 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: FONT_UI,
      color: COLOR_TEXT,
      size: 12
    },
    hoverlabel: {
      bgcolor: 'rgba(8,12,17,0.94)',
      bordercolor: 'rgba(255,139,77,0.45)',
      font: { family: FONT_MONO, color: COLOR_TEXT, size: 12 }
    },
    scene: {
      bgcolor: 'rgba(0,0,0,0)',
      xaxis: {
        title: { text: '马赫数', font: { family: FONT_UI, size: 13, color: COLOR_TEXT } },
        backgroundcolor: COLOR_AXIS_BG,
        gridcolor: COLOR_GRID,
        zerolinecolor: 'rgba(148,170,196,0.4)',
        tickfont: { family: FONT_MONO, color: COLOR_TEXT_DIM, size: 11 },
        showbackground: true
      },
      yaxis: {
        title: { text: '高度 (m)', font: { family: FONT_UI, size: 13, color: COLOR_TEXT } },
        backgroundcolor: COLOR_AXIS_BG,
        gridcolor: COLOR_GRID,
        zerolinecolor: 'rgba(148,170,196,0.4)',
        tickfont: { family: FONT_MONO, color: COLOR_TEXT_DIM, size: 11 },
        showbackground: true
      },
      zaxis: {
        title: { text: '加速度 (m/s²)', font: { family: FONT_UI, size: 13, color: COLOR_TEXT } },
        backgroundcolor: COLOR_AXIS_BG,
        gridcolor: COLOR_GRID,
        zerolinecolor: 'rgba(148,170,196,0.4)',
        tickfont: { family: FONT_MONO, color: COLOR_TEXT_DIM, size: 11 },
        showbackground: true,
        rangemode: 'nonnegative'
      },
      camera: {
        eye: narrowView
          ? { x: 1.95, y: -1.85, z: 1.05 }
          : { x: 1.5, y: -1.42, z: 0.8 }
      },
      aspectratio: { x: 1.35, y: 1, z: 0.78 }
    }
  };
  const config = {
    responsive: true,
    displaylogo: false,
    toImageButtonOptions: {
      format: 'png',
      filename: `wt-accel-3d_${currentAircraftName || 'aircraft'}`,
      width: 1600,
      height: 1000
    }
  };
  // 检测全 null 数据：若所有 z 值均为 null（飞机无法加速），Plotly surface 会因
  // 缺少有效顶点而触发 WebGL uniformMatrix4fv 错误。此时显示占位提示，跳过渲染。
  const hasValidData = zFiltered.some(row => row.some(v => v != null));
  if (!hasValidData) {
    const el = document.getElementById('plot-3d');
    if (el) {
      // Plotly 可能尚未加载（懒加载），仅在已加载时清理
      if (window.Plotly) { try { Plotly.purge(el); } catch (e) { /* 忽略 */ } }
      el.innerHTML = '<div class="plot-placeholder">该飞机在当前参数下无正加速度区域<br><span class="plot-placeholder-sub">（推力不足以克服阻力，无法加速）</span></div>';
    }
    return;
  }
  // 懒加载 Plotly.js：首次渲染时从 CDN 加载（约 3.5MB），后续调用复用缓存
  try {
    await loadPlotlyOnce();
  } catch (err) {
    const el = document.getElementById('plot-3d');
    if (el) {
      el.innerHTML = '<div class="plot-placeholder">3D 渲染库加载失败<br><span class="plot-placeholder-sub">请检查网络后重新选择飞机</span></div>';
    }
    setStatus('Plotly.js 加载失败', true);
    return;
  }
  // 串行化渲染：所有 Plotly 操作排队执行，避免并发 WebGL 上下文操作导致损坏。
  // 每次渲染使用递增 token，过时的请求（用户已切换到其他飞机）会被跳过。
  renderToken++;
  const myToken = renderToken;
  renderQueue = renderQueue.then(() => {
    if (myToken !== renderToken) return;  // 已被更新的请求取代，跳过
    return performRender(traces, layout, config);
  });
}

/**
 * 执行实际的 Plotly 渲染。
 * 每次都彻底重建 DOM 元素以获取全新的 WebGL 上下文，从根本上避免
 * uniformMatrix4fv 错误（Plotly 在同一 div 上反复渲染会复用损坏的 WebGL 程序对象）。
 */
function performRender(traces, layout, config) {
  return new Promise((resolve) => {
    const oldEl = document.getElementById('plot-3d');
    if (!oldEl) { resolve(); return; }
    // 清理旧图表并替换为全新 DOM 元素（新元素 = 新 WebGL 上下文）
    try { Plotly.purge(oldEl); } catch (e) { /* 忽略 */ }
    const parent = oldEl.parentNode;
    const newEl = document.createElement('div');
    newEl.id = 'plot-3d';
    newEl.className = oldEl.className;
    parent.replaceChild(newEl, oldEl);
    // 在新的宏任务中渲染，确保 DOM 替换已应用
    requestAnimationFrame(() => {
      try {
        Plotly.newPlot('plot-3d', traces, layout, config).then(resolve).catch((err) => {
          console.error('3D 曲面渲染失败:', err);
          resolve();
        });
      } catch (err) {
        console.error('3D 曲面渲染失败:', err);
        resolve();
      }
    });
  });
}

// ===== 5.5 渲染最佳爬升路线 2D 图表 =====
/**
 * 单独的 2D 图表：横轴高度(m)，左纵轴马赫数，右纵轴 SEP 爬升率(m/s)。
 * 双 y 轴同时展示「高度 → 最佳爬升马赫数」速度程序与对应的稳态爬升率，
 * 让飞行员直观读出每个高度应飞的速度与能获得的爬升率。
 */
async function renderClimbRouteChart(climbRoute) {
  const el = document.getElementById('plot-climb');
  if (!el) return;
  // 无数据时显示占位提示
  if (!climbRoute || climbRoute.length === 0) {
    if (window.Plotly) { try { Plotly.purge(el); } catch (e) { /* 忽略 */ } }
    el.innerHTML = '<div class="plot-placeholder">该飞机在当前参数下无可用爬升路线<br><span class="plot-placeholder-sub">（推力不足以克服阻力，无 SEP>0 状态）</span></div>';
    return;
  }
  // 懒加载 Plotly.js（与 3D 曲面共用同一 Promise）
  try {
    await loadPlotlyOnce();
  } catch (err) {
    el.innerHTML = '<div class="plot-placeholder">渲染库加载失败<br><span class="plot-placeholder-sub">请检查网络后重新选择飞机</span></div>';
    return;
  }
  const alts = climbRoute.map(p => p.altitude_m);
  const machs = climbRoute.map(p => p.mach);
  const angles = climbRoute.map(p => p.climb_angle_deg);
  const tass = climbRoute.map(p => p.tas_kmh);
  const accels = climbRoute.map(p => p.accel_mps2);

  // 主轨迹：马赫数 vs 高度（左 y 轴，绿色实线 + 圆点）
  const traceMach = {
    type: 'scatter',
    mode: 'lines+markers',
    x: alts,
    y: machs,
    name: '最佳爬升马赫数',
    line: { color: COLOR_GREEN, width: 3, dash: 'solid' },
    marker: { size: 8, color: COLOR_GREEN, line: { color: '#faf9f5', width: 1 } },
    hovertemplate:
      '<b>高度 %{x} m</b><br>' +
      '马赫数: <b>%{y:.3f}</b><br>' +
      'TAS: %{customdata[0]:.0f} km/h<br>' +
      '加速度: %{customdata[1]:.2f} m/s²<br>' +
      '机头向上: <b>%{customdata[2]:.1f}°</b><extra></extra>',
    customdata: tass.map((t, i) => [t, accels[i], angles[i]])
  };
  // 副轨迹：机头向上角度 vs 高度（右 y 轴，橙色虚线 + 方块）
  const traceAngle = {
    type: 'scatter',
    mode: 'lines+markers',
    x: alts,
    y: angles,
    name: '机头向上角度',
    yaxis: 'y2',
    line: { color: COLOR_ACCENT, width: 2, dash: 'dash' },
    marker: { size: 7, color: COLOR_ACCENT, symbol: 'square', line: { color: '#faf9f5', width: 1 } },
    hovertemplate:
      '<b>高度 %{x} m</b><br>' +
      '机头向上: <b>%{y:.1f}°</b><extra></extra>'
  };

  const layout = {
    autosize: true,
    margin: { l: 62, r: 62, t: 46, b: 48 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: FONT_UI,
      color: COLOR_TEXT,
      size: 12
    },
    hovermode: 'x unified',
    hoverlabel: {
      bgcolor: 'rgba(8,12,17,0.94)',
      bordercolor: 'rgba(255,139,77,0.4)',
      font: { family: FONT_MONO, color: COLOR_TEXT, size: 12 }
    },
    showlegend: true,
    legend: {
      orientation: 'h',
      x: 0,
      y: 1.16,
      xanchor: 'left',
      yanchor: 'top',
      bgcolor: 'rgba(0,0,0,0)',
      font: { family: FONT_MONO, size: 11, color: COLOR_TEXT_DIM }
    },
    xaxis: {
      title: { text: '高度 (m)', font: { family: FONT_UI, size: 13, color: COLOR_TEXT } },
      gridcolor: COLOR_GRID,
      zerolinecolor: 'rgba(148,170,196,0.4)',
      tickfont: { family: FONT_MONO, color: COLOR_TEXT_DIM, size: 11 },
      showgrid: true,
      showline: true,
      linecolor: 'rgba(148,170,196,0.22)',
      ticks: 'outside',
      tickcolor: 'rgba(148,170,196,0.22)'
    },
    yaxis: {
      title: { text: '马赫数', font: { family: FONT_UI, size: 13, color: COLOR_GREEN } },
      gridcolor: COLOR_GRID,
      zerolinecolor: 'rgba(148,170,196,0.4)',
      tickfont: { family: FONT_MONO, color: COLOR_GREEN, size: 11 },
      showgrid: true,
      showline: true,
      linecolor: 'rgba(143,208,122,0.35)',
      ticks: 'outside',
      tickcolor: 'rgba(143,208,122,0.35)'
    },
    yaxis2: {
      title: { text: '机头向上角度 (°)', font: { family: FONT_UI, size: 13, color: COLOR_ACCENT } },
      overlaying: 'y',
      side: 'right',
      gridcolor: 'rgba(0,0,0,0)',
      tickfont: { family: FONT_MONO, color: COLOR_ACCENT, size: 11 },
      showgrid: false,
      showline: true,
      linecolor: 'rgba(255,139,77,0.35)',
      ticks: 'outside',
      tickcolor: 'rgba(255,139,77,0.35)'
    }
  };
  const config = {
    responsive: true,
    displaylogo: false,
    toImageButtonOptions: {
      format: 'png',
      filename: `wt-climb-route_${currentAircraftName || 'aircraft'}`,
      width: 1600,
      height: 800
    }
  };
  // 与 3D 渲染共用渲染队列，避免并发 WebGL/Canvas 操作冲突
  renderQueue = renderQueue.then(() => {
    try {
      Plotly.newPlot(el, [traceMach, traceAngle], layout, config);
    } catch (err) {
      console.error('爬升路线图表渲染失败:', err);
    }
  });
}

/** 清空 3D 图表与元数据面板，显示占位提示 */
function clearPlot() {
  renderToken++;  // 使任何进行中的渲染失效
  currentData = null;
  currentMatrix = null;
  currentFm = null;            // 清空缓存的飞机数据
  currentAircraftName = null;
  currentAircraftNation = null;
  currentPayloadKg = 0;        // 重置挂载质量
  // 重置挂载质量输入框
  const payloadInput = document.getElementById('payload-input');
  if (payloadInput) payloadInput.value = '0';
  // 清空图表区域
  const plotEl = document.getElementById('plot-3d');
  if (plotEl) {
    // Plotly 可能尚未加载（懒加载），仅在已加载时清理
    if (window.Plotly) { try { Plotly.purge(plotEl); } catch (e) { /* 忽略 */ } }
    plotEl.innerHTML = '<div class="plot-placeholder">请在上方搜索并选择一架飞机<br><span class="plot-placeholder-sub">（切换国家后需重新选择飞机）</span></div>';
  }
  // 清空爬升路线图表（不留占位文字，渲染时根据数据决定显示内容）
  const climbEl = document.getElementById('plot-climb');
  if (climbEl) {
    if (window.Plotly) { try { Plotly.purge(climbEl); } catch (e) { /* 忽略 */ } }
    climbEl.innerHTML = '';
  }
  // 清空元数据面板
  const metaPanel = document.getElementById('metadata-panel');
  if (metaPanel) metaPanel.innerHTML = '';
  // 复位图表卡片副标题与页面标题
  const sub3d = document.getElementById('plot-sub-3d');
  if (sub3d) sub3d.textContent = '选择飞机后显示加速度包线';
  const subClimb = document.getElementById('plot-sub-climb');
  if (subClimb) subClimb.textContent = '速度程序 · 机头向上角度 · 剩余功率';
  document.title = 'War Thunder 飞行模型 3D 加速度分析';
  setStatus('请选择飞机', false, 'idle');
}

// ===== 6. 加载飞机原始数据并在浏览器端计算 =====
async function loadAircraft(name, path, nation) {
  setStatus(`加载 ${name} ...`, false, 'busy');
  try {
    // 0. 选择飞机时即开始预加载 Plotly.js（与下方 .blkx 下载并行）
    //    首次渲染无需串行等待：飞机数据下载 + Plotly.js 下载同时进行
    const plotlyPreload = loadPlotlyOnce().catch(() => { /* 渲染时再处理错误 */ });
    // 1. 从服务器加载原始 .blkx 飞行模型数据
    const resp = await fetch(`../${path}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const fm = await resp.json();

    // 缓存当前飞机的原始数据与信息（供燃油滑动条重算使用）
    currentFm = fm;
    currentAircraftName = name;
    currentAircraftNation = nation;

    // 2. 在浏览器端实时计算加速度网格（服务器只提供数据）
    //    使用当前燃油滑动条值（currentFuelPct），默认 0.5
    await recomputeAndRender(`计算 ${name} 加速度...`);
    // 等待 Plotly.js 预加载完成（已加载则立即 resolve）
    await plotlyPreload;
  } catch (err) {
    console.error('加载飞机数据失败:', err);
    setStatus(`加载失败: ${err.message}`, true);
  }
}

/** 基于当前 currentFm + currentFuelPct + currentPayloadKg 重新计算并渲染 */
async function recomputeAndRender(statusMsg) {
  if (!currentFm || !currentAircraftName) return;
  if (statusMsg) setStatus(statusMsg, false, 'busy');
  // 让 UI 有机会更新状态栏
  await new Promise(r => setTimeout(r, 0));

  showProgress('计算加速度网格...');
  const data = await analyzeAircraft(currentAircraftName, currentFm, {
    fuel_pct: currentFuelPct,
    afterburner: true,
  }, updateProgress);

  // 挂载质量叠加到飞行质量，并重算加速度网格（质量变大→加速度降低）
  // 需同步重算 optimal 与 climb_route，使其与新质量下的 samples 一致
  if (currentPayloadKg > 0) {
    showProgress('重算挂载质量加速度...');
    const baseMass = data.metadata.flight_mass_kg;
    const newMass = baseMass + currentPayloadKg;
    // 用新质量重算加速度网格
    const [samples, grid] = await computeAccelGrid(currentFm, newMass, true, 0.1, 2.5, 0.05, updateProgress);
    data.samples = samples;
    data.grid = grid;
    data.metadata.flight_mass_kg = newMass;
    data.optimal = computeOptimal(samples, grid);
    data.climb_route = computeClimbRoute(samples, grid);
  }
  hideProgress();

  data.metadata.computed_at = new Date(Date.now() + 8 * 3600 * 1000)
    .toISOString().replace('Z', '+08:00');
  currentData = data;
  renderMetadata(data.metadata, currentAircraftNation, data);
  try {
    await render3DSurface(data.samples, data.grid, data.climb_route);
    await renderClimbRouteChart(data.climb_route);
  } catch (renderErr) {
    console.error('渲染出错（不影响数据）:', renderErr);
  }
  setStatus('就绪', false, 'ready');
}

// ===== 6.5 燃油与挂载质量控件 =====

/** 初始化燃油滑动条+数字输入框 与 挂载质量输入框事件 */
function initFuelSlider() {
  const slider = document.getElementById('fuel-slider');
  const fuelInput = document.getElementById('fuel-input');
  if (!slider || !fuelInput) return;

  // 同步滑动条已填充轨道宽度（CSS 变量 --fill，见 style.css）
  const syncFill = pct => slider.style.setProperty('--fill', `${pct}%`);
  syncFill(parseInt(slider.value, 10) || 50);

  // 滑动条输入时同步数字框
  slider.addEventListener('input', () => {
    const pct = parseInt(slider.value, 10);
    fuelInput.value = pct;
    syncFill(pct);
  });

  // 松开滑动条时才重算（避免拖动卡顿）
  slider.addEventListener('change', () => {
    const pct = parseInt(slider.value, 10);
    currentFuelPct = pct / 100;
    fuelInput.value = pct;
    syncFill(pct);
    if (currentFm && currentAircraftName) {
      recomputeAndRender(`重算 (${pct}% 燃油)...`);
    }
  });

  // 数字框输入时同步滑动条，失焦或回车时重算
  fuelInput.addEventListener('input', () => {
    let pct = parseInt(fuelInput.value, 10);
    if (isNaN(pct)) return;
    pct = Math.max(30, Math.min(100, pct));  // 钳制到 30-100
    slider.value = pct;
    syncFill(pct);
  });
  fuelInput.addEventListener('change', () => {
    let pct = parseInt(fuelInput.value, 10);
    if (isNaN(pct)) { fuelInput.value = Math.round(currentFuelPct * 100); return; }
    pct = Math.max(30, Math.min(100, pct));
    fuelInput.value = pct;
    slider.value = pct;
    syncFill(pct);
    currentFuelPct = pct / 100;
    if (currentFm && currentAircraftName) {
      recomputeAndRender(`重算 (${pct}% 燃油)...`);
    }
  });

  // 挂载质量输入框
  const payloadInput = document.getElementById('payload-input');
  if (payloadInput) {
    payloadInput.addEventListener('change', () => {
      let kg = parseFloat(payloadInput.value);
      if (isNaN(kg) || kg < 0) kg = 0;
      if (kg > 20000) kg = 20000;
      payloadInput.value = kg;
      currentPayloadKg = kg;
      if (currentFm && currentAircraftName) {
        recomputeAndRender(`重算 (挂载 ${kg} kg)...`);
      }
    });
  }
}

// ===== 7. 初始化 =====
async function init() {
  setStatus('初始化...', false, 'busy');
  try {
    const resp = await fetch('manifest.json?v=2');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const manifest = await resp.json();
    const datasets = manifest.datasets || [];
    const nations = manifest.nations || [];
    currentDatasets = datasets;
    currentNations = nations;

    // 填充国家筛选器
    populateNationSelect(nations);
    // 初始化搜索框事件
    initAircraftSearch();
    // 初始填充飞机列表（全部模式，按国家分组）
    updateAircraftList(datasets, nations, '__all__');

    // 注册国家筛选事件
    const nationSel = document.getElementById('nation-select');
    if (nationSel) {
      nationSel.addEventListener('change', () => {
        const code = nationSel.value;
        updateAircraftList(datasets, nations, code);
        // 切换国家时不自动选择飞机，清空当前图表并提示用户选择
        clearPlot();
      });
    }

    // 注册燃油滑动条事件
    initFuelSlider();

    // 进入网页时不自动选择飞机，显示占位提示等待用户选择
    if (datasets.length > 0) {
      clearPlot();
    } else {
      setStatus('manifest 中无数据集');
    }
  } catch (err) {
    console.error('初始化失败:', err);
    setStatus(`初始化失败: ${err.message}`, true);
  }
}

// 等待 DOM 加载完成后初始化
document.addEventListener('DOMContentLoaded', init);
