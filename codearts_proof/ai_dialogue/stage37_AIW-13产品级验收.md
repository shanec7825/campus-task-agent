# 阶段 37 · AIW-13 产品级验收（可执行部分）

> 日期：2026-11-14（Asia/Shanghai）。平台：华为云码道（CodeArts）。编排 team-leader；验收脚本本地 Playwright CLI（headless Chromium）；独立审查沿用 stage35/36 两轮 team-code-reviewer。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
> 依据：`aiw13-product-acceptance/{design.md,task.md}`、`acceptance-matrix.md`（AC-01～23）、`decisions.md` D-04/D-05/D-06/D-07/D-08。

## 1. 结论

**本地实现完成，最终使用验收待条件**：可执行的视觉收口、门禁、角色/设备模拟场景已完成并通过；真机、真实模型、人工晚会链路与部署按 D-06/D-07 保持待验收。本轮未提交、未推送、无新 CI、未部署。

## 2. T13-00 最终视觉收口

在最终功能上只做有真实不一致依据的两处令牌化，未扩大重构：

- `frontend/src/components/common/UserAvatar.vue`：`avatar--xs` 字号 `11px` → `var(--app-font-aux)`，回到统一字号阶梯（18px 头像内 13px）。
- `frontend/src/layouts/AppLayout.vue`：未读徽标 `color: #fff` → `var(--el-color-white)`，移除最后一处裸十六进制色值。

其余字体/间距/图标/卡片/主题/状态样式沿用 stage14 令牌与 r4 组件；`grep` 复查前端无新增 `12px` 字号、无新增裸色值（`#default` 插槽匹配为误报，已排除）。

## 3. T13-01 范围核对

- 有效范围：R-01～R-28 中未被 D-08 取消的条目；AC-01～06、08～09、11、13～23。
- **已取消不恢复**：AC-07（整批原子发布）、AC-10（新增检查点/自动推荐）、AC-12（AI 动作分支）、AIW-11 全部新增能力。
- 本轮新增证据只覆盖 AC-01/04/09/14/15/19/20/22 的可执行断言；其余 AC 沿用 stage24～36 的历史证据并在 §6 标明，不以阶段总勾选替代。

## 4. T13-02 隔离数据库

`work/aiw14/demo.db`（复制自 AIW-09 隔离库，未被真实库污染）：

- 2 个组织（`organizations=2`）、4 条组织成员（admin/collaborator/member）、5 个可用账号 + 1 个 `legacy_unclaimed`。
- 13 条个人链接、4 个 AI 会话 / 40 条消息、2 份成果 / 2 条预审；`activity_resources=0`（本库无活动资料条目，资料检索 UI 未在本轮取证）。
- 活动 1 有 1 个父任务 + 1 个子任务；活动 3/4/5 为本组织外无组织活动，仅负责人可见——用于验证角色可见性。

## 5. T13-03 门禁与安全检查

| 入口 | 结果 |
|---|---|
| `tests/backend/test_aiw10_precheck_version.py` | 8 passed |
| `test_aiw04_resource_review.py` + `test_aiw06_acceptance.py` | 15 passed / 1 skipped |
| `tests/backend/run_all.sh` | EXIT=0（1446 PASS / 0 FAILED；不覆盖 pytest） |
| `tests/frontend/run_all.sh` | ALL PASS（构建 4/4、契约 37/37、语音 21/21） |
| `vue-tsc --noEmit` | 0 error |
| `tests/security/test_security_redline.sh` | **12 通过 / 1 失败（B5b）**：命中 `.codeartsdoer/temp/accept/*.original.log` 工具临时目录（Git 忽略、未跟踪），未放宽门禁 |

## 6. T13-04 / T13-05 场景结果

