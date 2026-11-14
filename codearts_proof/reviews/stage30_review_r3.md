# stage30 独立代码审查（第 3 轮 · 终审）

- 审查角色：独立 Review Agent（CodeArts，只读复核，不修改业务代码）
- 审查范围：**仅第 2 轮遗留项（I-4、I-5）与 AC-18 侧栏叠压的新增修复，以及其相关回归**；不重审已关闭且未变化的代码
- 依据：`codearts_proof/reviews/stage30_review_r1.md`、`stage30_review_r2.md`、`.codeartsdoer/plans/aiw14-workbench-library-search/design.md` §3/§6/§9
- 日期：2026-11-14 17:2x
- 工作区状态：未提交改动；本轮只读，未改动任何文件

## 复核基线（当前工作区 blob，前 12 位）

```
AppLayout.vue        556af93362a3   （r2 基线 3f216f563001，已变）
TaskHall.vue         6de41e55f795   （r2 基线 fedf7bd38503，已变）
SearchOverlay.vue    d317c62a9cb6   （r2 基线 164d8202a53c，已变）
```

三处均与第 2 轮基线不同，符合“针对遗留项再修复”的前提，未发现无关文件被本轮改动。

## 本轮实跑的验证（不采信实现者结论）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `python tests/frontend/check_contracts.py --frontend frontend` | 0 | `RESULT: 32 passed, 0 failed`（项数与 r1/r2 一致，未破坏既有 32 项静态契约） |
| `cd frontend && npm run typecheck` | 0 | `vue-tsc --noEmit` 无输出，0 error |
| `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw09_history.py tests/backend/test_aiw14_library_search.py -q` | 0 | `29 passed in 3.16s` |

未执行：浏览器交互验收、前端重建、语音套件、后端全量 `run_all.sh`、真机与真实模型。
**注意**：仓库内唯一浏览器证据 `codearts_proof/reports/aiw14-browser.md`（17:07）与 `screenshots/aiw14-sidebar.png`（17:06）是**本轮修复前**的产物，其中 AC-18（「消息」被覆盖）与 AC-22（点击结果 q/from 为 null）仍记为 FAIL；本轮修复无对应的浏览器复核证据（见 N-7）。

---

## 逐条复核结论

### I-4 首次进入详情 push、切选 replace —— **已修复**

- 证据：`frontend/src/views/TaskHall.vue:364-377`
  - `selectCard`：移动端仍 `router.push({ name: 'activity' | 'detail', params: { id } })`（365-368）；
  - 分栏场景先记录 `restoreScrollTop`（369），再按 `detailId.value === null` 分流：首次进入用 `router.push(target)`，已在详情中切卡用 `router.replace(target)`（374-376）；
  - 目标 query 为 `{ ...copyQuery(), selectedType, selectedId }`。
- 与 design §3（“路由保留分类、筛选、selected type/id 与来源；不把自己每次切卡都变成无法返回列表的冗长历史”）一致：A→B→C 只产生 1 条历史，浏览器返回一次即回到列表。
- 关闭详情 `closeDetail`（379-381）→ `clearSelectionQuery`（343-349）→ `router.replace` 清 `selectedType/selectedId`；滚动恢复由 `watch(detailId)`（382-389）在 `detailId` 由非空变空时执行，关闭与浏览器返回两条路径都命中。
- 残留（低，不计入阻塞）：每次「打开—关闭」都会把当前历史项替换成新的列表项（`replace` 而非 `back`），多次开关后历史里堆积若干同 URL 的列表条目，返回需多按几次但始终停留在大厅。改用 `router.back()` 需额外处理深链（直接打开带 `selectedId` 的 URL）场景，现状是更安全的取舍，**不要求本轮修改**。
- 结论：r2 指出的“每次切卡都 push”已消除，本条关闭。

### I-5 搜索保留关键词与来源 —— **已修复（功能），但 `initial-query` 传参未接线（N-6）**

三处检查点逐一核对：

