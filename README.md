# 校园任务协同 AI Agent（CampusTaskAgent）

> 面向学生组织 / 社团 / 班级的**自然语言任务协同 AI Agent**。
> 一句话概括：**你负责说，AI 负责拆，系统负责盯，积分负责激励。**
>
> 详细部署文档见 [`readme/README.md`](readme/README.md)；本文的启动命令与之保持一致。

---

## 一、简介

学生组织日常协作的四个痛点：任务靠群里口头布置容易漏、推进没有反馈只能挨个催、新同学不知道从哪下手、排练开会容易忘。

本项目把这四件事收进一个系统：发布者用**打字或说话**的方式描述任务，系统自动结构化为任务草稿、指出歧义、拆解子任务、到点分级催办、验收后结算积分；执行者在大厅认领、照 SOP 执行、现场签到、拿积分。

开发全程在**华为云码道（CodeArts）**内完成，深度使用其 **Agent Team 多智能体协作**（领航员 / 构造师 / 画师 / 哨兵），使用痕迹归档于 [`codearts_proof/`](codearts_proof/)。

## 二、核心功能

| 功能 | 说明 |
|---|---|
| **默认 AI 智能模式** | 进入发布页**默认打开 AI 智能模式**（打字或说话即可解析）；手动表单保留为**兜底**，AI 不可用或用户主动切换时仍可发布 |
| **双 Agent 智能发布** | 提炼助手把自然语言解析成结构化任务（含动态 `extra_tags` 标签），并**剥离**「措辞严谨一点」这类风格要求；审核助手检查歧义并逐条提问，同时按风格要求润色 |
| **语音实时发布** | 浏览器原生语音识别 + **任一标点即切 / 无标点满 12 字强制切 / 连续 800ms 静默即切**的实时流式解析；interim 结果以 `live` 块逐字显示（刷新 ≤200ms），Edge 静默触发 `onend` 时自动续接；已解析片段按字段染色，文字块与数据面板**同字段同色**；说到「哎不对，是教四」会识别为更正并打红问号；**语音停止改由 `onend` 收尾**——末批必达、不重复（`stopping` 守卫拦住收尾窗口内的零散发片，缓冲只在尾片成功后才清空），停止后**仍自动进入审核/润色**并回到编辑态（原悬浮确认层已彻底删除，不会出现「取消即清空」）；**Edge 静默续接后同一句不会重复进入草稿**——续接时保留本地去重链（`dedupTail` 只在新建会话时清空）并对重新吐出的重叠前缀做重叠裁剪（`trimRestartOverlap`） |
| **草稿自动保存** | 草稿自动**本地持久化**：文字块、字段值、风格要求随输入写入本地存储，页面刷新或从后台切回后自动恢复（刷新不丢），清空草稿时同步清除快照 |
| **报名审批** | 学生报名是「申请」：`pending → approved / rejected / cancelled`；发布者（老师）**通过后才生效**，拒绝须填原因，审批前学生可**撤回**；名额是人数上限（`quota`，`null` 不限），已通过人数未满时其他人仍可报名；验收通过后**每名 approved 成员各得积分**（幂等） |
| **开始/截止时间分离** | 任务「开始时间」与「提交截止时间」是两个独立字段：AI 草稿、手动表单、草稿恢复、发布请求与任务详情分别保存，互不复制；只给开始时间不会编造截止时间，只给截止时间也不会写成开始时间；缺少合法截止时间时不触发基于截止时间的催办与逾期扣分 |
| **逐人执行与验收** | 每名 approved 成员有独立的 `not_started / in_progress / submitted / rejected / verified` 执行状态、提交与验收时间；A 提交/通过不会把 B、C 视为完成；发布者可针对单个成员验收通过或退回，退回只影响该成员；任务整体状态由成员状态聚合，全部成员验收通过才整体完成；积分按成员结算并保证同一任务同一成员不重复获得 |
| **逐人催办与逾期恢复** | 催办与逾期扣分按每名 approved 成员的实际状态计算：已提交待验收/已通过者不催办不扣分，退回者按当前状态与截止时间处理；逾期不是终态，未完成成员可继续补交，发布者可修改截止时间或取消；同一成员同一任务逾期扣分只发生一次，改期后提醒按新截止时间计算，历史流水不自动退还 |
| **增量解析** | AI 解析后左侧输入区**仍可用**；追加「人数修改为 6 人」再点「AI 增量解析」，只把本次文本 + 当前草稿发给模型，返回合并后的完整草稿与字段级 `changes`；追加原文以 `user_note` 块保留，**不写入数据字段** |
| **追溯块** | 左侧 5 类块：`raw`（解析数据，按字段色）、`ai_applied`（**仅在用户显式采纳** AI 建议 / 问号建议 / 润色时生成，紫 `#8B5CF6`）、`user_edit`（`用户：将…改为…`，青 `#0891B2`）、`user_note`（用户追加原文，灰 `#6B7280`）、`live`（语音临时块，蓝 `#3B82F6` 虚线）；**解析不再自动生成「AI建议：」追溯块**，紫块只在真采纳时出现；**建议语句只展示、不落字段**；**左侧文字块点击编辑入口已移除**，改字走右侧字段面板 + 增量解析 |
| **智能任务拆解** | 大任务拆成子任务并附 SOP 指导，支持 `depends_on` 依赖（前序未完成不可认领）；拆解已收紧——小任务不拆，**≥2 条子任务才渲染**子任务区，**发布时子任务默认不勾选**，需显式勾选才随主任务一并发布 |
| **任务流转** | 发布者直接指派 或 大厅开放认领 → 进度更新 → 提交 → 发布者验收 |
| **签到打卡** | 每任务每人一次，签到成功后通知发布者，作为积分与评优依据 |
| **分级智能催办 + SSE 实时通知** | APScheduler 三级提醒（截止前 / 当天 / 逾期），同任务同等级去重；通知经 SSE 即时到达（顶部红点 + 通知中心），不做邮件短信 |
| **旧提醒失效与变更影响** | 改期或取消后，同一任务旧截止时间版本的催办通知标记为「已失效」，保留历史但不计未读；发布者与当前成员会收到含旧值→新值、提醒重算与后续任务数的变更通知；后台改期前展示只读影响预览，确认后才执行既有 PATCH |
| **AI 用量账本与额度** | 每次成功的 AI 问答写用量账本，按 `request_id` 幂等，重试不重复计费；每日问答次数上限由 `AI_DAILY_QUOTA` 控制（默认 50），个人中心展示今日用量。额度用完只停 AI 问答，任务、通知、报名、审批与验收照常可用 |
| **积分体系** | 验收通过加分、逾期扣分，写 `credit_logs` 流水，形成正向激励闭环 |
| **任务知识库** | 发布成功后增量入库；下次发布时用 jieba 分词 + 标签重叠打分做相似检测，提示「与 XX 相似，可改时间快速发布」 |
| **Light / Dark 双主题** | 全站统一设计令牌：无手动选择时跟随系统，手动切换后记住偏好（`localStorage['cta_theme']`），首屏内联脚本避免闪白；导航、卡片、表格、表单、按钮与弹窗/日期/下拉/tooltip/popover 等浮层完整覆盖；字段与追溯色由颜色池输出 CSS 变量，同一字段两主题同色相、深色提亮 |
| **全站移动端适配** | ≤768px 切换为顶部紧凑栏 + 底部 4 项导航（后台仅发布者可见）；任务网格 320px 无横向溢出；个人中心、详情成员状态、发布者后台的宽表转为移动卡片并保留全部操作；主要触控目标 44×44；输入 16px；底部导航与弹窗计入安全区且内容可滚动；不依赖 hover/title，不使用全局 `overflow-x: hidden` |
| **离线 mock 模式** | 不配置 Key 也能完整演示：AI 返回规则化结果，不发任何外部请求 |

