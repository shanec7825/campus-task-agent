# 阶段 18：活动下任务流程连通（AIW-00）

> 状态：本地完成（工作树未提交）。日期：2026-11-13（Asia/Shanghai）。本轮是产品路线 AIW-00，不等于此前讨论的任何业务 phase 收尾，不恢复 stage17 之前已回退的未提交代码。

## 1. 需求来源与现场

用户在 stage17 交接后选定 **AIW-00：基线差距确认与必要流程连通**，要求打通「活动负责人看到并管理其活动下任务」「从活动详情直接在该活动下发布任务」「任务详情提示下层已完成待负责人确认」三条链路，并补行为回归。本轮实际收到的派工消息原文见 [启动指令归档](../prompts/agent_team_启动指令/2026-11-13_stage18_活动流程连通_启动指令.md)（用户侧原始消息未在本会话取得，未重建）。

- 分支 `main`；开工 HEAD `af43dc7e15120ebb85f90e5f39879d080c2715c1`（`fix(test): 可靠性回归适配 Cookie 会话与组织归属`）。
- 开工时工作区已有 stage17 的未提交文档差异（`AGENTS.md`、`docs/CI.md`、`LOG.md`、`prompt迭代记录.md`、`HANDOFF.md`、`DEVELOPMENT_RECORDS.md`、stage17 文档与启动指令、`reports/`）。本轮保留这些改动，只在其上追加，未回退、未覆盖。
- 计划与契约保存在本地忽略目录 `.codeartsdoer/plans/aiw00-activity-flow/`：
  - `design.md`：R1 负责人可见性、R2 活动下发布、R3 任务级待确认、R4 无组织活动发布授权；
  - `task.md`：T1（可见性 + 回归）、T2（活动发布入口）、T3（待确认提示）、T4（验证）、T5（审查）、T6（留痕）、T7（R4 授权修复 + CI 接入）、T8（授权修复复验）、T9（复审）。
- 已用编号：最大 stage 为 17，最大流程 Prompt 为 P-017。本轮取 **stage18**；本轮未产生业务 Prompt 变更，不新增 P 编号。

## 2. 决策与边界

- 沿用 FastAPI / SQLAlchemy / SQLite 与 Vue 3 + TypeScript + Element Plus；不新增依赖、表、迁移或路由。
- R1 只扩大**可见集合**：`_self_visible_condition` 增加「活动负责人」条件；`can_manage_task` 保持原实现，可见性不等于写权限。是否可验收仍由既有管理权分支裁决。
- R2 只让手动表单携带 `activity_id`；AI 模式发布的活动归属明确不在本轮范围。发布页保留 `ref<PublishMode>('ai')` 字面量初值以守住既有静态契约（`C-VOICEUI@4 §A`），活动入口在 setup 内切到手动模式。
- R3 为纯前端派生展示，不新增后端字段、不改业务状态、不自动调用验收接口。
- R4 由首轮独立审查发现：无组织活动（`org_id IS NULL`）没有组织角色可校验，等于任意登录用户都能向他人活动挂任务。裁定为**发布权只授予活动负责人本人**，其余登录用户 4030；组织内活动维持既有 `PUBLISH_ROLES` 校验。
- 本轮不提交、不推送、不部署，不运行真实模型、浏览器、真机，不查询远端 CI；验证一律使用隔离临时库。

## 3. 实际工具与派工

| 项目 | 本轮实际情况 |
|---|---|
| 平台 | 华为云 CodeArts 代码智能体（team-leader 编排）；平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验 |
| 实现 | coding-engineer 子 Agent 按 T1/T2/T3 并行实现，写集合互不重叠；T7 授权修复在本轮实现 Agent 中追加完成（执行者编号未单独取得，不归因具体子会话） |
| 验证 | team-result-verifier 执行 T4 与 T8，产出 [stage18 验证记录](../reports/stage18_验证记录.md) |
| 独立审查 | team-code-reviewer 两轮只读审查（T5、T9）：首轮针对全量 diff 与验证证据，第二轮只查修复后新增差异与未关闭项；审查结论在会话中给出，未落盘独立报告文件 |
| 记录 | 记录 Agent（T6）按 AGENTS §3 与 `docs/DEVELOPMENT_RECORDS.md` 归档本文件、LOG、HANDOFF 与启动指令 |
| 模型口径 | 未取得可核验的具体运行模型标识；不沿用历史阶段的模型声明 |

