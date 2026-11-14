# stage30 独立代码审查（第 1 轮）

- 审查角色：独立 Review Agent（CodeArts，只读，不修改业务代码）
- 审查范围：AIW-14 r1/r2 改动清单（AppLayout / router / LibraryPage / nav / browse / HoverPeek / api / 后端 Library+搜索 / 契约测试）
- 依据：`.codeartsdoer/plans/aiw14-workbench-library-search/design.md` §8/§9、`task.md`、`.codeartsdoer/plans/ai-workbench/execution-contract.md`
- 日期：2026-11-14
- 工作区状态：未提交改动；审查期间 `frontend/src/layouts/AppLayout.vue` 于 16:51 被并行 AIW-09 写者更新（AI 历史接入真实会话）。本报告只针对 AIW-14 相关段落；AI 历史数据接入属 AIW-09，不计入本轮结论。

## 审查基线（读取时的 blob）

```
AppLayout.vue        65f57efe087a
TaskHall.vue         7f67c5eb53c6
SearchOverlay.vue    d89a8161da97
HoverPeek.vue        1c9dc17a3423
api/library.ts       8fcb21eb2fcd
LibraryPage.vue      b0f076565fa2
routers/search.py    95e5ba295d0f
routers/library.py   aa8c40f0caef
```

## 复核的本地验证（不是采信原报告，而是本轮实际执行）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `python tests/frontend/check_contracts.py` | 0 | `RESULT: 32 passed, 0 failed`（含新增 ㉗～㉜ 6 项） |
| `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw14_library_search.py -q` | 0 | `23 passed in 3.13s` |

未执行/未参与：浏览器交互验收、后端 `run_all.sh`、前端构建与语音套件、真实模型与移动真机。前端契约脚本是静态文本断言，不能替代行为验证（见 S-12）。

---

## Critical Issues

无。

权限与数据面核对结论（抽样证据）：

- Library 列表/更新均按 `owner_id == current_user.id`；越权 PATCH 与不存在统一 `4040`，不区分（`library_service.py:83-96`、`routers/library.py:55-73`）。
- 新建 owner 只取自会话，客户端 `owner_id` 被 Pydantic 忽略（`library_service.py:99-113`，测试 `test_client_cannot_choose_owner`）。
- `url` 仅接受 http/https 且必须有 netloc，拒绝换行/制表符与超长（`library_service.py:42-55`）；超长/非法字段经全局 `RequestValidationError` handler 统一为 HTTP 200 + `code=4001`（`main.py:104-111`）。
- 搜索先 `visible_*` + `mine` 过滤，再标题匹配，再 `count`/`limit`；`%`/`_` 通过 `autoescape=True` 参数化，无注入面（`routers/search.py:56-95`）。

---

## Important Issues

### I-1 退出登录未清理 AIW-14 新增的 4 个 sessionStorage 键

- 位置：`frontend/src/layouts/AppLayout.vue:261-264`
- 问题：只删除旧键 `cta_hall_view` / `cta_my_tasks_view`，而本轮 `TaskHall.vue:49-52` 实际使用 `cta_hall_view_activity|task` 与 `cta_my_tasks_view_activity|task`。
- 影响：同一浏览器退出后登录另一个账号，会继承上一账号的筛选（scope/status/type）与滚动位置；属账号边界残留，虽不含对象标题，但会给出错误的状态暗示，并与 AIW-09 的“退出清缓存”口径不一致。
- 建议：按 `VIEW_KEYS` 派生统一清理（或抽 `clearViewState()`），并保留旧键兼容清理。

### I-2 前端 `LibraryLink` 类型声明了后端不返回的 `owner_id`

- 位置：`frontend/src/api/library.ts:10-19`（`owner_id: number` 在 12 行）
- 问题：`backend/app/schemas.py:978-988` 的 `LibraryLinkOut` 明确不返回 `owner_id`，契约 §9.2 与测试也断言“所有者不在响应暴露”。
- 影响：类型系统给出一个运行时恒为 `undefined` 的必填字段；后续若用 `link.owner_id === 当前用户` 做过滤或展示，会静默失效（尤其与“私有区”语义叠加时容易误判归属）。
- 建议：从接口删除 `owner_id`；若确需标识，改成 `owner_name` 之类显式可展示字段并同步后端契约。

### I-3 切换筛选/scope 后保留已不在集合中的选中项

