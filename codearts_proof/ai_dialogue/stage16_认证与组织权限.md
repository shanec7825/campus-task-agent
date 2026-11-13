# 阶段 16 · 认证与组织权限

> 日期：2026-11-13 ｜ 分支：`main` ｜ 提交：**无（工作区未提交）** ｜ 远程：未推送
> 计划：`.codeartsdoer/plans/phase2-auth-org/design.md`、`task.md`（按 `.gitignore` 本地忽略）
> 范围：用户需求的**阶段 2**——正式注册登录、邀请、精简组织权限、副本迁移验证。阶段 3/4/5 不在本轮。
> 编号说明：`LOG.md` 已使用到阶段 15，本轮沿用下一顺位「阶段 16」；历史行未做任何修改。

---

## 1 目标与需求来源

### 1.1 用户需求来源

用户要求把演示阶段的进程内 token 认证替换为可交付的正式认证与组织权限体系，并要求在数据库副本上完成结构升级验证。需求收敛为 R1~R9（`design.md §1.1`）：

| 编号 | 需求 | 关键约束 |
|---|---|---|
| R1 | 邀请注册与账号密码登录 | 必须有有效组织邀请才能建号，无公开自助注册；建号、写入成员关系、建立会话在同一事务完成；邀请过期 / 撤销 / 用尽 / 跨组织一律 **4001** 且不落库；管理员权不得由用户名前缀、客户端 `role` 字段或注册请求授予；与 legacy 演示账号同名时拒绝且不继承其数据、积分与组织关系；未知用户与错误密码返回同一文案 |
| R2 | 持久化会话、CSRF 与登录防护 | 会话来自 HttpOnly same-site Cookie，不把 `localStorage` bearer 当生产身份；会话持久化、带过期、退出即撤销，密码重置后撤销该用户全部会话；状态变更请求缺失 CSRF → **4030** 且不改数据；按 IP + 用户名限制连续失败登录；跨域与登录后跳转走白名单；部署声明 HTTPS 时才加 `Secure` |
| R3 | 组织、角色与职务 | 一个账号可加入多个组织且角色不同；组织角色固定 `admin` / `collaborator` / `member`；职务（班长、团支书等）只作成员元数据，不派生权限；平台管理员只经受控一次性命令授予；平台管理员不自动获得组织业务内容读取权；组织层级不继承管理权 |
| R4 | 统一资源授权 | 服务端统一评估列表、详情、搜索、直接 id、活动树、子任务、审批、签到、进度、验收、积分、通知、SSE、知识库；不可见资源统一 **4040**，不泄露存在性；活动与任务以 `org_id` 归属组织，子任务继承父任务；跨组织创建或挂接 **4001**；组织管理员管本组织、协作员管自建或被指派、成员读公开内容并报名与处理自身执行项；无组织 legacy 数据仅发布者 / 负责人 / 参与者可读 |
| R5 | 邀请生命周期 | 库中只存 token 摘要，明文只在创建响应出现一次；强制过期、最大次数与撤销，注册与 `used_count` 原子递增；并发注册不超最大次数；明文邀请 token 不写日志 |
| R6 | 受控密码重置 | 组织管理员或平台管理员发放一次性限时 token，不伪造「已发送」；消费后改密、标记已用并撤销全部会话；管理员不能读取既有密码 |
| R7 | 数据迁移与兼容 | 保留既有用户、活动 / 任务、报名、成员与积分记录 id；无密码旧账号标记 legacy 且不能登录，需受控重置；幂等加表 / 列 / 索引并产出迁移报告；先在副本执行，未经授权不迁移真实库 |
| R8 | 前端认证接入 | 请求带同源凭据与 CSRF 头，不在 `localStorage` 存可复用凭据；会话失效清空客户端状态并只跳转登录一次，保留内部返回路径；SSE 不把凭据放进 URL；退出先调服务端再清状态 |
| R9 | 覆盖与可验证性 | 行为测试覆盖：用户名不赋权、密码哈希、邀请过期与并发、会话退出 / 到期 / 重启、CSRF 拒绝、跨组织拒绝、ID 枚举、legacy 账号隔离、密码重置撤销；不以字符串检查作为授权行为的唯一证明 |

### 1.2 本轮明确不含

