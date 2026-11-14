# AIW-14 真实浏览器验收报告（AC-18～AC-22）

> 执行：2026-11-14，隔离库 `work/aiw14/demo.db`（复制自 `work/aiw09/demo.db`），
> `MAAS_MOCK=1`、`RUN_SCHEDULER=0`，8000 端口托管已构建的 `frontend/dist`。
> 脚本：`work/aiw14/browse/verify-browse.cjs`；机器结果：`work/aiw14/browse/browse-report.json`。
> 本轮未修改业务代码；未触碰 `backend/campus.db`；结束后已停止 8000 进程并释放端口。

## 1. 结论

- **验收组：8 组中 6 PASS / 2 FAIL；断言 152 条中 149 PASS / 3 FAIL。**
- **AC-19、AC-20、AC-21 PASS**；**AC-18 FAIL**（展开侧栏「消息」入口被其他分组覆盖）；
  **AC-22 FAIL**（搜索点击结果未保留搜索词/来源，准确详情本身 PASS）。
- 未验证项：三列关闭后的滚动恢复（数据量下页面不可滚，N/A）、搜索前端分页 UI（数据量不足）、
  共享资料条目渲染（隔离库无资源，仅验证分区与空态）。

### 1.1 AC 对照

| AC | 验收点 | 结果 | 证据 |
| --- | --- | --- | --- |
| AC-18 | 分组标题、SVG 图标、展开/折叠、搜索/新对话、管理者入口、底部个人区、最近记录查看全部、键盘/手机抽屉 | **FAIL** | S1（「消息」覆盖）×、S7 PASS |
| AC-19 | 胶囊一次只显示一类、键盘/触摸、两类筛选/滚动各自保存、刷新/后退可恢复 | PASS | S2 |
| AC-20 | 1440 三列、选中左 1 右 2、切选/关闭恢复、A 晚到不覆盖 B、刷新/深链/后退、预览联合区 | PASS | S3、S4 |
| AC-21 | 添加→刷新找回→更新、本人私有/他人拒绝、管理员不自动可读、危险 URL 拒绝、共享资料分区 | PASS | S5 |
| AC-22 | 搜索 mine 活动/任务、非 mine/跨组织不返回、空/错误/旧响应、分页、点击准确详情并保留搜索词 | **FAIL** | S6（搜索词/来源保留 ×） |

## 2. 环境与隔离口径

| 项 | 值 |
| --- | --- |
| 数据库 | `work/aiw14/demo.db`；启动时自动补齐 `library_links`，`/api/health` 返回 24 表、`mock:true` |
| 后端 | `python work/aiw14/serve.py`（uvicorn 127.0.0.1:8000，托管 `frontend/dist`） |
| 账号 | `orgadmin`（组织管理员/活动负责人）、`collab`（同组织协作者）、`outsider`（另一组织） |
| 浏览器 | Playwright Chromium（headless），复用 `work/aiw07/runner/node_modules/playwright` |
| 视口 | 桌面 1440×900；移动 390×844（`isMobile + hasTouch`） |
| 前端产物 | `frontend/dist`（2026-11-14 16:47 构建，本轮未重建） |

## 3. 原始断言（按验收组）

