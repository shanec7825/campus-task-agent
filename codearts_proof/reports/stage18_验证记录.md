# stage18 本地验证记录（T4 / T8）

- 基线提交：`af43dc7`（fix(test): 可靠性回归适配 Cookie 会话与组织归属）
- 被验证对象：工作树未提交改动——T1/T2/T3：`backend/app/services/authz.py`、`tests/backend/test_activity_workflow.py`、`frontend/src/views/ActivityDetail.vue`、`frontend/src/views/PublishPage.vue`、`frontend/src/components/Publish/ManualForm.vue`、`frontend/src/types/models.ts`、`frontend/src/views/TaskDetail.vue`；T7：`backend/app/services/authz.py`（`resolve_task_org`）、`tests/backend/test_activity_workflow.py`（新增 3 用例）、`.github/workflows/ci.yml`、`docs/CI.md`
- 权威契约：`.codeartsdoer/plans/aiw00-activity-flow/design.md` §2.2（C-AUTHZ-VISIBILITY@1 / C-FE-ACTIVITY-PUBLISH@1 / C-FE-TASK-CONFIRM@1 / C-ACTIVITY-PUBLISH-AUTH@1）
- 平台：win32 / git-bash；Python 3.12.10（无 `backend/.venv`，统一用 `PYTHON_BIN="$(command -v python)"`）；Node 25.2.1
- 验证时间：2026-11-13 23:05–23:10（首轮）；23:11–23:14（T2 修复后复跑）；2026-11-14（T8：T7 授权修复复跑 + 变异验证）

## 0. 结论

**PASS（T4 + T8 终态；首轮 FAIL 记录保留在 §3）**

首轮验证发现 1 项真实门禁失败（FAIL-1：`check_contracts.py` ⑰ `C-VOICEUI@4 §A`）。T2 按建议做最小修复后复跑 `tests/frontend/run_all.sh`：退出码 0，构建门禁 4/4 PASS、静态契约 25/25 PASS、语音切片单测 21 PASS / 0 FAIL。后端两套行为回归与后端全量脚本在本轮与复跑中均通过（断言 1412 条），因此当前工作树满足 R1/R2/R3 与本轮三个契约，且既有前端门禁恢复绿色。

T8 针对 T7 的 R4 授权修复复跑：`test_activity_workflow.py` 8 passed（新增 3 用例）、`test_auth_org_permissions.py` 47 passed、`test_activity_hierarchy.py` 13 passed、CI 配置的合并命令 68 passed、`tests/backend/run_all.sh` exit 0（1412 条 PASS）；两轮变异验证证明新增用例对「缺失 4030 校验」与「先写库后拒绝」均会失败。**T8 结论 PASS**，T7 的授权缺口已关闭且回归真实有效。

## 1. 实际命令与结果

