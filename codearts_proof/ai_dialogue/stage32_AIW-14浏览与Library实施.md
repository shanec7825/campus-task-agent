# stage32：AIW-14 浏览、分栏与 Library 实施（r1/r2）

> 日期：2026-11-14（Asia/Shanghai）。基线 HEAD `a4d2714`，工作区含 AIW-09 r2 语音未提交修复与 stage29～31 文档。本阶段只改 AIW-14 写集，未提交、未推送、无 CI、未部署。

## 1. 需求与范围

- 用户指令：按 AIW-14 → AIW-09 历史 → AIW-10 → AIW-12 → AIW-13 连续推进；已完成部分不重做；提交/推送/部署仍需当轮授权。
- 本阶段完成 AIW-14 r1（导航分组、胶囊分类、三列→左 1 右 2 分栏、HoverPeek 联合区）与 r2（Library 私有链接、mine 搜索）。
- 不做：AIW-11 取消项；不恢复业务提案执行/整批发布；不新增外部抓取、解析依赖、全组织搜索、个人资料共享。
- 计划：`.codeartsdoer/plans/aiw14-workbench-library-search/design.md` §8/§9、`task.md` S30-1～S30-6（本地忽略）。

## 2. 决策与边界

| 决策 | 口径 | 依据 |
| --- | --- | --- |
| r1 详情复用 | 右栏 `BrowseDetailPanel` 只读摘要 + 「打开完整详情」，不复制图谱/成员/验收写入 | design §9.1 |
| 分栏断点 | `≥1200px` 三列；`768–1199px` 两列（选中后 1:2）；`<768px` 单列并进独立详情 | design §8/§9.1、S30-2 实测 |
| Library owner | 只由当前会话判定；响应不含 `owner_id` | §9.2、审查 I-2 |
| 私有链接删除 | 不提供 DELETE，避免不可回滚删除 | §9.2 |
| 搜索范围 | 先 `scope=mine` + authz 可见性，再标题匹配、再分页；不返回组织内非 mine | §9.3 |
| 搜索返回 | `from=search&q=` + `cta_search_return`（sessionStorage）恢复关键词 | 审查 I-5、复验 R2-B |
| 预览语义 | `role="dialog" aria-modal="false"`，桥接 8px 间隙 + 120ms 关闭缓冲 | §8 C-FE-PEEK@2、审查 I-7 |
| 搜索浮层 | `aria-modal="true"` + Tab 循环 + 关闭归还焦点 | 审查 I-6 |

## 3. 实际工具与派工

- 平台：华为云码道（CodeArts）；平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
- 主 Agent 负责规划、契约冻结、验证执行与留痕；实现由 6 个 coding-engineer 并行（写集互斥），浏览器验收 1 个，独立审查 3 轮（每轮一个新会话/只读）。
- 实际命令（Windows Git Bash，显式解释器）：
  - `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`
  - `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`
  - `node work/aiw14/peek/reproduce-peek.cjs`
  - `node work/aiw14/browse/verify-browse.cjs` / `verify-browse-r2.cjs`

## 4. 产出

- 后端：`backend/app/routers/{library,search}.py`、`services/library_service.py`、`models.py`（`LibraryLink`，表基线 23→24）、`schemas.py`、`main.py`、`tests/backend/test_aiw14_library_search.py`、`tests/backend/verify_tables.py`。
- 前端：`components/nav/{NavIcon,SearchOverlay,HistoryEntry}.vue`、`views/LibraryPage.vue`、`components/browse/{HallTabs,ActivityBrowseCard,TaskBrowseCard,BrowseDetailPanel}.vue`、`views/TaskHall.vue`、`layouts/AppLayout.vue`、`router/index.ts`、`api/{library,search}.ts`、`components/common/HoverPeek.vue`。
- 门禁：`tests/frontend/check_contracts.py` 新增 ㉗～㉜（32 项）。
- 证据：`codearts_proof/reports/aiw14-browser.md`、`codearts_proof/screenshots/aiw14-*.png`、`work/aiw14/peek/README.md`、`codearts_proof/reviews/stage30_review_r{1,2,3}.md`。

## 5. 真实问题与处置

1. **旧测试与新契约冲突**：`test_aiw05_proactive_quota` 断言写账本前二次额度检查（AIW-12 阶段处理，见 stage34）。
2. **静态门禁字面量冲突**：`TaskHall.selectCard` 先写赋值式，㉛ 断言 `selectedType: type` 失败 → 改对象字面量，行为不变（历史记录同类问题再次出现）。
3. **类型错误**：`SearchOverlay` 相对路径少一级、`TaskHall` query 字面量推断过窄 → 修复后 `npm run typecheck` 0 error。
4. **HoverPeek 8px 间隙**：修复前真实浏览器复现 2/5（指针移到间隙中线面板即消失）；联合区 + 120ms 缓冲后 16/16 PASS。
5. **AC-18 侧栏叠压**：1440×900 展开侧栏「消息」被分组覆盖 → 新增 `.sidebar-scroll`（`min-height:0 + overflow-y:auto`），复验 1440/1920 均命中自身。
6. **AC-22 搜索返回**：首轮未带词/来源 → 补 `from=search&q=` + `cta_search_return` + `initial-query` prop，复验 PASS。
7. **门禁误报**：`overflow-wrap: anywhere` 触发 `: any` 检查 → 改项目既有 `break-word`。
8. **审查 N-6**：`:initial-query` 无对应 prop → 补 prop 并消费，重建 dist。

## 6. 验证与未完成项

- 后端全量：`run_all.sh` EXIT=0，1446 PASS（24 表基线、含新增 Library/搜索 23 用例）。
- 新增/相关：`pytest test_aiw14_library_search.py` 23 passed；与历史合并 29 passed。
- 前端全量：`run_all.sh` EXIT=0（构建 4/4、静态契约 32/32、语音 21/21）；`vue-tsc` 0 error。
- 浏览器（隔离库、8000 同源 dist、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：首轮 152 条断言 149 通过；复验 AC-18/AC-22 PASS；AIW-09 历史抽屉 URL 缺陷见 stage33。
- 独立审查：r1 0 Critical / 7 Important / 14 Suggestion；r2 0C / 2 遗留 Important；r3 0C / 0 阻塞（N-6 已在 r3 后修复，未再开第四轮，按上限如实记录）。
- 未完成：AIW-14 r4 增补（stage31 规划的「浏览头像彩色短卡」「活动详情/后台共用紧凑分工表并切换活动」）尚未实施；真实模型/真机未验证；未提交/推送/CI/部署。