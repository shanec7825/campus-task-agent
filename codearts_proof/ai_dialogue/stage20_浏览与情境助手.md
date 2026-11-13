# stage20 浏览与情境助手（AIW-02）

> 日期：2026-11-14。状态：实现完成、本地自动测试通过、首轮独立审查已执行并修复 4/5 项 Important；浏览器端到端仅部分验证；提交/推送/CI 待回填。
> 本文件只记录真实发生的事项；未执行的项目明确写「未验证」或「未执行」。

## 1. 需求来源与授权

- 来源：用户本轮定时阶段开发指令（原文归档 `prompts/agent_team_启动指令/2026-11-14_stage20_浏览与情境助手_启动指令.md`）；本地总计划 `ai-workbench/roadmap.md` 的 AIW-02「浏览与情境助手」。
- 授权：已确认范围内的阶段开发、必要修复、测试、独立审查与记录；提交、推送、对应 CI 跟踪按本轮指令第七条执行；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 非目标：受控业务动作、AI 额度、语音原生、多前置依赖图、成果上传与自动验收。

## 2. 开工基线

- 分支：`main`；HEAD `9ad625f725d8667f4f86cab4201708d224415a95`（stage19 文档回填）。
- 工作区：`git status --short` 为空，无既有未提交改动、无 stash；未发现其他会话写入者。
- 上一阶段 AIW-01 已提交 `d132f15` 并推送，CI run 43459560555 四个 job success。
- 本地计划新增 `aiw02-browse-context/{design,task}.md`（Git 忽略，不提交）。

## 3. 决策与范围

- 活动范围新增 `scope=all|mine` 查询参数，不新增路由/表；「我的任务」条件收敛到 `authz.my_task_condition`，活动与任务共用。
- 大厅任务区合并活动下第一层任务与独立任务；子任务不在大厅重复铺满；任务卡显示所属活动名（前端映射，不新增后端字段）。
- 悬浮预览只使用已加载数据，200ms、精确指针设备、Esc、焦点可开；触摸设备不注册。
- 三种 Agent 形态共用新的 `aiChat` store；问答请求契约不变，当前活动/任务只作界面标签，不进入模型上下文。
- 手机抽屉补全文字导航，保留既有底部四项导航。

## 4. 实际变更

后端：

- `backend/app/services/authz.py`：新增 `my_task_condition` 与 `APPROVED_STATUS`，`__all__` 同步。
- `backend/app/routers/tasks.py`：`scope=mine` 复用 `my_task_condition`，删除不再使用的 `_my_participating_task_ids` 与 `or_` 导入。
- `backend/app/routers/activities.py`：新增 `scope` 参数、`_mine_activity_condition`；可见条件与「我的活动」复用同一个 `visible_task_filter` CTE，避免同名 CTE 冲突。
- `tests/backend/test_aiw02_activity_scope.py`：新增 6 用例，隔离临时库。
- `.github/workflows/ci.yml`：backend-reliability 增加 `test_aiw02_activity_scope.py` step；`python -c "import yaml..."` 解析通过。

前端：

- `frontend/src/api/activities.ts`：支持可选 `scope`。
- `frontend/src/stores/aiChat.ts`：新增 AI 会话共享 store，含失败边界与登出 epoch 拦截。
- `frontend/src/components/ai/AgentDock.vue`：长条 + 微展开 + 完整页入口。
- `frontend/src/components/common/HoverPeek.vue`：200ms 悬浮预览、Esc、焦点、触摸禁用、面板限高。
- `frontend/src/components/task/TaskCard.vue`：可选 `activityTitle`。
- `frontend/src/views/TaskHall.vue`：任务区合并活动下任务、活动 scope、网格、预览、筛选与滚动恢复、请求序号防竞态。
- `frontend/src/views/AiConsole.vue`：改用 `aiChat` store，通知卡与 mock 提示保留。
- `frontend/src/views/ActivityDetail.vue`、`TaskDetail.vue`：底部接入 `AgentDock`。
- `frontend/src/layouts/AppLayout.vue`：手机菜单按钮与左侧抽屉；退出时重置 AI 会话与大厅视图缓存。

