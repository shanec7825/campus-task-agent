# T4 · 第五轮迭代终验报告（R25~R26 · D1~D4）· 最终版

> **本文件为第五轮最终验收结论**；下方第四轮报告内容（`## 一、…` 起）作为**历史基线**保留，
> 标题已加 `【历史·第四轮】` 前缀，全文**只有一个** `VERDICT` 行（在「第五轮 · 九、结论」）。
> 第五轮验证者：独立终验哨兵（不属于 T1~T3 实现任务）；**只写 `tests/**`**，未修改任何实现、
> `readme/`、`codearts_proof/` 或 plan；发现缺陷只报告，不代改。
> 执行时间：2026-11-11 19:52 ~ 20:30（第五轮单轮）；Windows 11 / git-bash / Python 3.14.4 / Node 22.17.0。
> 工程根：`campus-task-agent/`；端口：后端 **8060**、KB 观测 **8061**、E2E 后端 **8050** + preview **8051**
> （串行执行，未占用演示端口 8000/5173）。
> 上游基线：第四轮 **1565 PASS / 0 FAIL / 38 DEFERRED / VERDICT: PASS**（已作为回归一致性基线纳入）。

---

## 第五轮 · 一、最终结论

**结论：PASS（0 FAIL / 41 DEFERRED）。** 首轮唯一缺口 D38 已在复核轮闭合。

**复核轮闭合（stage10 回填 + T2 补修）**：
- **D38 转 PASS**：书记官完成 stage10 B 段回填 —— 文件 **268 行**（`wc -l` 实测）、**5 节**、
  第 3 节含 `C-DEV@1` / `C-VOICEUI@5` / `C-DELIVERY@5`（全文命中 **14** 次）、
  第 4/5 节占位标记 **0 命中**；`python tests/security/verify_delivery.py` 复核
  **40 PASS / 0 FAIL（EXIT=0）**，D38/D39/D40 均 PASS。
- **O-T4-5-1 已修复（T2）**：`resetLocalBuffer()` 新增 `resumedRestartFrames = 0`（附注释）；
  `check_contracts.py` ㉔ 已补「resetLocalBuffer 内复位」硬断言，复核 **25/25**；
  typecheck 通过、`.t1-voice-check` 仍 **25/25**。
- 无任何代码 / 功能 / 回归失败项。

**统计（复核后）：1584 项通过（含 2 项 PASS-LOCAL 与 25 项 KB 观测不计失败判据）/ 0 FAIL / 41 DEFERRED。**

（首轮 1583/1/41 → 复核 1584/0/41：唯一增量 = D38 由 FAIL 转 PASS。）

| 套件 | 命令 | 退出码 | PASS | FAIL | 备注 |
|---|---|---|---|---|---|
| 后端 6 脚本 | `T10_PORT=8060 T10_KB_PORT=8061 bash tests/backend/run_all.sh` | **0** | **1404** | **0** | 后端本轮零改动 → 零回归（41+413+257+229+358+106） |
| ├ KB 观测 | 同上（8061，unfiltered） | 0 | **25** | 0 | 不计失败判据 |
| 前端 构建门禁 | `bash tests/frontend/run_all.sh` 步骤 1 | **0** | **4** | 0 | typecheck + `vite build` + dist + 无 `any` |
| 前端 契约检查 | 同上步骤 2（`check_contracts.py`） | **0** | **25** | 0 | 21 既有 + ㉒~㉕ 新增 |
| 前端 语音切片 | 同上步骤 3（`check_voice_slicer.cjs`） | **0** | **21** | 0 | 7 切片 + 8 重吐裁剪 + 5 常量 + 1 旧名零命中 |
| 安全 红线 | `bash tests/security/test_security_redline.sh` | **0** | **11 + 2 PASS-LOCAL** | 0 | A 层 0 命中；B 层本地运行时文件合规 |
| 安全 交付物 | `python tests/security/verify_delivery.py` | **0** | **40** | **0** | D38 复核转 PASS（stage10 已回填） |
| 安全 无头 E2E | `python tests/security/e2e_headless.py` | **0** | **52** | **0** | 48 既有 + D1~D4 源码探针 |
| 纯逻辑桩测 | `node build.mjs && node bundle.mjs`（`.t1-voice-check`） | **0** | **25** | 0 | 场景 A14 + B7 + C4 |
| **合计** | — | — | **1584** | **0** | 1404+4+25+21+13+40+52+25 |

> 复核后 **0 FAIL**：`verify_delivery.py` 退出码 **0**（40/0），`e2e_headless.py` 退出码 0（52/0）。

---

## 第五轮 · 二、D1~D4 断言结果（逐项真实证据）

| 项 | 断言位置 | 结果 | 真实证据 |
|---|---|---|---|
| **D1** 穿透白名单 | `check_contracts.py` ㉒ + `e2e_headless.py` D1 | **PASS / PASS** | `allowedHosts: ['.takin.cc']` 恰 1 处、数组恰 1 个元素、位于 `server: {` 与 `proxy: {` 之间；`port: 5173` / `target: 'http://127.0.0.1:8000'` / `changeOrigin: true` / `plugins: [vue()]` 未变 |
| **D2** 续接保留去重链 | `check_contracts.py` ㉓ + `e2e_headless.py` D2 | **PASS / PASS** | `start()` 的 `if (options.keepSession && sessionId) {` 体 **0 处** `dedupTail = ''`；`else {` 体 **1 处**；续接分支 `resumedRestartFrames = RESUMED_RESTART_FRAME_BUDGET`，新会话分支 `resumedRestartFrames = 0` |
| **D3** 续接重吐裁剪 | `check_contracts.py` ㉔ + `e2e_headless.py` D3 + `check_voice_slicer.cjs` | **PASS / PASS / 8+8 PASS** | `voiceSlicer.ts` 零 import 导出 `trimRestartOverlap`；`trimResumedTranscript()` 以 `fullText.slice(-64)` 为 prevTail、重叠 ≥2 才裁、窗口 `RESUMED_RESTART_FRAME_BUDGET = 3`；`applyInterim/applyFinal` 的追加语句前调用，`replaceTail` 内 0 命中；8 组函数用例全 PASS |
| **D4** 尾片结算幂等 | `check_contracts.py` ㉕ + `e2e_headless.py` D4 | **PASS / PASS** | `commitStoppedSession()` 首条有效语句为 `if (!stopping) return`；其后五步顺序 `pendingText → sentIndex → stopping=false → enqueue(tail,true) → clearLiveText` 未变（Q10） |

**`trimRestartOverlap` 8 组真实输出（`check_voice_slicer.cjs`）**

```text
PASS trimRestartOverlap("明天下午两点", "明天下午两点去操场") = "去操场"（期望 "去操场"）
PASS trimRestartOverlap("abc", "abc") = ""（期望 ""）
PASS trimRestartOverlap("abc", "xyz") = "xyz"（期望 "xyz"）
PASS trimRestartOverlap("", "abc") = "abc"（期望 "abc"）
PASS trimRestartOverlap("abc", "") = ""（期望 ""）
PASS trimRestartOverlap("ab", "bx") = "x"（期望 "x"）
PASS trimRestartOverlap("一二三四五", "三四五六七八") = "六七八"（期望 "六七八"）
PASS trimRestartOverlap("资源时长两小时", "资源，时长两小时") = "资源，时长两小时"（期望 "资源，时长两小时"）
---- check_voice_slicer.cjs：21 PASS / 0 FAIL（7 切片 + 8 重吐裁剪 + 5 常量 + 1 旧名零命中）----
```

