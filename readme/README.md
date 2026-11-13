# 校园任务协同 AI Agent · 部署与运行说明

> 本文件是官方提交要求的 `readme/` 主体：环境依赖、一键安装、部署运行步骤、演示账号、
> `.env` 配置、离线 mock 说明与常见问题。
> 契约来源：本工程规划契约 `C-BOOT@1`（后端基线）、`C-SHELL@1`（前端端口与构建）。

---

## 1. 环境依赖

| 组件 | 要求 | 说明 |
|---|---|---|
| Python | **≥ 3.10**（推荐 3.11 / 3.12） | 3.14 部分依赖可能缺少预编译轮子，见第 9 节常见问题 |
| Node.js / npm | **≥ 18** | 前端为 Vite 5 + Vue 3 |
| 浏览器 | **Chrome / Edge** 最新版 | 语音输入依赖浏览器原生 Web Speech API；Firefox / Safari 不支持 |
| 操作系统 | Windows 10+ / macOS / Linux | Windows 可用 `cmd`（`install.bat`）或 `git-bash`（`install.sh`） |
| 网络 | 首次安装需要 | 需拉取 PyPI 与 npm 依赖；离线演示时的 AI 调用不联网 |

可选：`curl`（健康检查）、`bash`（`install.sh` 与 `backend/scripts/*.sh` 冒烟脚本）。

---

## 2. 一键安装

脚本位于工程根的 `readme/` 目录。脚本会自行推导工程根，因此**推荐在工程根目录执行**；也可用脚本绝对路径在任意目录执行（无需手动 `cd`）。

**Linux / macOS / Windows git-bash**

```bash
bash readme/install.sh
```

**Windows cmd（不使用 WSL）**

```bat
readme\install.bat
```

两个脚本行为一致：

| 步骤 | 动作 | 幂等性 |
|---|---|---|
| 1 | 选择 Python：优先 `python3.12` / `python3.11`，找不到则退回系统 `python` 并提示 3.14 兼容性风险 | — |
| 2 | 创建 `backend/.venv`，已存在则保留 | **不删除**已有环境 |
| 3 | `pip install -r backend/requirements.txt` | 可重跑 |
| 4 | `npm install`（在 `frontend/`），已存在 `node_modules` 则跳过 | **不删除**已有依赖 |
| 5 | 在 `backend/` 下调用 `app.db.init_db()` 建 11 张表（含 `task_applications` / `task_members` / `activities`），并执行幂等增量迁移 | 建表与迁移幂等 |
| 6 | 打印 `.env` 提示与启动命令 | — |

> 脚本**不会**自动创建 `backend/.env`（避免真实 Key 被误提交），请按第 6 节手动创建或直接以 mock 模式运行。

---

## 3. 部署运行步骤

以下命令在**工程根目录**执行。

```bash
# 终端 1 · 后端（端口 8000）
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# macOS / Linux：把解释器换成 .venv/bin/python

# 终端 2 · 前端（端口 5173，/api 经 Vite 代理到 127.0.0.1:8000）
cd frontend
npm run dev
```

> **公网穿透访问**：`frontend/vite.config.ts` 的 `server.allowedHosts = ['.takin.cc']` 已放行该域名及其所有子域，
> 通过内网穿透的公网域名访问前端**不再返回 `403 Blocked request`**（Vite dev server 会对 `Host` 头做白名单校验，
> 默认只放行 `localhost` / `.localhost` 与所有 IP）。该白名单**仅 Vite 开发服务器需要**；
> `npm run build` 的静态产物由反向代理（Nginx / Caddy）托管，**Host 校验由反代负责**，无需写进 `vite.config.ts`。

启动后：

| 项 | 地址 / 说明 |
|---|---|
| 前端页面 | `http://localhost:5173` |
| 后端 API | `http://127.0.0.1:8000` |
| 健康检查（无需登录） | `GET http://127.0.0.1:8000/api/health` |
| `/api` 代理 | 前端所有 `/api` 请求（含 SSE）由 Vite 代理到 `http://127.0.0.1:8000`，无需额外配置 CORS |
| 接口文档 | `http://127.0.0.1:8000/docs`（FastAPI 自带） |

健康检查返回示例（`tables` 为 11 张表，`mock` 表示是否离线模式）：

