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

### 1.1 GitHub Token 配置与验证

未认证调用只有 **60 次/小时**，而一次导入课程至少用掉 `/repos` + `/commits` 两格
（大仓库还要 `/git/trees` 或 `/contents`）。配额用光时后端回
`429 RATE_LIMITED`，提示里带「剩余 N/60、HH:MM 后可重试」——**看到这句就说明是配额，
不是网络或代码问题**。

```powershell
# ① 配：.env 里这一行（经典 PAT 勾 public_repo；fine-grained PAT 只需 Contents: Read）
#    REPOLEARN_GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# ② 重启（API 只在启动时读 .env）
.\stop.ps1
.\start.ps1 -SkipInstall
# ③ 验证：应显示 token 指纹，而不是"未配置"
.\.venv\Scripts\python.exe -m repolearn.cli doctor
#    [      ok] GitHub 凭据: 已配置 ghp_…6789（长度 40，上限 5000 次/小时）
```

三种失败形状与各自含义（**别混为一谈**，下一步动作完全不同）：

| 现象 | 后端错误码 | 真实原因 | 处理 |
|---|---|---|---|
| `403 rate limit exceeded` + `X-RateLimit-Remaining: 0` | `RATE_LIMITED`（HTTP 429） | 配额耗尽（未认证 60/h，认证 5000/h） | 等提示里的时间，或配 token |
| `401 Bad credentials` | `INVALID_KEY`（HTTP 401） | token 被撤销/过期/**等号后多了空格**（`Bearer  ghp_…`） | `cli doctor` 会指出 `padded`；修 `.env` 后重启 |
| `403 Forbidden`（无 rate limit 字样） | `REPO_FORBIDDEN`（HTTP 403） | 仓库私有/被封禁 | 换公开仓库（MVP 不支持私有仓库） |

省额度的两条实现细节（改代码时别顺手删掉）：

* `fetch_repo_meta` / `resolve_commit` 有 **60 秒进程内缓存**（`CACHE_TTL_SECONDS`），
  键含 `owner/repo` 与 ref；失败结果不进缓存，所以"修好 token 后立刻重试"能成功。
* `X-RateLimit-Remaining: 0` 时 `request_with_retry` **不做退避重试**：重试只会
  再撞一次同一格配额，代价是用户多等几秒。

## 2. 生成类

| 症状 | 判断 | 处理 |
|---|---|---|
| 课程一直是「生成中」 | API 在 N9 前重启过，`generating` 版本没收敛 | 重启 API：reaper 启动时会把它置 `failed` 并释放 `generation_locks`；或 `cli requeue-stale` |
| Job 卡在 `running` 但没进度 | 心跳停了（进程被杀/挂死） | `cli requeue-stale`（阈值 `REPOLEARN_JOB_STALE_SECONDS`，默认 90s） |
| 课程 `partial` | 部分课时失败 / 锚点覆盖率 < 80% / 章节不全 | 正常降级结果；看 `course.quality_report.reasons`，可点「重新生成」 |
| `failed_budget` | 超 job 级预算（默认 2,000k tokens / 50 USD / 25 分钟）；错误提示里会写明是哪一档、对应哪个环境变量 | 提高 `.env` 的 `REPOLEARN_JOB_MAX_TOKENS` / `REPOLEARN_JOB_MAX_USD` / `REPOLEARN_JOB_DEADLINE_MS`（改完重启 API），或收敛课程规模；已生成课时仍可读 |
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

---

## 真链路 E2E（`node scripts/e2e-real.mjs`）

| 症状 | 原因 | 处理 |
|---|---|---|
| 退出码 **2**，提示端口被占用 | 上一次没清干净，或 `start.ps1` 还在跑 | 先 `.\stop.ps1`，再重跑。编排器**故意不自动换端口**——自动换端口会让"CI 为什么跑的是 3101"变成新的谜 |
| 退出码 2，提示 `.venv` 缺失 | 没建虚拟环境 | ` .\start.ps1 -SkipInstall` 建环境后重跑（不静默回退到系统 python，那会污染全局包） |
| `book-and-degrade` 红，`gates.g2` 是 `unknown` | 第 5.5 步没跑或 `REPOLEARN_RUN_DIR` 没指对 | 看 `var/e2e/<runId>/run/preflight.json` 是否存在；它必须由**本轮**写入 |
| `gates.g2` 是 `ok` 但 PDF 仍降级 | `probe_gates.mjs` 看的是 Node 侧 playwright 缓存，产品降级看的是 **Python** playwright | `python -m playwright install chromium` + `pip install -e ".[pdf]"`，两条都要 |
| `next dev` 与 `start.ps1` 互相把 `.next` 写坏 | 两个 dev server 共用构建目录 | 编排器已设 `REPOLEARN_NEXT_DIST_DIR=.next-e2e`（相对名，见下）；手动并跑时也照做 |
| 假 GitHub 不通 | 端口/夹具路径错，或 `--fixture` 目录不存在 | 单独跑 `python scripts/fake_github.py --port 9911 --fixture tests/fixtures/github --snapshot tests/fixtures/repos/tiny_v1`，看到 `fake-github listening on ...` 即正常 |

> **`.next-e2e` 必须是相对路径**：Next 的 `distDir` 按项目目录解析，传绝对路径会得到
> `apps/web/E:\...` 这种非法目录（实测失败）。它落在 `apps/web/.next-e2e`，与 `.next` 隔离。

## 搜索（FTS）

| 症状 | 原因 | 处理 |
|---|---|---|
| 课程数量不少，但搜 2 个字没结果 | 你在看 `mode` 吗？trigram 的匹配单位是 3 字符 | 响应里的 `fallback_reason` 应为 `query_too_short`；若 `mode=fts` 却返回空，说明闸门被绕过 |
| Doctor 的「搜索」显示 `degraded` | SQLite < 3.34 或编译期没带 trigram（`course_search` 没建） | 升级 Python/SQLite 后自动启用；期间一切查询回落 `LIKE`，功能不少但慢 |
| 新生成的课程搜不到，老课程能搜到 | FTS 触发器被某次 batch 重建删掉了 | `python -m repolearn.cli reindex-search` 重建；再看 `pytest -q apps/api/tests/test_search.py -k trigger` |
| `reindex-search` 打印 `fts unavailable ... nothing to do` 并退出 0 | 能力本来就没有 | 正常。维护命令在"本来就没有"的机器上变红只会训练人忽略它 |

## 升级（仓库有新 commit）

| 症状 | 原因 | 处理 |
|---|---|---|
| 点「检查更新」很久没反应 | 大仓库要下载并解包整包 tarball | 同步路径有 20s 预算，超时返回 `202 + job_id`；去任务列表看进度 |
| 升级后进度"变少了" | `percent` 按公式 `floor(old * kept/old_lessons)` 且不超过 `floor(100*kept/new_lessons)` 下调 | 这是**有意**的：新版本课时变多时，旧百分比不再等价。只降不升是有断言守住的不变式 |
| 升级后锚点跳到别的行 | 复制来的课时锚点指向**旧 commit** | 这是设计（`anchor_origin: "mixed"`），UI 会标注"来自上一版"；要新锚点请用 `/rebuild` |
| `409 JOB_CONFLICT` | 同一新 sha 已有任务在跑 | 响应里带 `job_id`，直接跳过去看，不要重试 |