派工约束：每个实现任务只读 `task.md` 条目与对应契约 ID，只写自己的写集合；验证必须针对实际落盘代码；审查不得以作者结论代替 diff 阅读。

## 4. 产出与问题

| 产出 | 本轮实际内容 |
|---|---|
| [stage18 验证记录](../reports/stage18_验证记录.md) | 真实命令、退出码、断言计数、契约逐项核对、失败项与变异验证 |
| `backend/app/services/authz.py` | `:74-87` 新增活动负责人可见条件（`exists().where(Activity.id == task.activity_id, Activity.owner_id == user.id)`）；`:195-196` 无组织活动非负责人 4030 |
| `tests/backend/test_activity_workflow.py` | 新增 600 行 / 8 个用例：负责人读他人任务、活动树包含他人任务、验收可达（4090）、无关成员 4040、独立任务不获可见性、非负责人向无组织活动发布 4030、负责人本人发布成功、PATCH 移入他人无组织活动 4030 |
| `frontend/src/views/ActivityDetail.vue` | `:85-88` 跳转 `publish?activity=<id>`；`:185`「在此活动下新建任务」按钮（`type="primary"`），原「发布相关事务」降为次级 |
| `frontend/src/views/PublishPage.vue` | `:29-34` 解析 `?activity` 为正整数；`:39-42` 保持 `'ai'` 初值并在活动入口切手动；`:105-112` 归属提示；`:123` 传入 `activity-id` |
| `frontend/src/components/Publish/ManualForm.vue` | `:31-32` 新增 `activityId` prop；`:203-220` 构造 payload 并仅在正整数时加入 `activity_id` |
| `frontend/src/views/TaskDetail.vue` | `:204-210` `awaitingOwnerConfirm` 派生值；`:899` 提示文本；`:1225-1231` 使用 `var(--app-font-aux-lg)` + `var(--el-color-warning)` |
| `frontend/src/types/models.ts` | `:283-285` `TaskCreatePayload.activity_id?: number \| null` |
| `.github/workflows/ci.yml` | `:40-41` 后端行为套件加入 `tests/backend/test_activity_workflow.py`，步骤名同步 |
| `docs/CI.md` | `:8`、`:21` 描述与本地等价命令同步 |

| 问题编号 | 实际问题与依据 | 处理 | 状态 |
|---|---|---|---|
| S18-I01 | 首轮前端门禁真实失败：`check_contracts.py` ⑰ `C-VOICEUI@4 §A` 要求 `PublishPage.vue` 的 `activeTab` 初值字面量为 `'ai'`，而 T2 首版写成三元表达式 `activityId.value !== null ? 'manual' : 'ai'`（`tests/frontend/run_all.sh` exit 2） | 改回 `ref<PublishMode>('ai')`，随后 `if (activityId.value !== null) activeTab.value = 'manual'`；对外行为不变 | 已修复，复跑 25/25 PASS |
| S18-I02 | 首轮独立审查 Important：新增行为回归未接入 CI，`test_activity_workflow.py` 只在本地存在 | T7 把该文件加入 `.github/workflows/ci.yml` 与 `docs/CI.md`；本地执行同一合并命令 68 passed，YAML 解析通过 | 已修复；真实 Actions 未运行 |
| S18-I03 | 首轮独立审查 Important：无组织活动缺少发布授权，任意登录用户可向他人无组织活动创建任务 | `resolve_task_org` 增加 `org_id is None && owner_id != user.id → ApiError(4030, "无权在该活动下创建事务", 403)`；补 3 个行为用例；变异 M1/M2 证明用例如有缺口会失败 | 已修复并验证 |
| S18-I04 | 首轮独立审查 Important：活动负责人可见性扩大被质疑连带扩大写面 | 复核：改动仅新增 `_self_visible_condition` 一项，`can_manage_task` 分支未动；用「无关成员仍 4040」「负责人验收返回 4090/成功」与「独立任务不获可见性」界定了可读与可管的边界；第二轮审查 PASS | 已关闭（未改代码，靠边界用例与复核） |
| S18-I05 | 验证环境中把两个后端测试文件放同一 pytest 进程执行时出现过 `1 failed, 17 errors`，全部为 setup 阶段 `OSError: [WinError 10051]` 与 `Sandbox Network Error: hit restricted [127.0.0.1:<随机端口>]`；同一合并命令另一次为 18 passed | 判定为沙箱拦截随机回环端口的环境问题；单文件独立运行与 `tests/backend/run_all.sh`（固定端口 8040/8041）稳定通过；未在无沙箱环境复验合并方式 | 已归因，环境遗留 |