- 位置：`frontend/src/views/TaskHall.vue:312-315`（`handleFilterChange`）、`350-360`（`changeType` 有清理，筛选路径没有）
- 问题：契约 §8 C-BROWSE-TABS@3 要求“切分类或 scope 后不保留无效选中对象”。`changeType` 清了 `selectedType/selectedId`，但 `handleFilterChange`（改 scope/status/claim_type）只 `loadCurrent()`。
- 影响：例如从“全部”切到“我的任务与活动”后，右侧详情仍展示不在左列表中的对象；左列表无选中态、右侧有内容，用户无法判断选择是否仍有效；刷新后同样复现。
- 建议：筛选变化后按新集合判断 `selectedId` 是否仍存在（或一律清空选择并保留滚动恢复），与 `changeType` 行为对齐。

### I-4 分栏选择全部使用 `router.replace`，“浏览器返回”无法回到列表

- 位置：`frontend/src/views/TaskHall.vue:362-372`（`selectCard` → `replace`）、`374-377`（`closeDetail` → `replace`）
- 问题：契约 §8 C-BROWSE-SPLIT@1 / design §3 要求“明确区分进入详情、切选、关闭、浏览器返回”，并要求“不把自己每次切卡都变成无法返回列表的冗长历史”。
- 影响：当前方案只满足后半句。用户在详情右栏按浏览器返回，会直接离开大厅（回到上一个页面或空历史），既不能关闭右栏也不能回到列表原位置；“返回恢复列表”的预期路径不存在。
- 建议：至少在一次“打开详情”时用 `push`（切选再 `replace`），关闭用 `router.back()`（或 `replace` 但拦截 popstate 语义），并在阶段文档中明确这一取舍与验证结果。

### I-5 搜索结果点击后不保留关键词与来源，返回不回搜索结果

- 位置：`frontend/src/components/nav/SearchOverlay.vue:125-137`（`openActivity/openTask`）、`106-118`（关闭面板）
- 问题：design §6 要求“结果点入准确分类/选中详情并保留词和来源，后退回结果”；§8 也写“保留关键词返回”。实现关闭面板后直接 `push` 独立详情，未把 `q` 或 `from=search` 带入路由，返回后既不自动打开面板也不恢复搜索上下文。
- 影响：用户失去搜索结果只能重新输入；多轮检索成本上升，且与验收口径不一致。
- 建议：跳转时附带 `query: { q, from: 'search' }`，详情/大厅读取后重开面板并回填；或改为落到当前大厅 `selectedType/selectedId` 并保留 `q`。

### I-6 搜索面板声明 `aria-modal` 但无焦点陷阱与焦点恢复

- 位置：`frontend/src/components/nav/SearchOverlay.vue:145-153`（`role="dialog" aria-modal="true"`）、`106-118`（打开只 `focus()` 输入框，关闭无归还）
- 问题：在 `aria-modal="true"` 下，键盘与读屏应被限制在对话框内；当前 Tab 可移到背景页面元素，关闭后焦点落在被移除的 DOM 节点/`body`，未回到触发的搜索按钮。
- 影响：键盘与读屏用户会“漏出”到背景、找不到返回位置；与 design §6“键盘焦点/返回明确”不符。
- 建议：实现最小焦点陷阱（Tab 循环 + 关闭时 `restoreFocus`），并把 `Esc` 处理放到面板容器（现在依赖事件冒泡，输入框之外的可聚焦元素未覆盖）。无需引入新依赖，手写即可。

### I-7 HoverPeek 用 `role="tooltip"` 承载可滚动/可交互面板，且未与触发卡片关联

- 位置：`frontend/src/components/common/HoverPeek.vue:149-153`
- 问题：WAI-ARIA 的 tooltip 不应包含可交互内容；此处面板 `overflow-y: auto` 且承载事实表与提示，属于“信息卡”而非 tooltip。卡片（`role="button"`）也没有 `aria-describedby` 指向面板。
- 影响：读屏用户无法把面板内容与卡片关联，键盘也无法滚动面板；执行契约 §4 要求“交互面板的语义与焦点实现前核对”。
- 建议：面板改为普通 `div`（或 `role="group"` + `aria-label`），由卡片 `aria-describedby` 关联；若需键盘可达，允许面板获得焦点或提供等价详情入口。

---

## Suggested Improvements

### S-1 搜索重复创建同一个可见性递归 CTE

- 位置：`backend/app/routers/search.py:68`、`93`
- 说明：`_visible_activity_condition` 已接收并复用 `visible_tasks`，但任务查询又内联调用一次 `authz.visible_task_filter(db, current_user)`。同一条 SQLAlchemy 会话里重复构造同名递归 CTE 是既有注释（`activities.py:41-43`）明确提示的风险点。
- 建议：复用变量：`task_query.filter(visible_tasks, authz.my_task_condition(...), ...)`。

