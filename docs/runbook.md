# 排错手册（runbook）

> 面向"出了问题要立刻知道看哪里"的人。所有路径相对仓库根。

## 0. 30 秒定位法

```powershell
.\.venv\Scripts\python.exe -m repolearn.cli doctor   # 各依赖三态 + hint
curl http://127.0.0.1:8000/healthz                   # db / kernel / migration / gates
curl http://127.0.0.1:8787/healthz                   # coreVersion / activeRuns
Get-Content var\logs\api.err.log -Tail 40            # 后端真正报错的位置
```

`/healthz` 的三块分别回答：数据库能不能连、Kernel 是哪一档（kernel/exec/template）、
迁移跑没跑、Gate 0 三态。**任何"启动成功但功能缺失"都应先看这里**，而不是先翻代码。

## 1. 启动类

| 症状 | 原因 | 处理 |
|---|---|---|
| `start.ps1` 立即退出，提示 node/python 版本 | 环境不满足（Node < 20 / Python < 3.11） | 装对应版本；`scripts\check_env.ps1` 会给出准确指引 |
| 端口占用（退出码 2） | 上一次没关干净 | `.\stop.ps1`（按 PID + 端口双路清理）；或 `.\start.ps1 -Port 3100` |
| API 60 秒内没健康（退出码 3） | 迁移没跑 / 依赖缺失 / 端口被占 | 看 `var\logs\api.err.log`；`cli migrate` 手动补 |
| **Web 页面 500，日志里有 `EvalError: Code generation from strings disallowed`** | 机器上有全局 `NODE_ENV=production`，`next dev` 的 edge middleware 沙箱因此禁用代码生成 | `start.ps1` 已显式钉住 `NODE_ENV`；如果你是手工起前端，请先 `$env:NODE_ENV='development'` |
| **`start.ps1` 起不到前端，报 `%1 不是有效的 Win32 应用程序`** | 直接 `Start-Process pnpm`：pnpm 是 `.cmd`/`.ps1` 垫片 | 已修复（经 `cmd.exe /c` 启动）；手工启动时用 `pnpm -C apps/web dev` |
| Web 起不来但 API 正常 | `apps/web/node_modules` 缺失或 `.env.local` 冲突 | `pnpm install`；确认没有手写 `REPOLEARN_API_BASE` 到客户端组件 |
| `seed-demo` 第二次执行报唯一约束 | 旧版本非幂等 | 已修复；如仍报错先 `cli migrate` 再跑 |
| PowerShell 报"字符串缺少终止符" | 脚本被编辑器存成了无 BOM 的 UTF-8 + 中文 | 本仓库脚本一律 ASCII；改动时保持 ASCII，或存成 UTF-8 BOM；`scripts\parse_check.ps1` 可验证 |

## 2. 生成类

| 症状 | 判断 | 处理 |
|---|---|---|
| 课程一直是「生成中」 | API 在 N9 前重启过，`generating` 版本没收敛 | 重启 API：reaper 启动时会把它置 `failed` 并释放 `generation_locks`；或 `cli requeue-stale` |
| Job 卡在 `running` 但没进度 | 心跳停了（进程被杀/挂死） | `cli requeue-stale`（阈值 `REPOLEARN_JOB_STALE_SECONDS`，默认 90s） |
| 课程 `partial` | 部分课时失败 / 锚点覆盖率 < 80% / 章节不全 | 正常降级结果；看 `course.quality_report.reasons`，可点「重新生成」 |
| `failed_budget` | 超 job 级预算（180k tokens / 0.35 USD / 25 分钟） | 提高 `REPOLEARN_JOB_MAX_TOKENS`，或收敛课程规模；已生成课时仍可读 |
| `CONTRACT_VIOLATION` | 模型产出连续两次不合 schema | 换更强的模型（设置 → 角色），或降低课时数 |
| 课程内容明显是"简化版" | Agent 内核不可用（状态 C） | `pnpm -C services/agent-kernel install`；`cli doctor` 看 G1 |
| 锚点行号对不上 | 分析降级（无 tree-sitter），或 commit 变了 | `pip install tree-sitter-language-pack`；或重建课程 |

### 心跳与回收的判定逻辑（排错时最有用的一条）

节点执行期间每 15 秒写一次 `jobs.heartbeat_at`，**回收阈值只在心跳也停更时才生效**。
所以"任务被自己判死然后重复烧 token"这件事在当前实现里不会发生；如果你看到
`attempts > 1`，那是进程真的退出过。

## 3. 音频 / PDF

