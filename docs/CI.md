# 自动化测试

GitHub Actions 在 push、pull request 和手动触发时执行 `.github/workflows/ci.yml`。
工作流只读仓库，不部署应用，不调用真实模型，也不需要模型密钥或仓库 Secrets。

| 检查 | 环境 | 内容 |
|---|---|---|
| Backend reliability | Ubuntu / Windows，Python 3.12 | 逐人成员状态、开始/截止时间、改期、补交、积分幂等、迁移与权限回归 |
| Backend API and SSE integration | Ubuntu，Python 3.12 | 临时数据库启动后端，执行建表、报名、REST、mock AI、增量解析和 SSE/催办套件 |
| Frontend build, voice and public source security checks | Ubuntu，Node.js 22 | 类型检查、生产构建、静态契约与语音切片算法，构建完成后执行既有凭证字面量与交付红线检查 |

后端使用临时 SQLite 数据库，关闭后台定时调度，测试需要时显式调用催办扫描。
可靠性测试和安全扫描的通过结果，不代表真实模型质量、浏览器语音服务或线上部署已验证。
既有交付文档验收依赖本地 AI 工具规划文件，因此不作为公开仓库 CI 的门禁。

本地运行：

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest tests/backend/test_reliability.py -q
bash tests/backend/run_all.sh
npm ci --prefix frontend
bash tests/frontend/run_all.sh
bash tests/security/test_security_redline.sh
```

`bash tests/frontend/run_all.sh` 会完成类型检查、生产构建、静态契约与语音切片算法检查，产出 `frontend/dist`；
随后在同一作业内执行 `bash tests/security/test_security_redline.sh`，与上表合并后的前端作业顺序一致。

后端集成脚本优先使用 `PYTHON_BIN`，其次使用项目虚拟环境，再使用 PATH 中的 Python。
Windows Git Bash 下可显式设置 `PYTHON_BIN=C:/path/to/python.exe`。

本次首个 Git 提交保存初始化时的现有业务实现及 CI 配置。
本地 AI 工具配置、临时数据库、凭证文件、依赖和构建产物不纳入版本控制。
当前登录为用户名自动建号的演示机制；公开源码不等于适合直接部署成公开业务服务。
