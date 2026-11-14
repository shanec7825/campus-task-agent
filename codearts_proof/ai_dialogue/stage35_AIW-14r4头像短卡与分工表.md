# 阶段 35 · AIW-14 r4：头像彩色短卡与共用任务分工表

> 日期：2026-11-14（Asia/Shanghai）。平台：华为云码道（CodeArts）。实际编排为 team-leader（本 Agent），执行 coding-engineer 并行/串行 4 人 + 1 名契约断言工程师，独立只读审查 1 名 team-code-reviewer。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
> 需求来源：用户接续指令「继续执行本项目当前已确认的开发计划」+ `ui-reference-r4.md` §2（参考图2）与 `design.md` §10 冻结契约。

## 1. 需求来源与边界

用户在前一轮完成 AIW-14 r1/r2、AIW-09 历史、AIW-12 额度并发后，要求从首个未完成增量接续：**AIW-14 r4 → AIW-09 历史 → AIW-10 → AIW-12 → AIW-13**（AIW-09 历史与 AIW-12 已收口）。

r4 范围：

- 浏览页活动/任务卡改为参考图2的**柔和彩色短矩形 + 头像主行**，标题为常规字重 16px，卡片只保留 2–3 行摘要。
- 活动详情、浏览右栏、发布者后台共用**紧凑任务分工表**（任务/状态/执行成员/开始/截止/完成情况/操作），支持父子展开。
- 活动详情标题区提供活动切换（只列后端可见活动，`router.replace` 不堆历史）。
- 后台桌面任务区复用同一表格并增加活动筛选，保留既有指派/验收/详情入口；移动端保留卡片列表。

不做：AIW-11（已取消）、真实头像上传、任务表内联编辑、新的写接口、成就规则（D-05）、文件解析（D-04）。

## 2. 决策与冻结契约

| 决策 | 结论 |
| --- | --- |
| 头像来源 | 本地生成：`userId % 4` 四组主题柔和色 + 姓名首字，不请求外部图片、不新增用户头像字段 |
| 表格数据 | 活动树节点补 `start_time`、`assignees[{user_id,name}]`、`completed_children/total_children`、`activity_id`；`assignee_names` 保留向后兼容 |
| 活动切换数据源 | 复用 `listActivities({ scope: 'all' })`（服务端已叠可见性），不新增接口；选项最多 20 条且当前活动必在 |
| 后台复用方式 | 桌面替换为共用表格，`actions` 作用域插槽保留既有 handler；移动端保留卡片 |
| 契约缺口处置 | S30-9 报告 `ActivityTaskNode` 缺 `activity_id` → 裁定由后端 DTO 增补（父子同值），不做前端可选兜底 |

冻结契约（`design.md` §10）：`C-ACT-TABLE-DTO@1`、`C-USER-AVATAR@1`、`C-BROWSE-CARD@2`、`C-ACTIVITY-TABLE@1`、`C-ACTIVITY-SWITCH@1`、`C-ADMIN-TABLE-REUSE@1`。

## 3. 实际派工

| 任务 | 执行者 | 写集 | 结果 |
| --- | --- | --- | --- |
| S30-7 活动树只读投影 | 投影实现工程师（coding-engineer） | `backend/app/{schemas.py,services/activity_service.py}`、`tests/backend/test_aiw14_activity_table.py` | 完成；补丁追加 `activity_id` |
| S30-8 头像与彩色短卡 | 头像卡片工程师（coding-engineer） | `frontend/src/components/common/UserAvatar.vue`、`components/browse/{ActivityBrowseCard,TaskBrowseCard}.vue` | 完成 |
| S30-9 共用表格与活动切换 | 表格与切换工程师（coding-engineer） | `components/task/ActivityTaskTable.vue`、`types/models.ts`、`views/ActivityDetail.vue`、`components/browse/BrowseDetailPanel.vue` | 完成（报告契约缺口，已裁定） |
| S30-10 后台复用与筛选 | 后台表格工程师（coding-engineer） | `views/AdminConsole.vue` | 完成；类型门禁失败 1 处已回原实现者修复 |
| S30-11 契约断言 | 契约断言工程师（coding-engineer） | `tests/frontend/check_contracts.py` | 完成，新增 ㉝–㊲ |
| 独立审查 | 独立审查员（team-code-reviewer，只读） | — | 见 §5 |

## 4. 产出

