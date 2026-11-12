# tests/security · 安全红线、交付物与无头端到端终验

本目录是规划契约 `T12` / `T15` 的**独立验证产物**，只做只读检查与记录，**不修改任何实现、文档或 plan**。
最终验收结论见 [`ACCEPTANCE.md`](./ACCEPTANCE.md)（当前：`VERDICT: PASS`）。

| 文件 | 作用 |
|---|---|
| `test_security_redline.sh` | 安全红线扫描（**A 层严格 + B 层本地运行时文件**，共 13 项）：源码/交付物 Key 字面量、前端与 dist 凭证变量、`.gitignore` 覆盖 6 项、`backend/.env` 与 `backend/*.db` 合规性（`PASS-LOCAL`） |
| `verify_delivery.py` | 交付物与契约一致性：`readme/`、`codearts_proof/`、根 README、端口/账号/env、留痕真实性（27 项） |
| `e2e_headless.py` | 无头端到端功能验收：认证→发布→流转→验收积分→签到→通知→双 Agent→KB→分解→SSE→前端页面（27 项） |
| `ACCEPTANCE.md` | 逐条 PASS / DEFERRED / FAIL、缺陷与风险、最终 VERDICT |
| `README.md` | 本文件：运行方式、检查项、退出码语义 |

---

## 一、运行方式

所有命令在**工程根**（`campus-task-agent/`）执行。

### 1. 安全红线

```bash
bash tests/security/test_security_redline.sh
echo $?          # 0 = 全部 PASS；1 = 存在 FAIL
```

脚本自行推导工程根，只读扫描，不启动服务、不写文件。

### 2. 交付物与契约一致性

```bash
# Windows（推荐使用后端虚拟环境自带的 Python）
backend/.venv/Scripts/python.exe tests/security/verify_delivery.py

# macOS / Linux / 其它 Python 3.9+
python3 tests/security/verify_delivery.py

# 指定工程根 / 指定规划契约（plan 被移动或修订后复验）
python3 tests/security/verify_delivery.py --root /path/to/campus-task-agent \
  --plan /path/to/.codeartsdoer/plans/campus-task-agent/plan.md

echo $?          # 0 = 全部 PASS；1 = 存在 FAIL；2 = 工程根不存在
```

仅使用 Python 标准库，不安装任何依赖。

> **D19 不硬编码任何默认值**：脚本从 `plan.md` 的 `#### 2.2.1` 表格动态解析 9 个 env 默认值，
> 再与 `readme/README.md`、根 `README.md`、`backend/.env.example` 三方比对。
> plan 不存在 / 找不到 2.2.1 小节 / 表格缺变量 ⇒ D19 **FAIL** 并输出具体原因。
> `.env.example` 中 `MAAS_MODEL` 强制精确比对；`MAAS_MOCK` 允许示例预置 `1`；其余占位值（`your-...` / `example.com`）豁免。

### 3. 无头端到端功能验收（8020 / 5175）

```bash
backend/.venv/Scripts/python.exe tests/security/e2e_headless.py
echo $?          # 0 = 全部 PASS；1 = 存在 FAIL；2 = 环境/启动失败

# 调试时保留临时数据库目录
backend/.venv/Scripts/python.exe tests/security/e2e_headless.py --keep-temp
```

脚本自动完成：
1. 后端 `DATABASE_PATH=<临时>/t15.db MAAS_MOCK=1 RUN_SCHEDULER=0`，端口 **8020**；
2. 前端 `npm run preview -- --port 5175 --strictPort --host 127.0.0.1`（要求 `frontend/dist` 已构建）；
3. 27 项断言（见下）；
4. 结束终止进程、删除临时库/临时目录、释放 8020/5175。

> 中文 JSON 一律以 `ensure_ascii=False` + UTF-8 发送，不使用 curl，避免 Windows 控制台编码问题。
> 终止前端使用 `taskkill /F /T`（Windows），后端使用 `terminate()` 并在超时后 `kill()`。

### 4. 安装脚本幂等（人工/CI 手动执行）

在**已有** `.venv` 与 `node_modules` 的工程根重跑，避免联网升级与污染开发库：

```bash
TMPD="$(mktemp -d)"
PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
DATABASE_PATH="$TMPD/install_idempotent.db" \
  bash readme/install.sh
```