**既有契约不回退**：`check_contracts.py` 的 ①~㉑ 全部 PASS（含第四轮 C1~C5）；
`check_voice_slicer.cjs` 的 7 组 `sliceChunk` + 5 常量 + `sliceByPunctuation` 零命中全部 PASS。

---

## 第五轮 · 三、本轮脚本改动清单（全部在 `tests/**`）

| 文件 | 改动 |
|---|---|
| `tests/frontend/check_voice_slicer.cjs` | 新增第 2 组 **8 条 `trimRestartOverlap`** 断言（含用户实测「资源，时长两小时」原样用例）；原有 7 切片 + 5 常量 + 旧名零命中保留 → **21 项** |
| `tests/frontend/check_contracts.py` | 新增 **㉒ D1**（allowedHosts 恰 1 元素 + port/proxy/plugins 冻结 + 键路径区间）、**㉓ D2**（`if/else` 分支提取：续接 0 命中、新建会话 1 处、窗口计数）、**㉔ D3**（导出 + import + 追加路径前裁剪 + replaceTail 零命中 + **`resetLocalBuffer()` 复位 `resumedRestartFrames = 0`**）、**㉕ D4**（首条有效语句 + 五步顺序）；㉑ 中「无守卫只打 INFO」的旧观察分支改为**硬断言**（与 ㉕ 同口径）→ **21 → 25 项** |
| `tests/frontend/MANUAL_CHECKLIST.md` | 新增第 9 节 **M29~M31**（A 场景静默续接不重复 / B/C 场景说完立刻停 10 轮 / D 场景公网穿透 200 可登录）+ 第 10 节「第五轮未执行项汇总」；全部 `[ ]` + 原因 + 责任 + 解锁条件 |
| `tests/security/e2e_headless.py` | 新增 `probe_round5_source()`：**D1** vite 白名单、**D2** `start()` 分支结构、**D3** `trimRestartOverlap` 导出与接入、**D4** 首行守卫（独立复算，与契约检查不同实现路径）→ **48 → 52 项** |
| `tests/security/verify_delivery.py` | 新增 `check_round5_delivery()`：**D38** stage10 存在 + 5 节 + §1 两项反馈（录两遍/403）+ §2 根因关键词（`dedupTail`/`keepSession`/`B7`/`C5 收尾时序`）+ §4/§5 非占位 + §4 含实测计数；**D39** LOG「阶段 10」；**D40** 两份 README（`allowedHosts`/`takin.cc`/`dedupTail`/续接）→ **37 → 40 项** |
| `tests/security/pack_delivery.py` | `KEY_FILES` 追加 stage10；新增**二次开包校验**（包内 stage10 / ACCEPTANCE 与磁盘字节一致、唯一 VERDICT 可解析、stage10 占位时 VERDICT 不得为 PASS）+ 显式打印 `ENV_IN_ZIP` / `DB_IN_ZIP` |
| `tests/security/ACCEPTANCE.md` | 本文件（第五轮结论，唯一 `VERDICT`） |

> 未改动 `tests/backend/**`（后端本轮零改动，仅用 8060/8061 运行）；
> 未改动任何实现文件、`readme/`、`codearts_proof/`、plan 或 `.t1-voice-check` 源码
> （仅按任务要求重跑其构建产物 `bundle.mjs`）。

---

## 第五轮 · 四、复核轮实测计数（已用于 stage10 B 段回填）

- **后端**：`1404 PASS / 0 FAIL`（主验证 6 脚本：41 / 413 / 257 / 229 / 358 / 106）；KB 观测 **25**（不计判据）。
- **前端**：构建门禁 `4 / 0`；契约 `25 / 0`（㉔ 含 resetLocalBuffer 复位）；语音切片 `21 / 0`。
- **安全**：红线 `11 + 2 PASS-LOCAL / 0`；交付物 **`40 / 0`（EXIT=0，D38 复核转 PASS）**；无头 E2E `52 / 0`。
- **纯逻辑桩测**：`25 / 25`（场景 A14 + B7 + C4）。
- **合计通过**：**1584**（0 FAIL；41 DEFERRED 不计 PASS）。
- **本轮 FAIL**：**0**（首轮 D38 已随 stage10 B 段回填转 PASS）。
- **stage10 §4 已含**：`1583 / 1404 / 163 / SENSITIVE_IN_ZIP=0`（与实测一致；复核后总通过数为 1584）。
- **zip 四项与二次开包结果**：见 T4 任务总结（本文件不自记录字节数，避免写盘自指）。

---

## 第五轮 · 五、对抗性探针（本轮新增，真实执行）

| # | 探针 | 执行方式 | 结果 |
|---|---|---|---|
| **A10** | **断言判别力（D1~D4）**：临时副本注入 ① `allowedHosts` 重复元素 ② 续接分支加 `dedupTail = ''` ③ 删除 `trimRestartOverlap` 的 import ④ 守卫改成 `if (stopping) return` | 复制 `frontend/src` + `vite.config.ts` 到 `tests/frontend/.tmp-probe-frontend-v5b` → 注入 → `check_contracts.py --frontend <副本>` | **handled**：㉒/㉓/㉔/㉕ **四项全部 FAIL**（`RESULT: 19 passed, 6 failed`；另 2 项 FAIL 为副本缺 `node_modules` 的 ⑩ 环境项，与 D1~D4 无关） |
| **A11** | **`trimRestartOverlap` 判别力**：把函数体换成恒等 `return transcript` | 复制 `voiceSlicer.ts` 到 `.tmp-slicer-probe` → `tsc` 编译 → `check_voice_slicer.cjs` | **handled**：8 组中 **4 组 FAIL**（有重叠的 4 组），4 组「无重叠原样返回」按定义仍 PASS |
| **A12** | **D4 双结算**：`stopping` 已为 false 时再次调用 `commitStoppedSession()` | `.t1-voice-check` 场景 A/B（尾片计数） | **handled**：尾片恰好一次（A8 / B4） |
| **A13** | **续接重吐**：`fullText` 尾部与 transcript 前缀重叠 | 8 组纯函数用例 + 接入结构断言 | **handled**：最长后缀=前缀裁剪正确；无重叠原样返回；全重叠返回空串 |

> 探针临时副本与编译产物在结束后删除；未修改任何实现文件（只读复制后注入副本）。

---

## 第五轮 · 六、打包与二次开包校验

- 打包脚本 `tests/security/pack_delivery.py`；`KEY_FILES` 新增 stage10。
- 排除规则继承第四轮：`backend/.env`、`*.db*`、`.venv`、`node_modules`、`__pycache__`、`*.pyc`、
  `dist-t*`、`.tmp*`、`*.log`。
- 打印四项：`PACKED_FILES / ZIP_SIZE_MB / SENSITIVE_IN_ZIP / DIST_FILES_IN_ZIP`；
  **本文件不写具体字节数**，避免「写盘 → 改变包大小 → 再写盘」的自指循环（数字见 T4 任务总结）。
- **二次开包校验（本轮新增）**：包内 stage10 与磁盘字节一致、包内 ACCEPTANCE 与磁盘字节一致、
  唯一 `VERDICT` 可解析；且「stage10 第 4/5 节仍占位」时 `VERDICT` **不得**为 PASS。
  复核轮 stage10 已收口（占位 **0 命中**）+ `VERDICT: PASS` → 一致性规则**满足**。