| # | 命令（工作目录＝项目根） | 退出码 | 断言/结果 | 日志 |
| --- | --- | --- | --- | --- |
| 1 | `python -m pytest tests/backend/test_activity_workflow.py -q` | 0 | `5 passed in 2.65s` | 终端输出 |
| 2 | `python -m pytest tests/backend/test_activity_hierarchy.py -q` | 0 | `13 passed in 3.59s` | 终端输出 |
| 3 | `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | 0 | 6 个验证脚本全过，`PASS:` 断言 1412 条，0 失败；末尾 `T5 全部主验证通过` | `/tmp/t4_backend.log` |
| 4 | `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`（首轮） | 2 | 构建门禁 4/4 PASS；`check_contracts.py` `RESULT: 24 passed, 1 failed`；步骤 3 未执行 | `/tmp/t4_frontend.log` |
| 5 | `python -m pytest tests/backend/test_activity_workflow.py -q`（复跑） | 0 | `5 passed in 2.81s` | 终端输出 |
| 6 | `python -m pytest tests/backend/test_activity_hierarchy.py -q`（复跑） | 0 | `13 passed in 3.89s` | 终端输出 |
| 7 | `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`（T2 修复后复跑） | 0 | 构建 4/4 PASS；`check_contracts.py` `RESULT: 25 passed, 0 failed`（⑰ PASS）；语音单测 21 PASS / 0 FAIL | `/tmp/t4_frontend_rerun.log` |

### 1.1 隔离性（未触碰真实库）

- 两个 pytest 文件在 `import app` 之前自行设置 `DATABASE_PATH=<tempfile.mkdtemp>/…db`、`MAAS_MOCK=1`、`MAAS_API_KEY=""`、`RUN_SCHEDULER=0`（`test_activity_workflow.py:41-48`、`test_activity_hierarchy.py` 同口径），未读写 `backend/campus.db`。
- `tests/backend/run_all.sh` 自建 `mktemp -d` 临时库（端口 8040/8041），清理输出：`INFO: 已停止 8040/8041 后端进程；临时数据库与日志已删除`。
- 验证后 `git status --short` 无新增中间产物（`.pytest_cache` 为工具缓存且被忽略；无 `.coverage`）。

### 1.2 后端全量脚本分步结果（`/tmp/t4_backend.log`）

| 步骤 | 行号区间 | 结果 |
| --- | --- | --- |
| ① 建表与数据形态（9 表） | 9–41 | 通过 |
| ② 报名审批矩阵（R16-AC1~AC16） | 42–455 | 通过 |
| ③ REST 全流程与错误码矩阵 | 456–714 | 通过 |
| ④ Agent mock 规则与知识库 | 715–948 | 通过 |
| ⑤ 增量解析 / 纯值 / 追溯红线 | 949–1314 | 通过 |
| ⑥ 真 SSE 推送与三级催办 | 1315–1467 | 通过 |
| 观测：KB 不过滤模式（不计入判据） | 1468–1500 | 通过（退出码 0） |

### 1.3 前端门禁分步结果

首轮（`/tmp/t4_frontend.log`，exit 2）：

| 步骤 | 结果 |
| --- | --- |
| [1/4] `npm run typecheck`（vue-tsc --noEmit） | PASS（无类型错误） |
| [2/4] `npm run build`（vite build，1729 modules） | PASS |
| [3/4] `dist/index.html` 存在且非空 | PASS（1186 字节） |
| [4/4] `src` 内无 `: any` / `as any` | PASS |
| 步骤 2/2 `check_contracts.py` | **FAIL**：24 passed, 1 failed（⑰） |
| 步骤 3/3 语音切片单测 | 未执行（步骤 2 失败退出） |

复跑（`/tmp/t4_frontend_rerun.log`，exit 0）：

| 步骤 | 结果 |
| --- | --- |
| [1/4]–[4/4] 构建门禁 | `RESULT: 4 passed, 0 failed` |
| 步骤 2/2 `check_contracts.py` | `RESULT: 25 passed, 0 failed`（⑰ PASS） |
| 步骤 3/3 语音切片单测 | `21 PASS / 0 FAIL`（tsc 编译 + node 断言） |
| 结尾 | `# ALL PASS：构建门禁 + 静态契约对齐 + 语音算法单测均通过` |

## 2. 契约逐项核对

### 2.1 C-AUTHZ-VISIBILITY@1（R1）— 全部通过

| 子项 | 证据 | 判定 |
| --- | --- | --- |
| `_self_visible_condition` 在既有 `or_(...)` 新增 `exists().where(Activity.id == task.activity_id, Activity.owner_id == user.id)` | `backend/app/services/authz.py:74-87` | PASS |
| `task.activity_id IS NULL` 时该条件为假（独立任务不获可见性） | 同上；用例「活动负责人读独立任务仍 4040」通过 | PASS |
| 对外签名不变（`can_view_task` / `require_task_view` / `visible_task_filter`） | `authz.py:91`、`:104`；diff 未改签名 | PASS |
| `visible_task_filter` 以 `_self_visible_condition` 为递归 CTE 锚点，后代继承不变 | `authz.py:97-101` | PASS |
| 负责人可读他人活动下任务详情（200 + 载荷） | `pytest test_activity_workflow.py` 用例 1 通过 | PASS |
| 活动树包含他人第一层任务及子任务 | 用例 3 通过 | PASS |
| 负责人验收可达（4090 而非 4040） | 用例 4 通过 | PASS |
| 无关用户仍 4040 | 用例 5 通过 | PASS |
| `can_manage_task` 分支未动 | diff 仅 `_self_visible_condition` 新增 7 行 | PASS |

