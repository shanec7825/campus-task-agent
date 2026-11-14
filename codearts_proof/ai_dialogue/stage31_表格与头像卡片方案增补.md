# stage31：表格与头像卡片方案增补

> 2026-11-14（Asia/Shanghai）。本轮为方案修订，业务代码未实施。HEAD 基线 `a4d2714f067ed0a819401a07434944878c6f9589`。stage30 的 AIW-14 正在开发，现场比交接中的“T14-02 起未实施”已有更多源码改动；本轮未验收这些在途实现。

## 1. 需求来源与授权

用户要求分析两张 UI 图，将表格用于活动详情与发布者后台、支持活动切换，将带头像的彩色短卡片用于浏览活动和任务，并尽量 1:1 复刻。原文见 [本轮请求](../prompts/agent_team_启动指令/2026-11-14_stage31_表格与头像卡片_用户原文.md)。本轮修改方案与留痕，未提交/推送/部署/删除/付费。

## 2. 现场基线与范围

- 已读 AGENTS、HANDOFF、DEVELOPMENT_RECORDS、roadmap、AIW-14 design/task 及相关需求/验收/决策。
- 现有 AIW-09 r2、AIW-14 前后端/测试、AGENTS 和文档未提交改动全部保留。详细初始文档副本及源码哈希在忽略目录 `work/stage31/before/`、`baseline.json`，不是远程备份。
- 本轮写集仅为 AIW-14 本地计划增补与入口、需求/验收/决策索引、HANDOFF 追加、LOG 新行及 stage31 文档。未接管 stage30 业务源码。

## 3. 决策与边界

1. 保留活动/任务胶囊、桌面三列与左 1 右 2；卡片视觉改为图2彩色底/头像/扁短矩形，不再强求近正方形。
2. 点击活动的完成态应直接看到分工表；独立活动详情和发布者后台复用表格展示层，各操作沿用现有权限。
3. 头像关联 user_id，卡片仍关联 activity_id/task_id；活动显示负责人，任务显示获批执行成员，未分配与发布者身份分清。
4. 当前 User 无头像字段、活动树缺成员 ID/开始时间/逐人状态；明确实施缺口，不能声称头像已存在或表格数据已齐全。
5. 不因参考图新增优先级、工时系统、评论、附件统计、blocked 状态、表格自定义字段或批量发布等未授权能力。

## 4. 实际工具与派工

平台为 Codex 桌面端，主 Agent 串行读取和编写文档；未调用实现或 Review 子 Agent。使用 ui-ux-pro-max 做状态颜色/移动表格只读检索；Vue 的首轮专项查询未命中，重试只返回通用加载生命周期建议，未将其当作本项目方案依据。使用 answer-me-with-html 生成说明页，不手写产品 HTML/CSS，不改业务前端。

精确模型部署标识未独立核验，未将本轮写成 CodeArts 实现。未改业务 Prompt，无业务模型试跑，不新增 Prompt 迭代编号。

## 5. 实际问题与处理

| 问题 | 原因/依据 | 本轮处理 |
|---|---|---|
| 旧方案“近方形/SVG图标/摘要右栏”与新截图冲突 | AIW-14 design §3/§8/§9.1 与卡片源码 | 新增 r4 优先契约，保留 r3 历史，入口显式提示 |
| 交接写未实施，现场已有代码 | git status 与 ActivityBrowseCard/TaskBrowseCard/Library/search 等文件 | 追加当前只读观察，不改写 stage30 验收结果、不覆盖在途代码 |
| 初次像素采样脚本失败 | 默认 Python 无 PIL；猜测的 tokens.css 路径不存在，退出码 1 | 未安装依赖；改用 Windows System.Drawing 读取四个像素，退出码 0；真实主题文件为 theme.css/color-pool.css |
| 首轮文档检查 51 通过 / 2 失败 | 检查报告尚未生成导致两条报告链接暂缺；5个业务文件哈希在本轮分析期间变化 | 保留首轮失败报告；报告落盘后复核链接；将源码变化作为并发观察单列，不回退他人改动、不声称源码哈希未变 |

以上是方案核对与工具问题，不冒充已复现并修复的线上 Bug。

## 6. 产出、验证与未完成

详细本地契约：`.codeartsdoer/plans/aiw14-workbench-library-search/ui-reference-r4.md`；已接入 design/task 与总计划入口。可携带摘要见 [方案摘要](../reports/stage31_表格与头像卡片方案摘要.md)。文档检查证据见 [检查报告](../reports/stage31_plan_document_check.json)。

首轮命令：在项目根目录运行 `PowerShell here-string | python -X utf8 -`，执行ID唯一性/契约覆盖/链接/忽略边界/源码哈希/`git diff --check`，EXIT=1，51通过/2失败，见 [首轮报告](../reports/stage31_plan_document_check_initial.json)。第二次将源码在途变更单列为观察，重新验证文档，EXIT=0，**52通过/0失败，91个本地链接有效**，见最终报告。源码哈希变化不代表本轮源码写入，亦未通过调整业务检查来放行实现。

同期观测到 `frontend/src/api/library.ts`、`frontend/src/components/nav/SearchOverlay.vue`、`frontend/src/components/common/HoverPeek.vue`、`frontend/src/layouts/AppLayout.vue`、`frontend/src/views/TaskHall.vue` 的哈希变化；本轮工具写操作未涉及这些文件，不能用“源码完全未变”描述共享工作区。未复查或验收外部实现。

说明页命令：`node C:/Users/Lenovo/.codex/skills/answer-me-with-html/scripts/am.mjs render C:/Users/Lenovo/.codex/visualizations/2026/11/14/01a1d940-718f-7992-81ff-9ab4238a560f/campus-ui-r4.md --no-open`，EXIT=0；7面板/1流程图/0风格警告，包含两张用户原图。产物在 `C:/Users/Lenovo/.answer-me-with-html/pages/两种视图-同一套活动与任务-20261114-165939.html`，属于方案说明，不是产品页面实现或浏览器验收。

未运行业务构建/回归、浏览器验证、真实模型、真机与独立代码审查。方案记录不等于功能交付；无本轮提交、推送、新 CI 或部署。
