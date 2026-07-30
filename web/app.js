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

// Anthropic 品牌色
const COLOR_ACCENT = '#d97757';   // 橙色强调（高加速度）
const COLOR_BLUE = '#6a9bcc';     // 冷色低值（低/负加速度）
const COLOR_CREAM = '#faf9f5';    // 中性白（零加速度）
const COLOR_GREEN = '#788c5d';    // Anthropic 绿
// 色阶：仅显示加速度 ≥ 0 的区域
//   奶白(零加速) → 浅橙 → 橙(中等加速) → 深橙红(强加速)
// 负加速度区域通过 z=null 过滤，不渲染曲面
const COLORSCALE = [
  [0.00, COLOR_CREAM],
  [0.35, '#e8a585'],
  [0.65, COLOR_ACCENT],
  [1.00, '#b85a3e']
];
// 色阶映射范围：0 m/s² 到 6 m/s²（典型最大加速度）
const COLOR_MIN = 0;
const COLOR_MAX = 6;

// ===== 1. 状态栏更新 =====
function setStatus(msg, isError = false) {
  const bar = document.getElementById('status-bar');
  if (!bar) return;
  bar.textContent = msg;
  if (isError) {
    bar.classList.add('error');
  } else {
    bar.classList.remove('error');
  }
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
function renderMetadata(metadata, nation) {
  const panel = document.getElementById('metadata-panel');
  if (!panel) return;
  if (!metadata) {
    panel.innerHTML = '';
    return;
  }
  const fmtNum = v => (v === undefined || v === null) ? '—' : Number(v).toLocaleString('zh-CN');
  const items = [
    { label: '空重', value: metadata.empty_mass_kg != null ? `${fmtNum(metadata.empty_mass_kg)} kg` : '—' },
    { label: '燃油质量', value: metadata.fuel_mass_kg != null ? `${fmtNum(metadata.fuel_mass_kg)} kg` : '—' },
    { label: '挂载质量', value: fmtNum(currentPayloadKg) + ' kg' },
    { label: '飞行质量', value: metadata.flight_mass_kg != null ? `${fmtNum(metadata.flight_mass_kg)} kg` : '—' },
  ];
  panel.innerHTML = items.map(it => {
    return `<div class="meta-item">` +
      `<div class="meta-label">${it.label}</div>` +
      `<div class="meta-value">${it.value}</div>` +
      `</div>`;
  }).join('');
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
    // 等高线增强可读性：在曲面表面绘制等值线
    contours: {
      z: {
        show: true,
        usecolormap: true,
        highlightcolor: '#ffffff',
        project: { z: true }
      }
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
      p.sep_mps != null ? p.sep_mps : null,
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
        'SEP(爬升率): <b>%{customdata[1]:.1f} m/s</b><extra></extra>'
    });
  }
  const layout = {
    autosize: true,
    margin: { l: 0, r: 0, b: 0, t: 20 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: "'Lora', 'Georgia', serif",
      color: '#faf9f5',
      size: 12
    },
    scene: {
      xaxis: {
        title: { text: '马赫数', font: { size: 13, color: '#faf9f5' } },
        backgroundcolor: 'rgba(31,31,29,0.6)',
        gridcolor: '#3a3a36',
        zerolinecolor: '#b0aea5',
        tickfont: { color: '#b0aea5', size: 11 },
        showbackground: true
      },
      yaxis: {
        title: { text: '高度 (m)', font: { size: 13, color: '#faf9f5' } },
        backgroundcolor: 'rgba(31,31,29,0.6)',
        gridcolor: '#3a3a36',
        zerolinecolor: '#b0aea5',
        tickfont: { color: '#b0aea5', size: 11 },
        showbackground: true
      },
      zaxis: {
        title: { text: '加速度 (m/s²)', font: { size: 13, color: '#faf9f5' } },
        backgroundcolor: 'rgba(31,31,29,0.6)',
        gridcolor: '#3a3a36',
        zerolinecolor: '#b0aea5',
        tickfont: { color: '#b0aea5', size: 11 },
        showbackground: true,
        rangemode: 'nonnegative'
      },
      camera: { eye: { x: 1.8, y: -1.6, z: 0.85 } },
      aspectratio: { x: 1.2, y: 1, z: 0.75 }
    }
  };
  const config = {
    responsive: true,
    displaylogo: false,
    toImageButtonOptions: { format: 'png', filename: 'wt-accel-3d', width: 1600, height: 1000 }
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
  const seps = climbRoute.map(p => p.sep_mps);
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
      'SEP(爬升率): <b>%{customdata[2]:.1f} m/s</b><extra></extra>',
    customdata: tass.map((t, i) => [t, accels[i], seps[i]])
  };
  // 副轨迹：SEP 爬升率 vs 高度（右 y 轴，橙色虚线 + 方块）
  const traceSep = {
    type: 'scatter',
    mode: 'lines+markers',
    x: alts,
    y: seps,
    name: 'SEP 爬升率',
    yaxis: 'y2',
    line: { color: COLOR_ACCENT, width: 2, dash: 'dash' },
    marker: { size: 7, color: COLOR_ACCENT, symbol: 'square', line: { color: '#faf9f5', width: 1 } },
    hovertemplate:
      '<b>高度 %{x} m</b><br>' +
      'SEP(爬升率): <b>%{y:.1f} m/s</b><extra></extra>'
  };

  const layout = {
    autosize: true,
    margin: { l: 60, r: 60, t: 20, b: 50 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: "'Lora', 'Georgia', serif",
      color: '#faf9f5',
      size: 12
    },
    showlegend: true,
    legend: {
      x: 0.02, y: 0.98,
      bgcolor: 'rgba(31,31,29,0.7)',
      bordercolor: '#3a3a36',
      borderwidth: 1,
      font: { size: 11 }
    },
    xaxis: {
      title: { text: '高度 (m)', font: { size: 13, color: '#faf9f5' } },
      gridcolor: '#3a3a36',
      zerolinecolor: '#b0aea5',
      tickfont: { color: '#b0aea5', size: 11 },
      showgrid: true
    },
    yaxis: {
      title: { text: '马赫数', font: { size: 13, color: COLOR_GREEN } },
      gridcolor: '#3a3a36',
      zerolinecolor: '#b0aea5',
      tickfont: { color: COLOR_GREEN, size: 11 },
      showgrid: true
    },
    yaxis2: {
      title: { text: 'SEP 爬升率 (m/s)', font: { size: 13, color: COLOR_ACCENT } },
      overlaying: 'y',
      side: 'right',
      gridcolor: 'rgba(0,0,0,0)',
      tickfont: { color: COLOR_ACCENT, size: 11 },
      showgrid: false
    }
  };
  const config = {
    responsive: true,
    displaylogo: false,
    toImageButtonOptions: { format: 'png', filename: 'wt-climb-route', width: 1600, height: 800 }
  };
  // 与 3D 渲染共用渲染队列，避免并发 WebGL/Canvas 操作冲突
  renderQueue = renderQueue.then(() => {
    try {
      Plotly.newPlot(el, [traceMach, traceSep], layout, config);
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
  // 清空爬升路线图表
  const climbEl = document.getElementById('plot-climb');
  if (climbEl) {
    if (window.Plotly) { try { Plotly.purge(climbEl); } catch (e) { /* 忽略 */ } }
    climbEl.innerHTML = '<div class="plot-placeholder">请在上方搜索并选择一架飞机<br><span class="plot-placeholder-sub">（选择飞机后将显示最佳爬升速度程序）</span></div>';
  }
  // 清空元数据面板
  const metaPanel = document.getElementById('metadata-panel');
  if (metaPanel) metaPanel.innerHTML = '';
  setStatus('请选择飞机');
}

// ===== 6. 加载飞机原始数据并在浏览器端计算 =====
async function loadAircraft(name, path, nation) {
  setStatus(`加载 ${name} ...`);
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
  if (statusMsg) setStatus(statusMsg);
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
  renderMetadata(data.metadata, currentAircraftNation);
  try {
    await render3DSurface(data.samples, data.grid, data.climb_route);
    await renderClimbRouteChart(data.climb_route);
  } catch (renderErr) {
    console.error('渲染出错（不影响数据）:', renderErr);
  }
  setStatus('就绪');
}

// ===== 6.5 燃油与挂载质量控件 =====

/** 初始化燃油滑动条+数字输入框 与 挂载质量输入框事件 */
function initFuelSlider() {
  const slider = document.getElementById('fuel-slider');
  const fuelInput = document.getElementById('fuel-input');
  if (!slider || !fuelInput) return;

  // 滑动条输入时同步数字框
  slider.addEventListener('input', () => {
    const pct = parseInt(slider.value, 10);
    fuelInput.value = pct;
  });

  // 松开滑动条时才重算（避免拖动卡顿）
  slider.addEventListener('change', () => {
    const pct = parseInt(slider.value, 10);
    currentFuelPct = pct / 100;
    fuelInput.value = pct;
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
  });
  fuelInput.addEventListener('change', () => {
    let pct = parseInt(fuelInput.value, 10);
    if (isNaN(pct)) { fuelInput.value = Math.round(currentFuelPct * 100); return; }
    pct = Math.max(30, Math.min(100, pct));
    fuelInput.value = pct;
    slider.value = pct;
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
  setStatus('初始化...');
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