---

## 第五轮 · 七、DEFERRED（41 项，不计 PASS）

第四轮 38 项继续有效；本轮新增 **3 项**（`MANUAL_CHECKLIST.md` 第 9 节，全部 `[ ]` + 原因 + 责任 + 解锁条件）：

| 编号 | 项 | 原因 | 责任 / 入口 |
|---|---|---|---|
| **M29** | 静默续接后同一句只出现一次（A 场景） | 需真实麦克风 + Edge 静默 `onend` 时序（plan `O-5-2`） | 演示负责人；`MANUAL_CHECKLIST.md` 第 9 节 |
| **M30** | 说完最后一个字立刻停止 ×10：末批必达、0 丢字 0 重复（B/C 场景） | 需真实麦克风反复 10 轮并核对后端记录 | 同上 |
| **M31** | 公网 `https://xxx.hn.takin.cc/` 返回 200 且可登录（D 场景） | 需真实 zeronews 穿透隧道（plan `O-5-1`） | 同上 |

> 计数：38（第四轮）+ 3（M29~M31）= **41 DEFERRED**。本机 `Host` 头模拟（200/403）与纯逻辑裁剪已自动化覆盖，
> 真实公网域名与真机听感仍如实记为 DEFERRED，不伪造 PASS。

---

## 第五轮 · 八、观察项（不判 FAIL，供 Leader 裁定）

| 编号 | 现象 | 判定与说明 |
|---|---|---|
| **O-T4-5-1**（**已修复/关闭**） | `resetLocalBuffer()` 未复位 `resumedRestartFrames`（plan R25-AC7 字面要求） | 复核轮 T2 已补 `resumedRestartFrames = 0`（附注释），`check_contracts.py` ㉔ 新增硬断言；复核 25/25、typecheck 通过、桩测 25/25 → **关闭** |
| **O-T4-5-2**（**已修复/关闭**） | stage10 §3 尚未登记 3 个契约 ID | 书记官 B 段回填已补齐：`C-DEV@1` / `C-VOICEUI@5` / `C-DELIVERY@5` 全文命中 **14** 次；D3 8 复核 PASS → **关闭** |
| **O-T4-5-3** | `frontend/run_all.sh` 步骤 2 失败会 `set -e` 跳过步骤 3 | 继承第四轮 O-T6-5；本轮步骤 2/3 均 PASS，不影响结论；建议后续改为无条件执行 |

---

## 第五轮 · 九、清理与环境证据

- 后端 8060 / KB 8061 / E2E 后端 8050 / preview 8051 进程均在脚本 `cleanup/finally` 中停止；临时 SQLite 与日志删除。
- 临时目录 `tests/frontend/.tmp-voice*`、`.tmp-probe-frontend-v5b`、`.tmp-slicer-probe`、`.tmp-slicer-out`
  与 `frontend/.t1-voice-check` 重新生成的 `bundle.mjs`（构建产物）已处理（后者为运行桩测所需，保留）。
- `frontend/dist` 为本轮正式 `npm run build` 产物（保留并打包）。
- 未删除 `.env` / `campus.db`；本报告仅修改 `tests/**`。

---

## 第五轮 · 十、结论（唯一 `VERDICT`）

第五轮 D1~D4 的实现与既有 P1~P4 回归**全部通过**：后端 **1404/0**、前端构建 **4/0**、契约 **25/0**、
切片 **21/0**、安全红线 **13/0**（11 PASS + 2 PASS-LOCAL）、交付物 **40/0**、无头 E2E **52/0**、
纯逻辑桩测 **25/25**；首轮唯一缺口 **D38** 已随 stage10 B 段回填转 **PASS**（占位 0 / 3 契约 ID /
268 行），**0 FAIL**，核心功能实测通过；41 项人工/真机项如实留作 DEFERRED。

```text
VERDICT: PASS
```

---

## 【历史·第四轮】一、最终结论

**结论：PASS（0 FAIL；38 项 DEFERRED 不计 PASS、亦不构成失败）。**
全文唯一的 `VERDICT` 行见第十一节；本节不重复该行。

**统计（复核后）：1565 项通过（含 2 项 PASS-LOCAL；其中 25 项 KB 观测不计失败判据）/ 0 FAIL / 38 DEFERRED。**

| 套件 | 命令 | 退出码 | PASS | FAIL | 备注 |
|---|---|---|---|---|---|
| 后端 6 脚本 | `T10_PORT=8050 T10_KB_PORT=8051 bash tests/backend/run_all.sh` | **0** | **1404** | **0** | 后端本轮零改动 → 零回归 |
| ├ KB 观测（unfiltered） | 同上（8051） | 0 | **25** | 0 | `similarity=[1.0,1.0,0.825]`，不计失败判据 |
| 前端 构建门禁 | `bash tests/frontend/run_all.sh` 步骤 1/2 | 0 | **4** | 0 | typecheck + vite build（1703 modules）+ dist + 无 `any` |
| 前端 契约检查 | `python tests/frontend/check_contracts.py` | **0** | **21** | **0** | 复核轮：⑲ 口径修正后 21/21 |
| 前端 语音切片单测 | `node tests/frontend/check_voice_slicer.cjs` | **0** | **13** | 0 | 步骤 2 失败被 `set -e` 中断，已单独复跑取证 |
| 安全 红线 | `bash tests/security/test_security_redline.sh` | **0** | **11 + 2 PASS-LOCAL** | 0 | A 层 0 命中；B 层本地运行时文件不在包内 |
| 安全 交付物 | `python tests/security/verify_delivery.py` | **0** | **37** | **0** | 复核轮：D35 随 stage9 回填转 PASS |
| 安全 无头 E2E | `python tests/security/e2e_headless.py` | **0** | **48** | **0** | 46 既有 + 2 新增（C1 源码 / C2 构建产物） |
| **合计** | — | — | **1565** | **0** | 见上表逐项 |

### 1.1 两轮执行与两项闭合（首轮 1563/2 → 复核 1565/0）

| 项 | 首轮结论 | 根因与处置 | 复核结论 |
|---|---|---|---|
| **⑲ C2 字号梯度** | FAIL（报 `AiPanel.vue` 5 处 `13px`） | **是断言口径错，不是实现缺陷**。Leader 核验基线：`AiPanel` 原为 **12px×5 / 13px×6 / 15px×2**；按 C2 映射（12→13、13→14、15→16）后应恰为 **13px×5 / 14px×6 / 16px×2**，与实测**完全吻合**。断言已改为「12px 归零 + 13px 恰 5 处且落在 5 个语义类 + 14px×6 + 16px×2」。**AiPanel 代码一行未改。** | **PASS** |
| **D35 stage9 收口** | FAIL（§3 缺 4 个契约 ID、§4/§5 占位） | 书记官完成 B 段回填：占位 **0 命中**；`C-VOICEUI@4=8 / C-TYPO@1=6 / C-TRACE@2=4 / C-DELIVERY@4=4`；§4 含 1404 / 1563 / 1.25 / `SENSITIVE_IN_ZIP=0`；§5 为 P1~P7（P6 明确记录「⑲ 是断言口径与 +1 映射矛盾，代码一行未改」）。 | **PASS** |

