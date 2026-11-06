# RepoLearn

> 粘贴一个 GitHub 仓库地址，得到一门**可追溯**的三层 AI 带读课程：
> 宏观架构 → 全局走读 → 深入源码。每一步讲解都能落回 `文件:行号`，
> 无法确定的行为明确标注为「教学模拟」。学完可以生成可在线阅读、可导出 PDF 的课程书籍。

```
浏览器 ──(同源 /api/*)──▶ Next.js 15 (apps/web, :3000)
                                │ BFF 转发 + SSE + Range 透传
                                ▼
                        FastAPI (apps/api, :8000)  ── 业务库 SQLite(WAL)
                                │  AgentRuntime 协议
                                ▼
                    agent-kernel (services/agent-kernel, :8787)
                        @aragon-agent/core  · 9 节点 LangGraph 工作流
```

---

## 1. 一分钟跑起来

前置：**Node.js ≥ 20**、**Python ≥ 3.11**、**pnpm**（`corepack enable`）。

```powershell
.\start.ps1
```

脚本会依次：探测环境（含 Gate 0 依赖三态）→ 安装依赖 → 生成 `.env` 里的密钥 →
迁移数据库 → 插入离线演示课程 → 按 kernel → api → web 顺序启动 → 等待健康检查 →
打印地址。首次打开 `http://localhost:3000` 会被引导到 `/setup` 完成 AI 服务配置。

关闭：

```powershell
.\stop.ps1
```

常用参数：

| 命令 | 作用 |
|---|---|
| `.\start.ps1 -SkipInstall` | 快速重启（跳过 pip/pnpm） |
| `.\start.ps1 -NoWeb` | 只起 API + Kernel（前端另行开发时用） |
| `.\start.ps1 -Port 3100` | 改前端端口 |
| `.\start.ps1 -Prod` | `next build && next start`，`REPOLEARN_ENV=production` |

> 没有 API Key 也能用：Gate 0 检测不到 Agent 内核时，课程降级为**静态分析模板版**
> （真实符号、真实行号，只是讲解深度有限），UI 会明确标注"简化版"。

---

## 2. 首次配置（`/setup` 五步）

1. **选择模型服务** —— Anthropic / OpenAI / Google / 自定义（OpenAI 兼容 / Anthropic 兼容 / Gemini 兼容）
2. **连通性与模型发现** —— 测延迟、列模型、显示每个模型的能力徽标（文本 / 视觉 / 工具 / JSON）
3. **语音服务（豆包 TTS，可跳过）** —— 填 appid / cluster / 音色，可试听 3 秒
4. **角色与默认模型** —— `planner` / `writer` / `critic` / `vision` / `quiz` / `embed` 六个角色各自选模型，支持"按能力自动分配"
5. **完成** —— 写入配置并生成一个新 revision（随时可回滚）

密钥以 AES-GCM 落库（AAD 绑定 profile id，防跨行搬运），出站只回 `last4`，
日志全量脱敏；`payload` 里不含任何密文，因此回滚不会"复活"旧密钥。

---

## 3. 目录结构

```
apps/web/                 Next.js 15 前端（RSC 外壳 + Client 岛屿 + BFF Route Handlers）
apps/api/                 FastAPI 后端
  repolearn/core/         配置 / DB / 错误码 / 日志 / 安全 / 时钟 / ID
  repolearn/models/       26 张表，一表一文件
  repolearn/schemas/      Pydantic v2（契约的唯一来源）
  repolearn/services/     领域服务（无 HTTP 依赖，可被 worker/CLI 复用）
  repolearn/providers/    LLM 四适配器 / TTS / AgentRuntime 三分支
  repolearn/workflow/     LangGraph 九节点 + prompts + 校验 + 发布
  repolearn/jobs/         队列 / runner / 心跳 / reaper / 事件
  repolearn/ingest/       GitHub 抓取 / 解包 / 路径守卫 / 镜像
  repolearn/analysis/     符号 / 调用图 / 知识图 / 关键链
  repolearn/rendering/    Mermaid→SVG / 书籍排版 / PDF
services/agent-kernel/    Node sidecar：@aragon-agent/core 的 Agent + 只读工具 + 预算
packages/contracts/       openapi.json + JSON Schema（前后端唯一契约）
scripts/                  环境探测 / 契约导出 / 夹具 / 清理
docs/                     spec.md（方案）+ runbook / architecture / api
var/                      运行时数据（sqlite、对象存储、日志）— 不入库
```