阶段 3（完整三层状态机与验收规则）、阶段 4（其余响应式、语音与原生）、阶段 5（完整回归与比赛材料）不在本轮。原生容器认证（Capacitor / Android / iOS）本轮无容器，明确**未做**；邮件 / 短信通道未接入；不做组织树继承。

---

## 2 决策与边界（Open decisions 已裁定）

| 编号 | 决策 | 影响 |
|---|---|---|
| D1 | **哈希算法降级为 scrypt**：环境无法安装 `argon2-cffi`（PyPI 不可达），改用标准库 `hashlib.scrypt`（n=16384, r=8, p=1，16 字节 salt），格式 `scrypt$16384$8$1$<salt_b64>$<hash_b64>`，校验用 `hmac.compare_digest` | 这是对「优先 Argon2id」的**显式替代偏差**，本文件与 `design.md` 开放决策 1 均已标注；不得声称已使用 Argon2id |
| D2 | **旧账号隔离**：`password_hash IS NULL` 的历史用户标记 `status='legacy_unclaimed'` | 该状态不可登录、不可被同名注册继承数据 / 积分 / 组织关系；需管理员发放一次性重置后才可用 |
| D3 | **组织归属不自动推断**：历史活动 / 任务 `org_id` 保持 `NULL` | 迁移报告只统计不猜测；legacy 数据仅按发布者 / 负责人 / 参与关系可见 |
| D4 | **平台管理员不自动读组织内容**：`platform_admin` 只加持 `POST /api/orgs` 与 `/api/admin/*` | 避免「平台管理员」成为跨组织内容后门 |
| D5 | **SSE 仅 Cookie 鉴权**：`GET /api/notifications/stream` 忽略 `?token=` | 不保留可重用凭据进 URL / 日志的兼容路径 |
| D6 | **`Secure` 由部署声明**：仅 `COOKIE_SECURE=1` 时给会话 Cookie 加 `Secure` | 本地 HTTP 验证默认关闭；生产 HTTPS 由部署显式开启 |
| D7 | **不新增运行时依赖**：不引入 passlib / pyjwt / itsdangerous，不做邮件 / 短信、组织树继承、原生容器认证 | 认证与权限全部用标准库 + 现有 FastAPI / SQLAlchemy 栈实现 |
| D8 | **迁移只动副本**：`scripts/migrate_phase2.py` 的 `--db` 必填，拒绝 `backend/campus.db`（除非 `--allow-real` + 终端确认），先带时间戳备份再 `init_db()` | 本轮真实库未被迁移；副本 `outputs/phase2/copy.db` 与报告为本地验证产物 |

边界：组织与工作层级是两套关系——`org_id` 只表达归属，`parent_id` / `activity_id` 只表达工作拆分；权限规则集中在 `app/services/authz.py`，路由不得重复实现角色判断。

---

## 3 工具、角色与派工

### 3.1 工具与模型

| 项 | 实际值 |
|---|---|
| 平台 | 华为云 CodeArts 代码智能体 |
| 实际编排 | team-leader |
| 执行 Agent | coding-engineer（T1~T9 共 9 路并行实现）、developer-test-generator（T10 行为测试）、team-code-reviewer（3 轮独立只读审查）、记录 Agent（T11 留痕） |
| 底层模型标识 | 平台显示 `deepseek-v4.1-flash-1017`，**未独立核验** |
| 运行环境 | Windows 11 + git-bash；Node 25.2.1 / npm 11.6.2；Python 3.12.10 |
| 数据 | 隔离演示库 `outputs/phase2/demo.db`；迁移副本 `outputs/phase2/copy.db`；未触碰真实业务数据 |

### 3.2 派工要点（按 `task.md` T1~T11）

