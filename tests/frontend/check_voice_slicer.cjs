#!/usr/bin/env node
/**
 * T8 语音切片算法单测（契约 `C-VOICEUI@2` + 第五轮 `C-VOICEUI@5 §2`：
 * 7 组切片 + 8 组续接重吐裁剪 + 5 常量 + 旧函数名零命中）。
 *
 * 用法（由 `tests/frontend/run_all.sh` 调用）：
 *   node check_voice_slicer.cjs <编译后的 voiceSlicer.js> <frontend/src 目录>
 *
 * 约束：
 * - `voiceSlicer.ts` 零 import，可被 `tsc` 单文件编译后由 Node 直接执行；
 * - 不使用任何新依赖（Node 内置 fs/path 即可）；
 * - 任一组断言失败 → 打印 FAIL 并以 1 退出（run_all.sh 据此中止）。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const compiledPath = process.argv[2];
const srcDir = process.argv[3];

if (!compiledPath || !srcDir) {
  console.error('FAIL 用法：node check_voice_slicer.cjs <voiceSlicer.js> <frontend/src>');
  process.exit(2);
}

let passed = 0;
let failed = 0;

function check(ok, message) {
  if (ok) {
    passed += 1;
    console.log(`PASS ${message}`);
  } else {
    failed += 1;
    console.error(`FAIL ${message}`);
  }
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

let mod;
try {
  mod = require(path.resolve(compiledPath));
} catch (error) {
  console.error(`FAIL 无法加载编译产物 ${compiledPath}：${error.message}`);
  process.exit(1);
}

if (typeof mod.sliceChunk !== 'function') {
  console.error('FAIL 编译产物未导出 sliceChunk()（C-VOICEUI@2 B）');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// 1) 7 组切片断言（第 4 组为 12 字强制切：13 字输入 → 前 12 字 + 剩余 1 字）
// ---------------------------------------------------------------------------
const sliceCases = [
  ['明天。', { chunk: '明天。', rest: '' }],
  ['明天。下午', { chunk: '明天。', rest: '下午' }],
  ['明天，下午。', { chunk: '明天，', rest: '下午。' }],
  ['我们明天下午两点在操场集合', { chunk: '我们明天下午两点在操场集', rest: '合' }],
  ['我们明天下午', null],
  ['', null],
  ['，', { chunk: '，', rest: '' }]
];

for (const [input, expected] of sliceCases) {
  const actual = mod.sliceChunk(input);
  check(
    deepEqual(actual, expected),
    `sliceChunk(${JSON.stringify(input)}) = ${JSON.stringify(actual)}（期望 ${JSON.stringify(expected)}）`
  );
}

// ---------------------------------------------------------------------------
// 2) 8 组 `trimRestartOverlap`（第五轮 D3 / `C-VOICEUI@5 §2` 续接重吐裁剪）
//
//    语义：返回 `transcript` 去掉「与 prevTail 尾部最长重叠的前缀」后的剩余文本；
//    重叠长度取最大值，任一入参为空串则原样返回 transcript。
//    第 8 组是用户实测原话（「资源，时长两小时」）：与 prevTail 无后缀=前缀重叠，
//    必须原样保留——纯函数不按标点猜测，前导逗号的裁剪由接入层窗口负责。
// ---------------------------------------------------------------------------
if (typeof mod.trimRestartOverlap !== 'function') {
  console.error('FAIL 编译产物未导出 trimRestartOverlap()（C-VOICEUI@5 §2）');
  process.exit(1);
}

const trimCases = [
  ['明天下午两点', '明天下午两点去操场', '去操场'],
  ['abc', 'abc', ''],
  ['abc', 'xyz', 'xyz'],
  ['', 'abc', 'abc'],
  ['abc', '', ''],
  ['ab', 'bx', 'x'],
  ['一二三四五', '三四五六七八', '六七八'],
  ['资源时长两小时', '资源，时长两小时', '资源，时长两小时']
];

for (const [prevTail, transcript, expected] of trimCases) {
  const actual = mod.trimRestartOverlap(prevTail, transcript);
  check(
    actual === expected,
    `trimRestartOverlap(${JSON.stringify(prevTail)}, ${JSON.stringify(transcript)}) = ` +
      `${JSON.stringify(actual)}（期望 ${JSON.stringify(expected)}）`
  );
}

// ---------------------------------------------------------------------------
// 3) 5 个算法常量（写死，禁止运行时修改）
// ---------------------------------------------------------------------------
const constantCases = [
  ['PUNCT_THRESHOLD', 1],
  ['MAX_CHUNK_CHARS', 12],
  ['SILENCE_CUT_MS', 800],
  ['FINAL_DELAY_MS', 800],
  ['LIVE_MAX_REFRESH_MS', 200]
];
for (const [name, expected] of constantCases) {
  check(mod[name] === expected, `${name} = ${mod[name]}（期望 ${expected}）`);
}

// ---------------------------------------------------------------------------
// 4) 旧函数名 `sliceByPunctuation` 在源码中零命中（markdown 历史说明允许保留）
// ---------------------------------------------------------------------------
let hits = [];
const scanRoots = [srcDir, path.resolve(__dirname)];
for (const root of scanRoots) {
  if (!fs.existsSync(root)) continue;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (['node_modules', 'dist', 'dist-t04', 'dist-t05', 'dist-t06'].includes(entry.name)) continue;
        walk(full);
      } else if (/\.(ts|vue|js|cjs)$/.test(entry.name)) {
        // 排除本检查脚本自身（其断言文本包含旧函数名，否则会自命中）
        if (path.resolve(full) === path.resolve(__filename)) continue;
        const text = fs.readFileSync(full, 'utf8');
        if (text.includes('sliceByPunctuation')) {
          const line = text.split(/\r?\n/).findIndex((row) => row.includes('sliceByPunctuation')) + 1;
          hits.push(`${path.relative(path.resolve(__dirname, '..', '..'), full)}:${line}`);
        }
      }
    }
  };
  walk(root);
}
check(hits.length === 0, `sliceByPunctuation 源码零命中（.ts/.vue/.js/.cjs；实际 ${hits.length} 处：${hits.join('、') || '无'}）`);

console.log(
  `---- check_voice_slicer.cjs：${passed} PASS / ${failed} FAIL` +
    `（7 切片 + ${trimCases.length} 重吐裁剪 + ${constantCases.length} 常量 + 1 旧名零命中）----`
);
process.exit(failed === 0 ? 0 : 1);