### S-2 `library_links.owner_id` 无数据库外键，与契约字面量存在偏差

- 位置：`backend/app/models.py:547-569`
- 说明：契约 §9.2 写“`owner_id`（FK `users.id`，索引）”，实现遵循项目“Demo 期不建数据库级外键”的全局约定（docstring 已说明）。
- 建议：在阶段文档/契约中显式记录该偏差，避免验收时被按 FK 字面量检查。

### S-3 时间戳函数两份实现且服务层函数体首行空行

- 位置：`backend/app/models.py:36`、`backend/app/services/library_service.py:33-36`
- 说明：`_now_local` 在模型与服务层重复；服务层版本 `def _now_local() -> str:` 后有空行。两处格式若漂移会造成 created/updated 口径不一致。
- 建议：服务层复用统一工具函数；去掉函数体首行空行。

### S-4 URL 校验未覆盖主机名与反斜杠/用户信息

- 位置：`backend/app/services/library_service.py:42-55`
- 说明：只校验 scheme 与 `netloc` 非空；`http://good.com\@evil.com`、`http://user:pass@host` 这类值可通过，浏览器解析可能与展示不一致（前端直接把它作为 `href`，`LibraryPage.vue:233-240`）。
- 建议：追加 `parts.hostname` 非空、拒绝反斜杠与 `@`（或明确允许 userinfo），降低误导链接与钓鱼面。属加固，不影响当前测试。

### S-5 编辑更新后本地列表顺序与后端排序不一致

- 位置：`frontend/src/views/LibraryPage.vue:113-127`（更新分支在 119 行原地 `map`）
- 说明：后端按 `updated_at desc, id desc` 返回；前端 `map` 原地替换，编辑后不重排，刷新才变化。
- 建议：更新后把该项移到首位，或重新拉取第一页。

### S-6 Library 共享资料固定只取 20 条且无分页入口

- 位置：`frontend/src/views/LibraryPage.vue:24`（`RESOURCE_LIMIT = 20`）、`56-67`（`loadResources`）、`284-305`（资料列表无分页入口）
- 影响：资料超过 20 条时用户看不到更多，也没有“加载更多”或总数量提示，容易误以为资料缺失。
- 建议：补分页/加载更多，或至少展示“仅显示前 20 条”。

### S-7 搜索展示总数与只展示 5 条无说明；关闭时未推进请求序号

- 位置：`frontend/src/components/nav/SearchOverlay.vue:59-70`、`86-104`、`213`/`230`（组标题里的 `total`）
- 说明：`total` 可能大于 5，但无“还有 N 条”提示；面板关闭时不清 `requestSeq`，关闭期间落地的响应仍会写入 `result`，下次打开可能短暂显示与当前输入不匹配的旧结果。
- 建议：展示“共 N 条，仅显示前 5 条”；关闭时 `requestSeq += 1` 并清 `loading`。

### S-8 tab 语义与键盘细节

- 位置：`frontend/src/components/browse/HallTabs.vue:56-60`（`aria-controls="browse-collection"`）、`37-50`（方向键）
- 说明：`TaskHall.vue:499-502` 的 tabpanel 位于 `v-else` 分支，loading/error 时该 ID 不存在；方向键在两端都做“交叉”，未支持 Home/End，与 APG 推荐（末尾 ArrowRight 不移动）有差异。
- 建议：tabpanel 容器始终渲染或用条件绑定 `aria-controls`；补 Home/End 与边界不循环语义。

### S-9 卡片角色与焦点可见性

- 位置：`frontend/src/components/browse/ActivityBrowseCard.vue:35-49`（`role="button"` + `aria-pressed`，41 行）、`89-93`（`outline: none`）、`TaskBrowseCard.vue` 同构
- 说明：这是列表选中而非开关；`aria-pressed` 语义偏弱（`aria-current` 或 listbox/option 更贴切）。`focus-visible` 时移除 outline 只改变边框色，键盘焦点不够明显。
- 建议：改用 `aria-current`（或 `role="option"` + `aria-selected`）；保留 2px 可见 outline。

### S-10 AppLayout 细节：无效 `aria-label`、重复图标、“最近”数据口径

- 位置：`frontend/src/layouts/AppLayout.vue:381`、`425`（`aria-label` 挂在无 `role` 的 `div` 上）；`managerNav` 两项共用 `admin` 图标（`80-93`）；`loadRecent` 取 mine 列表前 5 条（`170-180`）
- 说明：无 role 的 `div` 上 `aria-label` 通常不产生可访问名称；两个管理入口图标相同，折叠态无法区分；“最近活动/任务”实为“我相关的最新创建”，非最近访问。
- 建议：加 `role="group"`/`aria-labelledby`；为两个管理入口选不同 `NavIconName`；在文档/文案上校准“最近”的定义，待 09 历史接入后统一。