```bash
curl -s http://127.0.0.1:8000/api/health
# {"code":0,"msg":"ok","data":{"status":"ok","tables":["activities","checkins","credit_logs","kb_entries","notifications","parse_sessions","progress_logs","task_applications","task_members","tasks","users"],"mock":true}}
```

### 生产构建（可选）

```bash
cd frontend
npm run typecheck     # vue-tsc --noEmit，要求零 any
npm run build         # 产物输出 frontend/dist/
npm run preview       # 本地预览构建产物
```

静态产物需由 Web 服务器托管，并把 `/api` 反向代理到后端 8000（部署到华为云时可用 Caddy/Nginx 托管 `dist/` 并反代 uvicorn）。

---

## 4. 演示账号

登录接口为「**首次登录自动建号**」，无需导入任何 SQL、无需密码，输入用户名即可登录。

| 用户名 | 角色 | 展示名 | 可做什么 |
|---|---|---|---|
| `teacher01` | `publisher`（发布者） | 王老师 | 发布 / 拆解 / 指派 / 催办设置 / 验收，进入发布者后台 |
| `student01` | `student`（执行者） | 李同学 | 任务大厅认领、更新进度、提交、签到、查看积分 |
| `student02` | `student` | 张同学 | 同上 |
| `student03` | `student` | 陈同学 | 同上 |

角色判定规则（与后端实现一致）：

- 用户名以 `teacher` 开头 → `publisher`；
- 用户名以 `admin` 开头 → `admin`；
- 其余 → `student`。

---

## 5. 页面与功能入口

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 登录页 | 唯一公开页，输入演示账号用户名即可登录 |
| `/publish` | 统一发布页 | **默认 AI 智能模式**（手动表单为兜底）+ 文字 AI 解析 + 语音流式发布 |
| `/tasks` | 任务大厅 | 任务列表、状态筛选、认领 |
| `/tasks/:id` | 任务详情 | 子任务与依赖、SOP 指导、进度、提交、签到 |
| `/profile` | 个人中心 | 我的任务、积分流水、签到记录、通知中心 |
| `/admin` | 发布者后台 | 拆解确认、指派、催办设置、进度总览、验收 |

### 5.1 本轮迭代新增的四项能力（R12~R17）

| 能力 | 说明 |
|---|---|
| **报名审批** | 学生报名是「申请」而非占用任务：状态 `pending → approved / rejected / cancelled`；发布者（老师）**通过后才生效**，拒绝必须填写原因，审批前学生可**撤回**；名额是**人数上限**（`quota`，`null` 表示不限），`approved_count < quota` 时其他人仍可报名；验收通过后**每名 approved 成员各得积分**（幂等，不重复加分） |
| **增量解析** | AI 解析完成后左侧输入区**仍可继续输入**；追加「人数修改为 6 人」等新内容并点「AI 增量解析」，只把**本次追加文本 + 当前草稿**发给模型，返回合并后的完整草稿与字段级 `changes`（`old_value` 取当前草稿的值）；追加原文以 `user_note` 块保留，**不写入任何数据字段** |
| **追溯块** | 左侧 5 类块：`raw`（解析出的数据块，按字段染色）、`ai_applied`（**仅在用户显式采纳** AI 建议 / 问号建议 / 润色时生成，紫 `#8B5CF6`）、`user_edit`（`用户：将…改为…`，青 `#0891B2`）、`user_note`（用户追加原文，灰 `#6B7280`）、`live`（语音临时块，蓝 `#3B82F6` 虚线）；**解析不再自动生成「AI建议：」追溯块**，紫块只在真采纳时出现；**建议语句只展示、不落字段**，右侧只保留纯数据值；**左侧文字块点击编辑入口已移除**，改字走右侧字段面板 + 增量解析 |
| **语音实时** | 说话过程中**逐字可见**：任一标点即切（阈值 1）、无标点满 **12 字**强制切、连续 **800ms** 无新结果即切；interim 结果以 `live` 块实时显示（刷新 ≤200ms）；连续说话时 Edge 静默触发 `onend` 会自动续接识别；**停止录音改由 `onend` 收尾**——`stop()` 不再清缓冲，收尾窗口内识别帧照常入缓冲但不零散发片，`onend` 后延迟一个 `FINAL_DELAY_MS` 把剩余文本整体作为尾片发出，**末批必达、不重复**；停止后**仍直接回到编辑态并自动触发审核/润色建议**（不再有悬浮确认层） |