### S1 · 侧栏分组、SVG 图标、折叠态 aria 与当前页状态 — FAIL

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 分组标题含「主导航」 | 包含「主导航」 | 主导航 \| 管理 \| 最近 \| AI 历史 | PASS |
| 分组标题含「管理」 | 包含「管理」 | 主导航 \| 管理 \| 最近 \| AI 历史 | PASS |
| 分组标题含「最近」 | 包含「最近」 | 主导航 \| 管理 \| 最近 \| AI 历史 | PASS |
| 分组标题含「AI 历史」 | 包含「AI 历史」 | 主导航 \| 管理 \| 最近 \| AI 历史 | PASS |
| 主导航条目数 | 5 | 5 | PASS |
| 主导航每项 SVG 图标数 | 5 | 5 | PASS |
| 主导航含 AI 对话 | 包含「AI 对话」 | AI 对话与通知 \| 任务大厅 \| 我的任务 \| Library \| 消息 | PASS |
| 主导航含 通知 | 包含「通知」 | 同上 | PASS |
| 主导航含 大厅 | 包含「大厅」 | 同上 | PASS |
| 主导航含 我的任务 | 包含「我的任务」 | 同上 | PASS |
| 主导航含 Library | 包含「Library」 | 同上 | PASS |
| 主导航保留消息入口 | 包含「消息」 | 同上 | PASS |
| 管理者入口含「我发布的活动」 | 包含「我发布的活动」 | 我发布的活动 \| 发布者后台 | PASS |
| 管理者入口含「发布者后台」 | 包含「发布者后台」 | 我发布的活动 \| 发布者后台 | PASS |
| 管理者入口 SVG 图标数 | 2 | 2 | PASS |
| 最近活动 / 最近任务两组 | 2 | 2 | PASS |
| 最近活动有查看全部 | 包含「查看全部活动」 | 最近活动 / 暂无相关活动 / 查看全部活动 | PASS |
| 最近任务有查看全部 | 包含「查看全部任务」 | 最近任务 / 暂无相关任务 / 查看全部任务 | PASS |
| 最近条目有真实数据或空态 | >0 或空态 | True（断言时点为空态） | PASS |
| AI 历史分组存在 | 1 | 1 | PASS |
| AI 历史只渲染真实条目或空态 | 空态或真实 HistoryEntry | True | PASS |
| AI 历史有查看全部入口 | 包含「查看全部」 | AI 历史 / 暂无 AI 历史 / 查看全部 | PASS |
| Library 当前页 aria-current | page | page | PASS |
| 底部主题切换存在 | 1 个 | True | PASS |
| 底部个人入口 aria-label | 个人主页 | 个人主页 | PASS |
| 底部退出按钮 aria-label | 退出登录 | 退出登录 | PASS |
| 搜索入口 aria-label | 搜索 | 搜索 | PASS |
| 新对话入口 aria-label | 新对话 | 新对话 | PASS |
| 900 高侧栏无需内部滚动即可容纳内容 | True | True | PASS |
| 侧栏分组垂直不重叠 | 后一组 top >= 前一组 bottom | True | PASS |
| 侧栏导航项高度未被压缩（>=40px） | 全部 >=40 | True | PASS |
| **侧栏导航项未被其他分组覆盖** | **命中自身** | **False** | **FAIL** |
| 折叠态侧栏 is-collapsed | true | True | PASS |
| 折叠后主导航图标仍为 5 | 5 | 5 | PASS |
| 折叠后主导航文字标签隐藏 | 0 | 0 | PASS |
| 折叠后每项 aria-label 完整 | 5 | 5 | PASS |
| 折叠后每项 title 完整 | 5 | 5 | PASS |
| 折叠后 Library aria-current 保持 | page | page | PASS |
| 折叠后分组标题隐藏 | 0 | 0 | PASS |
| 折叠后 AI 历史保留图标与可访问名称 | 1 个 | True | PASS |
| 折叠后按钮切换为展开 | 展开侧栏 | 展开侧栏 | PASS |
| 展开后文字标签恢复 | 5 | 5 | PASS |

- 几何备注：`.sidebar-head:16-172`、`desktop-nav:188-365`、`sidebar-admin:381-472`、
  `sidebar-recent:488-629`、`sidebar-history:645-715`、`sidebar-foot:731-884`。
- 导航项：`消息:h44/covered`，其余 `AI 对话与通知/任务大厅/我的任务/Library/我发布的活动/发布者后台:h44/top`。
- 截图 `aiw14-sidebar.png`、`aiw14-split.png` 可见「消息」与「管理」/「最近」标题、条目叠压。
- 备注：断言时点最近接口返回空态（0 条）；截图时点已加载最近活动与 AI 历史，属异步晚到，不据此判缺陷。

