# stage30 独立代码审查（第 2 轮）

- 审查角色：独立 Review Agent（CodeArts，只读复核，不修改业务代码）
- 审查范围：**仅第 1 轮 Important（I-1～I-7）的修复与新 diff 及相关回归**；不重审已关闭且未变化的代码
- 依据：`codearts_proof/reviews/stage30_review_r1.md`、`.codeartsdoer/plans/aiw14-workbench-library-search/design.md` §3/§7-§8/§9
- 日期：2026-11-14 17:09
- 工作区状态：未提交改动；AppLayout / AI 历史侧栏由 AIW-09 写者并行更新（HistoryEntry、真实会话列表），**不计入本轮修复判定**，只确认其未破坏 I-1 清理与导航行为

## 复核基线（本轮读取的 blob，各取前 12 位）

```
AppLayout.vue        3f216f563001
TaskHall.vue         fedf7bd38503
SearchOverlay.vue    164d8202a53c
HoverPeek.vue        8e927e8565d4
api/library.ts       41c83f59b9a0
```

## 本轮实跑的验证（不采信实现者结论）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `python tests/frontend/check_contracts.py --frontend frontend` | 0 | `RESULT: 32 passed, 0 failed`（项数同第 1 轮，未新增针对 I-1～I-7 的断言） |
| `cd frontend && npm run typecheck` | 0 | `vue-tsc --noEmit` 无输出，0 error |
| `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw14_library_search.py tests/backend/test_aiw09_history.py -q` | 0 | `29 passed in 5.83s` |

未执行/未参与：浏览器交互验收、前端构建与语音套件、后端 `run_all.sh`、真实模型与移动真机。以下 I-4/I-5 的“返回/历史”结论来自代码路径阅读与路由语义，**未经浏览器行为验证**（第 1 轮 S-14 的缺口仍在）。

---

## 逐条 Important 结论

### I-1 退出登录清理 4 个 sessionStorage 键 —— 已修复

- 证据：`frontend/src/layouts/AppLayout.vue:257-275` 的 `handleLogout` 现清理 6 个键：旧键 `cta_hall_view`、`cta_my_tasks_view`（263-264）与新增的 `cta_hall_view_activity|task`、`cta_my_tasks_view_activity|task`（265-268），与 `TaskHall.vue:39-41` 的 `VIEW_KEYS` 完全对应；`try/catch` 保留隐私模式容错，`aiChat.reset()` / `notificationsStore.reset()` 顺序未变。
- AIW-09 交互确认：新增的真实会话列表只走服务端与 `aiChat` store，全仓未见新增的本地存储键（`grep` 仅命中既有 `cta_theme` / `cta_user` / `cta_draft_v1` / `cta_sidebar_collapsed`）；`isActive()`（AppLayout `:134-`）对 `hall/detail/activity` 的归类未变；契约 ㉗/㉙ 与 typecheck 均通过。**未破坏 I-1 清理与导航。**
- 残留（建议级，见 N-4）：清理列表是硬编码 6 行，未从 `VIEW_KEYS` 派生；下次新增键仍需手工同步，且契约测试未断言该清理。

### I-2 `LibraryLink` 删除 `owner_id` —— 已修复

- 证据：`frontend/src/api/library.ts:9-17` 接口只剩 `id/title/url/note/created_at/updated_at`，注释显式写明“响应不含 `owner_id`”；全仓 `owner_id` 仅剩活动/发布相关（`types/models.ts:248`、`ActivityDetail.vue:62`、`PublishActivityPage.vue:53` 等），`LibraryPage.vue` 不再引用。
- 与后端 `LibraryLinkOut`（`backend/app/schemas.py`）契约一致，typecheck 0 error。

### I-3 切换筛选后清失效选中 —— 已修复（主路径），附一处一致性缺口

- 证据：`frontend/src/views/TaskHall.vue:312-317` `handleFilterChange` 先 `writeView` 再 `clearSelectionQuery()`（343-349，删除 `selectedType/selectedId` 并 `replace`）再 `loadCurrent()`；`changeType`（352-362）行为一致；`onMounted`（410-412）也清洗非法 query。
- 缺口（低风险，见 N-5）：`resetFilters()`（319-327）同样扩大/改变集合，但未调用 `clearSelectionQuery()`。因清除筛选只会扩大集合，已选对象多数仍存在，实际风险低；但与“一律清空、与 `changeType` 对齐”的口径不完全一致。

