# 阶段 36 · AIW-10 可执行增量：预审绑定资料版本与过期验收拒绝

> 日期：2026-11-14（Asia/Shanghai）。平台：华为云码道（CodeArts）。编排 team-leader，执行 coding-engineer 2 人并行 + 1 人补回归，独立只读审查 1 轮（team-code-reviewer）。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
> 范围依据：`aiw10-documents-review/design.md` §1–§6、`task.md` T10-06/T10-07、`decisions.md` D-04。

## 1. 需求来源与边界

用户要求从 AIW-14 r4 之后继续 AIW-09 历史 → AIW-10 → AIW-12 → AIW-13；AIW-09 历史与 AIW-12 额度在前一轮已收口。D-04（首批文件格式/大小/解析依赖）**未确认**，因此本阶段只做不依赖文件格式的可执行部分：

- 预审 digest 覆盖**被引用资料版本**：任务/活动要求或资料版本任一变化即 stale。
- 预审行保存当次 `resource_snapshot`，历史行不改写。
- 人工验收**通过**时拒绝过期预审；退回与无预审路径保持兼容。
- 任务详情过期文案与「通过」入口提示。

挂起（未做）：附件上传/下载、格式解析、页码/片段定位、文件类型与大小校验、OCR——全部依赖 D-04。

## 2. 决策与冻结契约

| 决策 | 结论 |
| --- | --- |
| digest 资源来源 | `resource_service.latest_resource_versions(db, *, task, limit=5)`，仅权限内当前版本 |
| 资源视角 | 固定为**成果提交者**（`submission.user_id`）；审核者视角只用于权限判定，避免审核者可见更多往期资料时误判过期 |
| 迁移 | `ALTER TABLE submission_prechecks ADD COLUMN resource_snapshot TEXT`，幂等、不回填；旧行读取归 `[]` |
| 验收拒绝范围 | 仅 `pass=true`；无预审不阻断；`pass=false` 退回不受影响；校验先于任何写库 |
| 前端 | 过期标签「要求或资料已变化，预审过期」；「通过」在最新成果预审 stale 时 disabled 并提示重新预审；「退回」可用 |

契约：`C-PRECHECK-EVIDENCE@2`（design.md §6，含 2026-11-14 资源视角唯一化补丁）。

## 3. 实际派工

| 任务 | 执行者 | 写集 | 结果 |
| --- | --- | --- | --- |
| S36-1 后端 digest/快照/过期拒绝/迁移/测试 | 预审版本工程师 | `backend/app/{models,db,schemas,services/submission_service,routers/tasks}.py`、`tests/backend/test_aiw10_precheck_version.py` | 完成；报告资源视角缺口 → 裁定后修正 |
| S36-2 前端过期文案与验收入口 | 预审前端工程师 | `frontend/src/views/TaskDetail.vue`、`frontend/src/types/models.ts` | 完成 |
| S36-1 补丁（审查回归） | 预审版本工程师 | `tests/backend/test_aiw10_precheck_version.py` | 见 §5 |

## 4. 产出

- `_requirement_digest(task, activity, resources)` 纳入 `[{id,version}]`；新增 `_current_digest`、`_resource_snapshot`、`latest_precheck`、`require_fresh_precheck`。
- `SubmissionPrecheck.resource_snapshot`（JSON，默认 `[]`）+ 幂等迁移；`PrecheckResourceSnapshot`、`PrecheckOut.resource_snapshot`。
- `verify_task` 在 `pass=true` 时对目标成员最新成果最新预审做新鲜度校验，过期返回 4090 且不写成员/积分/通知。
- `TaskDetail.vue`：过期标签、`passBlockedByStalePrecheck`、通过按钮 disabled 与 `verify-hint`、4090 透出后端消息。
- AIW-13 T13-00 附带两处视觉收口：`UserAvatar` xs 字号改用 `--app-font-aux`；`AppLayout` 徽标 `#fff` 改用 `--el-color-white`。

## 5. 真实问题与验证

1. **资源视角缺口（实现者报告）**：预审由成员发起、验收由审核者执行；若按调用方视角算 digest，审核者可见更多同组织往期资料时会把成员预审误判 stale → 裁定 digest/stale/验收三处统一用提交者视角，新增回归。
2. **审查结论**：0 Critical / 3 Important / 9 Suggestion，判定「有条件提交」。
   - I1：`run_all.sh` 只跑 6 个旧脚本，不覆盖 pytest —— 已按实际口径更正，AIW-10 回归只以 pytest 结果为证。
   - I2/I3：审核者发起预审、多目标过期不部分写入缺回归 → 已补用例。
   - S3：旧表无列迁移缺回归 → 已补。
   - 其余 Suggestion（N 倍 digest 开销、资源窗口保守 false stale、PrecheckResult 未含 resource_snapshot、后台不展示 stale、前端禁用缺点击证据）记录为未处置，不扩大范围。
3. **验证结果**：
   - `tests/backend/test_aiw10_precheck_version.py`：**8 passed**（5 条主用例 + 审查补丁 3 条：审核者发起预审用提交者视角、多目标 stale 整体 4090 且无部分写入、旧表无 resource_snapshot 列迁移幂等；另含审核者更宽可见性不误拒、过期通过 4090 无写入、退回/无预审兼容）。
   - `test_aiw04_resource_review.py` + `test_aiw06_acceptance.py`：**15 passed / 1 skipped**。
   - 后端 `run_all.sh`：**EXIT=0（1446 PASS / 0 FAILED）**，但该脚本不覆盖 pytest，**不作为本条增量回归证据**。
   - 前端：构建 4/4、契约 37/37、语音 21/21 ALL PASS；`vue-tsc --noEmit` 0 error。
   - 浏览器：本阶段未新增 AIW-10 UI 点击取证；预审过期拒绝由 API 测试覆盖，前端 disabled 状态未实测点击。
4. **未验证**：D-04 相关文件能力、真实模型、真机、深色主题、安全红线本轮未跑；未提交、未推送、无新 CI、未部署。

## 6. 未完成项

- AIW-10 附件上传/下载、解析、片段定位、格式与大小校验：D-04 未确认。
- AIW-12 成就：D-05 未确认。
- AIW-13：T13-00 已做两处视觉收口，完整角色/设备与晚会链路验收待继续。
- 审查 Suggestion 中未处置项见 §5。