### S2 · /tasks 胶囊只渲染一类、`?type=` 持久化与刷新/后退一致 — PASS

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 胶囊 tab 数量 | 2 | 2 | PASS |
| tablist 语义 | tablist | tablist | PASS |
| 默认活动 tab 选中 | true | true | PASS |
| 默认任务 tab 未选中 | false | false | PASS |
| 默认只显示活动卡 | activity>0 且 task=0 | True | PASS |
| 点击任务后 URL type | task | task | PASS |
| 切换后只显示任务卡 | task>0 且 activity=0 | True | PASS |
| 任务 tab 选中 | true | true | PASS |
| 活动 tab 未选中 | false | false | PASS |
| 任务筛选状态已持久化 | 含 status=verified | True | PASS |
| 刷新后 URL type 保持 | task | task | PASS |
| 刷新后任务 tab 仍选中 | true | true | PASS |
| 刷新后仍只显示任务卡 | task>0 且 activity=0 | True | PASS |
| 刷新后任务筛选从 sessionStorage 恢复 | verified | verified | PASS |
| 键盘右方向键切到任务 | true | true | PASS |
| 切分类不堆积历史条目 | 3 | 3 | PASS |
| 后退回 /tasks 仍为任务集合 | task | task | PASS |
| 后退后任务卡仍显示 | >0 | True | PASS |
| 我的任务亦有胶囊 tab 2 个 | 2 | 2 | PASS |
| 我的任务默认活动 tab 选中 | true | true | PASS |
| 我的任务切换后不显示活动 | 0 | 0 | PASS |
| 我的任务任务空态可区分 | 包含「还没有与你相关的任务」 | 还没有与你相关的任务 / 你还没有需要执行或管理的任务…… | PASS |

- 备注：默认活动卡 4 张、任务卡 0；切任务后任务卡 1 张、活动卡 0。
- 备注：任务筛选写入 `{"status":"verified","scope":"all","type":"all","scrollTop":0}`。

### S3 · 1440 三列 → 左 1 右 2 分栏、关闭恢复、刷新/深链/晚到响应 — PASS

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 活动卡数量足够三列 | >=3 | True | PASS |
| 1440 宽列表为三列 | 3 | 3 | PASS |
| 前三张卡片同一行 | 1 | 1 | PASS |
| 分栏 URL selectedType | activity | activity | PASS |
| 分栏 URL selectedId | 1 | 1 | PASS |
| 分栏容器 class | True | True | PASS |
| 详情面板 aria-label | 选中事项摘要 | 选中事项摘要 | PASS |
| 详情标题为选中活动 | 包含「2026 迎新志愿活动」 | 2026 迎新志愿活动 | PASS |
| 左侧约占 1/3 | 0.25~0.42 | True | PASS |
| 右侧约占 2/3 | 0.55~0.75 | True | PASS |
| 分栏后列表变为单列 | 1 | 1 | PASS |
| 左侧列表卡片同列排列 | 1 | 1 | PASS |
| 关闭后清空 selectedType | null | null | PASS |
| 关闭后清空 selectedId | null | null | PASS |
| 关闭后恢复三列 | 3 | 3 | PASS |
| 切换选中更新详情 | 包含「AIW-08 桌面走查活动」 | AIW-08 桌面走查活动 | PASS |
| 刷新后仍按 URL 恢复分栏 | True | True | PASS |
| 刷新后详情仍为选中项 | 包含「2026 迎新志愿活动」 | 2026 迎新志愿活动 | PASS |
| 深链直接恢复选中详情 | 包含「2026 迎新志愿活动」 | 2026 迎新志愿活动 | PASS |
| 晚到的活动 A 不覆盖已选 B | 包含「2026 迎新志愿活动」 | 2026 迎新志愿活动 | PASS |
| 晚到后标题不含被丢弃的 A | false | false | PASS |

- 实测左列占比 0.329、右详情占比 0.658。
- 滚动恢复：页面高度不足 900，未观测，记 N/A（不伪报）。
- 截图 `aiw14-split.png`（1440 宽，左 1 右 2，选中「2026 迎新志愿活动」）。

### S4 · HoverPeek 卡片/8px 间隙/面板联合区、Esc、快划不弹 — PASS

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 停留后出现预览面板 | 1 | 1 | PASS |
| 鼠标经过 8px 间隙面板不关闭 | 1 | 1 | PASS |
| 移入面板保持打开 | 1 | 1 | PASS |
| 面板内点击不关闭 | 1 | 1 | PASS |
| 面板内滚动不关闭 | 1 | 1 | PASS |
| 移出联合区后关闭 | 0 | 0 | PASS |
| 再次停留打开面板 | 1 | 1 | PASS |
| Esc 关闭面板 | 0 | 0 | PASS |
| 快速划过不弹出 | 0 | 0 | PASS |

