# 案例 1：git-bash 的 `python` 指向 MSYS2/mingw64，venv 生成 `bin/` 而不是 `Scripts/`

> 记录日期：2026-11-11 · 环境：Windows 11 + git-bash（`uname -s` = `MINGW64_NT-10.0-26200`）

## 一、现象

在 `backend/` 下按 README 建虚拟环境并启动：

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

启动时报：

```text
bash: .venv/Scripts/python.exe: No such file or directory
```

检查目录，只有 `bin/` 没有 `Scripts/`。

**实测命令与真实输出**

```text
$ which python
/c/msys64/mingw64/bin/python     ← 指向 MSYS2 的 mingw64 端口版解释器
$ python --version
Python 3.14.4
$ python -m venv <临时目录>/probe-venv
$ ls <临时目录>/probe-venv
Include
bin
lib
pyvenv.cfg
$ ls <临时目录>/probe-venv/bin/python*.exe
<临时目录>/probe-venv/bin/python.exe
<临时目录>/probe-venv/bin/python3.14.exe
<临时目录>/probe-venv/bin/python3.14w.exe
$ ls <临时目录>/probe-venv/Scripts
ls: cannot access '<临时目录>/probe-venv/Scripts': No such file or directory
```

> 探测用的 venv 建在系统临时目录，验证完即删除，未污染工程。

## 二、原因

1. **解释器来源不同**：git-bash 的 `PATH` 中 `/c/msys64/mingw64/bin` 排在 Windows 官方 CPython 之前，裸 `python` 命中的是 **MSYS2 mingw64 构建的 Python 3.14.4**，而不是官方 CPython。
2. **venv 目录布局不同**：MSYS2 版 Python 按 POSIX 前缀规则创建虚拟环境，在 Windows 上生成的是 `Include/ + bin/ + lib/ + pyvenv.cfg`（`bin/python.exe`），而官方 CPython 生成的是 `Include/ + Lib/ + Scripts/ + pyvenv.cfg`（`Scripts/python.exe`）。
3. **项目约定**：脚本、README、冒烟脚本统一使用 `.venv/Scripts/python.exe`（官方 CPython 布局），因此 MSYS 布局必然找不到该文件。

补充佐证（交付用的 venv 是官方解释器建的）：

```text
$ ls backend/.venv
Include  Lib  Scripts  pyvenv.cfg
$ ls backend/.venv/bin
ls: cannot access 'backend/.venv/bin': No such file or directory
$ backend/.venv/Scripts/python.exe --version
Python 3.14.0
```

## 三、让码道怎么修

**不改业务代码**，只修正环境与脚本/文档口径：

1. 用官方 CPython 绝对路径重建虚拟环境（先删旧 `.venv`）：

```bash
rm -rf backend/.venv
"C:/Users/<用户名>/AppData/Local/Programs/Python/Python314/python.exe" -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

2. 脚本层防御：`readme/install.sh` 同时探测 `.venv/Scripts/python.exe` 与 `.venv/bin/python`；在 `OS=Windows_NT` 且 `python` 路径命中 `msys` / `mingw` / `/usr/bin/*` 时打印提示，避免静默产出不可用环境。
3. 文档层：`readme/README.md` 常见问题 Q2 写明该陷阱与显式建 venv 的命令。

**禁止项**：不修改 `requirements.txt` 去"适配"MSYS 解释器；不要求用户放弃 git-bash。

## 四、结果

重建后环境可用：

```text
$ ls backend/.venv
Include  Lib  Scripts  pyvenv.cfg
$ backend/.venv/Scripts/python.exe --version
Python 3.14.0
```

`pip install -r requirements.txt` 成功，实测安装版本：

```text
fastapi       0.162.3
pydantic      2.14.3
SQLAlchemy    2.1.8
uvicorn       0.54.0
APScheduler   3.11.3
jieba         0.42.1
openai        3.49.0
python-dotenv 1.2.4
```

后端随后可正常启动，`GET /api/health` 返回 `{"code":0,...}`。

- **是否回归**：`install.sh` 的"已有 `.venv` 保留不删除"逻辑未受影响；本机 Python 3.14 该批次依赖均有可用轮子，未触发编译问题。
- **结论**：已解决。