### S-11 分栏在窗口缩小与 URL 直开时的行为

- 位置：`frontend/src/views/TaskHall.vue:184-188`、`203`
- 说明：从宽屏缩到 `<768px` 时 `splitSelection` 变 `null`，详情直接消失，但 `selectedType/selectedId` 仍留在 URL；直接以 `?selectedId=` 打开窄屏页面也不会跳转详情或清洗 query。
- 建议：窄屏读取到有效选中时 `router.push` 到独立详情（符合 design“窄屏点击进入全宽详情”），或在 `onMounted` 清洗无效 query。

### S-12 分栏详情错误文案不区分撤权

- 位置：`frontend/src/components/browse/BrowseDetailPanel.vue:37-44`（`errorMessage`）、`117-121`（`ErrorState` 固定文案）
- 说明：契约 §8 要求“加载/错误/撤权状态显示在右侧”。当前 `4040/4030` 与网络失败共用“摘要加载失败，可打开完整详情页查看”，撤权时打开详情同样失败。
- 建议：按 `ApiError.code` 区分“无权查看/对象不存在/网络失败”，撤权时不显示“打开完整详情”。

### S-13 活动标题缺失时展示内部 ID

- 位置：`frontend/src/components/browse/TaskBrowseCard.vue:31-36`
- 说明：活动标题未随任务列表返回时显示 `所属活动 #<id>`，把内部标识暴露给用户。
- 建议：降级为“所属活动”，不展示 ID。

### S-14 前端新增契约只有静态文本断言，无行为级自动化

- 位置：`tests/frontend/check_contracts.py:2395-2710`（㉗～㉜）
- 说明：断言为字符串/正则匹配，能防回退标记，但不能验证“旧搜索响应不覆盖新词”“A 晚到不覆盖 B”“滚动恢复”“HoverPeek 间隙路径”等行为；这些目前只有实现者手工/浏览器证据。
- 建议：在阶段文档中明确“前端交互结论来自浏览器验收、无自动化行为测试”，不要将 32/32 静态检查表述为交互验收通过；若后续引入组件测试框架须先取得依赖授权。

---

## 需求/契约逐项核对（本轮）

| 契约 | 结论 | 依据 |
| --- | --- | --- |
| C-NAV-GROUPS@3：分组、折叠 aria、Library 入口、历史空态 | 通过（历史空态已由 AIW-09 真实数据取代，属后续阶段演进） | AppLayout 主导航/管理/最近/底部、`aria-label`+`title`+`aria-current`；router `library` + `PAGE_TITLES` |
| C-BROWSE-TABS@3：query 唯一集合、tab 语义、独立持久化 | 基本通过；S-8、I-3 | HallTabs tablist/tab；TaskHall `VIEW_KEYS` 四键 |
| C-BROWSE-SPLIT@1：三列/分栏、晚到丢弃、关闭恢复 | 部分通过；I-3、I-4、S-11、S-12 | CSS 三列/两列/单列；BrowseDetailPanel `requestSeq` |
| C-FE-PEEK@2：联合区、120ms、Esc、触摸边界 | 通过；I-7（语义） | `::before` 8px 桥接、`top: calc(100% + 8px)`、matchMedia 精确指针、触摸隐藏 |
| C-LIBRARY@1：owner 会话、私有过滤、非法输入、无 DELETE | 通过；I-2、S-2 | service + router + 23 项后端测试 |
| C-MY-SEARCH@1：mine→authz→匹配→分页、无跨组织泄漏 | 通过；S-1、S-7 | search.py 条件顺序与测试 |
| 未新增依赖/旁路授权/积分/通知 | 通过 | `git status` 无 package.json/依赖变更；仅复用 `authz`、`listResources`、`request` |
| 未混入 AIW-11 取消能力 | 通过 | 改动文件中无取消条目/取消路由 |

---

## 结论

- Critical：0
- Important：7（I-1～I-7）
- Suggestion：14（S-1～S-14）
- 阻断项：无 Critical，不阻断本阶段合并前提；但 **I-1/I-2/I-3/I-4/I-5** 属契约或账号边界问题，建议在提交前修复或由负责人在阶段文档中明确接受并记录取舍。
- 第 2 轮审查只需针对上述修复产生的新 diff 与相关回归，不再重审未变化部分。