### S5 · Library 本人链接添加/更新/刷新找回，私有隔离与共享分区 — PASS

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 私有分区存在 | 1 | 1 | PASS |
| 私有分区标题 | 我的参考链接 | 我的参考链接 | PASS |
| 共享资料分区存在 | 1 | 1 | PASS |
| 共享分区标题 | 我可见的活动 / 任务资料 | 我可见的活动 / 任务资料 | PASS |
| 添加后列表出现本人链接 | 1 | 1 | PASS |
| API 返回本人新建链接 | 存在 | True | PASS |
| 刷新后仍能找回链接 | 1 | 1 | PASS |
| 更新标题后列表生效 | 1 | 1 | PASS |
| 旧标题已被精确替换 | false | false | PASS |
| javascript: 地址被拒绝并提示 | 有中文错误提示 | True（链接必须以 http:// 或 https:// 开头） | PASS |
| 危险地址未新增列表项 | 计数不变 | True | PASS |
| 同组织另一账号可创建自己的链接 | 0 | 0 | PASS |
| 同组织另一账号列表不含本人链接 | 0 | 0 | PASS |
| 同组织另一账号 API 不含本人链接 | False | False | PASS |
| 组织管理员列表不含他人私有链接 | 0 | 0 | PASS |
| 他人 PATCH 本人链接被拒绝 code=4040 | 4040 | 4040 | PASS |

- 备注：共享资料当前条目 0、空态 1（隔离库无 `activity_resources`，仅验证分区与空态）。
- 截图 `aiw14-library.png`（私有链接更新后 + 共享资料分区）。

### S6 · 顶部搜索只返回 mine 活动/任务、空/错误/旧响应、点击落准确详情 — FAIL

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 搜索按钮打开 dialog | dialog | dialog | PASS |
| 搜索输入 aria-label | 搜索关键词 | 搜索关键词 | PASS |
| 活动组标题为「我的活动」 | 包含「我的活动」 | 我的活动 1 / 2026 迎新志愿活动 / 活动 · 王老师 · 截止 2026-11-22 18:00 | PASS |
| 活动组结果标题正确 | 包含「2026 迎新志愿活动」 | 2026 迎新志愿活动 | PASS |
| 活动组计数 | 1 | 1 | PASS |
| 任务组为空时不渲染分组 | 0 | 0 | PASS |
| 分页 limit=1 只返回 1 条 | 1 | 1 | PASS |
| 分页 total 仍为完整命中数 | >=1 | True（total=4） | PASS |
| 非 mine 可见任务不混入搜索 | 0 | 0 | PASS |
| 非 mine 显示空态 | 包含「没有找到」 | 没有找到与「场地」匹配的活动或任务。 | PASS |
| 无结果空态可区分 | 包含「没有找到」 | 没有找到与「ZZZ不存在的关键词」匹配的活动或任务。 | PASS |
| 搜索失败显示错误态 | 有错误文案 | True | PASS |
| 错误态提供重试 | 1 | 1 | PASS |
| 重试后恢复结果 | 1 | 1 | PASS |
| 旧搜索响应不覆盖新词 | false | false | PASS |
| 新词结果/空态已落地 | 包含「场地」 | 没有找到与「场地」匹配的活动或任务。 | PASS |
| 点击结果落到准确活动 id | /activities/1 | /activities/1 | PASS |
| 详情页展示所选活动 | 包含「2026 迎新志愿活动」 | True（页面正文，已截断） | PASS |
| **点击结果保留搜索词 q（契约 AC-22）** | **迎新** | **null** | **FAIL** |
| **点击结果保留来源 from=search（契约 AC-22）** | **search** | **null** | **FAIL** |
| Esc 关闭搜索面板 | 0 | 0 | PASS |
| 跨组织账号搜索不返回他人活动 | 0 | 0 | PASS |
| 跨组织显示空态 | 包含「没有找到」 | 没有找到与「迎新」匹配的活动或任务。 | PASS |

- 备注：`search?q=活动&limit=1 => activities.total=4, items=1`。
- 备注：实际详情 URL `http://127.0.0.1:8000/activities/1`；页面无「返回搜索」入口（true）。
- 截图 `aiw14-search.png`（活动分组结果）。