## 三、技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3.5 + Vite 5.4 + TypeScript 5.9 + Element Plus 2.14 + Pinia 2.3 + vue-router 4.6 |
| 后端 | FastAPI 0.162 + Uvicorn 0.54 + SQLAlchemy 2.1 + Pydantic 2.14 + SQLite |
| AI | 华为云 MaaS（OpenAI 兼容协议，`openai` SDK 3.49），运行时模型 `DeepSeek-V4.1-Flash-1017`；**已关闭 DeepSeek 思考模式以降低延迟** |
| 调度与检索 | APScheduler 3.11（催办）+ jieba 0.42（分词相似度，无外部向量库） |
| 实时推送 | 原生 SSE（`text/event-stream`），无 WebSocket 依赖 |

完整清单（含 License 与实测版本）见 [`readme/开源组件说明.md`](readme/开源组件说明.md)。

## 四、目录结构

```
（工程根）/
├── backend/                  FastAPI 应用（端口 8000）
│   ├── app/
│   │   ├── main.py           入口：lifespan / CORS / 路由挂载 / /api/health
│   │   ├── db.py  models.py  schemas.py  deps.py  errors.py
│   │   ├── routers/          auth / tasks / checkin / credits / notifications / kb / agent
│   │   ├── agents/           提炼助手、审核助手、LLM 客户端、mock 数据
│   │   ├── services/         SSE hub、通知、催办调度、积分、知识库
│   │   └── utils/            JSON 读写工具
│   ├── scripts/              冒烟脚本 smoke_core.sh、smoke_sse.sh
│   ├── requirements.txt      后端依赖
│   └── .env.example          环境变量占位值（不含真实 Key）
├── frontend/                 Vue 3 SPA（端口 5173）
│   ├── src/
│   │   ├── api/              接口封装（统一 fetch）
│   │   ├── stores/           Pinia：user / draft / notifications
│   │   ├── views/            登录 / 发布 / 大厅 / 详情 / 个人中心 / 发布者后台
│   │   ├── components/       VoiceComposer + common/ThemeToggle.vue
│   │   ├── composables/      useVoiceComposer / useSSE / useTheme
│   │   ├── router/ styles/ utils/（styles 含 color-pool.css 与 theme.css）
│   │   └── layouts/AppLayout.vue（桌面导航 + 手机底部导航）
│   ├── vite.config.ts        端口 5173 + /api 代理到 8000
│   └── package.json
├── readme/                   一键安装脚本与交付文档
└── codearts_proof/           码道使用留痕（ai_dialogue / prompts / debug / screenshots / video）
```