---

## 4. 常见问题

| 症状 | 处理 |
|---|---|
| `start.ps1` 报端口被占用 | 先 `.\stop.ps1`；它会按 PID + 端口双路清理 |
| 课程是"简化版"，没有 AI 讲解 | Gate 0 的 G1 未通过：`pnpm -C services/agent-kernel install` 后重启；`cli doctor` 可看三态 |
| 没有配音 | 豆包未配置或配额问题：课程会自动切「字幕推进」模式，不影响完课 |
| 下载 PDF 变成"打印视图" | Chromium 未安装：`python -m playwright install chromium` |
| `pnpm install` 报 ignored build scripts | `pnpm approve-builds --all --yes` |
| 生成中途被打断，课程一直"生成中" | 重启服务即可（reaper 会自动把它置为 `failed` 并释放锁） |

更完整的排错手册见 [`docs/runbook.md`](docs/runbook.md)。

---

## 5. 门禁与可证明（CI）

`.github/workflows/ci.yml` 六个 job，每个都对应一条"否则只能靠人记得敲"的命令：

| job | runner | 做什么 |
|---|---|---|
| `api` | windows-latest（**必须 Windows**：要真调 PowerShell 5.1 解析 `start.ps1`） | `ruff` + `pytest` + `export-openapi --check` |
| `kernel` | ubuntu + Node **22** | `npm ci` + `node --test` + `tsc` |
| `web` | ubuntu + pnpm **12.18.0**（显式 pin） | `contracts:check` + `tsc` + `vitest` + `next build` |
| `e2e-offline` | ubuntu | `playwright test`（44 条离线用例，零后端） |
| `e2e-real` | ubuntu，`needs: [api, web]` | `node scripts/e2e-real.mjs`（三进程 + 假 GitHub） |
| `gates` | ubuntu | 只做一件事：全部成功则 `exit 0`，作为**唯一** required status check |

两条纪律写在 workflow 注释里：**不许 `continue-on-error`**（把门禁软化等于删掉它），
**lockfile 与 devDependency 必须同一次提交**（否则 `--frozen-lockfile` 首跑就红）。

---

## 6. 真链路端到端（`scripts/e2e-real.mjs`）

离线 E2E 打的是"前端契约"，真链路打的是"前端契约 ↔ 后端行为"这条最容易断的缝。
编排器做八件事：端口探测（占用即失败，退出码 2，**不自动换端口**）→ 隔离目录
`var/e2e/<runId>/`（db / objects / logs / run）→ 11 个显式环境变量（不继承开发机
`.env`）→ `migrate` + `seed-demo` → **本轮** Gate 0 探测写 `preflight.json` →
起 fake GitHub / api / web → 等三处就绪 → 跑 `playwright.real.config.ts` 并收整棵
进程树，写 `var/e2e/last-run.json`。

`runtime=template` 是关键：整条链路在没有 LLM Key 的机器上也能跑，因此这条门禁
在 CI 上不会变成 always-skip。四条用例覆盖：导入→SSE→工作台→播放、答题→证据→
重放幂等→完课、书籍→PDF 入口与 `g2` 一致、真后端 scan/fts 结果集一致。

---

## 7. 企业自建 GHE

```powershell
# .env
REPOLEARN_GITHUB_API_BASE=https://ghe.example.com/api/v3
REPOLEARN_GITHUB_WEB_BASE=https://ghe.example.com
```

端点**只能来自服务端环境变量**（请求体里没有任何参数能改它，否则就是一个 SSRF 洞）。
而端点的返回值按**不可信数据**处理：`html_url` 走 scheme+host 白名单（否则回退到
配置拼装，防存储型 XSS）、重定向逐跳校验（防 302 SSRF）、体积同时校验 `Content-Length`
与解包累计（防"声称 1KB 实发 1GB"）。Doctor 面板会显示当前端点与 token 状态。

---

## 8. 搜索模式（`REPOLEARN_SEARCH`）