### I-4 选择 push、关闭 replace —— **部分修复**

- 证据：`TaskHall.vue:364-374` `selectCard` 改为 `router.push({ query: { ...query, selectedType, selectedId } })`（移动端仍 push 独立详情，365-368）；`closeDetail`（376-378）→ `clearSelectionQuery` → `router.replace`（343-349）。
- 已达成的部分：浏览器返回不再直接离开大厅；按一次返回会回到上一个选中，多次后回到无选中列表；滚动位置经 `restoreScrollTop` + `detailId watch`（369、380-387）恢复。
- **未达成的部分**：`selectCard` 是**每次切卡都 push**，A→B→C 会在 history 生成 `[list, A, B, C]`，用户需连续按 3 次返回才回到列表。design §3 原文要求“**不把自己每次切卡都变成无法返回列表的冗长历史**”，第 1 轮建议也明确“至少一次打开详情用 push（切选再 replace）”。当前实现仍是“每次切选产生一条历史”；`closeDetail` 用 `replace` 而非 `router.back()`，浏览器返回也无法关闭右栏（只能回退到上一选中）。
- 结论：核心可用性（返回可回列表）已恢复，**“切选应 replace”的冗长历史要求未实现**；需改为“首次打开 push、后续切选 replace”，或在阶段文档中明确记录该取舍。

### I-5 搜索结果保留关键词与来源 —— **部分修复**

- 证据：`frontend/src/components/nav/SearchOverlay.vue:174-192` 的 `openActivity/openTask` 已在跳转时附带 `query: { from: 'search', q: keyword }`（写入口径满足第 1 轮建议的“附带 query”）。
- **未达成的部分**：全仓无消费端。`route.query` 的全部读取点（`AiConsole.vue:115-180`、`LoginPage`、`PublishPage`、`RegisterPage`、`ResetPassword`、`TaskHall.vue:93/172/178/332/344/390`）没有任何 `from` 或 `q` 处理；`AppLayout.vue:208-211` 的 `openSearch()` 不读路由，也不回填 `SearchOverlay` 的 `query`（初值仍是 `''`）。因此浏览器返回或重新打开面板时既不自动展开搜索，也不恢复关键词，与 design §6“结果点入……保留词和来源，后退回结果”、§8“保留关键词返回”不一致。
- 结论：只完成“写入参数”，未完成“读取并恢复上下文”；`from=search&q=` 目前是**无消费者的装饰性 query**，还可能被 `TaskHall.copyQuery()` 带入后续选中 query 一直挂在 URL 上。

### I-6 搜索面板焦点陷阱与焦点归还 —— 已修复

- 证据：`SearchOverlay.vue:34-35` 记录 `previousActiveElement`；`110-132` 关闭时 `restoreFocus()`（`document.contains` 守卫）；`134-167` `focusableElements()` 从 `panelRef` 取可聚焦节点并实现 Tab / Shift+Tab 首尾循环（含“焦点在面板外则拉回”）；`204-214` 的 `role="dialog" aria-modal="true"` 在外层容器上挂 `@keydown` 与 `@keydown.esc`，Esc 可覆盖面板内全部子元素，不再依赖输入框冒泡。
- 说明：Tab 陷阱沿用现有 keydown 路径，未引入依赖，符合“最小实现”口径。

### I-7 HoverPeek 语义与键盘可达 —— 已修复

- 证据：`HoverPeek.vue:159-166` 面板改为 `role="dialog" aria-modal="false"` + `:aria-label="props.label"` + `tabindex="0"`；`106-111` `focusin` 打开面板、`113-119` `focusout` 出联合区关闭（`relatedTarget` 在 root 内即忽略）；`121-123` + `125-129` Esc 在 document 级关闭；**无焦点陷阱**，符合非模态信息面板；`72-78` 用 `:focus-visible` 区分“键盘焦点”与“指针点击面板”，避免面板粘住；`209-217` 触摸禁用保留。
- 残留（建议级，见 N-3）：`TaskHall.vue:516/559` 使用处未传 `label`，所有面板可访问名称都是默认“卡片预览”，未与具体卡片标题关联；也未加 `aria-describedby`（第 1 轮为“可选”建议，不影响本条判定）。