> 说明：报名审批取代第一轮的「单任务单负责人」模型（`assignee_id` 降级为首位 approved 的兼容字段，多成员展示以 `assignee_names` 为准）。

### 5.2 第三轮体验修复的四项改动（B1~B11）

| 改动 | 说明 |
|---|---|
| **悬浮确认层已删除** | 语音结束**直接回到编辑态**并**自动触发审核/润色建议**；原底部悬浮确认层（含「取消即清空已说内容」的分支）已彻底删除，已说内容始终保留，不会再被误点清空 |
| **子任务默认不随主任务发布** | 拆解收紧：小任务不拆，**≥2 条子任务才渲染**子任务区；发布页子任务复选框**默认未勾选**，需用户显式勾选才随主任务一并发布 |
| **草稿自动本地持久化** | 文字块、字段值、风格要求随输入自动写入本地存储，页面刷新或从后台切回后自动恢复（**刷新不丢**）；执行「清空草稿」时同步清除本地快照 |
| **已关闭 DeepSeek 思考模式** | 后端调用 MaaS 模型时**关闭思考模式**以降低首字与整段解析延迟，语音流式与增量解析的响应更快 |

### 5.3 第四轮体验微调（C1~C5）

| 改动 | 说明 |
|---|---|
| **发布页默认 AI 智能模式** | 进入 `/publish` 默认停在 **AI 智能模式**，打字或说话即可解析；手动表单保留为**兜底**（AI 不可用或用户主动切换时使用） |
| **全站字号整体 +1px** | 以全局字号变量统一抬升为主、硬编码 `font-size` 逐处 +1px 为辅，行高与既有排版不被破坏（不破版） |
| **左侧文字块点击编辑入口已移除** | 不再通过点击文字块改字；修改统一走**右侧字段面板**与**增量解析**两条路径（用户明确表示不需要块内编辑入口） |
| **解析不再生成「AI建议：」追溯块** | 解析（含增量解析）只落值、不留紫块；只有用户**显式采纳** AI 建议 / 问号建议 / 润色时才生成 `ai_applied` 紫块，左侧不再被无意义的追溯块淹没 |
| **语音停止改由 `onend` 收尾** | 停止时进入收尾窗口、不再清缓冲；窗口内识别帧照常入缓冲但不零散发片，`onend` 后延迟一个 `FINAL_DELAY_MS` 整体发尾片 ⇒ **末批必达、不重复**；尾片成功后仍自动进入审核，**两个 agent 顺序不变**，停止后仍出审核建议 |
| **语音续接不重复** | Edge 连续说话时静默触发 `onend` 会自动续接识别；续接时**保留本地去重链**（`dedupTail` 只在**新建会话**时清空），并对续接后重新吐出的重叠前缀做**重叠裁剪**（`trimRestartOverlap`）⇒ 同一句**不会**重复进入草稿，也不会带出上一句的前导逗号 |

> 说明：本轮对第三轮的块编辑口径做了**反转**——第三轮 B5 是「修好并保留块内编辑」，第四轮用户明确「能编辑但不想要这个入口」，故入口整体移除，改字统一走右侧字段面板 + 增量解析。

### 5.4 第一阶段可靠性改进

| 改动 | 说明 |
|---|---|
| **开始时间与截止时间分离** | `tasks.start_time` 与 `tasks.deadline` 是两个独立字段。AI 草稿的 `Draft.deadline`、字段面板、草稿本地恢复、`toTaskPayload()` 发布请求与任务详情分别承载，互不复制；只给开始时间时 `deadline=null`，只给截止时间时 `start_time=null`。自然语言截止时间若无法解析为合法时间，调度器跳过截止相关提醒与扣分并记录日志 |
| **逐人执行与验收** | 新增 `task_members` 表，每名 approved 成员独立记录 `not_started / in_progress / submitted / rejected / verified`、`submitted_at`、`verified_at`、`rejection_reason`。提交/退回/验收只改目标成员；发布者可按成员验收或退回，退回者修改后可重新提交。任务整体状态由成员状态聚合：全部 `verified` 才整体完成；任一成员 `submitted` 时任务为 `submitted`，但不代表其他成员已完成；任一成员 `rejected` 时任务回到 `in_progress` |
| **逐人催办与逾期扣分** | 催办按每名 approved 成员状态判断：`submitted/verified` 不催办、不扣分；`not_started/in_progress/rejected` 按截止时间触发 warning/urgent/overdue。逾期扣分按 `(task_id, user_id)` 只写一次；去重键包含截止时间版本，改期后按新时间重新提醒，历史通知与积分流水保留 |
| **逾期可恢复** | `overdue` 不再是只能取消的终态：未完成成员仍可补交，发布者可验收或退回，也可修改截止时间；合法未来截止时间可把 `overdue` 恢复为 `claimed/in_progress/submitted`。发布者取消仍保留；取消后成员不能继续提交/验收 |
| **兼容与迁移** | `init_db()` 只增列/索引/补行：为 legacy 单负责人任务补 approved 报名与 `task_members` 行，状态按任务状态映射一次，`submitted_at/verified_at` 留 `NULL`；`notifications.dedupe_key` 与 `uq_task_members_task_user` 幂等创建。迁移不删库、不重建、不伪造个人提交/验收时间，重复执行不产生重复行 |