脚本：`work/aiw13/verify-aiw13.cjs`（本地忽略）；报告 `work/aiw13/aiw13-report.json`；dist 同源 8000 + 隔离库、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`；**24/24 PASS**。

| 断言组 | 结果 |
|---|---|
| 未登录 `/admin` → `/login`（AC-01） | PASS |
| 普通成员 `/admin` 不显示发布者后台并给出引导（AC-01） | PASS |
| 发布者后台可见、父子任务展开（AC-01/19/20） | PASS |
| 大厅活动/任务胶囊与两类短卡（AC-19/20） | PASS（collab 仅 1 个可见活动，按真实可见性断言） |
| 活动详情任务表 + 依赖与时间图（AC-04/20） | PASS |
| 表格任务链接应用内跳转、返回回到活动详情（AC-20） | PASS（点击 `.el-page-header__back`） |
| 搜索 → 详情并保留 `q=迎新`（AC-22） | PASS |
| 深浅主题切换、深色非白、无溢出（AC-15） | PASS |
| 390×844 `/tasks`、`/activities/1`、`/tasks/1`、`/admin` 无横向溢出（AC-15/20） | PASS（390/390）；另 Library/搜索/历史抽屉亦无溢出 |
| AI 页额度展示 `0/50，剩余 50`（AC-14 UI） | PASS |
| 预审过期「通过」禁用（AC-09 UI） | **PASS**：独立脚本 15/15，含过期标签、`通过` disabled、「请先重新预审」提示、后端 4090、390 无溢出 |
| 完整报名/提交/退回/重提/验收移动链路（T13-05） | **PASS**：独立脚本 15/15（390 报名→后台审批→进度→提交→退回→看到原因→重提→预审→验收→积分 +2→状态 verified） |
| 长标题/图谱/键盘可用（T13-05） | 部分：r4 两行截断与表格 44px 展开热区已验；搜索 Tab 焦点留在面板内已验（aux 脚本） |
| 390 搜索 / Library / 历史抽屉（T13-05） | **PASS**：aux 脚本 **11/11**（浮层打开与结果、Esc 关闭、Library 无溢出、历史抽屉条目与 Esc、Tab 焦点） |

截图：`codearts_proof/screenshots/aiw13-{admin-roles,desktop-hall,dark-hall,mobile-task,precheck-stale,mobile-precheck-stale,mobile-apply,mobile-verified}.png`。

### 6.0 补充取证脚本

- `work/aiw13/verify-ac09-stale-ui.cjs` → `ac09-stale-ui-report.json`：**15/15 PASS**（API 构造 stale + 桌面/390 UI 断言）。
- `work/aiw13/verify-mobile-chain.cjs` → `mobile-chain-report.json`：**15/15 PASS**（390 全链路）。
- `work/aiw13/verify-mobile-aux.cjs` → `mobile-aux-report.json`：**11/11 PASS**（390 搜索/Library/历史与键盘焦点）。
- 过程中发现：`submission_prechecks.resource_snapshot` 迁移只在 `init_db()`（服务 lifespan）执行，**运行中的旧服务不会自动补列**；重启隔离服务后迁移成功。属启动接线预期，不是代码缺陷，但部署/升级时需重启服务。

### 6.1 场景过程中的口径修正（非产品缺陷）

- 大厅活动卡数量按 collab 实际可见 1 个活动断言；活动 3/4/5 无组织，仅负责人可见，不能按 4 张写死。
- `el-page-header` 的返回热区是 `.el-page-header__back`，点击外层 `.el-page-header__left` 中心不触发；手动 `history.back()` 与图标点击均能回到 `/activities/1`。

## 7. T13-06 / T13-07 / T13-08 待条件

- **T13-06 真机**：D-06 未授权设备/浏览器；语音安全区、软键盘、横竖屏、弱网均未验证。
- **T13-07 真实模型**：D-06 未授权调用；AC-16 固定评测未执行，不宣称质量结论。
- **T13-08 晚会人工链路**：未做真实人工发布/报名/提交/验收与录屏；既有自动化全链路为 stage24 的 `test_aiw06_acceptance.py`（本轮 15/1 中覆盖，未重跑人工）。
- **T13-11 提交/CI/部署**：无本轮授权，未提交推送；D-07 部署/公开试用未授权。

## 8. T13-09 审查

- stage35（r4）：0 Critical / 3 Important，全部修复并复跑门禁。
- stage36（AIW-10）：0 Critical / 3 Important，全部处置；9 条 Suggestion 记录未处置。
- 本轮 AIW-13 只改 2 处令牌化样式，属低风险纯样式，未单独开第三轮审查；沿用两轮审查结论，未把自查冒充独立复审。

## 9. 限制与回退

- 回退：AIW-13 只改 2 个样式值，可逐行还原；AIW-10 新增列 `resource_snapshot` 为增量列，回退代码后旧列保留但无读取方，不影响既有数据；r4 新增组件可单独删除并恢复旧 `ActivityTaskTree`（旧组件未删除）。
- 已知未处置 Suggestion：`list_submissions` 每提交者各算 digest（N 倍开销）、资源窗口保守 false stale、`PrecheckResult` 未含 `resource_snapshot`、后台验收入口不展示 stale、预审 stale 前端禁用缺真实点击证据。
- 安全红线 B5b 为忽略目录残留，未清理工具临时目录、未改基线。

## 10. 剩余条件与下一次最短步骤

1. D-06 授权后：真机语音/安全区/键盘/横竖屏 + 固定真实模型评测。
2. 人工晚会链路：按 T13-08 真实操作并录屏，替换自动化截图口径。
3. 提交/推送/CI 需当轮授权；部署按 D-07 单独确认。
4. 建议下次接续：真机语音/安全区/键盘（D-06）与固定真实模型评测；人工晚会链路需真实操作与录屏。