### 1.2 判定口径

- **Oracle 检查（本轮新契约）**：C1 默认 AI / C2 字号基线 / C3 块编辑零残留 / C4 留痕口径 / C5 收尾结构，
  以 plan P4 的 `C-VOICEUI@4` / `C-TYPO@1` / `C-TRACE@2` / `C-DELIVERY@4` 为唯一事实来源；
- **Consistency 检查（既有回归）**：P1~P3 的后端 9 表 / 报名审批 / 双人加分 / SSE 催办 / 链式增量 /
  前端 typecheck / build / P1~P3 契约（⑫~⑮）全部保持 PASS；
- `DEFERRED` 只表示本环境无法自动验证（真实麦克风 / 真实 MaaS / 浏览器 DOM 激活态与点击），**不计 PASS**；
- 后端全部使用**临时 SQLite 库 + `MAAS_MOCK=1` + `RUN_SCHEDULER=0`**，未污染仓库。

---

## 二、执行流与验证方法

1. **静态契约先行**：`check_contracts.py` 21 项（P1 5 + P2 6 + 第三轮 4 + 第四轮 6）与
   `check_voice_slicer.cjs` 13 项确认实现与契约对齐。
2. **后端回归**：`tests/backend/run_all.sh`（8050/8051）启动临时库后端，依次执行 6 个脚本；本轮后端零改动。
3. **构建与前端运行时**：`npm run typecheck` + `vite build` 生成**正式** `frontend/dist`（1703 modules），
   e2e 用该 dist 起 preview（8051）。
4. **安全与交付**：`test_security_redline.sh`、`verify_delivery.py`（37 项，含 D35~D37）、
   `e2e_headless.py`（48 项，含 C1/C2 探针）。
5. **纯逻辑时序单测**：`frontend/.t1-voice-check`（`node build.mjs && node bundle.mjs`）复跑 C5 的 A/B/C
   场景，**25 断言 PASS**（A14 + B7 + C4）。
6. **断言判别力对抗探针**：对 C1/C2/C3/C4 断言注入缺陷，验证其**会 FAIL**（防永真空断言），见第六节。
7. **复核轮**：修正 ⑲ 口径 → 重跑 `check_contracts.py`（21/0）、`verify_delivery.py`（37/0）、
   `test_security_redline.sh`（11+2/0）、`e2e_headless.py`（48/0）→ 重打交付包并二次开包校验。

说明：本轮为**体验微调迭代**（R21~R24），不是单点 bug-fix，因此不存在「补丁前 baseline」意义上的二阶段运行；
所有套件均在**最终实现**上运行，并用 P1~P3 断言做回归一致性检查。
C5 的「真机语音三条保证」与 C1 的「浏览器 Tab 激活态」按计划 `O-D4-1` / `O-D4-4` 记 **DEFERRED**。

---

## 三、本轮脚本改动清单（全部在 `tests/**`）

### 3.1 后端 `tests/backend/`

| 文件 | 改动 |
|---|---|
| （无） | 本轮后端零改动；`run_all.sh` 未改，仅以 `T10_PORT=8050 T10_KB_PORT=8051` 运行以避让演示端口 |

### 3.2 前端 `tests/frontend/`

| 文件 | 改动 |
|---|---|
| `check_contracts.py` | **① 删除第三轮 ⑯ `check_block_text_v3`**（`trigger=[]` / `if (editing.value) return` / document 外部点击 / popperClass 正向断言与 C3 直接冲突），替换为第四轮 `check_block_text_v4` 反向断言；**② 修正 ⑦ `check_block_kinds`**：去掉「必须有 `el-popover`」「必须有 `v-else`」两条已被 C3 推翻的断言，改为「**禁止** `el-popover` + 必须有 `el-tooltip`」；③ 新增 ⑰C1 / ⑱C2(typography+main.ts) / ⑲C2(字号梯度) / ⑳C4 / ㉑C5 共 6 项（16 → 21 项）；④ 新增 `function_body()` / `arrow_property_body()` 符号锚定工具（括号配对跳过 `start(options = {})` 默认值对象）；⑤ 零残留扫描关键字用**字符串拼接**构造，避免检查器自指假命中；⑥ **复核轮修正 ⑲**：删除「AiPanel 不得出现 13px」判据，改为「12px 归零 + 13px 恰 5 处且选择器集合等于 5 个语义类 + 14px×6 + 16px×2」，并新增 `css_font_size_selectors()` 辅助（按行回溯取选择器，把处数与语义类绑定） |
| `MANUAL_CHECKLIST.md` | 新增第 7 节 **M23~M28**（C1 默认 AI 与切 Tab 保活 / C2 四页字号目视 / C3 点块不弹框 / C4 解析无紫块且三类采纳出紫块 / C5 末批必达+不重复+两 agent 顺序 / C5 停 1 秒再停与连续 10 次），新增第 8 节「第四轮未执行项汇总」；未执行项一律 `[ ]` + 原因 + 责任 + 解锁条件 |
| `run_all.sh` | 未改（仍为 构建门禁 → 契约 → 语音三步） |

### 3.3 安全 `tests/security/`

| 文件 | 改动 |
|---|---|
| `e2e_headless.py` | 端口 8040/8042 → **8050/8051**；新增 `probe_round4_source()`：**C1 源码级断言**（`ref<PublishMode>('ai')` + 双 `v-show` 面板 + `.mode-panel` 无 `v-if`，docstring 说明为何不能用构建产物/DOM）+ **C2 构建产物断言**（dist CSS 含 `--el-font-size-base:15px` / `small:14px` / `extra-small:13px`）；既有 46 项全部保留 → 48 项 |
| `verify_delivery.py` | 新增 `check_round4_delivery()`：**D35** stage9 存在 + 5 节 + §1 覆盖 C1~C5 + §2 含 v1/否决/（覆盖\|反转\|作废）+ §3 含 4 个契约 ID + **§4/§5 非占位**；**D36** LOG 含「阶段 9」；**D37** 两份 README 四项语义正则 → 37 项 |
| `pack_delivery.py` | `KEY_FILES` 追加 `codearts_proof/ai_dialogue/stage9_第四轮体验微调.md` |
| `ACCEPTANCE.md` | 本文件（第四轮最终结论，唯一 `VERDICT`） |

---

## 四、执行结果明细（真实命令、退出码、断言数）

### 4.1 后端 `T10_PORT=8050 T10_KB_PORT=8051 bash tests/backend/run_all.sh` → **EXIT=0**

| 脚本 | 断言数 | 结果 | 关键输出 |
|---|---|---|---|
| `verify_tables.py` | 41 | **PASS** | 9 表齐全；`task_applications` 唯一约束；`health.tables` 9 项 |
| `test_applications.py` | 413 | **PASS** | 报名/审批/满额 4090/撤回/双人各 +20 幂等/双人签到/legacy/`scope=mine` |
| `test_api_e2e.py` | 257 | **PASS** | apply→approve→claimed 全流程；4010/4030/4040/4001 矩阵；`credited_user_ids` 两人 |
| `test_agent_mock.py`（default） | 229 | **PASS** | P1 规则逐条；三片累计原文；简单任务拆解 `[]`；晚会类 2~6 条；介绍文案 ≥20 字 |
| `test_agent_incremental.py` | 358 | **PASS** | `extract_stream` 三参；payload 三键且无累计原文；`join_style_prompt` 8 组；`needs_intro` 6 组；三片链式 changes 逐步收窄；纯值红线 |
| `test_sse_and_reminder.py` | 106 | **PASS** | 5 秒内 `event: notify`；三级催办；逾期 -10；二次扫描 0 新增 |
| KB 观测（8051，unfiltered） | 25 | **PASS（不计失败判据）** | `similarity=[1.0,1.0,0.825]`、top≤3、降序 |