本轮没有新增真实产品排错实例，`codearts_proof/debug/` 实例索引未变；S18-I01 属门禁口径冲突，已在本文件与验证记录中留存证据，不冒充已修复的产品 Bug。

## 5. 验证与未完成项

工作目录均为项目根；Python 3.12.10，统一 `PYTHON_BIN="$(command -v python)"`；测试均在 `import app` 前设置临时 `DATABASE_PATH`、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`，未触碰 `backend/campus.db`。完整证据见 [stage18 验证记录](../reports/stage18_验证记录.md)。

| 命令或检查 | 退出码与真实结果 | 范围 |
|---|---|---|
| `python -m pytest tests/backend/test_activity_workflow.py -q` | 0；`8 passed`（T4 时 5 passed，T7 增加 3 例后 8 passed） | 隔离临时库，真实 HTTP + Cookie/CSRF |
| `python -m pytest tests/backend/test_activity_hierarchy.py -q` | 0；`13 passed` | 活动层级回归 |
| `python -m pytest tests/backend/test_auth_org_permissions.py -q` | 0；`47 passed` | 认证与组织权限回归 |
| `python -m pytest test_auth_org_permissions.py test_activity_hierarchy.py test_activity_workflow.py -q`（CI 配置原文） | 0；`68 passed` | 与 CI 配置一致的本地等价命令 |
| `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | 0；6 个脚本全过，`PASS:` 断言 1412 条，末尾 `T5 全部主验证通过` | 临时库 + 固定端口真实后端 |
| `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`（首轮） | 2；构建 4/4 PASS，`check_contracts.py` 24 passed / 1 failed（⑰） | 真实门禁失败，见 S18-I01 |
| 同上（修复后复跑） | 0；构建 4/4、契约 25/25、语音切片 21 PASS / 0 FAIL | 前端门禁全绿 |
| 变异 M1（删除 4030 校验） | exit 1；`2 failed, 6 passed` | 证明新增用例能捕获授权缺口回归 |
| 变异 M2（保留 4030 但先写库） | exit 1；同 2 个用例失败 | 证明「授权失败不写库」断言有效 |

### 5.1 契约核对

- `C-AUTHZ-VISIBILITY@1`：9 个子项全部 PASS（验证记录 §2.1），含 `can_manage_task` 未动、独立任务不获可见性。
- `C-FE-ACTIVITY-PUBLISH@1`：静态核对全部 PASS（§2.2），端到端浏览器链路未动态验证。
- `C-FE-TASK-CONFIRM@1`：静态核对全部 PASS（§2.3），未在浏览器构造「全部子任务 verified 且父任务未验收」场景。
- `C-ACTIVITY-PUBLISH-AUTH@1`：7 个子项全部 PASS（§6.3），含文案逐字、显式 `org_id` 不能绕过、失败不写库、PATCH 不产生字段变更。

### 5.2 审查结论

- 第一轮：**不阻塞提交，但 3 项 Important**（S18-I02 CI 接入、S18-I03 无组织活动授权、S18-I04 负责人写面复核）；均已处置。
- 第二轮：仅查修复后新增 diff 与相关回归，**PASS，无新增阻断项**。
- 审查依据：本轮 diff、`stage18_验证记录.md` 的命令与计数、变异结果。审查未落盘独立 JSON/Markdown 报告，本文件只转述会话结论，不代替报告原文。

### 5.3 未验证范围

1. **未提交、未推送、未部署**；工作区改动仍在本地。
2. **未运行真实 GitHub Actions**：仅本地解析 YAML 并执行同一条命令，Ubuntu/Windows runner 结果未知。
3. **浏览器 / 真机 / 移动端视口未验证**：R2 端到端跳转与 R3 渲染均为静态核对。
4. **真实模型未调用**：全程 `MAAS_MOCK=1`。
5. **合并 pytest 的沙箱间歇失败**未在无沙箱环境复验（S18-I05）。
6. 组织内活动与外组织 admin 的组合场景由既有套件覆盖，本轮未另造用例。

## 6. 提交与后续

本轮仅本地落盘，未提交、未推送、未部署，CI 未查询。下一轮拿到明确提交授权后，应按 AGENTS §6 先核对实际暂存清单（排除计划、日志、数据库与凭证），再提交并观察与 SHA 对应的 CI 运行；真实浏览器/真机走查与 R2/R3 的动态验证仍待安排。