# stage24 整体验收（AIW-06）

> 日期：2026-11-14。状态（截至本记录）：验收套件完成并**1 passed**；后端 `run_all` **EXIT=0**；前端 `run_all` **EXIT=0**（构建 4/4、契约 25/25、语音 21/21）；安全红线 **12 通过 / 1 失败（B5b）**；独立审查三轮 **0/4 → 0/2 → 0/0 Important**；桌面 + 390×844 截图 8 张；真实模型、真机、移动端完整提交/验收、深色主题未验证。业务提交 `a728788` 已推送，CI run 43532974986 四个 job 全 success（见第 8 节）。

## 1. 需求来源与授权

- 来源：用户本轮「每小时触发一次的阶段开发任务」指令（原文归档 `codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage24_整体验收_启动指令.md`）；本地总计划 `ai-workbench/roadmap.md` 的 AIW-06「整体验收」。
- 授权：AIW-00 至 AIW-06 已确认范围内的阶段开发、必要修复、测试、独立审查与记录；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作、修改安全策略。
- 非目标：不新增产品功能、路由、表或依赖；不改状态机、授权、通知、积分实现；不做收费/支付、多级审批、最终自动验收、真实模型或真机验收。

## 2. 开工基线

- 分支 `main`；开工 HEAD `d25c91cc2fd38910fff76d2934465e46558c5fdd`（stage23 文档回填）。
- 工作区已有上次 AIW-06 运行留下的未提交内容：`.github/workflows/ci.yml`、`docs/CI.md` 已修改；`tests/backend/test_aiw06_acceptance.py`、`codearts_proof/screenshots/stage24/` 未跟踪。本次按“未完成阶段优先收尾”接续，不重做、不回退。
- 上次运行状态：验收套件已写、CI 已接入、浏览器在提交 v1 与预审失败后中断；阶段门禁、独立审查、留痕、提交推送与 CI 未执行。
- 开工快照：`outputs/aiw06/opening-head.txt`、`opening-git-status.txt`、`opening-diff.patch`（上次运行生成）；本次接续差异见 `outputs/aiw06/closing-opening-diff.patch`。
- 未发现其他会话或子任务仍在工作区写入的迹象；未启动第二个写入者。

## 3. 决策与范围

- 本轮是**验收增量**，不改业务实现；只在验收中证实的测试缺口上补断言。
- 验收口径沿用既有契约：`4020` 依赖未完成、`4090` 旧稿/版本冲突、`4040` 跨组织不可见、stale 提醒不计未读、`request_id` 幂等不重复扣额度。
- AI 引用必须由服务端映射且只来自 `visible_task_filter` 可见任务；测试补外组织任务反例，禁止把“回答非空”当作权限内引用已验证。
- 隔离库在 import app 前设置环境；import 后断言 engine 指向临时库，模块退出先 `dispose()` 再删目录。
- 截图口径：design 要求桌面 1440×900、移动 390×844。实际 `01/03/04/05` 为 1425 宽，不重拍；报告如实标注，不声称全部满足。移动端只验证首页与详情浏览，完整提交/验收列未验证。

## 4. 实际变更

- 新增 `tests/backend/test_aiw06_acceptance.py`：一条完整晚会协作链路（活动/资料/任务/依赖/报名/审批/进度/提交/预审/退回/重提/旧版拒绝/验收/积分/通知/改期/AI/跨组织）。
- `.github/workflows/ci.yml`：Backend reliability job 接入 `test_aiw06_acceptance.py`。
- `docs/CI.md`：检查说明与本地命令加入整体验收套件，补充「AI 额度与请求幂等」。
- 新增 `codearts_proof/screenshots/stage24/01-08`：桌面 AI 首页、事务大厅、活动详情、成员提交 v1、预审失败、后台改期影响卡；移动 AI 首页、任务详情。
- 新增本记录、`codearts_proof/reports/stage24_整体验收.md`、启动指令原文；更新 `codearts_proof/LOG.md`、`docs/HANDOFF.md`。
- 未修改任何业务实现、表结构、依赖或主题令牌。

## 5. 真实问题与处置