判定标准：退出码 0；输出含 `[1/4] [跳过] 已存在 backend/.venv` 与 `[3/4] [跳过] 已存在 frontend/node_modules`；
重跑前后 `pip freeze`、`node_modules` 顶层条目、`package-lock.json` 哈希不变；仓库内不产生 `.db`。

> `readme/install.sh` 不支持 `SKIP_INSTALL` 之类的跳过开关；上述环境变量用于把安装行为限制为"离线 + 临时库"，
> 脚本本身仍完整执行四个步骤。Windows `cmd` 可用 `readme\install.bat`，判定标准相同。

---

## 二、检查项清单

### A. 安全红线（12 项）

| 编号 | 检查项 |
|---|---|
| A01 | 源码/测试/文档/交付物 Key 扫描（强模式 `(^\|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}`；范围：`backend/app`、`frontend/src`、`tests`、`readme`、`codearts_proof`、根 `README.md`、`.env.example`；`.env` 本身除外；仅检测脚本自身为白名单） |
| A02 | 弱模式 `sk-[A-Za-z0-9]` 诊断（仅 INFO，不参与判定） |
| A03 | `frontend/src` 无 `MAAS_API_KEY` |
| A04 | `frontend/dist` 无 `MAAS_API_KEY`（附加） |
| A05~A09 | `.gitignore` 含 `.env` / `.venv` / `node_modules` / `*.db` / `dist` |
| A10 | `.gitignore` 放行 `.env.example`（`!.env.example`） |
| B4 | `backend/.env` 若存在：必须被 `.gitignore` 覆盖、不在交付目录内、**不读取/不打印 Key 值** → `PASS-LOCAL`；不存在同样 PASS |
| B5 | `backend/*.db` 若存在：必须被 `*.db` 覆盖、不在交付目录内、测试使用 `DATABASE_PATH=<临时库>` → `PASS-LOCAL`；不存在同样 PASS |
| B5b | 日志 / 临时 / 备份 / 交换文件残留（严格 0 命中） |

> **`sk-` 误报陷阱**：CSS 类名 `task-name`、`mask-border`、包名 `campus-task-agent-frontend` 都含子串 `sk-`。
> 判定使用"词边界 + 至少 16 位 Key 字符"的强模式；弱模式命中只作诊断输出。

### B. 交付物与契约（27 项）

| 编号 | 检查项 |
|---|---|
| D01~D05 | `readme/` 5 件套：`README.md`、`install.sh`、`install.bat`、`开源组件说明.md`、`码道应用总结.md` |
| D06 | `codearts_proof/LOG.md` |
| D07 | `ai_dialogue` 6 份阶段文件 |
| D08~D09 | `prompts/agent_team_启动指令/`、`prompts/业务Agent/` 目录 |
| D10 | `prompts/prompt迭代记录.md` |
| D11 | `debug/template.md` |
| D12~D13 | `screenshots/`、`video/` 目录 + `.gitkeep` |
| D14 | 根 `README.md` |
| D15~D16 | 端口 8000 / 5173 与后端启动命令 `--port 8000` |
| D17 | 演示账号 `teacher01` / `student01~03` |
| D18 | 9 个 env 变量名齐全 |
| **D19** | **env 默认值三方比对：plan 2.2.1 动态解析 vs `readme/README.md` vs 根 README vs `.env.example`** |
| D20 | 根 README 与 `readme/README.md` 启动命令段落一致 |
| D21 | `ai_dialogue` 五小节齐全、占位标注与归档状态一致（防"占位写成已完成"） |
| D22 | `LOG.md` 至少 6 行真实记录 |
| D23 | `debug/` 至少 3 篇排错实例 |
| D24 | `开源组件说明.md` 覆盖 `2.2.14` 的 14 个组件（含版本/用途） |
| D25 | `ai_dialogue`「产出」表声明的仓库路径均真实存在（编造检测） |
| D26 | `.env.example` 变量集合与 `2.2.1` 一致 |
| D27 | 根 README 演示账号一致 |

### C. 无头端到端（27 项）