- 后端：`backend/app/schemas.py`（`ActivityAssigneeOut`、节点新字段）、`backend/app/services/activity_service.py`（`_assignees_payload`、`activity_id`、子任务计数）、`tests/backend/test_aiw14_activity_table.py`（5 用例）。
- 前端：新增 `components/common/UserAvatar.vue`、`components/task/ActivityTaskTable.vue`；改造 `components/browse/{ActivityBrowseCard,TaskBrowseCard,BrowseDetailPanel}.vue`、`views/{ActivityDetail,AdminConsole}.vue`、`types/models.ts`。
- 校验：`tests/frontend/check_contracts.py` 新增 5 项（㉝–㊲），总数 37。
- 证据：`work/aiw14/browse/verify-browse-r4.cjs` 与 `r4-report.json`（本地忽略）、`codearts_proof/screenshots/aiw14-r4-{hall,activity,admin,mobile-hall,mobile-activity,mobile-admin}.png`。

## 5. 真实问题与验证

1. **契约缺口**：`ActivityTaskNode` 缺 `activity_id`，而「所属活动」列与后台标题映射需要来源 → 裁定后端 DTO 增补（父子同值），前端保留可选类型兼容。
2. **类型门禁**：`AdminConsole.vue:207` 将 `ActivityTaskNode` 强转 `TaskItem` 触发 TS2352 → 回原实现者修复后 `vue-tsc --noEmit` 无错误。
3. **静态契约 ㊱ 失败**：断言只认带引号的 `'切换活动'`，实际标签为模板文本 `>切换活动<`（`ActivityDetail.vue:354`）→ 按既定惯例修正断言口径，代码未改；复跑 37/37 PASS。
4. **浏览器断言口径**（非产品缺陷）：大厅默认「活动」tab 只有 4 张卡（任务卡在「任务」tab）；活动 5 无任务时组件显示「暂无任务」空态而非表格；后台为 el-select 且 collab 只可见 1 个同组织活动（活动 3/4/5 无组织，仅负责人可见）；后台桌面 0 行由表格内空态提示。均按真实行为修正脚本并复验。
5. **验证结果**：
   - `tests/backend/test_aiw14_activity_table.py`：**5 passed**。
   - 活动层级 + 流程回归：**21 passed**。
   - 后端 `run_all.sh`：**EXIT=0**（23 表主验证，1446 PASS 级）。
   - 前端 `run_all.sh`：**ALL PASS**（构建 4/4、契约 37/37、语音 21/21）。
   - `vue-tsc --noEmit`：无错误。
   - r4 浏览器（dist 同源 8000 + 隔离库 `work/aiw14/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：**41/41 PASS**，覆盖 1440/390 视口、彩色底与头像尺寸、标题字重、右栏表格、父子展开、活动切换与空态、后台父子组装与筛选、操作入口、无横向溢出。
7. **独立审查与修复**：`team-code-reviewer` 只读一轮，**0 Critical / 3 Important / 若干 Suggestion**，结论「有条件提交」。三项 Important 全部回原实现者修复：
   - 表格任务链接由裸 `<a :href>` 改为 `<router-link name:'detail'>`，避免整页刷新丢失返回来源；新增 `meta` 作用域插槽与子任务徽标。
   - 后台 `tableTasks` 按 `parent_id` 组装 `children`，并用 `#meta` 恢复分配方式/报名配额/积分/催办摘要；桌面与移动视图口径一致。
   - 契约 ㉟ 列序断言由集合包含改为精确顺序，并修正脚本 `NameError` 与函数式 `metaSummary` 误判；复跑 **37/37 PASS**。
   修复后重跑：`vue-tsc` 无错误、前端 `run_all` **ALL PASS**、r4 浏览器 **41/41 PASS**。审查轮次上限按项目规则为三轮，本轮仅一轮修复后未再开第二轮独立复审；修复项已由门禁与浏览器独立验证。
8. **真实未验证**：真实模型、真机、深色主题复测、安全红线本轮未重跑；未提交、未推送、无新 CI、未部署。

## 6. 未完成项

- AIW-10：D-04（文件格式/大小/解析依赖）未确认，上传/解析/版本/预审挂起。
- AIW-12 成就：D-05 规则未确认，未新增发奖写路径。
- AIW-13：最终视觉收口与完整角色/设备验收；真机与真实模型按 D-06 待验收。
- 全域搜索后端未实现（前端入口与提示存在），属既有范围边界。