| 任务 | 执行 | 核心要求 | 契约 |
|---|---|---|---|
| T1 | coding-engineer | 5 张新表 + `users` / `activities` / `tasks` 新列；幂等迁移与 `legacy_unclaimed` 标记；预挂载 `routers.orgs`、`routers.registration`；`verify_tables` 期望 16 张表 | `C-DATA-AUTH@1`、`C-MIGRATION-3@1` |
| T2 | coding-engineer | scrypt 哈希、持久化会话、Cookie 下发、CSRF 依赖、login / logout / me、登录限流、`create-platform-admin` CLI | `C-HASH@1`、`C-SESSION@1`、`C-AUTH-API@1` |
| T3 | coding-engineer | 组织 / 成员 / 邀请服务与路由；邀请原子消费注册；一次性重置并撤销全部会话 | `C-ORG@1` |
| T4 | coding-engineer | 唯一授权实现：角色、可见 / 可管理、SQL 可见性过滤、`resolve_task_org` | `C-AUTHZ@1` |
| T5 | coding-engineer | 任务、活动、报名接口接入可见性预过滤与组织归属校验 | `C-TASK-ORG@1` |
| T6 | coding-engineer | 签到 / 积分 / 通知 / SSE / 知识库 / 解析端点统一授权；SSE 改 Cookie | `C-OTHER-AUTH@1`、`C-SSE-AUTH@1` |
| T7 | coding-engineer | 前端同源 Cookie + CSRF，登录 / 注册 / 重置页与路由守卫 | `C-FE-AUTH@1` |
| T8 | coding-engineer | 组织上下文与类型、`api/orgs.ts`、SSE 去 token 参数 | `C-SSE-AUTH@1`（前端侧） |
| T9 | coding-engineer | 副本迁移脚本：拒绝真实库、带时间戳备份、迁移报告 | `C-MIGRATION-3@1`（脚本侧） |
| T10 | developer-test-generator | 隔离库行为测试：不赋权、哈希、邀请并发、会话、CSRF、跨组织、ID 枚举、legacy 隔离、重置撤销 | 全部 |
| T11 | 记录 Agent | 六节阶段留痕、`LOG.md`、P-016、`walkthrough.md` | — |

派工约束：每个 coder 只读自己的 `task.md` 条目与对应契约 ID，写集合隔离，互不读取同伴实现；先冻结 11 份 §2.2 契约再并行开工；不运行构建 / 测试（由验证阶段执行）。

---

## 4 产出

### 4.1 修改 / 新增文件（`git status` 实测，工作区未提交）

> 工作区同时包含阶段 15 的未提交改动；下表只列阶段 2 相关文件。

**后端新增**

- `backend/app/security.py`、`backend/app/cli.py`
- `backend/app/services/{session_service,org_service,authz}.py`
- `backend/app/routers/{orgs,registration}.py`

**后端修改**

- `backend/app/{models,schemas,db,main,deps}.py`、`backend/requirements.txt`（记录哈希实现说明）
- `backend/app/routers/{auth,tasks,applications,activities,checkin,credits,notifications,kb,agent}.py`

**后端测试与脚本**

- 新增 `tests/backend/test_auth_org_permissions.py`、`tests/backend/verify_phase2_migration.sh`
- 修改 `tests/backend/verify_tables.py`（期望表清单 16 张）、`tests/backend/run_all.sh`、`tests/backend/{test_applications,test_api_e2e,test_agent_mock,test_agent_incremental,test_sse_and_reminder}.py`
- 新增 `scripts/migrate_phase2.py`、`scripts/seed_phase2_demo.py`、`scripts/run_phase2_demo.sh`

**前端**

- 新增 `frontend/src/api/orgs.ts`、`frontend/src/views/RegisterPage.vue`、`frontend/src/views/ResetPassword.vue`
- 修改 `frontend/src/api/{client,auth,notifications}.ts`、`frontend/src/stores/user.ts`、`frontend/src/router/index.ts`、`frontend/src/layouts/AppLayout.vue`、`frontend/src/composables/useSSE.ts`、`frontend/src/types/models.ts`、`frontend/src/App.vue`
- 修改 `frontend/src/views/{LoginPage,AdminConsole,TaskHall,TaskDetail}.vue`、`frontend/src/components/task/TaskCard.vue`、`frontend/src/styles/{theme,typography}.css`

**CI、文档与留痕**

- 修改 `.github/workflows/ci.yml`、`docs/CI.md`、`README.md`、`readme/README.md`
- 新增本文件；修改 `codearts_proof/LOG.md`、`codearts_proof/prompts/prompt迭代记录.md`（P-016）；新增 `outputs/phase2/walkthrough.md`
- 截图归档 `codearts_proof/screenshots/stage16/`（5 张）

### 4.2 契约与数据形态