### 2.2 C-FE-ACTIVITY-PUBLISH@1（R2）— 静态核对通过，端到端未动态验证

| 子项 | 证据 | 判定 |
| --- | --- | --- |
| `ActivityDetail.vue` 新增「在此活动下新建任务」，`router.push({name:'publish', query:{activity}})` | `ActivityDetail.vue:85-88`、`:185` | PASS |
| 仅当 `activity.value !== null` 渲染 | 按钮位于 `v-else-if="activity"` 分支内（`:134`–`:189`） | PASS |
| `PublishPage.vue` 解析 `route.query.activity` 为正整数（`Number.parseInt` + `isFinite` + `>0`），无效/缺省为 `null` | `PublishPage.vue:29-34` | PASS |
| `activityId !== null` 时默认手动模式 | `PublishPage.vue:39`（字面量初值 `'ai'`）→ `:42` `if (activityId.value !== null) activeTab.value = 'manual'` | PASS（首轮三元初值曾被门禁判 FAIL，见 §3/§3.1） |
| `ElAlert type="info" :closable="false"` 展示「任务将归属活动 #<id>」 | `PublishPage.vue:102-109` | PASS |
| `<ManualForm :activity-id="activityId" />` 传入归属 | `PublishPage.vue:120` | PASS |
| `ManualForm` props `activityId?: number \| null` 默认 `null`；提交时仅在正整数时加入 `activity_id` | `ManualForm.vue:32`、`:203`、`:220` | PASS |
| `TaskCreatePayload` 增加 `activity_id?: number \| null`，其余字段未改 | `models.ts:283-285` | PASS |
| 无权限仍由后端 4030/4001 提示、前端不回退 | `ManualForm.vue` 沿用既有 `errorMessage` 分支（未新增旁路） | PASS（沿用既有路径，静态核对） |

### 2.3 C-FE-TASK-CONFIRM@1（R3）— 静态核对通过

| 子项 | 证据 | 判定 |
| --- | --- | --- |
| `awaitingOwnerConfirm` = `subtasks.length > 0 && every(status==='verified') && task.status !== 'verified'` | `TaskDetail.vue:204-210` | PASS |
| 展示位置：「子任务与依赖」卡片头部下方 | `TaskDetail.vue:899`（卡片标题 `:895`，`SubTaskTree` `:900`） | PASS |
| 固定文案「下层工作已完成，待负责人确认」 | `TaskDetail.vue:899` | PASS |
| 仅用现有令牌，无新增 hex、无 12px | `.confirm-hint` 用 `var(--app-font-aux-lg)`(14px) + `var(--el-color-warning)`（`TaskDetail.vue:1225-1231`）；`git diff` 新增行无 `#hex`、无 `font-size: 12px` | PASS |
| 不改状态、不加 API、不影响按钮可用性 | diff 仅新增 computed + 一行 `<p v-if>` + 样式；`subtasks` 仍取 `task.children`（`:202`） | PASS |

## 3. 失败项（首轮历史记录，已修复；不复写历史结论）

### FAIL-1（首轮，已修复）：前端静态契约门禁 ⑰ `C-VOICEUI@4 §A 发布页默认 AI 智能模式`

- 命令：`PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`
- 退出码：2（`[run_all] 步骤 2/2 失败：静态契约对齐未通过（check_contracts.py 退出码 1）`）
- 证据：`/tmp/t4_frontend.log:123-125`
  ```
  [17/25] FAIL  ⑰ C-VOICEUI@4 §A 发布页默认 AI 智能模式 + 双面板 v-show
          views/PublishPage.vue:39 `activeTab` 初值不是 `ref<PublishMode>('ai')`（R21-AC1 默认智能模式）
  ```
