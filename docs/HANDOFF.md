# 当前开发交接

> 更新日期：2026-11-13（Asia/Shanghai，stage18 收尾）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 当前 HEAD：`4c3c875b8d3c4c62fc88daa190ad35f7b1ba4655`（`feat(activity): 打通活动下任务发布与负责人可见性`），已推送 `af43dc7..4c3c875`，本地与 `origin/main` 一致。
- 工作树：提交后干净；stage18 的代码/测试/CI/文档均已提交（见 §2），不再只看本地文件。
- stage17 时点的事实（保留）：用户说明已回退到上次提交，开工 `git status --porcelain=v1 --branch` 仅显示 `## main...origin/main`；回退命令、时间与原因未知，不推断。
- stage18 授权范围：AIW-00 活动下任务流程连通（R1 负责人可见性、R2 活动下发布、R3 任务级待确认、R4 无组织活动发布授权）；不新增依赖/表/迁移/路由。用户随后明确授权提交与推送，本轮已完成；未部署。
- 本轮使用编号：留痕 **stage18**；未产生业务 Prompt 变更，不新增 P 编号。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `backend/app/services/authz.py` | `:74-87` 新增活动负责人可见条件；`:195-196` 无组织活动非负责人 4030。`can_manage_task` 未动 | 可见性只扩大读取，不自动授予写权限 |
| `tests/backend/test_activity_workflow.py` | 新增 600 行 / 8 用例，隔离临时库 + Cookie/CSRF 真实 HTTP | 修改授权或活动流程时必须重跑；已接入 CI |
| 前端活动发布链路 | `ActivityDetail.vue` 入口、`PublishPage.vue` 解析 `?activity` 并默认手动、`ManualForm.vue` 携带 `activity_id`、`models.ts` 补字段 | AI 模式仍不带活动归属，属未完成范围 |
| 任务详情待确认提示 | `TaskDetail.vue` 纯派生 `awaitingOwnerConfirm`，不改状态、不调接口 | 仅在全部子任务 verified 且父任务未验收时展示 |
| CI 与文档 | `.github/workflows/ci.yml:40-41`、`docs/CI.md` 加入 `test_activity_workflow.py` | 真实 Actions 已核对：run 43453696153（`4c3c875`）四个 job success，未逐行审阅日志正文 |

## 3. stage17 回退时的核对结果（历史，保留不改）

| 对象 | stage17 核对结果 | 接手规则 |
|---|---|---|
| 前次未提交的 7 个修改文件与 1 个测试文件 | 当时不在 Git 工作区差异中 | 不把其实现算入基线；stage18 的 `test_activity_workflow.py` 是本轮重新实现并新增的 |
| `.codeartsdoer/plans/phase3-activity-workflow/` | 当时不存在 | 旧接手指令失效；现用 `aiw00-activity-flow` 计划 |
| `tests/backend/test_activity_workflow.py` | 当时不存在 | 现由 stage18 新增并接入 CI |
| 活动下发布关联、负责人建任务入口、任务级待确认提示 | stage17 时源码未保留旧增量 | stage18 已按 AIW-00 重新实现，见 §2 |
| 活动负责人授权 | stage17 时新增可见范围条件不在工作区 | stage18 重新实现并以行为回归验证 |
| 产品方向 | UI、三形态助手、资源、通知与协作目标保留在本地总计划 | 只变更实施起点，不自动恢复全部已回退代码 |

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读要求。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源、问题记录与并行写入约束。
3. [本地总计划](../.codeartsdoer/plans/ai-workbench/roadmap.md)：完整产品方案，属于本地忽略文件。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw00-activity-flow/design.md) 与 [task.md](../.codeartsdoer/plans/aiw00-activity-flow/task.md)：冻结 R1~R4 与 4 份契约；`task.md` 同时是下一轮补口的任务状态依据。
5. [stage18 过程与验证](../codearts_proof/ai_dialogue/stage18_活动下任务流程连通.md) 与 [stage18 验证记录](../codearts_proof/reports/stage18_验证记录.md)：本轮真实命令、计数、失败项与未验证范围。
6. [stage17 过程与验证](../codearts_proof/ai_dialogue/stage17_回退基线与开发交接整理.md)：回退基线整理与记录规则来源。

本地计划缺失时，先告知用户并请求提供文件或明确新的设计依据；不要从历史 HTML、旧 phase2 计划或文件名推导完整需求。无需为使链接可用而把忽略目录强制提交。

## 5. 验证、审查与提交状态

- 本地验证（隔离临时库，未触碰 `backend/campus.db`）：`test_activity_workflow.py` **8 passed**、`test_activity_hierarchy.py` **13 passed**、`test_auth_org_permissions.py` **47 passed**、CI 等价合并命令 **68 passed**；`tests/backend/run_all.sh` **exit 0（1412 条 PASS）**；`tests/frontend/run_all.sh` 修复首轮真实门禁失败后 **exit 0**（构建 4/4、契约 25/25、语音切片 21 PASS）。证据见 `codearts_proof/reports/stage18_验证记录.md`。
- 回归敏感度：变异 M1（删除 4030 校验）与 M2（先写库后拒绝）均导致 2 个新增用例失败，证明用例不是摆设。
- 独立审查两轮：首轮 3 项 Important（CI 未接入、无组织活动授权缺口、负责人写面）均已处置；第二轮 PASS，无阻断项。审查结论在会话中给出，未落盘独立报告。
- **未验证**：浏览器/真机/移动端视口、真实模型（全程 `MAAS_MOCK=1`）；CI 只核对到 job 级结论，未逐行审阅日志。合并 pytest 在沙箱下出现过 `WinError 10051` 间歇失败，归因环境且未在无沙箱复验。
- **提交与 CI**：提交 `4c3c875` 已推送 `origin/main`；run [43453696153](https://github.com/shanec7825/campus-task-agent/actions/runs/43453696153) 的 backend-reliability（ubuntu/windows）、backend-integration、frontend 四个 job 均 success。**未部署**。stage17 及更早阶段文档中的“待提交/已推送”等表述属当时状态。

## 6. 下一步

- stage18 已提交并推送（`4c3c875`），对应 CI 全绿。提交前已核对实际暂存清单（排除 `.codeartsdoer/`、`outputs/`、日志、数据库与凭证）。
- 待补的动态验证：R2「活动详情 → 发布页 → 带 `activity_id` 创建任务」的浏览器链路，R3「全部子任务 verified 且父任务未验收」的渲染场景。
- 后续增量候选：AI 模式发布的活动归属、AI 默认首页与权限内问答；均待下一轮明确选定范围。下一次新阶段先扫描编号，当前最大 stage 为 18。

## 7. 新 Agent 的最短启动指令

```text
先读取 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md
以及交接文件指向的本地总计划，核对 Git 基线和当前文件。
本轮目标由我在这条指令后明确指定；没有目标时先报告现状，不展开开发。
执行选定阶段前先完善对应 design.md 与 task.md。
按项目规则记录真实过程、问题与验证，不自动进入下一阶段。
提交、推送、部署与删除按本轮明确授权执行。
```
