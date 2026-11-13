# stage20 验证记录（脱敏归档）

> 阶段：AIW-02「浏览与情境助手」。日期：2026-11-14。
> 本报告只摘录实际执行的命令、退出码与结果；原始日志保留在本地忽略目录 `outputs/aiw02/`，不提交。

## 1. 环境

- 工作目录：项目根 `D:\Users\Lenovo\Downloads\campus-task-agent-delivery\campus-task-agent`。
- Windows Git Bash；Python 3.12.10；Node 25.2.1 / npm 11.6.2（环境启动值，未重复探测）。
- 后端测试使用各测试文件自建的 `tempfile.mkdtemp` 隔离 SQLite，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`，不触碰 `backend/campus.db`。
- 前后端测试均未使用真实模型；浏览器为 Playwright MCP 对 8000 同源 dist 的模拟视口。

## 2. 后端

| 命令 | 退出码 | 结果 | 本地日志 |
|---|---|---|---|
| `python -m pytest tests/backend/test_aiw02_activity_scope.py -q` | 0 | 6 passed（最终代码回归） | `outputs/aiw02/pytest-aiw02-final.log` |
| `python -m pytest tests/backend/test_auth_org_permissions.py tests/backend/test_activity_hierarchy.py tests/backend/test_activity_workflow.py -q` | 0 | 68 passed | `outputs/aiw02/pytest-auth-activity-after-review.log` |
| `python -m pytest tests/backend/test_reliability.py -q` | 0 | 11 passed | `outputs/aiw02/pytest-reliability-after-review.log` |
| `python -m py_compile backend/app/routers/tasks.py backend/app/routers/activities.py backend/app/services/authz.py` | 0 | 语法检查通过 | 终端输出 |
| `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | 0 | 1412 PASS（verify_tables 30、报名 410、E2E 255、agent mock 229、增量 358、SSE 105、KB 观测 25） | `outputs/aiw02/backend-runall-final.log` |

首次修复后复跑聚合门禁时，8040 健康检查超时；单独启动定位为 `backend/app/routers/tasks.py:332` 的 `SyntaxError`（空行整理误删 `except` 缩进）。修复缩进后 `py_compile` EXIT=0，再次运行 `run_all` 得到上述 1412 PASS；不以失败前的旧日志作为最终证据。

首次运行新增测试时出现 2 failed：`Multiple, unrelated CTEs found with the same name: 'visible_task_ids'`；修复见 `debug/case4_活动范围递归CTE同名冲突.md`。

## 3. 前端

| 命令 | 退出码 | 结果 | 本地日志 |
|---|---|---|---|
| `npm run typecheck` | 0 | 无类型错误（中间轮次） | `outputs/aiw02/typecheck-4.log` |
| `npm run build` | 0 | `✓ built`（中间轮次） | `outputs/aiw02/build-4.log` |
| `python tests/frontend/check_contracts.py` | 0 | 25 passed / 0 failed（中间轮次） | `outputs/aiw02/contracts-3.log` |
| `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh` | 0 | 最终代码：构建 4/4、契约 25/25、语音 21/21 | `outputs/aiw02/frontend-runall-final.log` |

最终代码以 `frontend-runall-final.log` 为准；`typecheck-4`、`build-4`、`contracts-3` 是中间轮次，不能单独作为最终修复证据。

修复后已重新执行 typecheck、build 与完整 `run_all.sh`；不再以修复前日志作为本轮通过依据。

## 4. 浏览器（模拟视口）

- 环境：`outputs/phase2/serve_backend.py` 在 8000 端口托管最新 `frontend/dist`，隔离演示库 `outputs/phase2/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`。
- 首轮已验证：`/ai` 默认入口、通知卡、历史 mock 会话与来源；`/tasks` 摘要显示「1 个活动 · 1 个活动任务 · 0 个独立任务」，活动下任务「外语角志愿者招募」出现在任务区并显示「所属活动 · 外语角筹备」；悬浮预览 100ms 时面板 0 个、320ms 时 1 个、移开 80ms 后 0 个。

### 4.1 补验收尾轮（2026-11-14，同一环境、新构建）

| 检查项 | 实测读数 |
|---|---|
| 返回位置 | 进入详情前 `cta_hall_view.scrollTop=448`；`page.goBack()` 返回 `/tasks` 后 `scrollY=448`，筛选仍为「范围：我的任务与活动」。Playwright 点击会先把按钮滚入视口，故保存值 448 是点击时位置，非脚本预设的 240 |
| AgentDock 长条 | 任务详情 `.agent-dock` 可见，上下文「任务：外语角志愿者招募」；输入草稿可写入 |
| AgentDock 微展开 | `#agent-dock-panel` 可见、历史消息 2 条；`aria-expanded` false→true |
| 完整页共享草稿 | 点击「打开完整页」进入 `/ai`，输入框保留同一草稿；标题「AI 助手」 |
| aria-controls 修复前 | 字面字符串 `expanded ? 'agent-dock-panel' : undefined` |
| aria-controls 修复后 | 收起 `null`；展开 `agent-dock-panel` 且面板 count=1、可见；再收起 `null`、panel count=0 |
| 手机抽屉 | 390×844；菜单按钮 `45.6×44`；底部四项导航保留；抽屉含完整文字导航、发布、主题、用户、退出；当前页 aria-current=page；横向 `scrollWidth=clientWidth=320`；Esc 关闭 |
| 深色主题 | `html.dark=true`、`data-theme=dark`、`--app-bg=#0f1115`、`aria-pressed=true`；再次切换恢复 light |

- 截图归档：`codearts_proof/screenshots/stage20/{desktop-hall-final,desktop-dock-expanded-final,mobile-drawer-final,mobile-drawer-dark-final}.png`。
- 未验证：真实模型、真机、悬浮预览快速划过与卡片间隙（演示库仅 1 活动 1 任务）。
- 记录：`outputs/aiw02/walkthrough.md`（本地忽略，补验原始读数）。

## 5. 提交与 CI

- 主体代码提交 `8b7f818be49d0b78c1bdc6c18f7353a5df8084ac`，已推送 `origin/main`（`9ad625f..8b7f818`，推送前 `0 0` 无分叉）。
- CI run `43466871644`：Frontend、Backend reliability（ubuntu/windows）、Backend integration 四个 job 均 **success**。
- 补验轮：`AgentDock.vue` 一行修复；提交 SHA 与对应 CI 结果待提交推送后回填。
- 未部署；docs 回填提交不改变业务代码。

## 6. 结论口径

- 自动测试：后端相关套件与前端门禁通过；属于本地真实执行结果。
- 浏览器：首轮部分验证；补验轮已覆盖返回位置、AgentDock 三形态、390×844 抽屉、深色主题并产出截图。真实模型、真机与预览间隙仍未验证。
- 真机、真实模型、部署：未验证/未执行；CI 结果在提交推送后另行回填。