- 判据来源：`tests/frontend/check_contracts.py:1289-1293`（正则 `ref<PublishMode>\(\s*'ai'\s*\)` 必须命中）与 `:1294-1300`（禁止 `ref<PublishMode>('manual')`）
- 代码现状：`frontend/src/views/PublishPage.vue:39` 为 `const activeTab = ref<PublishMode>(activityId.value !== null ? 'manual' : 'ai')`，不满足字面量断言。
- 判定：**真实门禁失败**。不是检查脚本误读——规则要求初值字面量为 `'ai'`，而当轮 R2 要求「由活动入口进入时默认手动模式」。两者可同时满足：保留 `const activeTab = ref<PublishMode>('ai')` 初值，随后在 `parseActivityId` 结果非空时改为 `activeTab.value = 'manual'`（不改变任何对外行为）。当前实现选择三元初值，导致既有门禁与 CI 变红。
- 影响：`tests/frontend/run_all.sh` 退出码 2 → CI 前端门禁失败；步骤 3 语音单测因此未运行。功能行为本身（普通入口仍为 AI 模式、活动入口为手动模式）未回归。

### 3.1 修复后复跑（T2 最小修复）

- 修复内容（`frontend/src/views/PublishPage.vue`，其他文件未改）：
  - `:39` `const activeTab = ref<PublishMode>('ai')`（恢复门禁要求的字面量初值）；
  - `:41-42` 保留「默认智能模式，手动为兜底」注释，`if (activityId.value !== null) activeTab.value = 'manual'`（活动入口在 setup 内切到手动模式，对外行为与 R2 一致）；
  - `git diff --stat` 复核：仅 `PublishPage.vue` 由 +24/-1 变为 +25/-1，其余 8 个文件改动量与首轮一致。
- 复跑命令与结果：
  - `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh` → **exit 0**
    - `RESULT: 4 passed, 0 failed`（[1/4] typecheck、[2/4] vite build、[3/4] dist/index.html、[4/4] 无 any）
    - `check_contracts.py` `RESULT: 25 passed, 0 failed`，`[17/25] PASS ⑰ C-VOICEUI@4 §A`
    - 步骤 3/3 语音切片单测：`check_voice_slicer.cjs：21 PASS / 0 FAIL（7 切片 + 8 重吐裁剪 + 5 常量 + 1 旧名零命中）`
    - 末尾 `# ALL PASS：构建门禁 + 静态契约对齐 + 语音算法单测均通过`
  - 后端未受该修复影响，仍单独复跑：`test_activity_workflow.py` 5 passed、`test_activity_hierarchy.py` 13 passed。
- 判定：FAIL-1 已关闭，无新增失败项。

## 4. 未验证范围

1. **R2 端到端动态链路未验证**：仓库无前端 e2e/组件测试基础设施，`ActivityDetail → publish?activity=N → POST /api/tasks {activity_id}` 的浏览器级行为只做了静态代码核对；后端 `activity_id` 落库与层级/组织校验由 `tests/backend/test_activity_hierarchy.py`（13 passed）间接覆盖。
2. **R3 渲染行为未动态验证**：`awaitingOwnerConfirm` 为纯派生 computed，无组件单测环境；仅核对表达式、展示位置与样式令牌，未在浏览器中构造「全部子任务 verified 且父任务未验收」场景。
3. **语音切片单测**：首轮因步骤 2 中止未执行，复跑已执行并通过（21 PASS / 0 FAIL）。
4. **真实模型 / 真机 / 移动端视口未验证**：本轮 `MAAS_MOCK=1`，无真机浏览器与移动端截图证据。
5. **真实库与历史数据**：按计划使用临时隔离库，未对 `backend/campus.db` 做任何检查（本轮范围外，也符合「无保留业务数据」的既定决定）。
6. **合并 pytest 运行在本执行沙箱下不稳定（环境限制，非代码缺陷）**：把两个后端测试文件放在同一进程执行（`pytest test_activity_workflow.py test_activity_hierarchy.py`）时，出现过 `1 failed, 17 errors`；错误全部为 setup 阶段 `OSError: [WinError 10051]`，栈指向 `socket.socketpair()` 的 TCP 回退分支，并打印 `Sandbox Network Error: hit restricted [127.0.0.1:<随机端口>]`；另一次同样的合并运行得到 `18 passed`。单文件独立运行连续多次稳定通过，`tests/backend/run_all.sh`（固定端口 8040/8041 的真实 HTTP）也通过，故判定为沙箱拦截随机回环端口造成的间歇性环境问题，不影响本轮四类入口的结论；未在无沙箱环境重跑合并方式。