| 编号 | 现象 | 根因与处置 | 状态 |
|---|---|---|---|
| S24-I01 | 上次运行浏览器走查在提交 v1、预审 fail 后中断 | Playwright MCP 同一消息重复 invoke 触发超时/告警；本次改为单步单调用，补后台改期影响卡与移动端截图，并在页面宽度评估后停止浏览器操作，不继续重试 | 已停止，证据已补部分 |
| S24-I02 | 首轮独立审查 0 Critical / 4 Important | ① AI 问答未断言 `citations` 与权限范围；② stage24 留痕未落盘；③ 01/03/04/05 截图非 1440×900；④ 移动端完整操作与桌面验收入口证据不足。①已补外组织任务反例与引用子集断言；②本轮补齐；③④按报告口径如实标注偏差/未验证 | ①②已处置；③④如实标注 |
| S24-I03 | 第二轮复核新增 I5：临时目录 atexit 清理实测无效 | Windows 上 engine 连接池未释放，`shutil.rmtree` 抛 `PermissionError`，`ignore_errors=True` 静默吞掉。改为 `engine.dispose()` 后再删除；探针运行前后均 11 个目录，已关闭 | 已修复 |
| S24-I04 | 安全红线本地 12 通过 / 1 失败（B5b） | 仅因 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/temp/`、`work/` 被忽略日志残留；未删除证据、未改基线、未提高阈值 | 如实记录 |
| S24-I05 | 演示服务占用 8000 端口 | 上次运行遗留 `outputs/aiw06/serve.py` 进程；本轮复用完成走查后停止，确认端口释放，未删除文件 | 已处置 |
| S24-I06 | 浏览器操作多次重复触发 | 主 Agent 在同一消息重复提交相同 Playwright 调用；已停止浏览器调用，未继续重试，未把静态核对冒充页面验证 | 已停止 |

## 6. 验证（真实命令与结果）

后端：

- `PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw06_acceptance.py -q`：**1 passed**（3.46s，EXIT=0）。
- `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`：**EXIT=0**；verify_tables 58 项（23 表）、applications 410、api_e2e 255、agent_mock 229、incremental 358、sse 105、unfiltered 25。
- 隔离证据：运行前后 `backend/campus.db` 均不存在；临时目录探针 `TMP_BEFORE=11`、`TMP_AFTER=11`。

前端：

- `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`：**EXIT=0**，构建 4/4、契约 25/25、语音 21/21，dist 已重建。

安全红线：

- `PYTHON_BIN="$(command -v python)" bash tests/security/test_security_redline.sh`：**12 通过 / 0 PASS-LOCAL / 1 失败 / 共 13 项**（B5b），EXIT=1。

浏览器：

- Playwright MCP，`http://127.0.0.1:8000` 同源 dist + `outputs/aiw06/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`。
- 实测：AI 首页通知与额度；事务大厅活动下任务；活动详情任务全景；成员提交 v1；预审 fail（时间一致性）；后台改期影响卡（成员 1、后续任务 0、通知接收人 2）；移动 AI 首页与任务详情。
- 页面宽度：`innerWidth=390`、`docScrollWidth=375`、`horizontalOverflow=false`。
- 截图归档 `codearts_proof/screenshots/stage24/`（8 张）。

## 7. 独立审查

- 三轮独立 Review Agent（general，只读）：首轮 0 Critical / 4 Important / 12 Suggestion；第二轮 0 Critical / 2 Important / 5 Suggestion；第三轮 **0 Critical / 0 Important / 3 Suggestion**。
- 已修复：AI 引用权限范围、活动/任务字段、旧版验收无副作用、逐人 verified、精确 stale、HTTP 200、临时目录清理。
- 未修 Suggestion：全量 pytest 时 skip 分支可能残留空目录；CI 文档可注明本套件需单文件运行；活动/任务固定日期。
- 第三轮后未再开第四轮；第三轮后仅补文档留痕，未改测试或业务代码。

## 8. 证据、未验证范围与提交状态

- 证据：本记录、`reports/stage24_整体验收.md`、截图 8 张、`outputs/aiw06/*.log`（本地忽略）。
- 未验证：真实模型、真机、移动端完整提交/验收、深色主题、部署、全量 pytest 的 skip 形态。
- 提交/推送/CI：业务提交 `a728788af906ccd2bf529166321f467277beec92` 已推送 `origin/main`；对应 CI run `43532974986`（run_number 20）**completed / success**，四个 job 全 success（Backend API and SSE integration、Frontend build/voice/public source security checks、Backend reliability ubuntu-latest、Backend reliability windows-latest）。核对方式为 GitHub REST API（本机无 `gh`）。未部署。
- 2026-11-14 CI 回填续跑：本轮读取现场、实跑 `tests/backend/test_aiw06_acceptance.py`（**1 passed**，5.15s，EXIT=0）核对代码现状后回填 CI 结论与本轮启动指令；未改业务代码、测试或表结构，未新开独立审查（无新增业务 diff）。