# 案例 2：`python-dotenv` 在依赖里，但应用没有加载 `.env`

> 记录日期：2026-11-11 · 环境：backend/.venv（Python 3.14.0）+ python-dotenv 1.2.4

## 一、现象

T10 自动化验证阶段发现：按 README 把 `backend/.env.example` 复制为 `backend/.env` 后，`.env` 中的配置**不生效**——`/api/health` 返回的 `mock` 与 `.env` 预期不一致，`DATABASE_PATH` 也不起作用；只有把变量显式注入到 shell（`MAAS_MOCK=1 RUN_SCHEDULER=0 ... uvicorn ...`）才生效。

**实测命令与真实输出**（当时应用内没有任何 `load_dotenv` 调用）

```text
$ cd backend
$ .venv/Scripts/python.exe -c "import os; print(os.getenv('MAAS_MOCK'))"
None        ← .env 存在也不生效，os.environ 里没有该变量
```

## 二、原因

1. `uvicorn` / FastAPI **不会自动读取** `.env` 文件，配置只来自进程环境变量（`os.environ`）。
2. `python-dotenv` 已写入 `requirements.txt`，但它的能力必须靠**显式调用** `load_dotenv()` 才会注入 `os.environ`；当时 `backend/app` 内没有任何调用点，所以依赖"装了但没用上"。
3. 结果与 README 指导的"复制 `.env.example` 为 `.env` 即可配置"不一致，属于**文档与实现不一致**而非用户操作问题。

## 三、让码道怎么修

在**配置被读取的最早位置**加载 `.env`，并且保证自动化验收的 shell 注入优先：

```python
# backend/app/db.py 顶部（import os 之后、create_engine 之前）
BACKEND_DIR = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env", override=False)
except ImportError:  # python-dotenv 缺失时退化为纯环境变量
    pass
```

**三条硬约束**

1. `override=False`：**shell 注入优先**。T10/T11/T12 的自动化脚本用 `MAAS_MOCK=1 RUN_SCHEDULER=0 DATABASE_PATH=<临时库>` 注入，不能被开发者本机 `.env` 覆盖。
2. 文件缺失时**静默**：`load_dotenv()` 返回 `False`，不抛异常，保证未建 `.env` 的干净环境也能启动（此时按"无 Key ⇒ mock"降级）。
3. `ImportError` 兜底：即使环境里缺 `python-dotenv` 也不阻塞启动。
4. 加载点必须早于所有 `os.getenv(...)`（`db.py` 的模块级 `DATABASE_PATH` 读取之前），且所有模块都经过 `app.db` 导入，保证顺序稳定。

## 四、结果

**代码位置**：`backend/app/db.py:16-23`（`load_dotenv(BACKEND_DIR / ".env", override=False)`）。

**三态行为实测**（在临时目录构造 `.env`，避免污染工程；命令与真实输出如下）：

```bash
T=$(mktemp -d); printf 'MAAS_MOCK=1\n' > "$T/.env"; W=$(cygpath -w "$T/.env")
cd backend
# A. 文件存在 → 生效
.venv/Scripts/python.exe -c "import os;from dotenv import load_dotenv;load_dotenv(r'$W', override=False);print('MAAS_MOCK=', os.getenv('MAAS_MOCK'))"
# B. shell 已注入 → shell 优先（不被文件覆盖）
MAAS_MOCK=0 .venv/Scripts/python.exe -c "import os;from dotenv import load_dotenv;load_dotenv(r'$W', override=False);print('MAAS_MOCK=', os.getenv('MAAS_MOCK'))"
# C. 文件缺失 → 静默返回 False
.venv/Scripts/python.exe -c "import os;from dotenv import load_dotenv;print('loaded=', load_dotenv(r'<不存在的路径>', override=False), 'MAAS_MOCK=', os.getenv('MAAS_MOCK'))"
```

真实输出：

```text
[A 文件生效]
MAAS_MOCK= 1
[B shell 优先]
MAAS_MOCK= 0
[C 文件缺失静默]
loaded= False MAAS_MOCK= None
```

**项目侧验证**

```text
$ grep -n "load_dotenv" backend/app/db.py
19:        from dotenv import load_dotenv
21:    load_dotenv(BACKEND_DIR / ".env", override=False)
```

- `backend/.env` 不存在时后端仍可启动（`mock` 判定回落到"`MAAS_API_KEY` 为空 ⇒ mock"）。
- T10 的 `tests/backend/run_all.sh` 全部用例以 shell 注入变量运行，`override=False` 保证不被本机 `.env` 干扰，用例全绿。
- **是否回归**：`app/db.py` 只新增加载逻辑，未改动引擎/会话/建表行为。
- **结论**：已解决。