> 后端主验证合计 **1404 PASS / 0 FAIL**；含 KB 观测共 **1429** 行 PASS。
> 清理：`INFO: 已停止 8050/8051 后端进程；临时数据库与日志已删除`。

### 4.2 前端

| 命令 | 退出码 | 结果 | 关键输出 |
|---|---|---|---|
| `bash tests/frontend/run_all.sh`（首轮，步骤 1/2） | 0 | **4 PASS / 0 FAIL** | `typecheck 通过`；`vite build` 成功（**1703 modules**）；`dist/index.html 424 字节`；`: any / as any` 无命中 |
| `python tests/frontend/check_contracts.py`（**复核轮**） | **0** | **21 PASS / 0 FAIL** | ⑯ 块编辑零残留（扫描 46 文件，4 个残留符号全仓 0）；⑰ `activeTab='ai'` + 双 `v-show`；⑱ 6 变量 + 顺序（index.css 第 4 行 → typography.css 第 5 行 → App.vue 第 7 行）；**⑲ PASS**：`12px=0`、`13px=34 / 14px=34 / 15px=7 / 16px=11`，AiPanel `12→0 / 13→5（5 语义类）/ 14→6 / 16→2`；⑳ 三处显式采纳留痕；㉑ stopping/onend/兜底/顺序全通过 |
| `node tests/frontend/check_voice_slicer.cjs` | 0 | **13 PASS / 0 FAIL** | 7 组切片；5 常量 1/12/800/800/200；`sliceByPunctuation` 源码 0 命中 |

**⑲ 复核输出原文（关键段）**

```text
[19/21] PASS  ⑲ C-TYPO@1 C 字号 +1 梯度：12px 归零 + BlockText/AiPanel 集合 + 逐文件分布
        `font-size: 12px` 全局 0 处（含排除 BlockText/AiPanel 后 0 处）；
        分布 13px=34 / 14px=34 / 15px=7 / 16px=11；
        components/VoiceComposer/BlockText.vue 集合={16px,15px}；
        components/Publish/AiPanel.vue 基线映射正确：12px→0 处、13px→5 处（原 12px×5，
        落在 ['.composer__hint','.composer__legend','.polished__label','.publish-bar__reason','.review__note']）、
        14px→6 处（原 13px×6）、16px→2 处（原 15px×2）；逐文件分布见上方 INFO 清单
RESULT: 21 passed, 0 failed
```

**C2 字号真实分布（`src/**/*.vue`，逐文件）**

| 文件 | 13px | 14px | 15px | 16px | 其它 |
|---|---|---|---|---|---|
| `components/Publish/AiPanel.vue` | 5 | 6 | 0 | 2 | — |
| `components/Publish/ManualForm.vue` | 1 | 0 | 0 | 0 | — |
| `components/Publish/SimilarTip.vue` | 1 | 1 | 1 | 0 | — |
| `components/Publish/SubTaskCard.vue` | 3 | 1 | 0 | 1 | — |
| `components/VoiceComposer/BlockText.vue` | 0 | 0 | 1 | 1 | — |
| `components/VoiceComposer/FieldPanel.vue` | 0 | 1 | 0 | 0 | — |
| `components/VoiceComposer/VoiceButton.vue` | 1 | 1 | 0 | 0 | — |
| `components/VoiceComposer/WarnBubble.vue` | 1 | 2 | 0 | 0 | 11px×1（不在 +1 范围） |
| `components/admin/AssignDialog.vue` | 1 | 0 | 0 | 0 | — |
| `components/admin/ReminderRuleForm.vue` | 1 | 0 | 0 | 0 | — |
| `components/common/EmptyState.vue` | 0 | 1 | 0 | 0 | — |
| `components/common/LoadingState.vue` | 0 | 1 | 0 | 0 | — |
| `components/task/SopSteps.vue` | 1 | 1 | 0 | 0 | — |
| `components/task/SubTaskTree.vue` | 4 | 1 | 1 | 0 | — |
| `components/task/TaskCard.vue` | 2 | 2 | 0 | 1 | — |
| `layouts/AppLayout.vue` | 0 | 0 | 1 | 1 | — |
| `views/AdminConsole.vue` | 3 | 1 | 0 | 2 | 20px×1 |
| `views/LoginPage.vue` | 1 | 1 | 0 | 0 | 22px×1 |
| `views/Profile.vue` | 7 | 5 | 1 | 2 | 18/20/26px 各 1 |
| `views/PublishPage.vue` | 0 | 1 | 1 | 0 | 20px×1 |
| `views/TaskDetail.vue` | 1 | 6 | 1 | 1 | 20px×1 |
| `views/TaskHall.vue` | 1 | 2 | 0 | 0 | 20px×1 |
| **全局合计** | **34** | **34** | **7** | **11** | 11px×1（WarnBubble） |

**「原 15px 处数 = 现 16px 新增处数」核对**（以第三轮 `dist` 组件级 CSS chunk 作为迁移前快照，
快照时间 16:17，早于本轮施工）：

| 文件组（dist chunk） | 迁移前 12/13/14/15/16 | 迁移后 13/14/15/16 | 核对 |
|---|---|---|---|
| `Profile`（单文件） | 7 / 5 / 1 / **1** / 1 | 7 / 5 / 1 / **2** | 12→13、13→14、14→15 逐档吻合；**现 16px 2 = 原 15px 1 + 原 16px 1** ✔ |
| `TaskDetail` 组（TaskDetail+SopSteps+SubTaskTree） | 6 / 8 / 2 / **1** / 0 | 6 / 8 / 2 / **1** | 四档逐档吻合；**现 16px 1 = 原 15px 1** ✔ |
| `AdminConsole` 组（AdminConsole+ReminderRuleForm+AssignDialog） | 5 / 1 / 0 / **2** / 0 | 5 / 1 / 0 / **2** | **现 16px 2 = 原 15px 2** ✔ |
| `TaskHall`（单文件） | 1 / 2 / 0 / 0 / 0 | 1 / 2 / 0 / 0 | 无 15/16px，吻合 ✔ |
| `LoginPage`（单文件） | 1 / 1 / 0 / 0 / 0 | 1 / 1 / 0 / 0 | 无 15/16px，吻合 ✔ |
| `BlockText` | — / — / — / **1** / 0 | 0 / 0 / **1** / **1** | raw 15→16、追溯 14→15 ✔ |
| `AiPanel`（按 Leader 核验基线） | **12×5 / 13×6 / — / 15×2** | 13×**5** / 14×**6** / — / 16×**2** | **四档逐档吻合**（原 12→13、13→14、15→16）✔ |

> 结论：7 组「原 15px 处数 = 现 16px 新增处数」核对**全部成立**。

### 4.3 安全 / 交付 / 无头 E2E（复核轮）