| 症状 | 处理 |
|---|---|
| 播放器显示"无配音" | 豆包未配置或 3 次重试失败 → `timing_source=estimated`，字幕自动推进（设计如此） |
| 试听失败（`/setup` 第三步） | 检查 appid / cluster / access_token 是否同一应用；火山控制台需开通「语音合成」 |
| 音频拖动卡住 | 检查 BFF 是否透传了 `Range`（应返回 206 + `Content-Range`）；`curl -I -H "Range: bytes=0-3" http://127.0.0.1:8000/v1/objects/audio/<key>` |
| PDF 导出变"打印视图" | Chromium 缺失（G2）；`python -m playwright install chromium` 后重试 |
| PDF 页数为 0 | `pdf_exports.error` 有原因；引擎不可用时**不会**生成假 PDF（这是刻意的） |

## 4. 数据与磁盘

```powershell
# 数据在
var\data\repolearn.db          # 业务库（WAL）
var\data\langgraph.sqlite      # LangGraph checkpoint（故意与业务库分文件）
var\objects\mirrors\<sha8>\    # 仓库镜像（只读，LRU 2GB）
var\objects\audio\<hh>\<hash>.mp3
var\objects\pdf\, diagrams\, artifacts\
```

- **备份**：直接拷 `var\data\repolearn.db`（先停服务，或接受 WAL 未合并）；
  `var\objects` 是内容寻址的，可单独备份。
- **清理**：`cli prune`（镜像 LRU + 过期幂等键）。它**只删镜像**——音频/PDF 被数据库引用，
  误删会直接 404。
- **重置**：删 `var\` 后 `cli migrate` + `cli seed-demo`。

## 5. 契约漂移

```powershell
.\.venv\Scripts\python.exe -m repolearn.cli export-openapi          # 重新导出
.\.venv\Scripts\python.exe -m repolearn.cli export-openapi --check  # CI 用：不一致即失败
```

改了后端 schema 却没重新导出，`--check` 会失败。这是**唯一**能阻止
"后端改了字段、前端还在传旧字段"的机制——不要绕过它。

## 5.5 端到端测试（离线层）

```powershell
cd apps\web
npx playwright install chromium   # 仅首次（约 200MB）
npx playwright test               # 14 条，离线，不需要后端 / 不需要 API Key
```

- 全部请求由 `page.route('**/api/**')` 顶替，因此它验证的是**前端契约**，不是后端。
  后端仍然靠 `pytest`（197 条）与 `docs/api.md` 的约定负责。
- 失败排查顺序：`test-results/**/error-context.md` 里有失败瞬间的无障碍树快照，
  比截图更能定位"元素到底在不在"；需要逐帧回放时用
  `npx playwright show-trace test-results/**/trace.zip`。
- 报 `Executable doesn't exist at ...ms-playwright` → 忘了 `npx playwright install chromium`。
- 报 `webServer` 启动超时 → 端口 3000 被占用；`reuseExistingServer` 只在
  `start.ps1` 已经起过 web 时才复用，`stop.ps1` 后重跑即可。
- 断言全文案（而不是正则）是有意的：文案是产品的一部分，改文案时用例就是回归清单；
  但文案同时出现在字幕条与 Momo 侧栏，因此用例一律**限定区域**断言。

## 6. 安全相关

- 内部令牌：`REPOLEARN_INTERNAL_TOKEN` 由 `start.ps1` 首次生成。缺失时 API 会**放行**
  （本地 CLI 调试用），生产环境必须存在。不带令牌直接打 `:8000/v1/*` 应返回 401。
- 密钥轮换：`POST /v1/settings/rotate-secret`（需 CSRF）。失败同事务回滚。
  轮换后把旧 key 放到 `REPOLEARN_SECRET_KEY_PREVIOUS` 可平滑过渡。
- 日志里出现密钥说明有回归：`cli doctor` 之后 grep `var\logs\*.log`，命中即 bug
  （`core/logging.py::redact` 是最后一道网）。

## 7. 已知边界

- SQLite 单写者：`REPOLEARN_MAX_CONCURRENT_JOBS` 默认 1。调大不会更快，只会更容易撞 `busy_timeout`。
- 搜索默认全表扫描（`limit ≤ 50` + 300ms 超时）。课程量到数千条再考虑 `REPOLEARN_SEARCH=fts`。
- 未登录单用户（`usr_local`），但所有查询都带 `user_id`，为多用户留了形状。
- 不执行用户仓库代码：整条链路没有 `subprocess` 执行仓库内容的路径。
