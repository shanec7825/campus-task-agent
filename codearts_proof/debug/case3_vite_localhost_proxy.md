# 案例 3：Vite 5 只监听 localhost（IPv6），且 `/api` 代理硬编码 8000

> 记录日期：2026-11-11 · 环境：Windows 11 + Node v22.17.0 + Vite 5.4.21

## 一、现象

T11 前端联调为避开标准端口占用，使用**后端 8010 + 前端 5174** 的组合，出现三个互相叠加的现象：

| 操作 | 结果 |
|---|---|
| `curl http://localhost:5174/` | `200`（页面能打开） |
| `curl http://127.0.0.1:5174/` | 无响应（连接被拒/超时） |
| 浏览器访问 5174 页面，前端请求 `GET /api/health` | `500`（接口全挂，但页面本身正常） |

真实记录出处：`tests/frontend/README.md:78-81`、`tests/frontend/MANUAL_CHECKLIST.md:16`，以及 `tests/security/ACCEPTANCE.md:120`（`vite preview` 需显式 `--host 127.0.0.1`）。

## 二、原因

1. **本机把 `localhost` 优先解析为 IPv6**：实测 Node v22.17.0

```text
$ node -e "require('dns').lookup('localhost',{all:true},(e,a)=>console.log(JSON.stringify(a)))"
[{"address":"::1","family":6},{"address":"127.0.0.1","family":4}]
```

Vite 5 在 `server.host` 未显式设置时只监听 `localhost`（本机即 `::1`），因此 `127.0.0.1` 上没有监听，直连必然无响应。这是本机解析差异，不是项目缺陷。

2. **代理目标硬编码**：`frontend/vite.config.ts` 由 T1 冻结，`proxy['/api'].target` 固定为 `http://127.0.0.1:8000`。后端改到 8010 后，代理仍把 `/api` 打到未启动的 8000，连接拒绝被 Vite 转成 **HTTP 500**。

## 三、让码道怎么修

**不改 `vite.config.ts`**（冻结契约；一旦改动会影响 8000/5173 的标准验收与 T12 的端口比对），改用流程约束：

1. **人工验收固定标准端口**：浏览器地址一律用 `http://localhost:5173/`（被占用时用 `http://localhost:5174/`），**禁止用 `127.0.0.1`** 访问前端。
2. **非标端口组合只做两段式冒烟**，不通过前端代理断言接口：
   - ① 页面可访问性：`curl http://localhost:5174/` 与 `/login` 都应 `200`；
   - ② 后端直连：`curl http://127.0.0.1:8010/api/health` 等接口断言 `code=0`。
3. **预览构建产物需显式绑地址**：`vite preview` 加 `--host 127.0.0.1`（T12 的实际做法），否则 `127.0.0.1` 首轮连接被拒。
4. **文档与清单显式提示**：把"前端能开但接口全 500"写入常见问题与人工清单前置条件，避免误判为功能缺陷。

## 四、结果

- 两段式冒烟（T11 真实记录，`tests/frontend/README.md:110-111`、`MANUAL_CHECKLIST.md:166-167`）：
  - 后端 8010 + 临时库 + `MAAS_MOCK=1`：`/api/health`（8 表 + `mock=true`）、`login`、`/api/tasks`、`/api/agent/extract`、`/api/agent/review`、`/api/agent/stream/parse`、`/api/kb/similar` 全部 `code=0`；
  - 前端 `http://localhost:5174/` 与 `/login` 均 `200`。
- 代理 500 被判定为**预期行为**（代理指向未启动的 8000），不计缺陷，已写入 `tests/frontend/README.md:131` 的排查表。
- T12 侧复现与规避：`vite preview --host 127.0.0.1` 后 `127.0.0.1:5175` 可访问（`tests/security/ACCEPTANCE.md:120`），最终 R09 判定 PASS。

**复现命令**（根因部分无需启动前端；端口部分需先执行 `cd frontend && npm run dev -- --port 5174`）：

```bash
# 根因：localhost 优先解析为 IPv6
node -e "require('dns').lookup('localhost',{all:true},(e,a)=>console.log(JSON.stringify(a)))"

# 端口行为（需前端已在 5174 运行）
curl -s -o /dev/null -w "localhost:5174 -> %{http_code}\n" http://localhost:5174/
curl -s -m 3 -o /dev/null -w "127.0.0.1:5174 -> %{http_code}\n" http://127.0.0.1:5174/
```

- **是否回归**：未改动任何前端配置与源码；标准端口（8000/5173）验收路径不受影响。
- **结论**：已解决（通过流程约束与文档提示解决，而非修改冻结的 `vite.config.ts`）。