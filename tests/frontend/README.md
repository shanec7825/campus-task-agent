# T11 · 前端构建、契约对齐与人工验收

本目录是前端验证的**唯一 write_set**（T11 独占），包含 5 个文件：

| 文件 | 作用 |
|---|---|
| `run_all.sh` | 一键入口：依次执行构建门禁 → 静态契约对齐，失败即停 |
| `test_build.sh` | 构建门禁：`typecheck` + `build`（正式生成 `frontend/dist`）+ `dist/index.html` + 禁止 `any` |
| `check_contracts.py` | 静态契约对齐：API 导出 / store action / 颜色池 / FieldPanel props / 无裸 `fetch` |
| `MANUAL_CHECKLIST.md` | 浏览器人工验收清单（语音切片、悬浮确认、红点、验收等无法自动化的行为） |
| `README.md` | 本文件：运行方式、端口约定、退出码、限制说明 |

> **所有权**：`frontend/dist` 由 T11 独占生成（其他任务只做 build 校验，不产物化 dist）。
> T11 只读实现代码，**不改任何实现文件**；失败项只报告"文件 + 行号 + 建议责任任务"，由 Leader 指派修复。

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| Node.js | ≥ 18（`npm` 可用） |
| 前端依赖 | `campus-task-agent/frontend/node_modules` **已安装**；本脚本执行 `npm run`，**不会**执行 `npm install`（禁止重装） |
| Python | ≥ 3.9，仅用标准库。优先自动使用 `backend/.venv/Scripts/python.exe` |
| 浏览器（仅人工清单） | Chrome / Edge（语音需 `webkitSpeechRecognition`） |

---

## 2. 运行方式

在**任意工作目录**执行均可（脚本自行推导 `frontend` 路径）：

```bash
# 一键执行（构建门禁 + 契约对齐）
bash campus-task-agent/tests/frontend/run_all.sh

# 只跑构建门禁（正式生成 frontend/dist）
bash campus-task-agent/tests/frontend/test_build.sh

# 只跑静态契约对齐（可指定前端根目录）
python campus-task-agent/tests/frontend/check_contracts.py
python campus-task-agent/tests/frontend/check_contracts.py --frontend /path/to/frontend
```

显式指定 Python 解释器：

```bash
PYTHON_BIN=/path/to/python bash campus-task-agent/tests/frontend/run_all.sh
```

### 退出码语义

| 脚本 | 退出码 | 含义 |
|---|---|---|
| `test_build.sh` | `0` | typecheck / build / dist / any 全部通过 |
| | `1` | `typecheck` 失败（短路，不再 build） |
| | `2` | `build` 失败 |
| | `3` | 产物断言失败（`dist/index.html` 缺失或为空 / 命中 `: any` 或 `as any`） |
| `check_contracts.py` | `0` | 5 项契约检查全部 PASS |
| | `1` | 至少 1 项 FAIL（输出文件与行号） |
| `run_all.sh` | `0` | 两项全部通过 |
| | `1` | 构建门禁失败（原因见 `test_build.sh` 输出） |
| | `2` | 静态契约对齐失败 |

---

## 3. 端口约定（联调与人工验收）

`frontend/vite.config.ts` 由 T1 冻结，`/api` 代理**硬编码**指向 `http://127.0.0.1:8000`，**禁止修改**。

| 用途 | 后端 | 前端 | 说明 |
|---|---|---|---|
| **默认组合（推荐）** | `8000` | `5173` | 零配置，`npm run dev` 直接可用；人工验收用此组合 |
| **端口被占用时的备选** | `8010` | `5174` | `uvicorn ... --port 8010` + `npm run dev -- --port 5174`；**前端页面可打开，但 `/api` 仍代理到 8000**，因此该组合只用于后端直连冒烟与页面可访问性验证，完整联调必须回到 8000/5173 |

本机实测（Windows 11 + Git Bash + Vite 5.4）：

- `GET http://localhost:5174/` → `200`，`GET http://localhost:5174/login` → `200`
- `GET http://127.0.0.1:5174/` → 无响应（Vite 5 默认监听 `localhost` 的 IPv6 地址）
- **人工验收请统一使用 `http://localhost:5173/`（或 `5174`），不要用 `127.0.0.1`**
- 8010 + 5174 组合下 `GET /api/health` 经代理返回 `500`（代理指向未启动的 8000），属预期行为

### 联调启动命令（供人工验收，不由本脚本自动执行）

