# 阶段 45 · 详情页信息架构与视觉一致性（stage45）

> 日期：2026-11-15（Asia/Shanghai）。起点提交 `85805ed`（stage44 已推送，CI `43707123572` success）。
> 计划（本地 Git 忽略）：`.codeartsdoer/plans/v1-ui-detail-refine/design.md`、`task.md`。
> 状态：本地实现与门禁完成，独立审查 1 轮，**未提交、未推送、无新 CI**。

## 1. 需求来源

用户本轮原文见 [启动指令摘录](../prompts/agent_team_启动指令/2026-11-15_stage45_UI详情页优化_用户原文摘录.md)，两条诉求：

1. 图标、页面比例、形状、大小、布局「目前存在不协调」，需要统一。
2. 活动页面、任务页面的信息展示不够清楚，要求借鉴飞书、Todoist、Notion 的任务/活动管理信息展示方式并落到本项目。

同时要求「查找 UI 相关 skill 并下载、实现」。

## 2. 决策与边界

### 2.1 先补上阶段提交

stage44 的 19 个修改 + 4 个新增文件此前只在工作区。本轮先显式暂存（未用 `git add .`）、提交 `85805ed` 并推送 `origin/main`，CI `43707123572` success。提交信息含目的、验证与回滚。

### 2.2 skill 的实际处置

- 本机与平台没有可见的「UI skill 市场下载」通道（`listSkills` 只有本地/系统已注册项，市场侧只有上传与查询自有技能的工具）。
- 已注册且可用的 UI 相关 skill：`frontend-design`（system，含 5 套主题）、`modern-web-guidance`（user）。本轮按 `frontend-design` 的 **Linear Aesthetic** 主题执行（微边框、单一强调色、克制阴影、精确排版），未伪造「下载」行为。

### 2.3 设计取舍

| 需求 | 采用方案 | 依据 |
| --- | --- | --- |
| 图标一致性 | `NavIcon` 线宽统一 1.6，新增 10 个语义图标；尺寸 14/16/20/24 令牌 | Linear 风格细描边 |
| 页面比例 | 详情页 `1200px` + 「主区 1fr + 侧栏 304px」双栏，1080px 单列 | 飞书/Notion 详情页宽屏阅读 |
| 活动信息架构 | 头部摘要 → 完成率/待处理/已逾期 3 指标 → 按状态分组任务 → 属性侧栏 | Todoist 分组 + Notion 属性面板 |
| 任务信息架构 | 头部摘要（唯一主操作）→ 属性侧栏 → 主区按执行/内容/成果/成员/依赖分区 | Notion/飞书任务详情 |
| 列表比例 | 标题固定两行高度、元信息单行省略、32px 头像、`grid-auto-rows: 1fr` | 同一列表等高 |

### 2.4 边界

- 只改前端展示层；后端接口、数据模型、权限、业务规则未动。
- 不做：看板视图与拖拽排序、评论/动态时间线（后端无接口）、自定义字段、活动封面、移动手势。
- 颜色只组合既有 `--app-*` / `--el-*` 令牌，不新增裸 hex、不引入 12px 字号。

## 3. 实际工具与派工

平台：华为云码道（CodeArts）；显示模型 `deepseek-v4.1-flash-1017`，未独立核验。

- team-leader：写 `design.md`（§1 R1–R8、§2.1 方向、§2.2 八份契约、§2.3 交互矩阵）与 `task.md`（T1–T8），冻结契约后一次派工。
- coding-engineer ×5 并行：T1 令牌与图标；T2 三个详情共用组件；T3 活动详情；T4 任务详情；T5 大厅与卡片。
- coding-engineer T6：同步 `check_contracts.py` 并补 5 项断言；随后 T6-r 放宽 2 项过严断言。
- 独立只读审查 T7（team-code-reviewer）：范围 `85805ed..工作区`，结论「不可提交（修复 Important 后可提交）」。
- 修复回流：T9（T2 原实现者，状态映射）、T10（T3 原实现者，活动页）、T11（T4 原实现者，按钮层级）并行；T12（T6 原实现者，补强断言）。

