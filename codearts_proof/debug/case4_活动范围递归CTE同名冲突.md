# case4：活动范围查询出现同名递归 CTE 冲突

## 一、现象

- **时间**：2026-11-14。
- **环境**：Windows Git Bash；Python 3.12.10；隔离 SQLite；`MAAS_MOCK=1`、`RUN_SCHEDULER=0`。
- **操作步骤**：
  1. 为 AIW-02 新增 `GET /api/activities?scope=mine`，复用 `authz.visible_task_filter` 同时构造「活动可见」与「我的活动」条件。
  2. 执行 `python -m pytest tests/backend/test_aiw02_activity_scope.py -q`。
- **报错或现象**：`scope=mine` 用例 2 failed，其余 4 passed。

```text
sqlalchemy.exc.CompileError: Multiple, unrelated CTEs found with the same name: 'visible_task_ids'
```

## 二、原因

- **根因**：`visible_task_filter()` 每次调用都会创建一个名为 `visible_task_ids` 的递归 CTE。`list_activities` 中 `_visible_activity_condition()` 与 `_mine_activity_condition()` 各自调用一次，同一个 SQL 查询里出现两个同名但不同实例的 CTE，SQLAlchemy 拒绝编译。
- **判断依据**：完整栈指向 `visit_cte` 的 `CompileError`；活动 `scope=all` 只调用一次，因此通过；`scope=mine` 才触发。
- **影响范围**：只影响新增的活动 `scope=mine` 查询，不阻塞应用启动；`scope=all` 与任务列表不受影响。

## 三、让码道怎么修

- **下发给码道的指令要点**：
  1. 在 `list_activities` 中只创建一次 `visible_task_filter` 结果，并传给可见条件与「我的活动」条件；
  2. 保持授权语义不变：`mine` 仍必须同时满足可见性与「我的任务」；
  3. 不修改 `visible_task_filter` 的递归 CTE 语义，不改为 Python 全表过滤。
- **允许修改的文件**：`backend/app/routers/activities.py`。
- **禁止改动**：`authz.py` 的可见性规则、任务列表 `scope=mine` 行为、数据库结构。
- **修复后必须满足的验收条件**：
  1. `test_aiw02_activity_scope.py` 全部通过；
  2. 活动层级/认证/可靠性回归不退化；
  3. 跨组织与无关成员仍不可见。

## 四、结果

- **修复动作**：`_visible_activity_condition` 与 `_mine_activity_condition` 增加 `visible_tasks` 参数；`list_activities` 创建一次 `authz.visible_task_filter(db, current_user)` 后复用。
- **验证方式**：重跑新增测试与相关回归。
- **验证输出**：

```text
python -m pytest tests/backend/test_aiw02_activity_scope.py -q
6 passed in 2.80s

python -m pytest tests/backend/test_auth_org_permissions.py tests/backend/test_activity_hierarchy.py tests/backend/test_activity_workflow.py -q
68 passed

python -m pytest tests/backend/test_reliability.py -q
11 passed
```

- **是否回归**：活动层级、活动流程、认证权限、可靠性均已回归；后端 `run_all.sh` 1412 PASS。
- **结论**：已解决。