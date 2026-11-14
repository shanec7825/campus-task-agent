# stage30：AIW-14 r1 基线核对与契约冻结（已转入 stage32 实施）

> 日期：2026-11-14（Asia/Shanghai）。状态：**基线记录已完成**；本文只保留 T14-01 真实基线与 r1 契约冻结。后续实现、r4 覆盖与验证见 [stage32](stage32_AIW-14浏览与Library实施.md)；本文“业务代码尚未修改”是 T14-01 当时事实，不代表当前代码。基线 HEAD `a4d2714f067ed0a819401a07434944878c6f9589`，工作区含 AIW-09 r2 未提交修复与 stage29 文档，均不属本阶段改动。

## 1. 需求与范围

- 需求来源：用户本轮连续开发指令（r3），语音 r2 收口后按 AIW-14 → AIW-09 历史 → AIW-10 → AIW-12 → AIW-13 推进。
- 计划：`.codeartsdoer/plans/aiw14-workbench-library-search/design.md`、`task.md`（本地忽略）。
- r1 范围：分组图标侧栏、顶部搜索入口与 Library 入口、最近活动/任务、AI 历史占位（不造假数据）、活动/任务双段胶囊、三列短卡片与左 1 右 2 详情、HoverPeek 联合区。
- 不做：AIW-11 取消项；不新增模型图标供应、外链抓取、解析依赖、个人资料共享或全组织搜索。

## 2. T14-01 基线核对（实际读取源码）

| 项 | 当前事实 | 依据 |
|---|---|---|
| 路由 | `ai /ai`、`workbench /workbench`、`hall /tasks`、`my-tasks /my-tasks`、`published-activities`、`publish-activity /activities/new`、`detail /tasks/:id`、`activity /activities/:id`、`messages`、`profile`、`publish`、`admin`；无 Library 路由 | `frontend/src/router/index.ts` |
| 侧栏 | `mainNav` 5 项（AI/大厅/我的/消息/个人），`managerNav` 2 项（我发布的活动/发布者后台），最近活动/任务各 `RECENT_LIMIT`，底部主题与退出；桌面 208px/72px 折叠，移动底部 4 项 + 抽屉 | `frontend/src/layouts/AppLayout.vue` |
| mine 语义 | 任务 `scope=mine`：发布者 **or** 任一 approved 成员 **or** legacy `assignee_id`；活动 `scope=mine`：负责人 **or** 活动下存在我的任务；三者均先叠加 `authz.visible_*_filter` | `backend/app/routers/tasks.py:368-393`、`activities.py:140-160` |
| 列表形态 | `TaskHall` 目前活动区与任务区上下堆叠，卡片点击进入独立 `/activities/:id` 或 `/tasks/:id`；无内嵌详情组件 | `frontend/src/views/TaskHall.vue:315-420` |
| 图标 | 全站未引入 `@element-plus/icons-vue`，现有 SVG/emoji 检索无命中；需本地内联 SVG，不能加新依赖 | `frontend/src` 检索 |
| HoverPeek | 根节点 `mouseleave` 立即 `close()`，面板 `top: calc(100% + 8px)`；卡片与面板间存在 8px 几何间隙，源码上可触发离开关闭；**尚未浏览器复现** | `frontend/src/components/common/HoverPeek.vue:84-123` |
| 详情复用 | `ActivityDetail.vue` / `TaskDetail.vue` 是页面级组件，包含图谱、成员、验收等业务；r1 需要抽取可嵌入的展示层，独立页面壳保留旧 URL | `frontend/src/views/{ActivityDetail,TaskDetail}.vue` |

## 3. r1 契约冻结（详见 design.md §8）

- Library 新增 `/library` 路由与侧栏入口；本人私有链接与共享资料分区，不在 r1 实现写入，只建立入口与空态。
- 大厅/我的任务用 `?type=activity|task` 双段胶囊，一次只渲染一种集合；两类筛选/滚动分别用独立 sessionStorage 键。
- 三列布局断点：`≥1200px` 三列、`768–1199px` 两列、`<768px` 单列；详情选择写入 `?selectedType=&selectedId=`。
- HoverPeek 联合区：卡片、8px 视觉间隙与面板同属一个 hover 根，间隙由伪元素桥接或短关闭缓冲覆盖；保留 `delay` 快划不弹、Esc、键盘焦点与触摸点击详情。
- AI 历史在 09 提供真实数据前只显示「历史即将接入」空态，不伪造会话。

## 4. 验证与未完成

- 本轮 T14-01 只读核对，未改业务代码，未跑构建/浏览器；HoverPeek 间隙未复现，不能写已修复。
- 下一步 T14-02：分组图标侧栏与入口；T14-03 胶囊；T14-04 三列/分栏；T14-06 先复现预览再修复。
- 真实模型、真机、部署未验证；提交/推送未授权。