> 配置说明：本轮不新增环境变量或积分配置开关；催办仍由 `RUN_SCHEDULER` / `REMINDER_INTERVAL_SECONDS` 控制，默认奖励与逾期扣分额度沿用原值，不新增开关。
>
> 验证入口：`PYTHONPATH=backend python -m pytest tests/backend/test_reliability.py -q`（11 passed）；既有后端脚本见根 `README.md` 第八节。真实历史库迁移演练与真实浏览器页面走查不在本轮自动化范围内。

### 5.5 全站 UI 与移动端体验（阶段 14）

| 改动 | 说明 |
|---|---|
| **Light / Dark 双主题** | 由 `frontend/src/styles/theme.css` 统一提供 `--app-*` 设计令牌与 Element Plus `--el-*` 覆盖；导航、卡片、表格、表单、按钮以及弹窗、日期选择器、下拉、tooltip、popover 等传送层浮层均随主题切换。无手动选择时按 `prefers-color-scheme` 决定，手动选择后写入 `localStorage['cta_theme']` 并在刷新后保持；首屏由 `index.html` 内联脚本提前应用，避免明显闪白；切换只变更 `html.dark` 与 `data-theme`，不重挂路由、不清空草稿与输入 |
| **桌面 / 手机导航** | 桌面保留顶部横向导航；≤768px 改为顶部紧凑栏（品牌、主题、通知、退出）＋底部 4 项导航（任务大厅 / 发布任务 / 个人中心 / 发布者后台，后台仅发布者可见）。当前页有 `aria-current="page"`，通知锚点 `/profile#notifications` 会按固定头部高度偏移滚动 |
| **任务大厅与发布页** | 任务网格使用 `minmax(min(100%,300px),1fr)`，320px 无横向溢出；筛选触屏友好并常显当前筛选；卡片分别展示任务状态、我的报名状态、我的执行状态，不可报名原因直接可见。发布页 ≥961px 双栏、≤960px 单栏，手机发布栏吸底显示在底部导航之上且不遮住最后控件 |
| **宽表转移动卡片** | 个人中心积分/签到、任务详情成员状态、发布者后台任务表均同时渲染桌面表格（`.app-desktop-table`）与移动卡片（`.app-mobile-list`），可见性由 `theme.css` 的 768px 媒体查询唯一控制；移动卡片保留关键字段与全部操作（审核报名、拒绝原因、指派、改截止、催办、验收、取消） |
| **触控与安全区** | 移动端主要按钮与图标热区 44×44；输入/文本域 16px 避免 iOS 聚焦放大；底部导航与页面留白计入 `env(safe-area-inset-bottom)`；弹窗宽 `calc(100vw - 24px)`、最大高 `90dvh`、内容可滚且底部操作常显；日期面板与下拉在视口内限宽滚动 |
| **中文化与可读性** | 全站以 `el-config-provider :locale="zhCn"` 使用简体中文；字段/追溯色统一由颜色池输出 CSS 变量（`var(--c-*)`），同一字段在两个主题下同色相，深色下使用提亮变体 |