### S7 · 390×844 移动抽屉、底栏、单列点击进详情与移动搜索 — PASS

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 移动端桌面侧栏隐藏 | False | False | PASS |
| 移动顶栏可见 | True | True | PASS |
| 菜单按钮可见 | True | True | PASS |
| 底部导航可见 | True | True | PASS |
| 底部导航保留主要入口 | >=4 | True（AI / 大厅 / 消息 / 个人主页） | PASS |
| 移动抽屉复用分组（主导航） | 1 | 1 | PASS |
| 移动抽屉分组标题可见 | 主导航 | 主导航 | PASS |
| 抽屉主导航条目 SVG | 5 | 5 | PASS |
| 抽屉标记当前页 aria-current | >=1 | True（任务大厅） | PASS |
| 抽屉点击 Library 跳转 | /library | /library | PASS |
| 跳转后抽屉关闭 | false | false | PASS |
| 移动端胶囊仍为 2 个 | 2 | 2 | PASS |
| 移动端胶囊占满可用宽度 | >300px | True | PASS |
| 移动端卡片单列 | 1 | 1 | PASS |
| 移动端点击卡片进入独立详情 | True | True | PASS |
| 移动端搜索入口打开面板 | True | True | PASS |
| 移动端搜索可关闭 | 0 | 0 | PASS |

- 截图 `aiw14-mobile.png`（导航抽屉）、`aiw14-mobile-tasks.png`（单列卡片）。

### S8 · 浅色/深色主题截图与主题切换断言 — PASS

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 浅色主题默认 | false | false | PASS |
| 切换后进入深色主题 | true | true | PASS |

- 截图 `aiw14-light.png`（浅色 /tasks 三列）、`aiw14-dark.png`（深色 /tasks 三列）。

## 4. 缺陷复现步骤

### 缺陷 A（AC-18）：侧栏「消息」入口被覆盖

1. `cp work/aiw09/demo.db work/aiw14/demo.db`，`python work/aiw14/serve.py`，确认 `/api/health` 24 表、`mock:true`。
2. Playwright 1440×900 以 `orgadmin` 登录，打开 `/library`，保持侧栏展开。
3. 观察主导航最后一项「消息」：其文字与「管理」标题/「我发布的活动」及「最近」标题叠压。
4. 在该条目中心执行 `document.elementFromPoint`，命中元素 `closest('a')` 不是「消息」链接。
5. 证据：`aiw14-sidebar.png`、`aiw14-split.png`、断言“侧栏导航项未被其他分组覆盖 = false”、
   几何备注 `消息:h44/covered`。

### 缺陷 B（AC-22）：点击搜索结果不保留搜索词/来源

1. 以 `orgadmin` 登录，打开侧栏搜索，输入「迎新」。
2. 结果出现「2026 迎新志愿活动」，点击。
3. URL 变为 `/activities/1`，详情正确，但地址栏无 `q=迎新`、无 `from=search`；
   页面也无返回搜索结果的入口。
4. 证据：断言两项均 `null`；备注 URL 与“页面无「返回搜索」入口：true”。

## 5. 未验证范围

- 三列关闭详情后的滚动恢复：隔离库数据下页面高度不足 900，无法观测真实滚动，N/A。
- 搜索前端“加载更多/分页”交互：仅验证 API `limit=1` 切片与 total；数据量不足以触发 UI 分页。
- Library 共享资料条目渲染：`activity_resources` 为 0，只验证分区与空态；未构造共享资料数据。
- HoverPeek 在触摸设备不注册预览：移动端仅验证点击卡片进入独立详情，未构造触摸 hover 时序。
- 本轮不验证真实模型调用、语音、真实设备与线上部署；`MAAS_MOCK=1` 仅用于隔离。

## 6. 截图索引（真实截图，1440×900 或 390×844）