初始 ready set = 5（T1–T5），T6 依赖前五项产物，T7 依赖 T6，T8 依赖 T7。

## 4. 产出

新增：

- `frontend/src/components/detail/DetailHeader.vue`
- `frontend/src/components/detail/PropertyList.vue`
- `frontend/src/components/task/TaskGroupList.vue`

修改（12 个文件）：

- `frontend/src/styles/theme.css`（9 个新令牌，`:root`/`html.dark` 成对）、`typography.css`（`--app-font-label: 13px`）
- `frontend/src/components/nav/NavIcon.vue`（10 个新图标、线宽 1.6）
- `frontend/src/views/ActivityDetail.vue`、`TaskDetail.vue`、`TaskHall.vue`
- `frontend/src/components/activity/ActivityInfoSection.vue`（`variant: card | facts`）
- `frontend/src/components/task/{TaskCard,ActivityTaskTable}.vue`
- `frontend/src/components/browse/{ActivityBrowseCard,TaskBrowseCard}.vue`
- `tests/frontend/check_contracts.py`（51 → 57 项）

契约：`C-TOKEN-V2@1`、`C-ICON@2`、`C-DETAIL-HEADER@1`、`C-PROPERTY-LIST@1`、`C-TASK-GROUPS@1`、`C-DETAIL-LAYOUT@1`、`C-ACTIVITY-FACTS@1`、`C-CONTRACT-CHECK@1`。

## 5. 真实问题

1. **契约断言口径过严（2 项）**：`PropertyList` 用 `:class` 拼 `--cols-2`、`TaskGroupList` 的 section 属性跨行且用对象映射，首版断言按单行/条件表达式写死 → 54/56。判定为断言问题而非实现问题，改断言接受等价写法后 56/56。与历史「字面量断言 vs 等价改写」冲突同类。
2. **状态映射缺 2 值（审查 Important）**：后端任务状态域 7 值（`todo/in_progress/claimed/overdue/submitted/verified/cancelled`），首版只映射 5 值，`overdue` 会落进「待开始」组却显示「已逾期」→ 补 `claimed/overdue → active`。
3. **㊱ 断言丢绑定（审查 Important）**：把 `ActivityTaskTable` 换成 `TaskGroupList` 时只断言标签前缀，漏 `:expanded`/`@toggle` 会让展开失效但门禁全绿 → 补同片段三绑定断言。
4. **门禁盲区（审查 Important）**：新增 52–56 未覆盖 `C-ACTIVITY-FACTS@1` 与两页 `PropertyList` 接入 → 新增第 57 项（facts 分支不含标题/描述/进度/卡片外壳，发布页不传 variant）。
5. **指标口径与需求不一致（审查 Important）**：活动指标第 2 项原为「进行中」，全部任务待验收时显示 0 → 改「待处理」（非 verified/cancelled）。
6. **主操作层级不成立（审查 Important）**：任务详情「提交完成」固定 success、「签到」固定 warning，导致多高亮且 `submit`/`checkin` 时无 primary → 全部改由 `primaryAction` 决定，唯一 primary。
7. 顺手修复 3 条 Suggestion：「展开全部」补 `aria-controls`；`activity-stats` ≤768px 自适应列；裸 `gap: 2px` 改 `var(--app-space-1)`。
8. 未处置 Suggestion（9 条中的其余 6 条）：位置导航与 kicker 路径重复、「更新进度」双入口、依赖文本箭头 `→`、`PropertyList` 用 index 作 key、同页 6/8/12px 圆角并存、`ActivityTaskTable` 移动端 toggle 24px。

## 6. 验证与未完成项

实际命令（项目根 / `frontend`）：