> 配置说明：本轮**不新增环境变量或业务开关**。主题偏好仅存于浏览器 `localStorage['cta_theme']`（`light` / `dark`），无记录时跟随系统；任务详情在报名被拒时读取既有 `GET /api/applications/me` 展示拒绝原因，不改变报名/审批规则。
>
> 忽略规则：根 `.gitignore` 新增 `/outputs/`、`/.playwright-mcp/`、`/work/`，只排除版本控制，不删除本地文件；其中无已跟踪文件。
>
> 验证入口与实际结果：`PYTHON_BIN=python bash tests/frontend/run_all.sh` → `EXIT=0`，构建门禁 **4 passed / 0 failed**、静态契约 **25 passed / 0 failed**、语音切片 **21 PASS / 0 FAIL**。浏览器走查（8000 同源 dist）实测 `/tasks` 320=305/320、390=375/390、1440=1425/1440，390 `/admin` 桌面表 `display:none`、移动卡 `display:block`；四组截图与 `walkthrough.md` 位于 `outputs/ui-redesign/`（本地忽略）。真机软键盘、横竖屏、安全区与真实麦克风权限未验证。

### 5.6 主动协作与 AI 用量（AIW-05）

| 改动 | 说明 |
|---|---|
| **旧提醒失效与变更通知** | 改期或取消后，同一任务中不属于新截止时间版本的催办通知标记为 `stale`，历史保留但不计未读；发布者与当前 approved 成员收到变更通知，包含旧值→新值、提醒按新时间重算与受影响后续任务数 |
| **受控改期确认卡** | 发布者后台的改期对话框在确认前调用只读影响预览，展示当前截止→拟调整截止、提醒是否重置、受影响成员与后续任务、通知接收人；确认后才调用既有 `PATCH /api/tasks/{id}`，由后端再次校验权限并执行 |
| **AI 用量账本与额度** | 新增 `ai_usage_ledger`，每次成功回答写一条 `settled` 记录；客户端 `request_id` 提供幂等，重试返回首次结果，不新增消息或账本。每日次数上限由 `AI_DAILY_QUOTA` 控制（默认 50，0 表示当天不生成）；个人中心与 AI 页展示今日用量。额度用完只停问答，任务、通知、报名、审批与验收照常可用 |
| **边界** | 本轮不做收费、支付、套餐或供应商结算；额度单位与最终收费规则未确认。AI 仍不直接写业务表，改期仍由有权限的人确认后调用既有服务 |

---

## 6. `.env` 配置说明

后端配置文件为 `backend/.env`（已加入 `.gitignore`，仓库只提交占位值 `backend/.env.example`）。

```bash
cd backend
cp .env.example .env          # Windows cmd: copy .env.example .env
```

| 变量 | 默认值 | 语义 |
|---|---|---|
| `MAAS_API_KEY` | 空 | 真实 MaaS Key；为空 ⇒ 自动进入 mock 模式（不发起外部请求） |
| `MAAS_BASE_URL` | `https://example.invalid/v1` | OpenAI 兼容端点（华为云 MaaS） |
| `MAAS_MODEL` | `DeepSeek-V4.1-Flash-1017` | 运行时模型名（从 `.env` 读取，**禁止硬编码进代码**）；真实调用时若该值为空，`llm_client` 直接返回 `5001`「未配置 MAAS_MODEL，无法调用 LLM」，**不做静默占位模型兜底** |
| `MAAS_MOCK` | `0`（`.env.example` 中为 `1`） | `1` ⇒ 强制离线 mock，返回规则化示例结果 |
| `DATABASE_PATH` | `./campus.db` | SQLite 文件路径（相对 `backend/` 工作目录；支持绝对路径） |
| `RUN_SCHEDULER` | `1` | `0` ⇒ 不启动 APScheduler 催办调度器（自动化验收用） |
| `SSE_HEARTBEAT_SECONDS` | `15` | SSE 心跳间隔（秒），用于保活连接 |
| `REMINDER_INTERVAL_SECONDS` | `60` | 催办扫描间隔（秒） |
| `AI_DAILY_QUOTA` | `50` | 每人每日 AI 问答次数上限；`0` 表示当天不生成，任务、通知、审批与验收不受影响 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 允许跨域的前端来源，逗号分隔 |