## 5. 真实问题与处置

| 编号 | 现象 | 根因与处置 | 状态 |
|---|---|---|---|
| S20-I01 | 新增活动范围测试首次运行 2 failed：`Multiple, unrelated CTEs found with the same name: 'visible_task_ids'` | 同一查询内 `_visible_activity_condition` 与 `_mine_activity_condition` 各创建一次递归 CTE；改为在 `list_activities` 创建一次并传入两个条件，复用同一 CTE 对象 | 已修复，6 passed |
| S20-I02 | 新增测试第二次运行 import 失败：`IndentationError` | 编辑时重复插入 `_mine_activity_condition` 签名，旧签名空函数体；合并为单一定义 | 已修复 |
| S20-I03 | 浏览器 MCP 同消息重复调用，出现 `element is not stable` / `element was detached` | 同一条消息同时使用 `tool_call` 与直接工具名通道；按约定停止后续 MCP 交互 | 已停止，未再重试 |
| S20-I04 | 单次浏览器脚本 strict mode 多匹配：`我的任务与活动` 同时匹配筛选按钮与「当前筛选」文本 | 脚本选择器不够精确；未继续重跑，返回位置/AgentDock/抽屉保持未验证 | 未修复（验证脚本问题，非产品缺陷） |
| S20-I05 | 首轮独立审查 5 项 Important：CI 未接入、刷新后滚动未实现、留痕未完成、筛选竞态、端到端未验收 | 已接入 CI、scroll 节流 + beforeunload、requestId、完成记录；端到端未完成项如实保留 | 4 项已修复，1 项未关闭 |
| S20-I07 | 第二轮审查指出返回恢复条件 `window.scrollY === 0` 在详情返回时通常不成立，且加载期保护无法区分浏览器保留位置与用户主动滚动 | 去掉 `scrollY === 0` 条件；用 `wheel`/`touchmove` 标记加载期间用户主动滚动，只有未主动滚动时才恢复旧位置；卸载时递增 `loadSeq` | 已修复（代码逻辑，浏览器未复验） |
| S20-I08 | 第二轮审查指出修复后前端门禁仍引用修复前日志 | 修复后重新执行 `npm run typecheck`、`npm run build` 与 `tests/frontend/run_all.sh`，以 `typecheck-4.log`、`build-4.log`、`frontend-runall-after-review.log` 为准 | 已修复 |
| S20-I09 | 第二轮审查指出验证报告只指向 Git 忽略目录 | 新增 `codearts_proof/reports/stage20_验证记录.md` 与 `codearts_proof/debug/case4_活动范围递归CTE同名冲突.md`，并登记 debug 索引 | 已修复 |
| S20-I10 | 修复后复跑后端 `run_all.sh` 失败：8040 健康检查超时 | 单独启动定位 `tasks.py:332 SyntaxError: expected 'except' or 'finally' block`；空行整理时误删 `except` 缩进；修复缩进后 `py_compile` EXIT=0，`run_all` **1412 PASS** | 已修复 |
| S20-I11 | 第三轮审查 2 Important：加载期离开页面后仍可能对新页面 `scrollTo`；后端聚合门禁早于最后一次后端改动 | 增加 `disposed` 标志与键盘翻页主动滚动标记；修复语法后复跑 `run_all` 1412 PASS，最终 `test_aiw02` 6 passed | 已修复；未开第四轮（三轮上限） |
| S20-I06 | 审查 Suggestion：登出时异步 restore 可能把新 promise 置空；HoverPeek 面板可能溢出；AgentDock 缺 aria-controls | 增加 restore finally token 守卫、面板 `max-height/overflow`、`aria-controls` | 已修复 |

## 6. 验证（真实命令与结果）