| 配置 | 查询长度 | 生效模式 | 说明 |
|---|---|---|---|
| `scan` | 任意 | `scan` | `LIKE` 扫描，`limit ≤ 50`，keyset 游标 |
| `fts` | ≥3 字 | `fts` | FTS5 `trigram` + `bm25` 排序，`offset ≤ 200` 分页 |
| `fts` | 1–2 字 | **`scan`（回落）** | `fallback_reason=query_too_short` |
| `fts` | 任意 | `scan`（若 SQLite < 3.34 或无 trigram） | `fallback_reason=sqlite_too_old` |

为什么必须回落：trigram 的匹配单位是 **3 字符**，2 字中文查询（"缓存""异步""入口"）
在 FTS 下**返回 0 行且不报错**——库里有、用户搜不到。这比"慢"严重一个数量级。
响应里的 `mode` 是**实际生效**模式而不是配置值：让"开关说了 fts、其实走的 LIKE"
这种谎言不可能再出现。

---

## 9. 版本升级（仓库有了新 commit）

课程页顶部「检查更新」→ `POST /v1/courses/{id}/upgrade {dry_run:true}` →
抽屉展示受影响课时 → 确认后生成**新版本**。与「重新生成（`/rebuild`）」的区别：

| | `/rebuild` | `/upgrade` |
|---|---|---|
| commit | 同一个 sha | **新的** sha |
| 旧数据 | 同一版本内被覆盖 | 旧版本**原样保留** |
| 学习进度 | 不变 | 按公式迁移（只降不升） |
| 成本 | 可能全门重跑 | 只重讲被改动文件涉及的课时 |

判定是保守的文件级 diff（按 sha256 比对两份镜像，不用 git、不执行仓库代码）：
受影响课时 > 60% 或新增文件超过阈值 → 全量重建；否则只重讲受影响课时，其余深拷贝
（`playback_meta.copied_from` 可追溯）。复制来的课时锚点指向**旧 commit**，
UI 标注"来自上一版"，质量报告写 `anchor_origin: "mixed"`。

---

## 10. 开发

```powershell
# 后端
.\.venv\Scripts\python.exe -m pytest -q                 # 单测 + API 集成
.\.venv\Scripts\python.exe -m repolearn.cli doctor      # 依赖三态
.\.venv\Scripts\python.exe -m repolearn.cli export-openapi --check   # 契约漂移

# 前端
cd apps/web; npx tsc --noEmit; npm run test; npx next build

# 端到端（离线，playwright，不需要后端/API Key）
pnpm e2e                                                 # = cd apps/web && npx playwright test
npx playwright install chromium                          # 首次运行需要一次

# 契约生成 / 漂移门禁
pnpm contracts                                           # 生成 schema.d.ts + contracts/src/types.ts
pnpm contracts:check                                     # CI 门禁：不一致即失败

# 真后端端到端（三进程 + 假 GitHub，隔离 DB/对象/日志，不需要 API Key）
node scripts/e2e-real.mjs                                # 退出码 0 全绿 / 1 有用例失败 / 2 环境不可用
node scripts/e2e-real.mjs --spec import-to-lesson         # 只跑一条
python -m repolearn.cli e2e-report                        # 最近一次结果摘要

# 搜索索引维护（幂等；无法用 FTS 时打印一行并 exit 0）
python -m repolearn.cli reindex-search --batch 500

# 文档与清单自证
python scripts/count_workfiles.py docs/plans/repo-learn-hardening/spec.md
node scripts/probe_gates.mjs --print                     # Gate 0 三态，与 /healthz.gates 同源

# Agent 内核
cd services/agent-kernel; npm test; npm run typecheck
```

测试现状（本机实测，2026-11-06 复审轮）：**250 pytest + 37 kernel + 78 vitest + 44 playwright** 全绿，另有 **4 条真后端端到端**（`node scripts/e2e-real.mjs`）。
这组数字由 `tests/test_ci_and_docs.py::test_readme_test_matrix_matches_repo` 守住：README 写的 pytest 收集数与仓库实测不一致就直接红——文档说谎是本项目最不能接受的一类缺陷。

设计文档：[`docs/plans/repo-learn-platform/spec.md`](docs/plans/repo-learn-platform/spec.md)
（架构、接口、数据模型、测试编号、里程碑，以及评审记录）。