> 取值说明：「默认值」列取自规划契约 `C-BOOT@1`（`MAAS_MODEL` 默认值经 Leader 终验后裁定为 `DeepSeek-V4.1-Flash-1017`，与 `backend/.env.example` 一致）；`backend/.env.example` 中是可直接复制的**占位值**（如 `MAAS_BASE_URL=https://your-maas-endpoint.example.com/v1`、`MAAS_API_KEY=your-maas-api-key`），`MAAS_MOCK` 在示例文件中预置为 `1` 以便离线演示。
>
> **mock 与真实调用的边界**：`MAAS_API_KEY` 为空 **或** `MAAS_MOCK=1` ⇒ `is_mock_mode()` 为真，Agent 接口返回确定性 mock 结果（`mock:true`），不发起任何外网请求，也不会因缺少模型名报错。只有「已配置 `MAAS_API_KEY` 且未开启 mock」才会构造真实客户端；此时若 `MAAS_MODEL` 为空，接口明确返回 `5001`「未配置 MAAS_MODEL，无法调用 LLM」。`llm_client._build_client()` 同时保留防御性校验：非 mock 分支一旦发现缺少 `MAAS_API_KEY` 或 `MAAS_MODEL`，即抛 `LLMError(5001)`，**绝不用占位模型静默兜底**。
>
> **安全红线**：真实 Key 只能放在后端 `backend/.env`；前端 `frontend/src` 中不得出现任何 `MAAS_API_KEY` 或任何真实凭证。仓库内的示例值一律为占位值。

---

## 7. 离线 mock 模式

满足任一条件即进入 mock 模式（`GET /api/health` 返回 `"mock": true`）：

1. `MAAS_MOCK=1`；
2. `MAAS_API_KEY` 为空。

mock 模式的行为：

- 提炼助手 / 审核助手不发起任何外部 HTTP 请求，按固定规则返回结构化草稿与歧义提问；
- 语音流式切片、颜色联动、草稿本地持久化等前端交互**完全可用**，可完整演示；
- 反复演示同一句话时结果稳定，便于录屏与答辩。

因此**不配置 Key 也能跑通全流程**，适合评委在干净环境复现。

切换到真实模型：在 `backend/.env` 填写 `MAAS_API_KEY`、`MAAS_BASE_URL`、`MAAS_MODEL=DeepSeek-V4.1-Flash-1017`，并设置 `MAAS_MOCK=0`。

---

## 8. 语音输入说明

- 语音发布使用浏览器原生 Web Speech API（`webkitSpeechRecognition`），**仅在 `localhost` 或 `https` 安全上下文下可用**；
- 请使用 **Chrome / Edge**；其他浏览器下语音按钮会被禁用并提示「仅支持 Chrome / Edge」；
- 端口不影响可用性：`http://localhost:5173` 属于安全上下文，可正常录音；
- 若以局域网 IP（如 `http://192.168.x.x:5173`）访问，语音不可用，但不影响**手动发布**与**文字 AI 解析**（保底路径）。
- **语音实时可视化（本轮迭代）**：任一标点即切（阈值 1）、无标点满 **12 字**强制切、连续 **800ms** 无新结果即切；interim 结果以 `live` 块逐字显示（刷新 ≤200ms）；连续说话时 Edge 静默触发 `onend` 会自动续接识别，不会"说到一半没反应"；**停止录音改由 `onend` 收尾**——`stop()` 只进入收尾窗口不再清缓冲，窗口内最后一帧照常入缓冲、但不零散发片，`onend` 后延迟一个 `FINAL_DELAY_MS` 把剩余文本整体发尾片（**末批必达、不重复**），尾片成功后**自动触发审核/润色建议**（不会自动发布，也不再有悬浮确认层）。
- **语音续接去重（第五轮）**：Edge 在停顿后静默触发 `onend` 会**自动续接**识别（`continuous` 并非真无限）——续接**不清**本地去重链（`dedupTail` 只在**新建会话**时清空），并对续接后浏览器重新吐出的重叠前缀做**重叠裁剪**（`trimRestartOverlap`），**同一句不会重复进入草稿**，第二遍也不会带出上一句的前导逗号。

---

## 9. 常见问题（FAQ）

**Q1：Python 3.14 下 `pip install -r requirements.txt` 失败**
A：典型报错为 `pydantic-core` / `sqlalchemy` 找不到匹配的预编译轮子（需要本地编译工具链）。处理方式：
1. 安装 Python 3.11 或 3.12；
2. 删除 `backend/.venv`；
3. 重新执行 `install.sh` / `install.bat`（脚本会优先选中 3.12 / 3.11）。