| 阶段 | 断言 |
|---|---|
| 健康与认证 | `/api/health`（code=0、tables=8、mock=true）；teacher01 / student01 登录与角色 |
| 发布与可见 | `POST /api/tasks`（status=published、publisher_id、credit_reward）；学生列表可见且 `is_claimable=true` |
| 流转 | claim（claimed + assignee）；progress（in_progress + 进度记录）；submit（submitted） |
| 验收与积分 | verify `pass=true`（verified + `credit_delta=25`）；`/api/credits/me` 余额与流水 |
| 签到 | 首次签到成功；**重复签到被拒绝（对抗探针）** |
| 通知 | student 含"验收通过，积分到账"；teacher 含认领与签到 |
| 双 Agent | extract（mock、`教三→教四` corrections、style_prompt 剥离）；review（ambiguities/polished/suggested_sub_tasks）；stream/parse 两片（教三→教四） |
| KB | similar 命中已发布任务，`threshold=0.6` |
| 分解 | 非晚会标题返回空数组（契约）；"秋之韵"标题返回 3 条 + `depends_on=[null,0,1]` + SOP≥3 步 |
| SSE | 200 + `text/event-stream`，收到 `event: notify` 与认领事件 data |
| 前端 | `/`、`/login`、`/tasks` 200 且含 `#app`；dist 的 js/css 可访问且非空 |

### D. 其它

- 安装幂等 3 项（I01~I03，见上文第 4 节）
- DEFERRED 6 项：干净环境全量复现、浏览器人工 UI/语音、真实 MaaS、APScheduler 调度扫描、云部署/视频/zip、prompt 原文与 badcase 内容

---

## 三、退出码语义

| 脚本 | 退出码 | 含义 |
|---|---|---|
| `test_security_redline.sh` | `0` | 12 项安全检查全部 PASS |
| | `1` | 存在任一 FAIL（A 层 Key 字面量命中 / 前端或 dist 出现 `MAAS_API_KEY` / `.gitignore` 缺项；B 层本地 `.env`、`*.db` 存在但未被忽略或在交付目录内） |
| `verify_delivery.py` | `0` | 27 项交付物检查全部 PASS |
| | `1` | 存在任一 FAIL（文件缺失、端口/账号/env 不一致、plan 解析失败、留痕造假迹象、实例数量不足） |
| | `2` | 工程根不存在或参数非法（未执行检查） |
| `e2e_headless.py` | `0` | 27 项端到端断言全部 PASS |
| | `1` | 存在任一 FAIL（接口错误码/字段不符、SSE 未收到事件、前端页面或资源不可用） |
| | `2` | 环境/启动失败（缺少 `.venv`、缺少 `frontend/dist`、端口未就绪） |

> 退出码只反映**脚本可机器判定的事实**；`DEFERRED` 项不在脚本中自动判定，统一记录在 `ACCEPTANCE.md`。
> **脚本全部退出 0 也不等于整体验收通过**——整体结论以 `ACCEPTANCE.md` 的 VERDICT 为准。

---

## 四、约束与注意事项

1. **只读**：三个脚本不修改仓库文件；E2E 使用系统临时数据库，结束即删除。
2. **端口**：只使用 8020（后端）/ 5175（前端）；禁止占用 8000/5173（人工演示）与 8010/5174（T10/T11）。
3. **不修改实现**：发现缺陷写入 `ACCEPTANCE.md`，由对应 owner 修复后重跑受影响检查，验证者不自行改业务代码。
4. **不假设**：任何未执行项必须写 DEFERRED + 原因 + 责任任务，禁止以"应该没问题"代替证据。

---

## T8（第二轮迭代）更新

- 端口：后端 **8021**、前端 preview **8022**（T8 独占；临时库 + `MAAS_MOCK=1` + `RUN_SCHEDULER=0`）。
- `verify_delivery.py` 新增 `check_round2_delivery()`：**D28** stage7 五节齐全、**D29** LOG 含「阶段 7」、**D30** 两份 README 四项功能关键词、**D31** stage7 第 4/5 节是否真实收口（占位即 FAIL，对应 R17-AC1）。
- `e2e_headless.py` 业务流改为：登录 → 发布 → **报名×2 → 审批×2** → 进度×2 → 提交×2 → 验收（两人各 +25）→ 积分（两人）→ 签到×2 → 通知 → Agent/KB/分解/SSE/前端；实测 **37 PASS / 0 FAIL**。
- 最近一次安全红线（分层口径）：**11 PASS + 2 PASS-LOCAL / 0 FAIL**（A 层 Key 字面量 0 命中；`backend/.env` 与 `backend/campus.db` 被 `.gitignore` 覆盖且不入包）——详见 `ACCEPTANCE.md` 第五节；**VERDICT: PASS**。
