// 交叉验证辅助脚本：在 Node 中加载 web/compare.js（与 web/compute.js 共享全局作用域），
// 对给定的「记录数组」构建对比数据。
// 用法: node tests/js_compare_runner.js <records.json>
// 输出: JSON 到 stdout（generated_at 被置空以便与 Python 对比）
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function loadContext() {
  const sandbox = {
    setTimeout,       // compute.js 的 yieldToUI 依赖
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
    parseFloat,
    parseInt,
  };
  vm.createContext(sandbox);

  const read = (name) => fs.readFileSync(path.join(__dirname, '..', 'web', name), 'utf-8');
  // 先加载 compute.js 再加载 compare.js：与浏览器中两个 <script> 的加载顺序一致，
  // 同时验证两者共享全局作用域时没有命名冲突。
  vm.runInContext(read('compute.js'), sandbox);
  vm.runInContext(
    read('compare.js') +
    '\n;globalThis.__wtcmp = { buildComparison, computeCompareMetrics, normalizeMetric,' +
    ' pickProfileAltitudes, MAX_COMPARE_AIRCRAFT };',
    sandbox);
  return sandbox.__wtcmp;
}

function main() {
  const [recordsPath] = process.argv.slice(2);
  const records = JSON.parse(fs.readFileSync(recordsPath, 'utf-8'));
  const cmp = loadContext();
  const result = cmp.buildComparison(records);
  result.generated_at = '';  // 时间戳不参与比较
  process.stdout.write(JSON.stringify(result));
}

main();
