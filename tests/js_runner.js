// 交叉验证辅助脚本：在 Node 中加载 web/compute.js，计算指定 FM 的分析结果。
// 用法: node tests/js_runner.js <fm.json路径> <fuel_pct> [afterburner]
// 输出: JSON 到 stdout（metadata.computed_at 被置空以便与 Python 对比）
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function loadCompute() {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'web', 'compute.js'), 'utf-8');
  const sandbox = {
    setTimeout,       // computeAccelGrid 的 yieldToUI 依赖
    clearTimeout,
    console,
    Math,
    Date,
    JSON,
    Number,
    String,
    Array,
    Map,
    Object,
    isFinite,
  };
  vm.createContext(sandbox);
  // 在脚本末尾追加导出语句，把顶层函数暴露到全局命名空间
  vm.runInContext(src + '\n;globalThis.__wtfm = { analyzeAircraft };', sandbox);
  return sandbox.__wtfm;
}

async function main() {
  const [fmPath, fuelPct, afterburnerRaw] = process.argv.slice(2);
  const fm = JSON.parse(fs.readFileSync(fmPath, 'utf-8'));
  const afterburner = String(afterburnerRaw).toLowerCase() !== 'false';
  const compute = loadCompute();
  const result = await compute.analyzeAircraft(
    'test', fm, { fuel_pct: parseFloat(fuelPct), afterburner });
  result.metadata.computed_at = '';
  process.stdout.write(JSON.stringify(result));
}

main().catch((err) => {
  console.error('js_runner 失败:', err);
  process.exit(1);
});