| 文件 | 内容 |
| --- | --- |
| `codearts_proof/screenshots/aiw14-sidebar.png` | 1440 展开侧栏，/library 当前页，可见分组/SVG/最近/AI 历史/个人区 |
| `codearts_proof/screenshots/aiw14-split.png` | 1440 /tasks 三列选中后左 1 右 2 分栏 |
| `codearts_proof/screenshots/aiw14-library.png` | /library 私有链接更新后 + 共享资料分区 |
| `codearts_proof/screenshots/aiw14-search.png` | 顶部搜索「迎新」的活动分组结果 |
| `codearts_proof/screenshots/aiw14-mobile.png` | 390×844 导航抽屉（分组与当前页） |
| `codearts_proof/screenshots/aiw14-mobile-tasks.png` | 390×844 /tasks 单列胶囊与卡片 |
| `codearts_proof/screenshots/aiw14-light.png` | 浅色主题 /tasks 三列 |
| `codearts_proof/screenshots/aiw14-dark.png` | 深色主题 /tasks 三列 |
---

# 第 2 次复验（2026-11-14，dist 重建后）

> 触发：前端修复并重新构建 `frontend/dist`（2026-11-14 17:12 构建，7.45s）。
> 环境沿用同一隔离库 `work/aiw14/demo.db`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、8000 托管新 dist；
> 账号 `orgadmin` / `collab`；使用真实登录页登录 + 应用内导航（除明确要求的刷新验证外不整页 goto）。
> 脚本：`work/aiw14/browse/verify-browse-r2.cjs`；机器结果：`work/aiw14/browse/r2-report.json`。
> **历史第 1 次结论保留在上文，未被覆盖。**

## 2.1 复验结论

- **3 个复验组中 2 PASS / 1 FAIL；断言 59 条中 58 PASS / 1 FAIL。**
- **AC-18：PASS（22/22）**。1440×900 与 1920×1080 下「消息」「Library」「最近活动条目」「查看全部活动」「查看全部任务」均 `elementFromPoint` 命中自身且点击跳转正确；侧栏改为独立滚动容器，不再叠压。
- **AC-22：PASS（7/7）**。搜索→详情 URL 带 `from=search&q=迎新`；返回列表后重开面板自动回填原词并恢复活动结果；`cta_search_return` 记录 `{q,from}`。
- **AIW-09 历史：FAIL（30 条中 29 PASS / 1 FAIL）**。侧栏真实会话、抽屉「最近/全部」、续聊、刷新恢复、用量不变、新对话不扣额度、跨账号隔离均 PASS；
  唯一失败：**从历史抽屉点击会话后 URL 未写回 `conversation`**（实际 `/ai`），此时刷新会丢失选中会话。
  侧栏 AI 历史入口点击可正确写回 `?conversation=4` 并刷新恢复（6 条消息，不含会话 3 独有内容）。

## 2.2 R2-A · AC-18 侧栏叠压（PASS，22 条）

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| [1440] 侧栏主体独立滚动容器 | overflow-y auto/scroll | True（scrollHeight 1100 / clientHeight 699） | PASS |
| [1440] 消息 命中自身 | 中心 elementFromPoint 命中自身 | True | PASS |
| [1440] 点击 消息 跳转 | /messages | True | PASS |
| [1440] Library 命中自身 | 命中自身 | True | PASS |
| [1440] 点击 Library 跳转 | /library | True | PASS |
| [1440] 最近活动条目 命中自身 | 命中自身 | True（高度 28px） | PASS |
| [1440] 点击 最近活动条目 跳转 | /activities/:id | True | PASS |
| [1440] 查看全部活动 命中自身 | 命中自身 | True | PASS |
| [1440] 点击 查看全部活动 跳转 | /my-tasks?type=activity | True | PASS |
| [1440] 查看全部任务 命中自身 | 命中自身 | True | PASS |
| [1440] 点击 查看全部任务 跳转 | /my-tasks?type=task | True | PASS |
| [1920] 侧栏主体独立滚动容器 | overflow-y auto/scroll | True（scrollHeight 1100 / clientHeight 879） | PASS |
| [1920] 消息 命中自身 | 命中自身 | True | PASS |
| [1920] 点击 消息 跳转 | /messages | True | PASS |
| [1920] Library 命中自身 | 命中自身 | True | PASS |
| [1920] 点击 Library 跳转 | /library | True | PASS |
| [1920] 最近活动条目 命中自身 | 命中自身 | True（高度 28px） | PASS |
| [1920] 点击 最近活动条目 跳转 | /activities/:id | True | PASS |
| [1920] 查看全部活动 命中自身 | 命中自身 | True | PASS |
| [1920] 点击 查看全部活动 跳转 | /my-tasks?type=activity | True | PASS |
| [1920] 查看全部任务 命中自身 | 命中自身 | True | PASS |
| [1920] 点击 查看全部任务 跳转 | /my-tasks?type=task | True | PASS |