后端（工作目录项目根）：

- `python -m pytest tests/backend/test_aiw02_activity_scope.py -q`：首次失败（S20-I01），修复后 **6 passed in 2.80s**；审查修复后回归 **6 passed in 2.83s**；最终代码回归 **6 passed in 2.56s**（`outputs/aiw02/pytest-aiw02-final.log`）。
- `test_activity_hierarchy.py`：**13 passed in 4.66s**（`outputs/aiw02/pytest-activity-hierarchy.log`）。
- `test_activity_workflow.py`：**8 passed in 3.30s**（`outputs/aiw02/pytest-activity-workflow.log`）。
- `test_auth_org_permissions.py`：**47 passed in 15.51s**（`outputs/aiw02/pytest-auth.log`）。
- `test_reliability.py`：**11 passed in 6.45s**（`outputs/aiw02/pytest-reliability.log`）。
- `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`：第一次修复后复跑因 `tasks.py` 语法错误失败（S20-I10）；修复后 **EXIT=0**，`verify_tables` 30、报名 410、E2E 255、agent mock 229、增量 358、SSE 105、KB 观测 25，合计 **1412 条 PASS**（`outputs/aiw02/backend-runall-final.log`）。

前端（工作目录 `frontend`）：

- `npm run typecheck`：**EXIT=0**（`typecheck-4.log`，中间轮次；最终以 `run_all` 内的 typecheck 为准）。
- `npm run build`：**EXIT=0**（`build-4.log`，中间轮次；最终以 `run_all` 内的构建为准）。
- `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`：最终代码 **EXIT=0**（构建 4/4、契约 25/25、语音 21/21，`frontend-runall-final.log`）。
- `python tests/frontend/check_contracts.py`：**25 passed / 0 failed**（`contracts-3.log`，中间轮次；最终以 `run_all` 内的契约为准）。
- 脱敏归档报告：[stage20_验证记录](../reports/stage20_验证记录.md)；排错实例：[case4](../debug/case4_活动范围递归CTE同名冲突.md)。

浏览器（8000 同源 dist + `outputs/phase2/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：

- `/ai`：AI 默认入口、通知卡、历史 mock 会话与来源可见。
- `/tasks`：摘要「共 1 个活动 · 1 个活动任务 · 0 个独立任务」；活动下任务「外语角志愿者招募」出现在任务区并显示「所属活动 · 外语角筹备」。
- 悬浮预览：100ms 时面板 0 个；320ms 时 1 个（活动详情文本）；移开 80ms 后 0 个。
- **未验证**：返回位置、AgentDock 三形态、手机抽屉、深色主题、真实模型、阶段截图（`mobile-drawer.png`/`desktop-hall.png` 未产出）。

## 7. 独立审查

- 首轮独立 Review Agent（general，只读）：结论「需修复」，**0 Critical / 5 Important / 8 Suggestions**；Suggestion 中已处置 3 项（S20-I06）。
- 第二轮独立 Review Agent（general，只读）：结论「仍需修复」，**0 Critical / 3 Important**（返回恢复条件、修复后门禁旧日志、报告只指向忽略目录）。三项已处置（S20-I07/I08/I09）。
- 第三轮独立 Review Agent（general，只读）：结论「仍需修复」，**0 Critical / 2 Important**（加载期离开页面后仍可能新页面 `scrollTo`；后端聚合门禁早于最后后端改动）。两项已处置（S20-I10/I11）并完成最终回归；按项目「最多三轮」限制未再开第四轮，最后修复未经独立复核。
- 端到端未完成项见第 8 节；不把代码逻辑修复写成浏览器已验证。

## 8. 未完成与待回填

- 浏览器端到端未完成项：返回保位置、AgentDock 长条/微展开/完整页、390×844 抽屉、深色主题、真实模型。
- 提交/推送/CI：未执行；完成后回填提交 SHA、CI run 与结论。
- 截图：未产出；不以静态检查替代。