| 命令 | 结果 |
| --- | --- |
| `npx vue-tsc --noEmit` | EXIT=0 |
| `npm run build` | EXIT=0（`✓ built`，存在既有 chunk >500kB 警告） |
| `python tests/frontend/check_contracts.py` | **57 passed, 0 failed** |
| stage44 提交前复核 | `vue-tsc` EXIT=0、契约 51/51、`test_v1_avatar.py` 12 passed（临时 `DATABASE_PATH`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`） |
| GitHub Actions（stage44） | run `43707123572` / `85805ed` → success |

### 浏览器验收（2026-11-15 19:33–19:42，真实浏览器）

环境：`127.0.0.1:8000` 同源托管 `frontend/dist`（`MAAS_MOCK=1 RUN_SCHEDULER=0`），账号 `cta_student`；演示数据用 `cta_teacher` 经 `POST /api/activities/publish-batch` 发布活动 `id=1`「迎新晚会筹备」+ 5 个任务，并把状态置为 `in_progress/submitted/verified/overdue/published` 覆盖分组（开发库 `backend/campus.db`，无真实业务数据）。

| 场景 | 实测结果 |
| --- | --- |
| 1440 活动详情 | `.detail-grid` = `840px 304px`；分组「进行中 2 / 待验收 1 / 待开始 1 / 已完成 1」；属性 6 项（负责人 CT 辅导员 / 举办开始 `2026-11-20 18:00` / 截止 `2026-12-01 22:00` / 地点 / 组织「测试学院团委」/ 状态）；`scrollWidth - clientWidth = 0` |
| 1440 任务详情 | 标题「总策划」、kicker「迎新晚会筹备」；属性面板 7 项；`840px 304px`；`overflow = 0`；4 个操作按钮均为 default（学生未报名、任务已进行中，权限不可用，无 primary 符合预期） |
| 390×844 活动详情 | 单列 `343.2px`；`overflow = 0`；越界元素 0 |
| 390×844 任务详情 | 单列 `343.2px`；`overflow = 0`；操作按钮高 **44px**（`min-height: var(--app-touch)`） |
| 全站时间格式 | 任务详情正文 `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}` 命中数 **0** |

截图（真实浏览器、非模拟）：

- `codearts_proof/screenshots/stage45/hall-1440.png`
- `codearts_proof/screenshots/stage45/activity-1440.png`
- `codearts_proof/screenshots/stage45/task-1440.png`
- `codearts_proof/screenshots/stage45/activity-390.png`
- `codearts_proof/screenshots/stage45/task-390.png`

验收中发现并当场修复 4 项（均在本轮 diff 内）：

1. **ISO 时间带 `T`**：`2026-11-20T18:00` 直接展示。根因是全站 18 个文件同款 `value.length > 16 ? value.slice(0,16) : value`。统一改为 `value.slice(0,16).replace('T',' ')`（含 `ActivityInfoSection`、`TaskContentSections`、`TaskGraph`、`ActivityTaskTable`、`ActivityBrowseCard`、`TaskDetail`、大厅与其它页面）。
2. **活动属性「组织：未加入组织」**：后端 `ActivityOut.org` 为空，前端直接回退兜底。`ActivityDetail` 增 `infoActivity`：优先 `activity.org`，缺失时按 `org_id` 从 `userStore.orgs` 解析名称。
3. **未分配负责人头像显示「待」**：`UserAvatar` 空名回退「待分配」取首字，容易被读成状态。`TaskGroupList` 改为无负责人时不渲染头像。
4. **无子任务仍显示「0/0 子任务」**：改为仅在 `total_children > 0` 时显示。

未验证：

- 深色主题实拍（本轮只验证浅色）；`AdminConsole` 内 `ActivityTaskTable` 新箭头图标实机渲染。
- 后端全量 `run_all`、安全红线：本轮无后端代码改动，未重跑。
- 真机、真实模型、部署：未涉及。
- 验收中登记但未修：依赖/工作区间视图把已完成任务也列入「未排期」（契约 `C-TASK-GRAPH` 明确定义为时间完整性视图，非状态视图，不改）；任务「截止时间」在内容区与侧栏各出现一次（`TaskContentSections` 契约要求复用）；1440 侧栏底部留白。

未完成：提交 / 推送 / CI（需用户针对该动作的授权）。