## 2.3 R2-B · AC-22 搜索返回（PASS，7 条）

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 点击结果详情路径准确 | /activities/1 | /activities/1 | PASS |
| 详情 URL 保留 q | 迎新 | 迎新 | PASS |
| 详情 URL 保留 from=search | search | search | PASS |
| 返回后重开面板回填原词 | 迎新 | 迎新 | PASS |
| 返回后重开面板恢复结果 | 含「2026 迎新志愿活动」 | 2026 迎新志愿活动 | PASS |
| cta_search_return 记录词与来源 | `{"q":"迎新","from":"search"}` | 同左 | PASS |
| Esc 关闭搜索面板 | 0 | 0 | PASS |

- 详情 URL 实测：`http://127.0.0.1:8000/activities/1?from=search&q=%E8%BF%8E%E6%96%B0`。
- 截图 `aiw14-r2-search-return.png`（返回后重开搜索，恢复原词与结果）。

## 2.4 R2-C · AIW-09 历史（FAIL，30 条中 29 PASS / 1 FAIL）

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 侧栏 AI 历史显示 2 条真实会话 | 2 | 2 | PASS |
| 侧栏含「不支持时文字兜底问题」 | 包含 | 不支持时文字兜底问题 \| 任务完整页问题 | PASS |
| 侧栏含「任务完整页问题」 | 包含 | 同上 | PASS |
| 侧栏不再渲染空态 | 0 | 0 | PASS |
| 历史抽屉全部列表 2 条 | 2 | 2 | PASS |
| 抽屉有最近/全部两个 tab | 2 | 2 | PASS |
| 默认选中「全部」 | true | true | PASS |
| 「最近」切到本作用域空态 | 0 | 0 | PASS |
| 「最近」空态文案可区分 | 含「暂无历史会话」 | 暂无历史会话。 | PASS |
| 切回「全部」恢复 2 条 | 2 | 2 | PASS |
| 加载历史不产生新的 AI 用量 | 16 | 16 | PASS |
| 抽屉续聊旧会话加载 6 条消息 | 6 | 6 | PASS |
| 加载的是「任务完整页问题」会话 | 包含 | 任务完整页问题 | PASS |
| 抽屉在选会话后关闭 | false | false | PASS |
| 切换会话不产生新的 AI 用量 | 16 | 16 | PASS |
| **抽屉点会话写回 conversation query** | **4** | **null** | **FAIL** |
| 侧栏历史点击写回 conversation query | 4 | 4 | PASS |
| 刷新后 conversation query 保留 | 4 | 4 | PASS |
| 刷新后恢复 6 条消息 | 6 | 6 | PASS |
| 刷新后恢复指定会话而非最近一条（无会话3独有内容） | false | false | PASS |
| 刷新恢复会话不产生新的 AI 用量 | 16 | 16 | PASS |
| 新对话清除 conversation query | null | null | PASS |
| 新对话清空当前消息 | 0 | 0 | PASS |
| 新对话不扣额度 | 16 | 16 | PASS |
| 同组织另一账号侧栏显示自己的空态 | 含「暂无 AI 历史」 | AI 历史 / 暂无 AI 历史 / 查看全部 | PASS |
| 同组织另一账号侧栏不含他人标题（×2） | false | false | PASS |
| 同组织另一账号抽屉为空态 | 含「暂无历史会话」 | 暂无历史会话。 | PASS |
| 同组织另一账号 API 会话 total=0 | 0 | 0 | PASS |
| 跨账号直读他人会话返回 4040 | 4040 | 4040 | PASS |

- 用量全程：起始 16 / 加载历史 16 / 切会话 16 / 刷新 16 / 新对话 16。
- 截图 `aiw14-r2-history.png`（历史抽屉「全部」列表，2 条会话；侧栏 AI 历史同时显示 2 条）。

### 复验缺陷 C：历史抽屉点击会话后 URL 丢失 conversation（AIW-09 历史项）