---

## 新增问题（本轮新 diff 引入）

### N-1 搜索跳转时“关闭即归还焦点”与路由导航竞争（低）

- 位置：`SearchOverlay.vue:169-192`（`close()` → `emit false`）+ `110-132`（`watch modelValue` → `restoreFocus()` nextTick）+ `AppLayout.vue:770`（`<SearchOverlay v-model="searchOpen" />` 常驻布局）
- 现象：`openActivity/openTask` 在 `close()` 后立刻 `router.push`，`restoreFocus()` 在 nextTick 把焦点送回**仍然存在**的侧栏/顶栏搜索按钮，而页面已切到详情页。
- 影响：读屏与键盘用户的焦点落在导航搜索按钮而非新页标题/内容，属“关闭面板”与“离开页面”两种语义的焦点冲突。
- 建议：带 `from=search` 跳转时跳过 `restoreFocus()`（或仅在路由未变化时归还）。

### N-2 `from=search&q=` 无消费者（并入 I-5 遗留）

- 位置：`SearchOverlay.vue:180/190`；无读取点。
- 影响：URL 携带无效参数并可能被 `TaskHall.copyQuery()` 长期保留；验收时无法以“参数存在”作为“保留来源”的通过证据。

### N-3 HoverPeek 面板可访问名称未区分对象（建议）

- 位置：`TaskHall.vue:516-527`、`559-570`
- 建议：传 `:label="\`预览活动：${activity.title}\`"` / `任务`，并按需给卡片加 `aria-describedby`。

### N-4 退出清理与 `VIEW_KEYS` 未建立单一来源（建议）

- 位置：`AppLayout.vue:263-268` 与 `TaskHall.vue:39-41` 各维护一份键名；`tests/frontend/check_contracts.py:2602-2603` 只断言 TaskHall 侧存在，未断言 AppLayout 退出清理全部键。
- 建议：把键名抽到共享常量供两处引用，契约测试加一条“退出清理集合 ⊇ 4 个新键 + 2 个旧键”的断言。

### N-5 `resetFilters()` 未清选中（低）

- 位置：`TaskHall.vue:319-327`（对照 312-317）
- 影响：清除筛选后右栏可能仍展示一个不在左侧选中态的旧对象；因集合只扩大，实际命中概率低。

---

## 结论

| 项 | 第 1 轮 | 第 2 轮 |
| --- | --- | --- |
| I-1 退出清理 4 键 | Important | **已修复** |
| I-2 `LibraryLink.owner_id` | Important | **已修复** |
| I-3 筛选后清失效选中 | Important | **已修复**（`resetFilters` 一致性缺口 N-5 低风险） |
| I-4 选择 push / 关闭 replace | Important | **部分修复**（返回可回列表；每次切卡仍产生历史，未实现“切选 replace”） |
| I-5 搜索保留词与来源 | Important | **部分修复**（已写入 `from/q`，全仓无消费端，返回不恢复搜索） |
| I-6 焦点陷阱与归还 | Important | **已修复** |
| I-7 HoverPeek 语义/键盘 | Important | **已修复**（label 未按对象传入，建议级） |

- Critical：0（本轮未发现新增权限/数据面漏洞）
- Important：关闭 5 / 7；遗留 2 项（I-4、I-5 均为“部分修复”）
- 新增问题：N-1 低、N-2 并入 I-5、N-3/N-4/N-5 建议级
- 回归：契约 32/32、typecheck 0 error、后端 29 passed，均通过；AIW-09 并行改动未破坏 I-1 清理与导航归类
- 阻塞判定：**无 Critical 阻塞**。I-4、I-5 仍未满足 design §3/§6 原文（“切卡不产生冗长历史”“保留词和来源返回”），建议在提交前按第 3 轮修复（I-4 改“首次 push、切选 replace”；I-5 由 AppLayout/详情页读取 `from=search&q=` 重开面板并回填），或由负责人在阶段文档中明确记录取舍与未达成范围后再提交。