1. **`cta_search_return` 写入** —— 已实现。`SearchOverlay.vue:21` 定义常量；`persistSearchContext`（75-87）在关键词非空时写入 `JSON.stringify({ q, from: 'search' })`，为空时 `removeItem`；写入触发点有两处：`watch(query)`（131-151，输入/改词/清空即同步）与 `openActivity/openTask`（182-202，点击结果落详情前再写一次）。
2. **回填** —— 已实现。`readSearchReturn()`（89-102）校验 `parsed.from === 'search'` 后返回 `q.trim()`；`restoreSearchContext()`（153-162）仅在输入为空时回填，赋值后由既有 `watch(query)` 走同一防抖 + 序号守卫发起查询；`watch(modelValue)` 打开时先回填再聚焦输入（164-180），`!restored && query 非空 && result===null` 时补一次 `retry()`，避免关闭期间改词漏查。
3. **退出清理** —— 已实现。`AppLayout.vue:286` 在 `handleLogout` 的 `try` 内 `removeItem('cta_search_return')`，与既有 6 个视图键一起清理，`catch` 保留隐私模式容错。
4. **路由参数** —— `openActivity/openTask` 仍 push `query: { from: 'search', q: keyword }`（186-190、197-201）；`from/q` 在应用内**仍无读取端**（全仓 grep 仅命中写入处与 SearchOverlay 自身的注释），属 r2 的 N-2，低风险（URL 参数装饰性），由 sessionStorage 承担实际恢复。

**N-6（本轮新增代码缺陷）**：`AppLayout.vue:791` 向 `SearchOverlay` 传 `:initial-query="searchInitialQuery"`，但 `SearchOverlay.vue:23` 只声明 `defineProps<{ modelValue: boolean }>()`，**没有 `initialQuery` prop，也没有任何消费点**（全仓 `initial-query` 仅此一处）。后果：
- `openSearch` 里 `searchInitialQuery.value = readSearchReturnQuery()`（210-216）与 `readSearchReturnQuery()`（218-230）构成一条**从未生效的死链路**；
- 该属性按 Vue fallthrough 渲染为根 div 上的 `initial-query="…"` 脏属性；
- 实际回填完全由 SearchOverlay 自己读 sessionStorage 完成（功能等价，故不影响 AC-22 行为），但代码意图与真实路径不一致，后续维护者易误判；
- 两处读取口径也不一致：`readSearchReturnQuery()` 不校验 `from === 'search'`，`readSearchReturn()` 校验。
- 建议（1 行级）：在 `SearchOverlay` 声明 `initialQuery?: string` 并在打开时优先使用，或在 AppLayout 删除 `searchInitialQuery` / `readSearchReturnQuery` / 传参三处死链路；同时把键名抽为共享常量（与 r2 N-4 同源）。

**N-1（r2 记录，仍未处理）**：`openActivity/openTask` 先 `close()` 再 `push`，`watch(modelValue)` 的 `restoreFocus()`（203-208）仍会把焦点送到常驻的导航搜索按钮，而不是新详情页。低优先级可访问性遗留，不阻塞。

- 结论：r2 的“写入但无读取端”已消除（读取端落在 sessionStorage 回填 + 自动重查），AC-22 两条 FAIL 断言（URL 带 `q`、`from=search`）在代码层已可满足；**本条关闭，`initial-query` 未接线登记为 N-6**。

### AC-18 侧栏「消息」叠压 —— **代码层已修复，缺修复后浏览器证据**

- 结构：`AppLayout.vue:306-472` 新增 `.sidebar-scroll` 包裹 `sidebar-head` / 主导航 / 管理 / 最近 / AI 历史，`sidebar-foot`（474-）留在滚动区外；闭合正确（471 关 `sidebar-history`，472 关 `sidebar-scroll`），typecheck 与契约 ㉗ 均通过。
- 样式：`AppLayout.vue:1147-1161`
  - `.sidebar-scroll { display:flex; flex:1 1 auto; flex-direction:column; gap:space-4; min-height:0; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin }`
  - `.sidebar-scroll > * { flex-shrink: 0 }`
  - 前者提供唯一的受限高度滚动容器，后者禁止分组被压扁，直接对应浏览器断言“侧栏导航项未被其他分组覆盖”的失败原因（修复前分组在 `height:100vh; overflow:hidden` 的 flex 列中被挤压到相互覆盖）。
- `.app-sidebar`（1133-1145）保持 `height:100vh; overflow:hidden`，底部个人区 `flex: 0 0 auto`（1294-1302），滚动仅发生在主体，符合“底部个人区固定可见”的设计。
- 只有 `min-width:1025px` 断点定义该容器；≤1024px 时侧栏 `display:none`（803-805）、手机走独立 `el-drawer` 结构（629-789），不被本改动影响。
- 缺口：`screenshots/aiw14-sidebar.png` 与 `aiw14-browser.md` 均为修复前（17:06/17:07）产物，**本轮无覆盖该断言的复跑证据**（见 N-7）。

