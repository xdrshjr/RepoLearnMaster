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

## 5. 开发

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

# Agent 内核
cd services/agent-kernel; npm test; npm run typecheck
```

测试现状（本机实测）：**197 pytest + 37 kernel + 62 vitest + 14 playwright** 全绿。

设计文档：[`docs/plans/repo-learn-platform/spec.md`](docs/plans/repo-learn-platform/spec.md)
（架构、接口、数据模型、测试编号、里程碑，以及评审记录）。