**Q2：Windows + git-bash 下 `.venv` 里没有 `Scripts/` 目录**
A：说明 `python` 命令解析到了 MSYS2 / mingw 的解释器，它会生成 POSIX 版 `bin/` 布局，导致 `.venv/Scripts/python.exe` 不存在。请用官方 CPython 显式创建：

```bash
"C:/Users/<你的用户名>/AppData/Local/Programs/Python/Python312/python.exe" -m venv backend/.venv
```

之后统一使用 `.venv/Scripts/python.exe`，不要混用系统 `python`。

**Q3：`npm install` 慢或失败**
A：可切换镜像后重试：`npm config set registry https://registry.npmmirror.com`。已存在 `node_modules` 时安装脚本会跳过，可手动执行 `npm install` 更新。

**Q4：端口被占用（8000 / 5173）**
A：同一时刻只允许一个进程占用。先关闭旧进程：
- Windows：`netstat -ano | findstr :8000` 找到 PID 后 `taskkill /PID <pid> /F`；
- macOS / Linux：`lsof -ti:8000 | xargs kill -9`。

**Q5：语音按钮点了没反应 / 提示不支持**
A：检查是否使用 Chrome / Edge、是否通过 `localhost` 或 `https` 访问（见第 8 节）。可直接改用文字 AI 解析或手动表单发布。

**Q6：想清空演示数据**
A：停止后端，删除 `backend/campus.db`，重启后端（`lifespan` 会自动 `init_db()` 重建表），或在 `backend/` 下执行 `.venv/Scripts/python.exe -c "from app.db import init_db; init_db()"`。

**Q7：前端页面空白 / 接口 404**
A：确认后端已在 **8000** 启动；前端必须用 `npm run dev`（不要直接双击 `index.html`），否则 Vite 代理不生效。

**Q8：多名学生报名了同一任务，为什么催办只发给一个人？**
A：本轮报名审批已支持**多名额多成员**（每名 `approved` 成员可各自推进进度、提交、签到，验收时每人各得积分）；但催办与逾期扣分仍由第一轮的 `reminder_scheduler` 按任务首位 `approved` 成员（`assignee_id`）执行——该模块本轮未修改（迭代计划 `2.3.2 D2` 已列为已知限制）。多成员催办属后续迭代项，不影响报名、审批、验收与积分闭环。

**Q9：手机浏览器上点录音没反应？**
A：这是**纯浏览器形态的 Web API 边界，不是本项目 bug**：iOS Safari 没有 `webkitSpeechRecognition`；安卓 Chrome 的识别依赖 Google 语音服务，国内网络大概率不可用。桌面 Chrome / Edge 正常。
若需要移动端语音，可按以下路径实现（提示，不含代码）：
- iOS：App 壳（`WKWebView`）+ JS Bridge（`WKScriptMessageHandler` / `evaluateJavaScript`）→ 原生 `SFSpeechRecognizer`（`zh-CN`，需 `NSMicrophoneUsageDescription` + `NSSpeechRecognitionUsageDescription`）；
- Android：`WebView` + `@JavascriptInterface` → `android.speech.SpeechRecognizer`；
- 跨平台：Capacitor 壳 + 语音插件；纯浏览器备选：`getUserMedia` 录音 → 后端云 ASR。
改造要点：把采集/识别抽象为 provider（`browser-speech` / `native-bridge` / `server-asr`），`detectVoiceSupport` 作为唯一判定入口；并延续「只把定稿文本写入缓冲」（interim 只显示、final 才落地）。
详细说明见 [`codearts_proof/handover.md`](../codearts_proof/handover.md) ⑥。手动发布与文字解析在手机浏览器仍可用。

---

## 10. 测试脚本入口