## 五、快速开始

### 5.1 一键安装（推荐）

```bash
# 在工程根目录执行
# Linux / macOS / Windows git-bash
bash readme/install.sh

# Windows cmd（不使用 WSL）
readme\install.bat
```

脚本会自动：选择 Python（优先 3.12 / 3.11）→ 创建 `backend/.venv`（已存在则保留）→ 装后端依赖 → `npm install` → 初始化 SQLite → 打印启动命令。
**脚本不会自动创建 `backend/.env`**，请按 5.3 手动配置，或直接以 mock 模式运行。

### 5.2 启动

以下命令在**工程根目录**执行：

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

打开 `http://localhost:5173`，用演示账号登录即可。

健康检查（无需登录）：

```bash
curl -s http://127.0.0.1:8000/api/health
# {"code":0,"msg":"ok","data":{"status":"ok","tables":[...11 张表...],"mock":true}}
```

### 5.3 环境变量（`backend/.env`）

```bash
cd backend
cp .env.example .env      # Windows cmd: copy .env.example .env
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MAAS_API_KEY` | 空 | 真实 Key；为空 ⇒ 自动进入 mock 模式 |
| `MAAS_BASE_URL` | `https://example.invalid/v1` | OpenAI 兼容端点 |
| `MAAS_MODEL` | `DeepSeek-V4.1-Flash-1017` | 运行时模型名（从 `.env` 读取，禁止硬编码）；真实调用时若为空直接返回 `5001`，**不做占位模型兜底** |
| `MAAS_MOCK` | `0`（`.env.example` 为 `1`） | `1` ⇒ 强制离线 mock |
| `DATABASE_PATH` | `./campus.db` | SQLite 路径（相对 `backend/`） |
| `RUN_SCHEDULER` | `1` | `0` ⇒ 不启动催办调度器（自动化验收用） |
| `SSE_HEARTBEAT_SECONDS` | `15` | SSE 心跳间隔 |
| `REMINDER_INTERVAL_SECONDS` | `60` | 催办扫描间隔 |
| `AI_DAILY_QUOTA` | `50` | 每人每日 AI 问答次数上限；`0` 表示当天不生成，其他协作功能不受影响 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 允许跨域的前端来源，逗号分隔 |

> 取值说明：「默认值」列取自规划契约 `C-BOOT@1`（`MAAS_MODEL` 默认值经 Leader 终验后裁定为 `DeepSeek-V4.1-Flash-1017`）；`backend/.env.example` 中为**占位值**，`MAAS_MOCK` 预置为 `1` 以便离线演示。
>
> **mock 与真实调用的边界**：`MAAS_API_KEY` 为空或 `MAAS_MOCK=1` ⇒ 走确定性 mock（`mock:true`，无外网请求，也不会因缺少模型名报错）。只有已配置 Key 且非 mock 时才构造真实客户端；此时 `MAAS_MODEL` 为空会明确返回 `5001`。`llm_client` 在非 mock 分支对缺失 `MAAS_API_KEY` / `MAAS_MODEL` 一律抛 `LLMError(5001)`，**绝不用占位模型兜底**。
>
> 安全红线：真实 Key 只放在 `backend/.env`（已被 `.gitignore` 排除）；前端 `src/` 中不得出现 `MAAS_API_KEY` 或任何真实凭证；仓库内示例值一律为占位值。