| 检查 | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 安全红线 | `bash tests/security/test_security_redline.sh` | **0** | **11 PASS + 2 PASS-LOCAL / 0 FAIL**（A 层 0 命中；B 层 `.env`/`*.db` 被 `.gitignore` 覆盖且不入包） |
| 交付物 | `python tests/security/verify_delivery.py` | **0** | **37 PASS / 0 FAIL**：**D35 PASS**（stage9 5 节 / 4 契约 ID / 占位 0）、D36 PASS、D37 PASS |
| 无头 E2E | `python tests/security/e2e_headless.py` | **0** | **48 PASS / 0 FAIL**：46 既有 + `C1 发布页默认 AI（源码断言）` + `C2 构建产物含字号基线变量` |

**D35 回填证据（复核实测）**

| 证据项 | 实测 |
|---|---|
| stage9 二级标题 | 5 个（用户反馈 / Leader 决策与核验修正 / 派工与契约要点 / 真实产出 / 真实问题与修复） |
| 占位标记 | **0 命中**（`待 T1` / `待补写` / `B 段待补` / `（待` 全无） |
| 契约 ID 命中 | `C-VOICEUI@4=8`、`C-TYPO@1=6`、`C-TRACE@2=4`、`C-DELIVERY@4=4` |
| §4 实测数字 | 后端 1404 / 首轮合计 1563 / `ZIP_SIZE_MB=1.25` / `SENSITIVE_IN_ZIP=0` / `DIST_FILES_IN_ZIP=20` |
| §5 | P1~P7（P6 记录「⑲ 是断言口径与 +1 映射矛盾，代码一行未改」） |

### 4.4 C5 纯逻辑时序单测 `frontend/.t1-voice-check` → **EXIT=0**

| 场景 | 断言数 | 结果 | 关键证据 |
|---|---|---|---|
| A：片1 → stop → 晚到片2 → onend 延迟结算 | 14 | **PASS** | A4 stop 后无新增发送；A5 晚到帧入 pendingText；A8 尾片恰好一次（count=1）；A9 尾片内容=晚到文字；A10 总发送=片1+尾片（无重复）；A12 顺序 applyStream(9)→finishStreaming(11)→onAllChunksSent(12)；A14 通知恰好一次 |
| B：onend 丢失 → 3s 兜底结算 | 7 | **PASS** | B4 兜底到点尾片恰好一次；B5 兜底尾片含晚到文字；B7 兜底路径同样触发一次 review |
| C：空尾片 | 4 | **PASS** | C1 空尾片不产生额外请求；C2 仍结束 streaming；C3 仍通知一次 review |
| **合计** | **25** | **PASS** | `=== 结果：全部通过 ===`（任务书口径写「28」，实测为 A14+B7+C4=**25**，以实测为准） |

---

## 五、需求逐条判定（DEFERRED 不计 PASS）

### 5.1 R21 默认模式与字号基线（C1 / C2，9 条）

| 条目 | 判定 | 依据 |
|---|---|---|
| R21-AC1 默认 AI 智能模式 | **PASS（静态）/ DEFERRED（DOM 激活态）** | ⑰：`ref<PublishMode>('ai')` + 注释；e2e C1 源码探针 PASS；浏览器激活态 → M23 |
| R21-AC2 双面板 `v-show` 保活 | **PASS（静态）/ DEFERRED（切换后草稿保留）** | ⑰：两个 `.mode-panel` 均 `v-show`，无 `v-if="activeTab`；切换行为 → M23 |
| R21-AC3 切 Tab 草稿保留 | **DEFERRED** | 需浏览器交互 → M23（`useDraftStore()` 单例 + `v-show` 为静态依据） |
| R21-AC4 typography.css 6 变量 | **PASS** | ⑱：22/18/16/15/14/13px 逐字一致，无 color/font-family/`*`/rem/clamp |
| R21-AC5 main.ts 引入顺序 | **PASS** | ⑱：`index.css` 第 4 行 → `typography.css` 第 5 行 → `App.vue` 第 7 行；`color-pool.css` 保留 |
| R21-AC6 12/13/14/15 → 逐处 +1 | **PASS** | ⑲：全局 12px=0；7 组映射核对全部吻合（含 AiPanel 12×5→13×5、13×6→14×6、15×2→16×2） |
| R21-AC7 `font-size: 12px` 归零 | **PASS** | ⑲：全局 12px=0（含排除 BlockText/AiPanel 后 0；AiPanel 单独 0） |
| R21-AC8 无 rem/vw/scale、无色值改动 | **PASS** | ⑱ 无 rem/clamp；⑪ 无新增硬编码色值（93 行基线内、4 追溯色 0 命中） |
| R21-AC9 ≥20px 标题不动 | **PASS** | 分布表：20/22/26px 各文件保持不变；BlockText 集合恰 `{15px,16px}` |

### 5.2 R22 块交互收敛与留痕（C3 / C4，11 条）

| 条目 | 判定 | 依据 |
|---|---|---|
| R22-AC1 点击块不弹浮层/不抛错、仅高亮 | **PASS（静态）/ DEFERRED（点击 10 次）** | ⑯：`el-popover`/`editing`/`draftText`/`confirmEdit`/`cancelEdit`/`onDocumentPointerDown`/`popperClass`/`block-editor` 全 0；`emit('select')` 保留；点击行为 → M25 |
| R22-AC2 raw 块纯展示 + 光标与追溯块一致 | **PASS（能力）/ 观察项（cursor 取值）** | 单一 span + 单选入口；`cursor: pointer` 两侧一致（plan `§B-2` 写 `default`、`O-D4-6` 写「与追溯块一致」，两处口径冲突 → 观察项 O-T6-1，不计 FAIL） |
| R22-AC3 非 raw 块 `el-tooltip` 展示 reason | **PASS** | ⑯：`<el-tooltip :disabled="!isTraceBlock"` + `tooltipContent` 优先 reason |
| R22-AC4 AiPanel 无覆盖态/编辑入口 | **PASS** | ⑯：全仓 `blockOverrides`/`resolveBlockFieldKey`/`onEditBlock`/`@edit=` 0；`displayBlocks` 直接 `[...draft.blocks]` + live 虚拟块 |
| R22-AC5 右侧改字仍写字段 + `user_edit` + 清角标 | **PASS（静态）/ DEFERRED（浏览器）** | ⑯：`draft.setField(` 保留；⑳：`pushTraceBlock('user_edit'` 保留；⑬：corrections 只警示；M25 |
| R22-AC6 增量解析追加补充块并落值 | **PASS（静态）/ DEFERRED（浏览器）** | ⑯：`draft.applyExtractIncremental(` 保留；⑳：`appendUserNote` 保留；M25 |
| R22-AC7 清空文案不再引导块内编辑 | **PASS** | ⑯：含「请在右侧字段面板编辑对应字段，或补一句话做增量解析」；`点击左侧文字块` 0 命中 |
| R22-AC8 解析不生成 `ai_applied` | **PASS** | ⑳：`applyExtract` / `applyExtractIncremental` 体内 `ai_applied` 0 |
| R22-AC9 三处显式采纳留痕 | **PASS** | ⑳：`pushTraceBlock('ai_applied'` 恰 3 处，按函数边界定位到 adoptChange/adoptSuggestion/adoptPolished |
| R22-AC10 `appliedTextAt` 零命中 + 3 处 | **PASS** | ⑳（含别名零命中） |
| R22-AC11 发布请求体无「AI建议：」 | **PASS（静态）/ DEFERRED（真实请求体）** | ⑧ `toTaskPayload` 只读 fields 且函数体零 `blocks`；⑳ `res.applied_texts` 不消费；真实抓包 → M26 |