| 脚本 | 用途 | 用法 |
|---|---|---|
| `backend/scripts/smoke_core.sh` | 后端核心 REST 全流程回归（登录 → 发布 → 认领 → 进度 → 提交 → 验收 → 积分 → 签到 → 通知） | 先启动后端，再 `bash backend/scripts/smoke_core.sh`（默认 `BASE_URL=http://127.0.0.1:8002`，可用环境变量覆盖） |
| `backend/scripts/smoke_sse.sh` | SSE 连接注册表与分级催办调度自检 | `bash backend/scripts/smoke_sse.sh`（使用临时 `DATABASE_PATH`，结束自动清理） |
| `bash tests/frontend/run_all.sh` | 前端完整门禁：类型检查、生产构建、静态契约检查（25 项）与语音切片算法（21 断言），产出 `frontend/dist` | 项目根执行；本机 git-bash 若 `python3` 不可用，显式设置 `PYTHON_BIN=python` |
| `bash tests/security/test_security_redline.sh` | 公开源安全红线：凭证字面量、交付物与构建产物检查（A2b 要求 `frontend/dist` 存在） | 需先完成前端构建；CI 在同一前端作业构建后执行 |
| `frontend` 脚本 | 类型检查与构建 | `cd frontend && npm run typecheck && npm run build` |

前端与安全门禁也可一键执行：`bash tests/frontend/run_all.sh` 完成类型检查、生产构建、静态契约与语音切片算法检查并产出 `frontend/dist`；
随后执行 `bash tests/security/test_security_redline.sh`，产物安全扫描（A2b）因此能检查真实 dist。
CI 已把这两步放在同一个前端作业内按上述顺序执行，不再依赖单独的安全作业自行构建。

---

## 11. 目录结构

```
（工程根）/
├── backend/                 FastAPI 应用
│   ├── app/
│   │   ├── main.py          应用入口（lifespan / CORS / 路由挂载）
│   │   ├── db.py            引擎、会话、init_db()
│   │   ├── models.py        11 张表的 SQLAlchemy 模型
│   │   ├── schemas.py       Pydantic 模型
│   │   ├── deps.py          get_current_user 鉴权依赖
│   │   ├── errors.py        ApiError 与统一响应 ok()
│   │   ├── routers/         auth / tasks / checkin / credits / notifications / kb / agent
│   │   ├── agents/          提炼助手、审核助手、LLM 客户端、mock 数据
│   │   ├── services/        SSE hub、通知、催办调度、积分、知识库
│   │   └── utils/           JSON 读写工具
│   ├── scripts/             冒烟脚本（smoke_core.sh / smoke_sse.sh）
│   ├── requirements.txt     后端依赖
│   └── .env.example         环境变量占位值
├── frontend/                Vue 3 + Vite 5 SPA（端口 5173）
│   ├── src/
│   │   ├── api/             接口封装（统一 fetch）
│   │   ├── stores/          Pinia（user / draft / notifications）
│   │   ├── views/           登录 / 发布 / 大厅 / 详情 / 个人中心 / 后台
│   │   ├── components/      VoiceComposer 语音块化组件 + common/ThemeToggle.vue
│   │   ├── composables/     useVoiceComposer / useSSE / useTheme
│   │   ├── router/          路由表
│   │   ├── styles/          color-pool.css 字段颜色池 + theme.css 双主题令牌
│   │   └── utils/colorPool.ts
│   ├── vite.config.ts       端口 5173 + /api 代理到 8000
│   └── package.json
├── readme/                  本目录：安装脚本与交付文档
├── codearts_proof/          码道使用留痕（三层结构）
└── README.md                工程总览（与本文件启动命令一致）
```

---

## 12. 留痕说明（`codearts_proof/`）

按官方硬性核查项，开发过程留痕采用**三层结构**：

| 层级 | 目录 | 内容 |
|---|---|---|
| 第一层 · 原始对话整理 | `codearts_proof/ai_dialogue/` | 每个阶段一份 md，含「阶段 / 使用的 Agent / 输入 Prompt / 产出 / 问题」 |
| 第二层 · Prompt 资产 | `codearts_proof/prompts/` | Agent Team 启动指令、业务 Agent Prompt 版本演进、`prompt迭代记录.md` |
| 第三层 · 排错记录 | `codearts_proof/debug/` | `template.md` 与按模板补齐的实例（现象 / 原因 / 让码道怎么修 / 结果） |
| 汇总日志 | `codearts_proof/LOG.md` | 日期 / 阶段 / Agent / Prompt 要点 / 产出 / 问题 |
| 图片与视频 | `codearts_proof/screenshots/`、`video/` | 截图与录屏（大文件不入库，仅保留 `.gitkeep` 与索引说明） |

> 说明：留痕目录中的**模板文件**（阶段 md、debug 记录、prompt 迭代记录）为结构占位，需由各阶段负责人补入**真实**对话与截图；**不得编造**未发生的对话内容，未发生的阶段一律保留占位说明。