### 5.4 Mock 模式

`MAAS_MOCK=1` **或** `MAAS_API_KEY` 为空即进入离线 mock（`/api/health` 的 `mock` 字段为 `true`）：不发起外部请求，返回规则化示例结果；语音切片、颜色联动、草稿本地持久化等交互完全可用。

### 5.5 主题与手机端使用说明

- **主题切换入口**：登录后的顶部栏（手机在顶部紧凑栏）与登录页右上角均有主题按钮；点击即在 Light / Dark 间切换。
- **初始与记忆**：从未手动选择时跟随系统 `prefers-color-scheme`；手动选择后写入 `localStorage['cta_theme']`，刷新与重新进入保持。首屏由 `index.html` 内联脚本在样式加载前应用，避免明显闪白；切换只改 `html.dark` / `data-theme`，不重挂路由，草稿与输入不丢。
- **手机布局**：≤768px 使用顶部紧凑栏 + 底部 4 项导航（发布者后台仅 `publisher` 可见）；任务大厅、发布页、详情、个人中心与后台按单列/卡片重排，宽表在手机上显示为 `.app-mobile-list` 卡片并保留全部操作。
- **触控与键盘**：主要按钮与图标热区 44×44；输入与文本域 16px；底部导航与页面留白计入 `env(safe-area-inset-bottom)`；弹窗宽 `calc(100vw - 24px)`、最大高 `90dvh`、底部操作常显。
- **配置**：本轮不新增环境变量或业务开关；主题偏好仅存浏览器本地。验收尺寸为 320/375/390/430 与 768/1024/1440，详细说明见 [`readme/README.md`](readme/README.md) 第 5.5 节。

## 六、演示账号

**首次登录自动建号，无需密码，输入用户名即可登录。**

| 用户名 | 角色 | 展示名 | 可做什么 |
|---|---|---|---|
| `teacher01` | `publisher` | 王老师 | 发布 / 拆解 / 指派 / 催办设置 / 验收，进入发布者后台 |
| `student01` | `student` | 李同学 | 认领 / 进度 / 提交 / 签到 / 查看积分 |
| `student02` | `student` | 张同学 | 同上 |
| `student03` | `student` | 陈同学 | 同上 |

角色规则：`teacher*` → `publisher`、`admin*` → `admin`、其余 → `student`。

## 七、页面入口

| 路由 | 页面 |
|---|---|
| `/login` | 登录页（唯一公开页） |
| `/publish` | 统一发布页（**默认 AI 智能模式**，手动表单为兜底；文字 AI + 语音流式） |
| `/tasks` | 任务大厅 |
| `/my-tasks` | 我的任务（范围锁定本人参与/管理，不含全量） |
| `/published-activities` | 我发布的活动（管理者；发布活动入口） |
| `/activities/new` | 发布活动（管理者；预览与详情共用字段区块） |
| `/tasks/:id` | 任务详情（子任务 / SOP / 进度 / 签到） |
| `/profile` | 个人中心（我的任务 / 积分流水 / 签到 / 通知中心） |
| `/admin` | 发布者后台（拆解确认 / 指派 / 催办 / 验收） |

## 八、测试脚本入口

| 脚本 | 用途 |
|---|---|
| `bash backend/scripts/smoke_core.sh` | 后端核心 REST 全流程回归（登录 → 发布 → 认领 → 进度 → 提交 → 验收 → 积分 → 签到 → 通知），含错误码用例 |
| `bash backend/scripts/smoke_sse.sh` | SSE 与催办自检（三级扫描、去重、逾期扣分仅 1 行、调度器幂等） |
| `PYTHONPATH=backend python -m pytest tests/backend/test_reliability.py -q` | 第一阶段可靠性回归（起止时间分离、三成员 A/B/C、重复提交/验收/调度/重启、逾期补交、迁移、越权） |
| `bash tests/frontend/run_all.sh` | 前端完整门禁：类型检查、生产构建、静态契约检查（25 项）与语音切片算法（21 断言），产出 `frontend/dist` |
| `bash tests/security/test_security_redline.sh` | 公开源安全红线：凭证字面量、交付物与构建产物检查（A2b 要求 `frontend/dist` 存在）；CI 在同一前端作业构建后执行 |
| `cd frontend && npm run typecheck` | `vue-tsc --noEmit` 类型检查（要求零 `any`） |
| `cd frontend && npm run build` | 生产构建（产物 `dist/`） |