### 5.3 R23 语音收尾（C5，10 条）

| 条目 | 判定 | 依据 |
|---|---|---|
| R23-AC1 stop 只置窗口 + 3s 兜底 | **PASS** | ㉑：`stop()` 体内有 `stopping = true` / `FORCE_FINALIZE_MS`，**无** `resetLocalBuffer(` / `enqueue(` / `FINAL_DELAY_MS` |
| R23-AC2 onend 延迟 FINAL_DELAY_MS 提交唯一尾片 | **PASS** | ㉑：`onend` 含 `if (stopping)` → `finalizeTimer = setTimeout(..., FINAL_DELAY_MS)` → `commitStoppedSession()`；场景 A8 尾片 count=1 |
| R23-AC3 未停止时 Edge 静默续接（互斥） | **PASS（静态）/ DEFERRED（Edge 真机）** | ㉑：`onend` 两分支互斥；场景 A 验证停止分支不续接；真机 → M27/M20 |
| R23-AC4 窗口内保帧但不零散切片 | **PASS** | ㉑：`scheduleSlices()` 首条 `if (stopping) return`；`handleRecognitionResult` 仍调 `applyFinal/applyInterim`；场景 A5/A6 |
| R23-AC5 尾片成功后复位缓冲 + 收尾链 | **PASS** | ㉑：`drain()` 保留 `resetLocalBuffer()`；`finalizeIfIdle()` = `finishStreaming()` → `notifyAllChunksSent()`；场景 A13 |
| R23-AC6 开始/中止清 stopping 与定时器 | **PASS** | ㉑：`start()` / `abort()` 均含 `stopping = false` + 两定时器清理 |
| R23-AC7 末批必达 | **DEFERRED（真机）/ PASS（逻辑）** | 场景 A9「尾片内容=晚到文字」、B5「兜底尾片含晚到文字」；真机 → M27 |
| R23-AC8 不重复 | **DEFERRED（真机）/ PASS（逻辑）** | 场景 A10「总发送=片1+尾片，无重复 partial」、A8/B4「尾片恰好一次」；真机 → M27/M28 |
| R23-AC9 两 agent 顺序 | **DEFERRED（真机）/ PASS（逻辑）** | 场景 A12 顺序 `applyStream(9) → finishStreaming(11) → onAllChunksSent(12)`；㉑ `finalizeIfIdle` 顺序断言；真机 → M27 |
| R23-AC10 不改 voiceSlicer 5 常量 | **PASS** | ㉑ + `check_voice_slicer.cjs`：1/12/800/800/200 不变；`FINAL_DELAY_MS` 语义保持尾帧窗口 |

### 5.4 R24 留痕与终验（7 条）

| 条目 | 判定 | 依据 |
|---|---|---|
| R24-AC1 stage9 五节 | **PASS** | D35：5 个二级标题齐全 |
| R24-AC2 LOG / prompt / 两份 README | **PASS** | D36 LOG「阶段 9」；D37 两份 README 四项；P-009 存在 |
| R24-AC3 B 段与最终代码/实测一致 | **PASS** | D35：占位 0、4 契约 ID 命中、§4 数字（1404/1563/1.25/`SENSITIVE_IN_ZIP=0`）、§5 为 P1~P7 且 P6 与实测一致 |
| R24-AC4 前端契约检查按新口径 | **PASS** | ⑯~㉑ 已落地；旧 ⑯ 正向断言已**删除**而非叠加；⑲ 口径按 Leader 核验修正 |
| R24-AC5 全部通过并输出唯一 VERDICT | **PASS** | 前端契约 21/0、交付 37/0、E2E 48/0、红线 13/0、后端 1404/0 |
| R24-AC6 重打 zip 且不含敏感/依赖 | **PASS** | 见第九节：`SENSITIVE_IN_ZIP=0`，排除 `.env/*.db/.venv/node_modules/__pycache__/dist-t*/.tmp*` |
| R24-AC7 区分自动化可证与人工项 | **PASS** | 本报告第五节逐条标注 PASS / DEFERRED；DEFERRED 38 项见第八节 |

### 5.5 P1~P3 回归

**PASS**：后端 9 表、报名审批矩阵（413）、REST 全流程（257）、SSE 催办（106）、链式增量（358）、
前端 typecheck/build（4）、P1 5 项 + P2 6 项 + 第三轮 4 项契约（⑫~⑮）全部保持 PASS。

---

## 六、对抗性探针（主动破坏性验证）

| # | 探针 | 真实执行方式 | 结果 |
|---|---|---|---|
| A1 | **断言判别力（C3）**：向 `BlockText.vue` 注入 `el-popover v-model:visible="editing"` | 复制 `frontend/src` 到系统临时目录 → 注入 → 调用 `check_block_text_v4` | **handled**：基线 PASS，注入后 **FAIL**（命中「编辑浮层」） |
| A2 | **断言判别力（C1）**：把 `ref<PublishMode>('ai')` 改回 `'manual'` | 同上（临时副本） | **handled**：注入后 **FAIL**（定位 `manual` 旧默认值） |
| A3 | **断言判别力（C4）**：注入 `function appliedTextAt()` | 同上（临时副本） | **handled**：注入后 **FAIL**（`appliedTextAt` 命中） |
| A4 | **断言判别力（C2）**：向 `TaskHall.vue` 注入 `font-size: 12px` | 同上（临时副本） | **handled**：注入后 **FAIL** 且**单独定位到 `TaskHall`** |
| A5 | **断言判别力（⑲ 新口径）**：① 把 `.review__note` 的 13px 改回 12px；② 重命名 13px 的选择器 | 同上（临时副本） | **handled**：① **FAIL**「12px 仍有 1 处（AiPanel）」；② **FAIL**「13px 选择器集合与基线映射证据不一致」——证明新口径不是永真 |
| A6 | **空尾片**：停录时无待发文本 | `.t1-voice-check` 场景 C | **handled**：空尾片不产生额外请求、仍结束 streaming、仍通知一次 review |
| A7 | **onend 丢失**：3s 兜底是否重复发尾片 | `.t1-voice-check` 场景 B | **handled**：尾片 count=1、含晚到文字、无额外 partial、review 恰好一次 |
| A8 | **晚到帧重复**：stop 后浏览器补发最后一帧 | `.t1-voice-check` 场景 A | **handled**：晚到帧进缓冲（保帧）、不触发零散切片、总发送=片1+尾片 |
| A9 | **打包洁净**：包内敏感文件扫描 | 标准库 `zipfile` 二次开包 | **handled**：`SENSITIVE_IN_ZIP=0`；包内无 `.env` / `*.db`（见第十节） |

> A1~A5 是**对检查器自身**的破坏性验证（防止「读代码 → 写 PASS」式空断言）；
> A6~A8 是 C5 的运行时等价时序验证；真机麦克风场景仍 DEFERRED。

---

## 七、观察项（不判 FAIL，供 Leader 裁定）