- 冻结并实现的契约：`C-DATA-AUTH@1`、`C-HASH@1`、`C-SESSION@1`、`C-AUTH-API@1`、`C-ORG@1`、`C-AUTHZ@1`、`C-TASK-ORG@1`、`C-OTHER-AUTH@1`、`C-MIGRATION-3@1`、`C-FE-AUTH@1`、`C-SSE-AUTH@1`（11 份）。
- 数据库由 11 表扩为 **16 表**：新增 `organizations`、`org_members`、`invitations`、`user_sessions`、`password_resets`。
- `users` 新增 `password_hash`、`password_updated_at`、`status`、`platform_admin`；`activities` / `tasks` 新增 `org_id`；索引幂等创建。

---

## 5 真实问题与修复

| 编号 | 现象 | 原因 | 解决 | 证据 |
|---|---|---|---|---|
| Q1 | `argon2-cffi` 无法安装，哈希实现被阻塞 | 环境访问 PyPI 不可达，不能按「优先 Argon2id」落地 | 改用标准库 `hashlib.scrypt`（n=16384, r=8, p=1），并在 `design.md` 开放决策与本文件标注偏差 | `backend/app/security.py`；本文件 D1 |
| Q2 | 早期后端套件在登录步骤失败：`teacher01` 期望 200 + code=0，实际 200 + code=4001（参数校验失败） | 认证从演示 token 改为账号密码后，旧脚本仍按演示 token 时期的登录参数调用登录端点 | 测试脚本随 `C-AUTH-API@1` / `C-SESSION@1` 更新（`tests/backend/*.py`、`run_all.sh`），并在隔离库中准备演示账号与邀请数据 | 中间记录 `outputs/phase2/backend_run_all.log`（2026-11-13 19:40，失败）；最终 `run_all` **EXIT=0** 全 PASS |
| Q3 | Windows Git Bash 下验证入口无法直接按 `python3` 运行 | 本机只有 `python` 可执行文件，`python3` 不存在 | 验证命令显式设置 `PYTHON_BIN="$(command -v python)"` | `walkthrough.md` 命令表 |
| Q4 | 安全红线本地 1 项 FAIL：B5b「发现运行产物残留」 | 工作区存在 `.playwright-mcp/` 控制台日志、`outputs/phase2/` 验证日志、根目录 `pytest_*.log` / `probe_*.log` / `cov_run.log` 与 `work/` 历史文件 | 未删除用户文件（保留原始证据）；A 层源码 / 交付物 Key 扫描 0 命中，B4 / B5 通过；CI 干净检出未含这些本地文件 | `outputs/phase2/security_redline.log`：12 通过 / 1 失败 |
| Q5 | 首轮独立审查发现 2 项阻塞：写操作缺 CSRF 校验、派生组织越权 | 实现与 `C-SESSION@1` / `C-AUTHZ@1` 契约不一致 | 由原 coder 按契约修复，进入第二轮审查 | 见 §6.2 |
| Q6 | 第二轮审查 A1 / A2 / A3 三项问题 | 修复 diff 与相关回归中的契约 / 边界问题 | 逐项修复；第三轮审查「可提交，无新增阻断」 | 见 §6.2 |

---

## 6 验证、审查、未完成与证据索引

### 6.1 自动化验证（真实命令与结果）

工作目录：仓库根 `D:\Users\Lenovo\Downloads\campus-task-agent-delivery\campus-task-agent`（git-bash）。

```text
$ PYTHON_BIN="$(command -v python)" python -m pytest \
    tests/backend/test_auth_org_permissions.py tests/backend/test_activity_hierarchy.py -q
60 passed in 83.65s

$ PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh
EXIT=0
verify_tables 30 PASS、applications 410 PASS、api_e2e 255 PASS、
agent_mock 229 PASS、agent_incremental 358 PASS、sse 105 PASS、KB 观测 25 PASS
（全过程日志：/tmp/run_all_phase2_final4.log）

$ PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh
EXIT=0：构建门禁 4/4、静态契约 25/25、语音切片 21/21

$ bash tests/backend/verify_phase2_migration.sh
PASS：16 张表、既有数据保留、legacy 用户 4、重复执行幂等、备份存在、
迁移报告 outputs/phase2/migration_report.md
```

迁移报告实测（`outputs/phase2/migration_report.md`）：源库为副本 `outputs/phase2/copy.db`，备份 `copy.db.backup-20261113191810`；用户 4 人全部标记 legacy、有密码 0；活动 2 个、任务 13 个，`org_id` 均为空；结论「结构升级完成；组织归属未自动推断」。