## 5. 复现步骤

```bash
# 工作目录：项目根
python -m pytest tests/backend/test_activity_workflow.py -q      # T4 5 passed；T8（含 T7 新增 3 用例）8 passed
python -m pytest tests/backend/test_activity_hierarchy.py -q     # 13 passed
PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh   # exit 0，1412 条 PASS
PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh  # 修复前 exit 2（⑰ FAIL）；修复后 exit 0，25/25 + 21 PASS
python -m pytest tests/backend/test_auth_org_permissions.py -q    # T8：47 passed
python -m pytest tests/backend/test_auth_org_permissions.py tests/backend/test_activity_hierarchy.py tests/backend/test_activity_workflow.py -q  # T8：CI 命令 68 passed
```

## 6. T8：T7 授权修复复跑与回归敏感度验证

### 6.1 本轮被验证代码

| 文件 | 改动 |
| --- | --- |
| `backend/app/services/authz.py:195-196` | `resolve_task_org` 在 `elif activity is not None` 分支新增：`activity.org_id is None` 且 `int(activity.owner_id) != int(user.id)` → `ApiError(4030, "无权在该活动下创建事务", 403)`；未改 `parent is not None` 分支与组织内活动既有校验 |
| `tests/backend/test_activity_workflow.py:495-601` | 新增 3 用例：`test_non_owner_cannot_publish_under_orgless_activity`、`test_activity_owner_can_publish_under_own_orgless_activity`、`test_patch_into_others_orgless_activity_forbidden` |
| `.github/workflows/ci.yml:40-41`、`docs/CI.md:21` | `backend-reliability` job 的行为套件命令加入 `tests/backend/test_activity_workflow.py`，文档同步 |

### 6.2 复跑命令与结果（同一隔离规则：测试文件在 import app 前设临时 `DATABASE_PATH` + `MAAS_MOCK=1` + `RUN_SCHEDULER=0`）