| 编号 | 现象 | 判定与说明 |
|---|---|---|
| **O-T6-1** | `BlockText.vue:95` 为 `cursor: pointer`，plan `§B-2` 字面要求 `cursor: default` 且「不得再出现 `cursor: pointer`」 | plan `O-D4-6` 自身写「契约只固定『cursor 与追溯块一致』与『@select 保留』」——两处口径冲突；T3 注释明确写「光标与 raw 块统一为 pointer（点击只做高亮定位）」，属**有意设计**且不构成「可编辑」暗示。→ 观察项；若要求字面合规，T3 改 1 行 CSS |
| **O-T6-2** | `commitStoppedSession()` **没有** plan `C-5` 要求的首行 `if (!stopping) return` | 幂等实际由三处协同保证：`stop()` 的 `if (forceFinalizeTimer \|\| finalizeTimer) return` 防重入、`onend` 先清 3s 兜底、3s 兜底先 `detachRecognition()` 再结算；场景 A8/B4 实测「尾片恰好一次」。→ 结构写法不同但行为等价；若需字面合规，T1 加 1 行守卫 |
| **O-T6-3** | `useVoiceComposer.ts:156` 注释中提及旧名 `stopTimer`（「由原 `stopTimer` 重命名而来」） | 去注释后代码 0 命中（无声明/别名），属重命名演进说明，不违反 `Q5` |
| **O-T6-4**（**已关闭**） | 首轮曾把 `AiPanel` 的 5 处 `13px` 与 2 处 `16px` 视为超范围 | **Leader 核验基线为 12px×5 / 13px×6 / 15px×2**，映射后恰为 13×5 / 14×6 / 16×2 → 全部合规。观察项关闭（对应第七节 O-T6-4 与首轮 ⑲ FAIL 的误判） |
| **O-T6-5** | 前端 `run_all.sh` 在步骤 2 失败后 `set -e` 会跳过步骤 3（语音单测） | 复核轮已单独复跑 `check_voice_slicer.cjs`（13 PASS / 0 FAIL）取证；建议后续把步骤 3 改为无条件执行（超出本轮 `tests/frontend/run_all.sh` 授权改动范围，未改） |

---

## 八、DEFERRED 清单（38 项，不计 PASS）

| 编号 | 项 | 原因 | 责任 / 入口 |
|---|---|---|---|
| **M23** | 发布页首次进入即 AI Tab 激活 / 切手动再切回草稿保留 | 需浏览器 DOM 激活态（无 Playwright/Selenium） | 演示负责人；`MANUAL_CHECKLIST.md` 第 7 节 |
| **M24** | 四页字号目视 +1px 不破版 | 需人眼比对版面 | 同上 |
| **M25** | 点击任意块不弹编辑框、仅高亮；改字走右侧/增量 | 需浏览器点击 + Console | 同上 |
| **M26** | 解析后左侧无紫块；三类显式采纳仍出紫块 | 需浏览器点击 + Network 抓包 | 同上 |
| **M27** | 语音末批必达 / 不重复 / 两 agent 顺序（真机） | 需真实麦克风 + 原生识别时序（`O-D4-4`） | 同上 |
| **M28** | 停 1 秒再停 / 连续 10 次立刻停止（0 丢 0 重复） | 同上 | 同上 |
| M1~M22 | P1/P2/第三轮人工项（语音切片、尾句、气泡、润色、拆解、红点、后台、签到、增量、报名审批、我的报名、B1/B3/B6/B11） | 需浏览器/麦克风/双会话 | 演示负责人；`MANUAL_CHECKLIST.md` 第 1/2/5/6 节 |
| O1 | 真实 MaaS 增量解析 + 介绍文案 | 无真实凭证，统一 `MAAS_MOCK=1` | 演示负责人 |
| O2 | interim 真实刷新频率 ≤200ms | 依赖设备/浏览器版本 | 演示负责人 |
| O3 | Edge 长静默后 `onend` 续接 | 需 Edge + 真实麦克风 | 演示负责人 |
| O4 | 高并发 SQLite（database is locked） | 本轮不做并发压测（路由已 4090 兜底） | 演示负责人 |
| O5 | 真实 MaaS `thinking` 关闭与 `reasoning_content=None` | 无 `MAAS_API_KEY` | 演示负责人 / Leader |
| X01 | 干净环境全量重装复现 | 需联网下载 PyPI/npm | 演示环境负责人 |

> 计数口径：M23~M28 = 6；M1~M22 = 22；O1~O5 = 5；X01 = 1 → **合计 34 个编号**，其中 M1~M22 与
> 第三轮 32 项清单中的 B1/B3/B6/B11 分项按 4 项计（32 = 4 + 22 + 5 + 1）→ 本轮 **32 + 6 = 38 DEFERRED**。

---

## 九、打包与包内自检

- 打包脚本：`tests/security/pack_delivery.py`（Python 标准库 `zipfile`）。
- 目标：项目根 `campus-task-agent-delivery.zip`，遍历 `campus-task-agent/`。
- 排除：`backend/.env`、`*.db / *.db-journal / *.db-wal / *.db-shm / *.sqlite*`、`backend/.venv/`、
  `frontend/node_modules/`、`__pycache__/`、`*.pyc`、`.tmp*`、`dist-t*`、`*.log`。
- 保留：`frontend/dist/`（本轮正式构建产物，1703 modules）、`readme/install.sh`、`codearts_proof/` 全部留痕。
- 关键文件清单含 `codearts_proof/ai_dialogue/stage9_第四轮体验微调.md`（确认包内为**回填后**版本）。
- 四项自检（`PACKED_FILES / ZIP_SIZE_MB / SENSITIVE_IN_ZIP / DIST_FILES_IN_ZIP`）与
  **二次开包校验**结果（stage9 回填版本 / ACCEPTANCE 唯一 VERDICT / 无 `.env` 与 `*.db`）
  见第十节与 T6 任务总结（本文件不自记录 zip 字节数，避免「写盘→改变包大小→再写盘」的自指循环）。

---

## 十、清理与环境证据

- 后端 8050 / KB 8051 / E2E 8051 进程在脚本 `finally/cleanup` 中停止；临时 SQLite 与日志删除。
- `tests/frontend/.tmp-voice`、`.tmp-trace-*` 跑完即删；对抗探针临时目录（`probe-src-*` / `probe-c2-*`）跑完即删。
- `frontend/dist/index.html` 424 字节，为本轮正式构建产物（保留并打包）。
- 本报告仅修改 `tests/**`；未修改实现、`readme/`、`codearts_proof/`、plan；未新增运行依赖；
  未删除 `.env` / `campus.db`。

---

## 【历史·第四轮】十一、结论

第四轮契约（C1 默认 AI、C2 字号 +1、C3 块编辑零残留、C4 解析不留痕、C5 收尾 v2）与 P1~P3 全量回归
**全部通过**：前端契约 **21/0**（退出码 0）、交付核验 **37/0**（退出码 0）、无头 E2E **48/0**（退出码 0）、
安全红线 **13/0**（11 PASS + 2 PASS-LOCAL，退出码 0）、后端 **1404/0**（退出码 0）、语音算法 **13/0**、
C5 纯逻辑时序 **25/25**。首轮的两项 FAIL 已分别以「**断言口径修正**（⑲，代码未改）」与
「**stage9 B 段回填**（D35）」闭合；无 FAIL，核心功能实测通过，38 项人工/真机项如实留作 DEFERRED。

```text
【历史记录】第四轮结论为 PASS（1565 / 0 / 38 DEFERRED）。全文唯一 VERDICT 行已移至
「第五轮 · 十、结论」，此处不再输出 VERDICT 行，避免多结论并存。
```