### 6.2 独立审查（3 轮，只读）

| 轮次 | 范围 | 结论与处置 |
|---|---|---|
| 第一轮 | 本次全部改动 | **2 项阻塞**：写操作缺 CSRF 校验、派生组织越权 → 由原 coder 按契约修复并回归 |
| 第二轮 | 新增修复 diff、相关回归、未关闭问题 | A1 / A2 / A3 → 逐项修复 |
| 第三轮 | 仅新增差异与未关闭问题 | 结论「**可提交，无新增阻断**」 |

遗留**非阻断**问题（本轮未修，如实记录）：① 已登录状态下重置成功后页面 notice 丢失；② `parent` 分支未校验 `activity.org_id`；③ 登录限流为进程内实现，多进程部署不共享；④ 4030 / 4040 的 HTTP 状态口径未完全统一。

### 6.3 浏览器验证（模拟视口）

工具：Playwright MCP；账号 `member01`；视口 1440×900（桌面）与 390×844（手机模拟，非真机）。

| 检查项 | 实测结果 |
|---|---|
| 登录后的组织上下文 | 工作台显示「计算机学院团委 / 成员」 |
| 跨组织任务不可见 | `/tasks` 列表不含外院任务 |
| 跨组织直接 id 访问 | `/activities/2` 显示「活动不存在」（4040 口径） |
| 密码重置后的会话失效 | 重置成功跳转登录页，旧会话失效 |
| 邀请注册页 | 通过邀请链接进入注册页，页面可用 |
| 成员访问后台 | `/admin` 对成员跳转工作台 |

### 6.4 状态与未完成项

**本轮可声称的状态**

- **实现完成**（代码已写入工作区）。
- **自动测试通过**：pytest **60 passed**；后端 `run_all` **EXIT=0**（全部子套件 PASS）；前端 `run_all` **EXIT=0**（4/4、25/25、21/21）；迁移副本验证 **PASS**。
- **浏览器（模拟视口）验证**：1440×900 与 390×844 实测上述 6 项。
- **安全红线本地 12 通过 / 1 失败**：唯一失败为 B5b 运行产物残留（本地日志与 `work/` 历史文件）；**未**宣称安全红线全部通过，也**未**运行 CI。
- **未提交、未推送、未部署**；**真机验证未做**；**CI 未运行 / 未查询**，committed hash 与 CI 结果**待回填**。

**明确未完成**

1. 阶段 3（完整三层状态机与验收规则）。
2. 阶段 4（其余页面响应式、语音与原生桥接）。
3. 阶段 5（完整回归与比赛材料）。
4. iOS / Android 真机验证。
5. 邮件 / 短信通道（重置 token 由管理员直接返回）。
6. 平台管理员尚无前端组织创建入口（当前仅 `POST /api/orgs` 与 CLI）。
7. 本阶段提交、推送与 CI 结果（待授权后回填）。

### 6.5 证据索引

| 证据 | 路径 | 口径 |
|---|---|---|
| 阶段留痕 | `codearts_proof/ai_dialogue/stage16_认证与组织权限.md` | 可入 Git |
| 开发索引 | `codearts_proof/LOG.md`（阶段 16 行 + 说明） | 可入 Git |
| Prompt 演进 | `codearts_proof/prompts/prompt迭代记录.md`（P-016） | 可入 Git |
| 桌面截图 | `codearts_proof/screenshots/stage16/{desktop-workbench-member,desktop-hall-member,desktop-cross-org-denied,desktop-reset-success}.png` | 真实截图，已脱敏归档 |
| 手机截图 | `codearts_proof/screenshots/stage16/mobile-hall-member.png` | 浏览器模拟视口，非真机 |
| 走查与命令 | `outputs/phase2/walkthrough.md` | `/outputs/` 被 `.gitignore` 忽略，仅本地证据 |
| 迁移报告 | `outputs/phase2/migration_report.md` | 同上，副本验证产物 |
| 验证日志 | `outputs/phase2/{backend_run_all,frontend_run_all,security_redline}.log` | 同上；`backend_run_all.log` 为 19:40 中间失败记录，最终通过日志在 `/tmp/run_all_phase2_final4.log` |
| 行为测试 | `tests/backend/test_auth_org_permissions.py` | 可入 Git |