### 回归：既有契约、类型与 AIW-09 历史

- 32 项静态契约全 PASS（含 ㉗ 分组导航 / ㉙ AI 历史抽屉 / ㉛ 分栏 selectedType+selectedId），本轮三个文件的改动未触发现有断言文本或行号定位。
- `vue-tsc --noEmit` 0 error（也说明 `:initial-query` 的多余属性不会在类型层面被拦截，N-6 只能靠人工发现）。
- AIW-09 历史 29 passed（与 AIW-14 库/搜索一并跑），契约 ㉙ 通过：`HistoryEntry` 真实会话、`?conversation=` 恢复、侧栏最近 5 条未被侧栏滚动改动破坏。
- 契约测试**未断言** 退出清理集合与 `cta_search_return` 的写入/回填（grep 无命中），因此 32/32 不能作为 I-5 的通过证据；I-5 的判定来自代码路径阅读，非自动化回归。

---

## 新增问题

### N-6 `initial-query` 传参未接线（Important，功能等价、1 行可修）
- 位置：`frontend/src/layouts/AppLayout.vue:54-55、210-230、791`；`frontend/src/components/nav/SearchOverlay.vue:23`
- 影响：死链路 + 根元素脏属性 + 两处读取口径不一致（详见 I-5）。不改变当前可观察行为，但属明确实现缺陷。
- 建议：声明并消费 `initialQuery`，或删除 AppLayout 侧死链路；键名统一常量来源。

### N-7 修复后无浏览器证据（验证缺口，非代码缺陷）
- 位置：`codearts_proof/reports/aiw14-browser.md`（17:07）、`codearts_proof/screenshots/aiw14-sidebar.png`（17:06）
- 影响：AC-18 与 AC-22 在报告中仍为 FAIL，本轮的 `sidebar-scroll` 与搜索上下文写入/回填没有任何复跑或截图支撑；`frontend/dist` 也是修复前构建（16:47）。
- 建议：提交前重建前端并复跑 `work/aiw14/browse/verify-browse.cjs`，只复验 AC-18 覆盖断言与 AC-22 的 `q/from` 两条断言即可；或至少补一张修复后的侧栏截图并在报告中标注。

## 前轮遗留（本轮未变化，不重复审查）

| 编号 | 内容 | 级别 | 状态 |
| --- | --- | --- | --- |
| N-1 | 关闭面板后焦点归还与路由跳转竞争 | 低 | 仍在（`SearchOverlay.vue:203-208`） |
| N-2 | `from=search&q=` 无读取端 | 低 | 仍在（不影响 AC-22 断言） |
| N-3 | HoverPeek 面板可访问名称未按对象传入 | 建议 | 仍在 |
| N-4 | 退出清理键名与 `VIEW_KEYS` 未建单一来源 | 建议 | 仍在，本轮新增 `cta_search_return` 也以字面量出现 |
| N-5 | `resetFilters()` 未清选中 | 低 | 仍在 |

---

## 结论

| 项 | r2 | r3（本轮） |
| --- | --- | --- |
| I-4 首次 push / 切选 replace | 部分修复 | **已修复**（`TaskHall.vue:364-377`） |
| I-5 搜索保留词与来源 | 部分修复 | **已修复**（写入/回填/退出清理齐备；遗留 N-6 未接线，N-2 URL 参数无消费） |
| AC-18 侧栏「消息」叠压 | 新提出（浏览器 FAIL） | **代码层已修复**（`sidebar-scroll` 主体滚动，`AppLayout.vue:306-472 / 1147-1161`），缺修复后浏览器证据 |
| 32 项静态契约 | 32 passed | **32 passed** |
| `vue-tsc --noEmit` | 0 error | **0 error** |
| AIW-09 历史回归 | 29 passed | **29 passed** |

- Critical：0
- Important：本轮 2 项遗留均关闭；新增 1 项 N-6（`initial-query` 未接线）
- 建议：N-3 / N-4 / N-5；低：N-1 / N-2
- **阻塞判定：无 Critical、无功能阻塞。** I-4、I-5、AC-18 在代码层均已落地，可进入提交流程。提交前建议完成两件低成本的收尾：① 修掉或删除 N-6 的 dead prop 链路（1 行级）；② 重建 `frontend/dist` 并复跑 AC-18/AC-22 的浏览器断言，把 `aiw14-browser.md` 更新为修复后结果（当前报告会与代码不一致，容易被误读为“验收失败”）。