| # | 命令（工作目录＝项目根） | 退出码 | 结果 | 日志 |
| --- | --- | --- | --- | --- |
| 1 | `python -m pytest tests/backend/test_activity_workflow.py -q` | 0 | `8 passed in 3.08s`（T4 时为 5 passed，+3 即新增用例） | 终端输出 |
| 2 | `python -m pytest tests/backend/test_auth_org_permissions.py -q` | 0 | `47 passed in 15.03s` | 终端输出 |
| 3 | `python -m pytest tests/backend/test_activity_hierarchy.py -q` | 0 | `13 passed in 3.74s` | 终端输出 |
| 4 | `python -m pytest tests/backend/test_auth_org_permissions.py tests/backend/test_activity_hierarchy.py tests/backend/test_activity_workflow.py -q`（CI 配置原文） | 0 | `68 passed in 17.85s`（47+13+8） | `/tmp/t8_ci_cmd.log` |
| 5 | `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | 0 | 6 步全过，`PASS:` 断言 1412 条，末尾 `T5 全部主验证通过` | `/tmp/t8_backend_runall.log` |

补充：CI 合并命令在 T4 曾因沙箱拦截随机回环端口出现 `WinError 10051` 间歇失败（§4 第 6 条）；本轮同一命令一次通过（68 passed），与该环境归因一致，不构成本轮失败项。

### 6.3 契约 C-ACTIVITY-PUBLISH-AUTH@1 覆盖核对（读用例 + 真实 HTTP 断言）

| 契约要求 | 用例与断言 | 判定 |
| --- | --- | --- |
| 非负责人向无组织活动建任务 → 4030 + HTTP 403 | `test_non_owner_cannot_publish_under_orgless_activity:498-507`：`code=4030`、`status=403` | PASS |
| 文案逐字「无权在该活动下创建事务」 | 同用例 `:508-510` | PASS |
| 显式带 `org_id` 不能绕过 | 同用例 `:513-522` | PASS |
| 授权失败不写库 | 同用例 `:524-525`：`GET /api/activities/{id}` 的 `tasks == []` | PASS |
| 负责人本人向自己的无组织活动发布成功 | `test_activity_owner_can_publish_under_own_orgless_activity:528-547`：任务 `activity_id` 落库、`org_id is None`、活动树包含该任务 | PASS |
| PATCH 移入他人无组织活动 → 4030，且既有任务字段不被改写 | `test_patch_into_others_orgless_activity_forbidden:550-601`：先绕过「活动不存在」防护构造可见任务，再 `PATCH {activity_id}` 得 4030，随后 `GET` 断言 `activity_id is None`（PATCH body 仅含该字段，其它字段本就未提交） | PASS |
| `parent is not None` 分支与组织内活动行为不变 | `git diff` 仅新增 `:195-196` 两行；`test_activity_hierarchy.py` 13 passed、`test_auth_org_permissions.py` 47 passed | PASS |

### 6.4 回归敏感度验证（变异测试，未改仓库实现）

在 `tempfile.mkdtemp()` 副本中复制 `backend/` 与测试文件（不改工作树），施加两种变异后运行同一测试：

| 变异 | 结果 | 说明 |
| --- | --- | --- |
| M1：删除 `authz.py:195-196` 的 4030 校验 | exit 1，`2 failed, 6 passed`；失败项 `test_non_owner_cannot_publish_under_orgless_activity`、`test_patch_into_others_orgless_activity_forbidden` | 证明新增用例能捕获「授权缺口回归」；负责人成功用例与 5 个可见性用例不受影响，说明用例边界正确 |
| M2：保留 4030 抛错但先 `db.commit()` 一条任务（模拟先写后拒） | exit 1，同上 2 个用例失败；失败信息 `授权失败不得改写任务活动归属（实际 7）` | 证明「不写库」断言是有效的黑盒检查，不是摆设 |

变异副本已删除，工作树未受影响（`git status --short` 复核无新增文件）。

### 6.5 CI 配置核对

- YAML 可解析：`python -c "yaml.safe_load(...)"` → `YAML_OK jobs= ['backend-reliability', 'backend-integration', 'frontend']`。
- `backend-reliability` job 的两个 pytest 步骤：`test_reliability.py -q`，以及 `test_auth_org_permissions.py test_activity_hierarchy.py test_activity_workflow.py -q`（`.github/workflows/ci.yml:41`）。
- `docs/CI.md:21` 的本地等价命令与 workflow 完全一致；文档表格描述同步补充「活动工作流（负责人可见性、无组织活动发布授权）」。
- 未修改 workflow 权限、触发条件或其它步骤。

### 6.6 T8 未验证范围

1. **CI 实跑未发生**：仅本地解析 YAML 与执行同一条命令，未推送触发 GitHub Actions，Ubuntu/Windows runner 上的真实结果未验证。
2. **组织内活动与多组织成员组合场景**：由既有 `test_auth_org_permissions.py`（47 passed）与 `test_activity_hierarchy.py`（13 passed）覆盖，未针对「活动 `org_id` 非空但调用者是外组织 admin」另造新用例（既有套件已有跨组织 4030/4001 断言）。
3. **PATCH 其它字段的 no-write**：仅验证 `activity_id` 未被改写（该 PATCH body 只含此字段），未逐一断言 title/status 等字段。
4. **沙箱环境限制**：合并 pytest 运行仍受 §4 第 6 条记录的随机回环端口拦截影响，本轮一次通过，未在无沙箱环境复验。