1. 真实登录 `orgadmin`，侧栏点击「AI 历史 → 查看全部」进入 `/ai?history=1`。
2. 抽屉「全部」中有「任务完整页问题」，点击后会话消息正确加载（6 条），抽屉关闭。
3. 实际 URL 变为 `http://127.0.0.1:8000/ai`（`conversation=null`），刷新后会话丢失（消息 0 条）。
4. 对照：侧栏 AI 历史直接点击同一条目，URL 正确为 `/ai?conversation=4`，刷新恢复 6 条且不含会话 3 独有内容「账号A私密问题」。
5. 证据：断言“抽屉点会话写回 conversation query = null”；调试路径记录 URL `/ai`。

## 2.5 遗留观察（不计入本轮验收失败）

- 整页直连/刷新（非“登录页登录后应用内导航”）时，`AppLayout` 侧栏“最近活动/最近任务/AI 历史”未发起请求而显示空态；
  真实登录页登录后正常加载。此现象在验收中复现，建议另立任务核查 `onMounted` 与会话恢复时序；
  本轮按验收要求的“登录后侧栏”路径判定 PASS，刷新 `/ai?conversation=4` 的会话恢复已单独验证 PASS。

## 2.6 第 2 次复验截图

| 文件 | 内容 |
| --- | --- |
| `codearts_proof/screenshots/aiw14-r2-sidebar-1440.png` | 1440×900 展开侧栏，无叠压，最近条目与 AI 历史可滚动可达 |
| `codearts_proof/screenshots/aiw14-r2-sidebar-1920.png` | 1920×1080 展开侧栏，无叠压 |
| `codearts_proof/screenshots/aiw14-r2-search-return.png` | 返回列表后重开搜索，自动回填「迎新」并恢复活动结果 |
| `codearts_proof/screenshots/aiw14-r2-history.png` | 历史抽屉「最近/全部」与 2 条真实会话 |
## 2.7 R3 定向复验（修复后，2026-11-14 17:23；dist 构建 2026-11-14 17:22:41）

> 范围：只复验 2.4 的唯一失败断言——历史抽屉点击会话后 URL 是否写回 `conversation`，
> 以及随后整页刷新是否恢复该会话、用量是否不变。上文 2.4 的 FAIL 保留为修复前历史结论，不覆盖。
> 环境：同一隔离库 `work/aiw14/demo.db`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、8000 托管新 dist；
> 真实登录页登录 + 应用内导航；脚本 `work/aiw14/browse/verify-browse-r3.cjs`，结果 `r3-report.json`。

**R3 结论：PASS，13/13 断言全部通过。** 修复已生效：重复点击同一会话（store 的 `conversationId`
已指向该会话）也会显式写回地址栏，且刷新按 `?conversation=` 恢复指定会话。

| 断言 | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| 历史抽屉打开且显示全部 2 条 | 2 | 2 | PASS |
| 抽屉点会话写回 conversation query | 4 | 4 | PASS |
| 抽屉点会话后 history query 已清除 | null | null | PASS |
| 点击后确实发生 URL 写回 | true | true | PASS |
| 续聊旧会话加载 6 条消息 | 6 | 6 | PASS |
| 加载的是「任务完整页问题」会话 | true | true | PASS |
| 抽屉在选会话后关闭 | false | false | PASS |
| 切换会话不产生新的 AI 用量 | 16 | 16 | PASS |
| 整页刷新后 conversation query 保留 | 4 | 4 | PASS |
| 整页刷新后恢复 6 条消息 | 6 | 6 | PASS |
| 刷新恢复指定会话而非最近一条（无会话3独有内容） | false | false | PASS |
| 刷新后仍显示该会话的首条用户消息 | true | true | PASS |
| 刷新恢复会话不产生新的 AI 用量 | 16 | 16 | PASS |

- 点击后实际 URL：`http://127.0.0.1:8000/ai?conversation=4`；刷新后仍为 `?conversation=4`，消息 6 条。
- 用量全程：起始 16 / 切换后 16 / 刷新后 16。
- 截图：`codearts_proof/screenshots/aiw14-r3-history.png`（抽屉点击后会话已载入、URL 已写回；侧栏 AI 历史可见）。