```bash
# 终端 1：后端（临时库 + mock；演示时可用默认 campus.db 与 8000 端口）
cd campus-task-agent/backend
DATABASE_PATH="$(mktemp -d)/t11.db" MAAS_MOCK=1 RUN_SCHEDULER=1 \
  ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 终端 2：前端
cd campus-task-agent/frontend
npm run dev            # 默认 5173；被占用时 npm run dev -- --port 5174
```

演示账号：`teacher01`（publisher） / `student01`（student），首次登录自动建号，无需预置数据。

---

## 4. 本次执行结果（可复现证据）

环境：Windows 11 / Git Bash / Node（Vite 5.4.21）/ Python 3.14.0（`backend/.venv`）。

| 步骤 | 结果 |
|---|---|
| `npm run typecheck`（`vue-tsc --noEmit`） | **PASS** |
| `npm run build`（`vite build`，1702 modules） | **PASS**，`dist/index.html` 424 字节 |
| `grep -rnE ': any\|as any' src` | **PASS**，无命中 |
| `check_contracts.py`（5 项） | **PASS**，`RESULT: 5 passed, 0 failed` |
| 联调冒烟（后端 8010 + 临时 DB + `MAAS_MOCK=1`） | **PASS**：`/api/health` 8 表 + `mock=true`；登录 / 任务列表 / `extract` / `review` / `stream/parse` / `kb/similar` 均 `code=0` |
| 前端 5174 页面可访问 | **PASS**：`localhost:5174` 的 `/`、`/login` 均 `200` |

**负向自检**（证明断言不是"假绿"）：在临时副本中人为破坏 5 处契约，`check_contracts.py` 5 项全部 FAIL 且行号准确，退出码 `1`；空目录跑 `test_build.sh` 时 `typecheck` 失败并短路返回 `1`。

---

## 5. 覆盖边界

**自动化覆盖**：类型检查、生产构建、dist 产物、`any` 禁用、API 导出名、store action 名、颜色池色值、FieldPanel props、裸 fetch 禁止。

**不在自动化范围**（见 `MANUAL_CHECKLIST.md`）：真实麦克风切片时序、800ms 尾句、悬浮确认态、UI 染色与红色问号、相似提示条、一键采纳/替换、拆解批量发布、SSE 红点时效、指派与验收、签到重复提示。这些依赖真实浏览器 / 麦克风 / 双会话，必须人工执行并留截图证据。

---

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| `npm run typecheck` 报 `vue-tsc` 不存在 | `node_modules` 未安装；由 T1 负责，**不要**在此重装，联系 Leader |
| `ESOCKETTIMEDOUT` / `fetch` 超时 | 后端未启动；按第 3 节启动 8000 |
| 前端能开但接口全 500 | 后端不在 8000，或用了 8010 备选端口（代理写死 8000，见第 3 节） |
| 麦克风按钮置灰 | 非 localhost / https 页面，或浏览器不支持 `webkitSpeechRecognition` |
| `dist/index.html` 缺失 | `build` 失败，查看 `test_build.sh` 第 2 步输出与退出码 `2` |

---

## T8（第二轮迭代）扩展

- `check_contracts.py`：由 5 项扩为 **11 项**。新增：⑥ `TRACE_COLORS` 4 色与 `color-pool.css` 同值；⑦ `BlockKind` 五值（类型源 `types/models.ts`）+ `BlockText` 非 raw 只读 / live 虚线；⑧ `toTaskPayload` 函数体不含 `blocks`；⑨ `api/applications.ts` 5 导出 + `claimTask → Promise<ApplyResult>`；⑩ `traceText.formatChangeText` 5 组模板（`tsc` 单文件编译 + `node` 实跑）；⑪ 历史硬编码色值 **93 行 / 96 个色值**白名单逐行标注「非本轮引入」+ 4 个追溯色零命中。
- `check_voice_slicer.cjs`（新建）：7 组切片 + 5 常量 + `sliceByPunctuation` 零命中（13 PASS）。
- `run_all.sh`：新增步骤 3/3；`tsc` 产物必须放在 `tests/frontend/.tmp-voice`（`frontend/package.json` 为 `type: module`，放在 frontend/ 内会被 Node 当 ESM 解析）。
- `MANUAL_CHECKLIST.md`：新增 M16~M22（增量解析、建议采纳、手改留痕、语音实时、Edge 续接、报名审批、我的报名）。
- 最近一次实测：`EXIT=0`；构建 4 PASS、契约 11 PASS、语音 13 PASS。