## 九、已知限制与常见问题

- **语音输入**：依赖浏览器原生 Web Speech API，仅 **Chrome / Edge** 且需在 `localhost` 或 `https` 下可用；手动发布与文字解析不受影响。
- **Python 3.14**：部分依赖可能缺少预编译轮子，安装失败请改用 Python 3.11 / 3.12 重建 `backend/.venv`。
- **Windows + git-bash**：若 `python` 指向 MSYS2 解释器，`.venv` 会生成 `bin/` 而非 `Scripts/`，请用官方 CPython 显式创建虚拟环境。
- **公网穿透访问**：开发服务器（`npm run dev`）已在 `frontend/vite.config.ts` 放行 `*.takin.cc`（`server.allowedHosts`），穿透域名访问前端不再返回 403；该白名单**只在开发服务器生效**，生产静态产物由反向代理托管，Host 校验由反代负责。
- **多成员催办**：第一阶段可靠性改进后，催办与逾期扣分已按每名 approved 成员逐人计算，不再只针对首位 `assignee_id`；已提交待验收/已通过的成员不催办、不扣分，逾期扣分按 `(task_id, user_id)` 只发生一次。历史逾期扣分在改期后不自动退还。
- **移动端语音**：纯浏览器形态下，iOS Safari **无** `webkitSpeechRecognition`、安卓 Chrome 的识别依赖 Google 语音服务（国内网络常不可用）——属 Web API 边界而非本项目故障；桌面 Chrome/Edge 正常。若需移动端语音，可走 App 壳（WKWebView + JS Bridge → `SFSpeechRecognizer` / Android `SpeechRecognizer`）或 Capacitor + 语音插件，方案与改造点见 [`codearts_proof/handover.md`](codearts_proof/handover.md) ⑥。手动发布与文字解析在手机浏览器仍可用。
- **移动端视觉验收边界**：本轮四组截图与走查均为浏览器模拟（桌面 1440×900、手机 390×844）；实测 `/tasks` 320=305/320、390=375/390、1440=1425/1440，390 `/admin` 桌面表隐藏、移动卡片显示。真机软键盘、地址栏伸缩、横竖屏与安全区、真实麦克风权限未在真机验证；768/1024 与 `/publish`、`/profile` 的 320/375 未逐页量测。截图保存在本地忽略目录 `outputs/ui-redesign/`，详细数字见 `codearts_proof/ai_dialogue/stage14_全站UI与移动端改造.md`。

完整 FAQ 见 [`readme/README.md`](readme/README.md) 第 9 节。

## 十、留痕说明（`codearts_proof/`）

按官方硬性核查项，开发留痕采用**三层结构**：

| 层级 | 目录 | 内容 |
|---|---|---|
| 第一层 · AI 交互对话 | `codearts_proof/ai_dialogue/` | 14 个阶段 md，每份含「用户反馈 / Leader 决策与根因 / 派工与契约 / 产出 / 真实问题与修复」 |
| 第二层 · Prompt 资产 | `codearts_proof/prompts/` | Agent Team 启动指令、业务 Agent Prompt 演进、`prompt迭代记录.md` |
| 第三层 · 排错记录 | `codearts_proof/debug/` | `template.md`（现象 / 原因 / 让码道怎么修 / 结果）与实例 |
| 汇总与素材 | `codearts_proof/LOG.md`、`screenshots/`、`video/` | 开发日志、截图合集、演示录屏（大文件不入库） |

> **真实性声明**：留痕材料以「宁可留空，不可编造」为原则。未发生的阶段与对话一律保留「（待该阶段收尾由哨兵整理）」占位，不填入虚构内容；官方明确将伪造留痕视为违规。
> 文档中的 `DeepSeek-V4.1-Flash` 一律指 **`DeepSeek-V4.1-Flash-1017`**。

## 十一、交付物索引

| 交付物 | 位置 |
|---|---|
| 一键安装脚本 | `readme/install.sh`、`readme/install.bat` |
| 部署运行文档 | `readme/README.md` |
| 开源组件说明 | `readme/开源组件说明.md` |
| 码道应用总结 | `readme/码道应用总结.md` |
| 开发日志 | `codearts_proof/LOG.md` |
| 团队分工 | 朱思豪（技术负责人）、周一一（Agent 工作流与集成）、夏一一（产品负责人） |