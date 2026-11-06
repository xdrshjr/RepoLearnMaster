# RepoLearn 全栈平台 · 开发方案（spec.md）

> **文档版本**：**v2**（v1 首次方案设计 → v2 评审修订版）
> **状态**：**已评审 · 有条件通过**（见文末 `## 评审结论`）
> **日期**：2026-11-06（v1）/ 2026-11-06（v2 评审修订）
> **作者**：v1 方案架构节点；v2 由评审节点（Anthropic 工程视角，资深评审）逐节评审并就地修订
> **需求来源**：`doc/RepoLearn_PRD_v1.docx`（PRD v1.0）+ `doc/*.png`（7 张视觉设计稿）+ 本轮任务书"当前阶段"
> **交付物**：本文件。后续节点（开发 → Review）以本文件 §4 的"文件 / 模块变更计划"为执行清单，以 §10 的里程碑为交付顺序，以 §8 的测试编号为验收依据。

> **v2 相比 v1 的实质变化（一句话版）**：v1 的产品理解、三进程拓扑与"可追溯"设计是站得住的；v2 修正了 6 处"照做会跑不起来或跑起来就错"的缺陷（LangGraph 执行模型、浏览器同源通路、数据模型缺表、预算口径、Python 入口、外部依赖前置校验），把 14 处边界缺失补成可执行规则，并把 16 步一次铺完的排期改成"先纵切后铺量"的里程碑。**所有 P0/P1 已在正文就地修订，正文即最终口径，无需再对照 v1 阅读。**

---

## 评审记录（Review Notes）

> **评审对象**：本文件 v1 全文（14 章 / 约 1.28 万字中文正文）
> **评审人**：评审节点（资深评审，Anthropic 工程视角）
> **评审日期**：2026-11-06
> **结论摘要**：**有条件通过**。6 项 P0 与 14 项 P1 全部在 v2 正文就地修复（每条都给了落点章节）；14 项 P2 记录在案但不阻塞开工（其中 4 项顺手修掉）。

### 评审方法（四维，逐节过一遍）

| 维度 | 判据 | 本次发现的问题集中在 |
|---|---|---|
| **可行性** | 用项目现有/计划的技术栈，这段设计能不能真的实现？版本基线、异步模型、平台限制（Windows）、外部依赖是否可获取 | LangGraph 同步/异步 checkpointer、跨源 cookie、`weasyprint` 在 Windows、`aragon` CLI 与 npm 包同一失败域、无依赖前置校验 |
| **完备性** | 边界情况、错误路径、重启与回收、上线关注点是否写全 | Job 心跳、僵尸 `generating` 版本、答题幂等所需表、幂等键作用域、密钥在 Kernel 日志里的暴露 |
| **一致性** | 是否与 §2.1 已核实事实冲突；是否与本文其他章节自相矛盾 | 并发默认值 1 vs 2、音频 URL 两套写法、E2E 策略两套说法、文件清单与表清单对不上、预算三层量级打架 |
| **规模匹配** | 是否过度设计或欠定义 | 180 文件 / 16 步无纵切里程碑；CI 里塞了不可复现的性能门禁；`EXPLAIN` 门禁对模糊搜索不可达成 |

### P0（阻塞项：不修则交付不出"能跑的产品"，全部已修）

| # | 维度 | 问题（v1 原文） | v2 处置与落点 |
|---|---|---|---|
| **P0-1** | 可行性 | `checkpointer=SqliteSaver(...)` 配 `graph.ainvoke()`：`SqliteSaver` 是同步实现，异步图跑起来直接报错；并行 `Send` 分支写同一 state 字段却没有任何 reducer，LangGraph 会抛 `InvalidUpdateError`；state 里塞整份 `lessons`/`tree`/`knowledge_graph`，每次 superstep 都全文序列化数 MB 进 SQLite | §3.4 改为 `AsyncSqliteSaver`（`aiosqlite`）并说明与业务库物理隔离；给出**显式 reducer 表**（`lessons/traces/narration/failed_lessons/warnings`）；给出**单次 checkpoint ≤ 256 KB 体积预算**与"状态只存引用、产物体外持久化"的落地方式 |
| **P0-2** | 完备性 | 浏览器在 `:3000`、API 在 `:8000`：`SameSite=Lax` 的会话 cookie 不会随跨源 `fetch` 发送，于是 CSRF 双提交、SSE 的事件流鉴权、"Range 拖动音频"三件事同时失效；而 §3.11.5 又写"所有请求经 `lib/api/client.ts`"直连 API，两处口径冲突 | 新增**单一同源通路**硬约束：浏览器只与 Next.js 同源通信，API 只监听 `127.0.0.1` 且不面向浏览器；BFF Route Handler 负责转发（含 SSE 与 `Range`）。落点 §2.2 约束 6、§3.1、§3.3、§3.12、§7.5、§5.1 |
| **P0-3** | 完备性 | 数据模型与文件清单对不上：§6.2 有 `pdf_exports` 表但 §4.4 的模型文件清单里没有它；§5.2 的答题接口与 §8.2 的 T-QUIZ-1（重复提交幂等）需要一张答题记录表，全文**没有任何表承载它**；§6.1 写的"软删仅用于 `courses`"，而 `courses` 表并不存在 | §6.1 明确"**课程聚合根 = `course_versions`**，`course_id` 即 `course_versions.id`"；新增 `quiz_attempts` 表（幂等键 = `(user_id, quiz_item_id)`）；§6.2 表清单定为 **26 表**，§4.4 模型文件定为 **27 个**（26 表 + `__init__.py`，含 `pdf_export.py`、`quiz_attempt.py`、`idempotency_key.py`） |
| **P0-4** | 一致性 | 预算三层量级互相矛盾：§5.4 把"单次 run"上限定为 `maxTokens=180000`，而一次课程约有 23 次 run（N5 + 12×N6 + 12×N7），job 级却又写"≤180k tokens / ≤0.35 USD / 25 分钟" | §3.4 改为 **job / 节点 / run 三级预算表**（job 180k tokens 与 0.35 USD 为总闸，N5 20k、N6 每课时 9k、N7 每课时 2k、预留 28k）；§5.4 的单 run 默认值改为跟随节点（9k–20k、`maxTurns=16`）；§8.4 的成本门禁标注为 job 级 |
| **P0-5** | 可行性 | 根 `pyproject.toml` + `apps/api/repolearn` 的布局下，`python -m repolearn.cli` 没有定义可执行方式，而这正是 §10 步骤 1 的完成判据——第一步就不可达 | §4.1 `pyproject.toml` 行给出 `[tool.hatch.build.targets.wheel] packages = ["apps/api/repolearn"]` 与 `python -m venv .venv` + `pip install -e .` 的明确路径；§10 的 M0 判据同步改为 `python -m repolearn.cli --help` 在 `.venv` 内可跑 |
| **P0-6** | 可行性 | 三个**核心外部依赖在 Windows 上是否真能装**，全文没有做任何前置校验，也没有失败提示：`@aragon-agent/core`（闭源 npm 包，若私有 registry 不可达则 N5/N6/N7 主路径全废）、Chromium（PDF 引擎）、`tree-sitter` 语言轮子（N4 分析） | 新增 **§2.4 Gate 0 依赖可用性校验**：三条 `npm view` / `pip download` / Playwright 探测命令 + 各自失败时的降级路径与用户可见提示；`start.ps1` 在安装阶段前先跑 Gate 0 并把结果写进 `/healthz` 与设置页 Doctor 面板 |

### P1（重要：影响可用性/可靠性/可维护性，全部已修）

| # | 维度 | 问题 | v2 处置与落点 |
|---|---|---|---|
| **P1-1** | 完备性 | Job 心跳只在"节点推进"时写；N6 单节点可连续跑 10 分钟以上，必然触发 90 秒无心跳回收 → 误判为死任务、重复执行、重复烧 token | §3.11.2 规定**节点执行期间启动后台心跳**（每 15 秒更新 `heartbeat_at`），回收阈值只在心跳也停止时才生效 |
| **P1-2** | 一致性 | 并发 Job 默认值两处冲突：§3.12 写"并发 Job 上限默认 2"，R4 写"单 worker + 串行 claim（默认并发 1）" | 统一为 `REPOLEARN_MAX_CONCURRENT_JOBS`，**默认 1**（SQLite 单写者），PG 下建议 2；§3.12 与 R4 同步 |
| **P1-3** | 一致性 | `lessons.playback(JSON)` 被定义为"课时主体"，同时 `steps` 表又把 `playback.steps` 拆行——同一批数据两处写，没有同步规则，迟早分叉 | §6.2 规定**单一真源 = `steps` 表**；`lessons.playback` 只保留非步骤字段（`files`/`trace_key`/`certainty_legend`），`PlaybackBundle` 由二者拼装 |
| **P1-4** | 一致性 | §5.3 示例里音频地址是 `/objects/audio/ab/abc.mp3`，§5.2 定义的路由是 `/v1/objects/{kind}/{name}`，前端照抄会 404 | §5.3 示例改为对外 `/api/objects/audio/<hash>.mp3`（BFF 同源）→ 内部 `/v1/objects/audio/<hash>.mp3`，并写明 `Range`/`ETag` 透传 |
| **P1-5** | 可行性 | 把 SSE 与二进制流挂在 Next.js Route Handler 上，在 `next start` 或反代下会被缓冲（首帧迟迟不到、音频拖动失效），v1 的 §7.5 没有任何约束 | §3.3/§7.5 固定要求：`runtime="nodejs"`、`dynamic="force-dynamic"`、`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`、逐 chunk `flush()`、`Range` 原样透传 |
| **P1-6** | 可行性 | 在 `app/layout.tsx` 的服务端组件里做"300ms 超时后 `redirect('/setup')`"：RSC 没有超时能力，且 API 不可达时会对 `/setup` 自身也重定向，形成 302 循环 | §3.6.1 改为 `middleware.ts` 守卫（只读 cookie 中的 `setup_done` 标记 + 仅对白名单路径生效），API 不可达时**fail-open**：渲染"后端未就绪"页并给 `start.ps1` 排错指引，不重定向 |
| **P1-7** | 可行性 | 把 `weasyprint` 当作 PDF 兜底引擎：它在 Windows 需要手工安装 GTK/Pango，等同不可用，"兜底"是假的 | §13 问题 2 与 §3 相关表述改为：**MVP 唯一引擎 = Chromium**（`playwright install chromium`，由 `start.ps1` 负责），兜底是"打印优化 HTML + 浏览器打印为 PDF"，不再提 `weasyprint` |
| **P1-8** | 可行性 | `ExecCliRuntime` 用 `npx aragon exec` 兜底，但 `aragon` CLI 与 `@aragon-agent/core` 来自同一个包：包装不上时两条路一起废，降级链给人假的安全感 | §3.5.3/§3.5.4 明确**失败域**：`ExecCliRuntime` 只在"包已安装、Kernel 进程挂了"时有用；包不可用时的真正第二通道是**模板降级**（`quality_report.degraded=true` 并在 UI 明示），并在 Doctor 面板区分这三种状态 |
| **P1-9** | 完备性 | T-DB-2 要求"列表查询 `EXPLAIN` 无全表 SCAN"，但 `GET /v1/courses?q=` 用的是 `LOWER(col) LIKE LOWER(?)`，必然 SCAN —— 这条门禁永远不可达成 | §8.2 把 T-DB-2 收窄为"**游标分页主查询**必须命中复合索引"；模糊搜索单独定义：SQLite 走 FTS5 虚表、PG 走 `tsvector`，未启用 FTS 时显式允许扫描但 `limit ≤ 50` 且超时 300 ms |
| **P1-10** | 一致性 | E2E 策略自相矛盾：§8.1 写"`webServer` 起真实三进程，或用种子课程 mock"，§8.3 写"E2E 一律离线"；且"播放器 ≥55fps 用 `requestAnimationFrame` 计数断言"在无头 CI 里不可复现，会成为随机红灯 | §8.3 定为**离线 E2E 为主**（`page.route` 拦截）＋**1 条 real-backend 冒烟**（独立 CI 作业，允许失败重试）；帧率从 CI 硬门禁移除，改为本地基准脚本 + Chrome trace 抽检（长任务 < 50 ms） |
| **P1-11** | 规模匹配 | 180 文件 / 16 步一次铺完，中间没有任何"端到端可运行"的里程碑。这种排期最可能的结局是：交付一个文件很多、但 `.\start.ps1` 拉不起来的仓库 | §10 重组为 **M0 walking skeleton（三进程 + 向导 + 种子课程 + 启停脚本，必须真能打开页面）→ M1 数据与治理 → M2 摄取分析 → M3 生成工作流 → M4 学习工作台 → M5 完课/书籍/设置 → M6 收尾**；同时把 4 项非 MVP（`docker-compose.yml`、豆包 WS 流式试听、PDF 视觉回归、独立 `apps/worker`）标注为 defer（§11 第 19 项） |
| **P1-12** | 完备性 | `jobs.idempotency_key` 建的是**全局唯一**索引：`POST /v1/courses` 与 `POST /v1/books` 用同一个 UUID 会互相踩；`llm_profiles.active` 没有任何约束，可以同时存在两个 active profile，`/v1/setup/state` 的判定随即失真 | §6.2 幂等键改为 `idempotency_keys(scope, key, ...)` 复合唯一（scope = 路径模板）；`llm_profiles` 增加**部分唯一索引** `UNIQUE(active) WHERE active = 1`（PG 为 partial unique index） |
| **P1-13** | 完备性 | API 进程重启后，`course_versions.status='generating'` 的行永远不会收敛：用户看到"生成中"永远转圈，且同 `cache_key` 的新请求被 `generation_locks` 挡住 | §3.11.2 增加 **reaper**：启动时 + 每 60 秒把"`generating` 超过 job deadline + 5 分钟且无活跃 Job"的版本置 `failed`（`warnings` 记 `ORPHANED_GENERATION`），并释放对应 `generation_locks` |
| **P1-14** | 完备性 | Kernel 请求体里带明文 API Key，但 §3.13 只要求"结构化日志"，没有"**禁止记录请求体**"的硬约束；Fastify 默认 logger 与错误上报都可能把 body 打进日志文件 | §3.5.2 增加：`disableRequestLogging: true`、错误序列化白名单字段、密钥只在单次 run 的内存闭包中存活并在 `run.completed` 后置空；§3.13 增补"请求体不落日志"为硬规则，并在 T-SEC-1 里增加一条对 Kernel 日志的断言 |

### P2（记录在案，不阻塞开工；1–4 项已在 v2 顺手修掉）

| # | 问题 | 处置 |
|---|---|---|
| **P2-1** | `probe` 接口"失败也是 200"与 §5.1"失败统一错误体"的例外关系没写明 | **已修**：§5.2 标注 `probe` 为"测量接口"，200 + `ok=false` 是唯一例外，且其 `error.hint` 仍遵循同一形状 |
| **P2-2** | `settings_revisions.payload` 若含密文字段，回滚会把旧密钥"复活" | **已修**：§6.2 注明 `payload` **不含任何密文**，只存 `profile_id` 引用与角色分配 |
| **P2-3** | `course_versions.sections(JSON)` 与 `lessons.section_key` 双表达课程大纲 | **已修**：`sections` 为大纲权威，`lessons.section_key` 是冗余过滤列，由发布事务保证一致 |
| **P2-4** | `-Prod` 参数语义未定义（被 §4.1 当作接口暴露） | **已修**：§4.1 写明 `-Prod` = `next build && next start` + `REPOLEARN_ENV=production` + 不启用热重载 |
| **P2-5** | `ai_cache` 的 7 天过期与 `policy_version` 提升无联动 | 记录：policy 提升时清空相关 `ai_cache`（`scripts/prune_objects.py --ai-cache`） |
| **P2-6** | `mutagen` 缺失时时长只能估算（`duration_source="estimated"`） | 记录：估算偏差影响时间轴精度，已在 §3.8 标注 |
| **P2-7** | `job_events` 只保留 500 条，25 分钟长任务的 SSE 续传边界 | 记录：超出时以 `GET /v1/jobs/{id}` 快照对齐（§7.5 已有此路径） |
| **P2-8** | Azure OpenAI 的 deployment-name URL 形态未展开 | 记录：`compat_map.py` 里以 `provider=azure` 特化 URL 模板 |
| **P2-9** | `@monaco-editor/react` 4.x 对 React 19 的 peer 约束可能告警 | 记录：安装时用 `--strict-peer-deps=false` 或在 `pnpm.overrides` 固定 |
| **P2-10** | `/v1/metrics` 无鉴权（仅 `127.0.0.1` 可接受） | 记录：生产模式需加 token（§3.12 已限制监听地址） |
| **P2-11** | 播放器每 2 秒 `PUT /progress` 与 Job 写库争用（SQLite 单写者） | 记录：服务端合并写（5 秒窗口内同 `(user, course)` 只落一次） |
| **P2-12** | 深色主题导出 PDF 的色彩/对比度未验证 | 记录：PDF 使用亮色排版模板，与页面主题解耦 |
| **P2-13** | `code_notes.line` 的校验规则②③存在重叠（落在 focus 区间**或**文件内） | 记录：实现时以②为主，③仅用于无 focus 的步骤 |
| **P2-14** | `course_versions.status` 缺 `archived` 的迁移路径 | 记录：软删用 `deleted_at`，`archived` 留给后续版本 |

### 评审中保留但**未采纳**的自我怀疑（说明为什么不做）

1. **"要不要砍掉 `openai_responses` 适配器"** —— 不砍。任务书明确要求"自定义多种协议"，而 Responses API 的工具/流事件形状与 Chat Completions 不同，砍掉会在主机型升级时被动。它只是多一个适配器文件，不是架构负担。
2. **"要不要砍掉 `Send` 扇出、N6 内部并发就够了"** —— 不砍，但明确了它的边界：N6 是"课时级并发"，N7/N8 是"课时×节点级并发"。两者语义不同，混成一个会失去 LangGraph 的 per-branch 可观测性。代价是必须补 reducer（P0-1 已修）。
3. **"要不要把 SQLite 换成 PG 作为默认"** —— 不换。"全新克隆零依赖拉起"是本轮任务的硬要求，SQLite + WAL 是唯一满足它的选择；代价是并发上限为 1（P1-2 已明确）。

### 评审的验证方式（我实际做了什么）

1. 逐节读完全文 1–1187 行，对每一节问"这条规则在什么情况下会失败"。
2. 交叉核对：§4 文件清单 ↔ §6 表清单 ↔ §5 接口 ↔ §8 测试编号（发现 P0-3、P1-4、P1-9）。
3. 交叉核对默认值：§3.12 ↔ R4 ↔ §5.4 ↔ §8.4（发现 P0-4、P1-2）。
4. 平台核对：Windows + PowerShell 5.1 + 无 GTK + 无 Docker（发现 P0-5、P0-6、P1-7）。
5. 浏览器核对：跨源 cookie / `EventSource` / `Range` / 反代缓冲（发现 P0-2、P1-5）。

---

## 0. 阅读指南与术语

本方案面向三类读者：

1. **评审者**：先读 `## 评审记录` 的分级问题表（它同时是"这份方案被质疑过什么、现在怎么答"的索引），再读 §1、§2.4、§3.4、§3.5、§9、§10 与 `## 评审结论` —— 足够判断方案是否解决了任务书里的四类硬要求（配置引导、LangGraph + AragonAgent core、前后端对接、start/stop 脚本），以及每条风险是否已被降级处置。
2. **实现工程师**：以 §4 的文件表作为唯一工作量清单，以 §5 接口、§6 数据模型、§7 前端规格逐行落地；任何未在本文件中定义的决策都不应该由实现者临时发明，遇到缺口请回到评审节点补充。
3. **维护者**：§3.10–§3.13 解释了缓存、幂等、可靠性、安全、可观测性的设计动机，改代码前先读这几节，避免把保护性逻辑当成冗余删掉。

**术语表**

| 术语 | 含义 |
|---|---|
| 仓库（Repo） | 用户输入的公开 GitHub 仓库，标准化为 `owner/name` + `commit_sha` |
| 课程（Course） | 针对某仓库某个 Commit 生成的一份共享课程资产，版本化、可复用 |
| 三层 | 第一层宏观架构、第二层全局走读、第三层深入源码（PRD §3.2） |
| Step | 课程的最小播放单元：一段讲解 + 一个代码焦点 + 板书/互动，携带时间轴 |
| Anchor | 源码锚点：`file + symbol + line_start/line_end + commit_sha`，是"可追溯"的唯一凭据 |
| Trace | 模拟执行轨迹，每个节点标注 `certainty`（源码事实 / 静态推断 / 教学模拟） |
| Job | 异步任务记录（课程生成、书籍生成、PDF 导出、增量重建），可观察、可取消、可重试 |
| Kernel | `services/agent-kernel`，包裹 `@aragon-agent/core` 的 Node sidecar，为 LangGraph 节点提供 Agent 能力 |
| Profile | 一组 LLM/音频服务配置的不可变快照（provider + 协议 + 密钥引用 + 角色分配），可回滚 |
| Role | 模型角色：`planner` / `writer` / `critic` / `vision` / `quiz` / `embed`，每个角色独立选模型 |

---

## 1. 概述（Overview）

RepoLearn 是一个"输入 GitHub 链接、输出三层 AI 带读课程"的学习平台：用户粘贴仓库地址，系统解析仓库元数据、目录、核心源码与调用关系，生成一份版本化的共享课程；学习者在只读 IDE 中按宏观架构 → 全局走读 → 深入源码的顺序学习，随时对选中代码行提问，最后在完课页复盘并生成可在线阅读、可导出 PDF 的图文课程书籍。PRD 明确了产品边界：不承诺 30 分钟掌握全部细节，不在服务器执行用户仓库代码，所有执行演示都是标记清晰的教学模拟。

本阶段的工程目标不是再画一遍设计稿，而是把 `doc/` 里的 PRD 与 7 张视觉设计稿变成一个**真正能跑起来的完整项目**：Next.js 承载前端（复用设计稿的深灰黑底 + 薄荷绿强调色视觉体系），Python 后端承载仓库解析、课程资产生成、异步任务与数据持久化，LangGraph 作为课程生成的工作流骨架，AragonAgent 的 `@aragon-agent/core` 作为每个生成节点的 Agent 能力内核。任务书额外点名了三件必须补齐的事：首次启动的 AI 服务配置引导（多协议 LLM + 多模态感知 + 豆包 TTS）、根目录的 `start.ps1` / `stop.ps1` 开发启停脚本，以及"用户没考虑到但必须补上"的工程项（本方案在 §11 集中列出，共 18 项，均带落点）。

为什么架构上要拆成"前端 / 后端 / Agent 内核"三个进程而不是一个单体：仓库解析是 CPU 与 IO 混合的长任务，课程生成是分钟级、可中断、需要断点续跑的长事务，AragonAgent core 是 Node ESM-only 的运行时（`@aragon-agent/core` 明确要求 `"type": "module"` 且只能 `import`，无法在 Python 进程内加载）。三进程 + 数据库单点状态机是唯一同时满足"语言原生、可独立重启、故障域隔离"的拓扑。进程之间只通过 HTTP/SSE 与数据库通信，因此任一进程崩溃时另外两个进程仍可服务只读页面，Job 状态机保证重启后继续跑而不是从头重来。

设计语言上遵循任务的"Anthropic 顶级产品"要求：不是堆砌动效，而是**让信息密度和信任度可感知**——代码阅读区是主视觉、讲解紧贴对应的代码行、调用链压缩成可折叠细条、所有 AI 结论都带源码出处。视觉 token 采用 PRD §4 的 Supabase 风格（`#0B0F0E` 背景、`#1A211F` 卡片、`#3ECF8E` 薄荷绿强调、`#2A3330` 细线边框），字体使用 `Inter` + `JetBrains Mono`，所有交互元素有 `:focus-visible` 环、`prefers-reduced-motion` 降级、键盘可达。

---

## 2. 现状与约束

### 2.1 仓库现状（已核实）

| 项 | 事实 | 影响 |
|---|---|---|
| 工作目录内容 | 仅 `doc/`（PRD docx + 7 张设计稿 PNG）、`docs/plans/`（本方案）与 `.agentmesh/`（运行时）；**没有任何应用代码**，也没有 `README.md` / `CLAUDE.md` / `.claude-index` / `AGENTS.md` | **本方案必须自建目录约定，并把约定写进本文件**，不能假设继承既有风格 |
| Git | 已 `git init`（`master` 分支，**尚无任何 commit**）；`.gitignore` 与首次提交仍由开发节点在 M0 完成 | 本节点只改 `spec.md`，不初始化提交 |
| PRD | 已解析出正文 47 段 + 2 张表（三层编辑器呈现表、P01–P10 页面表） | §7 前端规格严格对齐 P01–P10 |
| 视觉稿 | 7 张 1672×941 截图（首页、宏观架构、全局走读、深入源码、行内提问、课程总结等），统一为深色 + 薄荷绿 + 左侧大纲 + 顶部三段进度 + 右侧 Momo 导师栏 | §7.2 把这些区块拆成可复用组件 |
| AragonAgent | `E:\TAKO-PROJECTS\AragonAgent`；`@aragon-agent/core`（0.2.63）闭源、ESM-only、npm 发布；导出 `Agent`、`defineTool`、`initProviders`、`textResult`；`agent.prompt()` 为异步事件流（`message_update` 内嵌 `text_delta`）；另有 `aragon exec` 提供 `--output-format stream-json` 的机器契约（29 种事件） | §3.5 的 Kernel 直接 `npm install @aragon-agent/core` 并以 `Agent` 类为节点能力；§3.5.4 提供 `aragon exec` 兜底通道 |

### 2.2 硬约束

1. **不在服务器执行用户仓库代码**。仓库内容按"不可信输入"处理：只读挂载、体量上限、路径穿越防护、禁止把 README/注释里的文本当指令执行（PRD §5）。
2. **AI 产物必须可追溯**：任何讲解、调用链、书籍章节都要能落回 `file + symbol + line + commit`；无法确定的行为只能标记为"教学模拟"。
3. **Windows 优先**：开发机是 Windows + PowerShell 5.1+，`start.ps1` / `stop.ps1` 必须能在 PowerShell 5.1 下运行（不能用 `??`、`&&`、`-Parallel` 等 7.x 语法）。
4. **首启可用**：全新克隆 + `npm i` + `python -m venv` 后，`.\start.ps1` 一条命令拉起全部服务，且没有配置任何 AI Key 时前端进入配置引导而不是报错崩页。
5. **无隐藏外部依赖**：MVP 不强制 Docker / Redis / PostgreSQL；默认 SQLite（WAL）+ 本地磁盘对象存储即可跑通全部 P0 功能，PG/Redis/S3 通过环境变量切换。
6. **单一同源通路（v2 新增，P0-2）**：**浏览器只与 Next.js 同源通信**。FastAPI 只监听 `127.0.0.1:8000`、Agent Kernel 只监听 `127.0.0.1:8787`，二者的端口不对浏览器暴露；所有浏览器请求（REST、SSE、音频/PDF 的 `Range`、图片）都走 `apps/web` 的 BFF Route Handler 转发。理由不是"架构洁癖"：`SameSite=Lax` 的会话 cookie 不会随跨源 `fetch` 发送，跨源就意味着 CSRF 双提交、SSE 鉴权、`Range` 拖动音频三件事同时失效，而修复它们（`SameSite=None; Secure`）要求 HTTPS，与"`.\start.ps1` 在 `http://localhost` 一键跑起来"直接冲突。同源是本项目唯一能同时满足"免配置启动"与"会话/CSRF 成立"的选择。
7. **外部依赖必须可探测（v2 新增，P0-6）**：任何"装不上就没法工作"的依赖（npm 闭源包、Chromium、tree-sitter 语言轮子）在首次安装阶段就要被显式探测，并给出**当前降级到什么程度**的可见结论；不允许出现"启动成功但功能静默缺失"。

### 2.3 技术栈决策（含被否决项）

| 层 | 选型 | 版本基线 | 为什么不是别的 |
|---|---|---|---|
| 前端框架 | Next.js（App Router） | 15.x / React 19 | 任务书要求 Next.js；App Router 的 RSC 让 P01/P02/P09 这类内容页零 JS 首屏，交互密集的 P03–P05 用 Client 岛屿 |
| 样式 | Tailwind CSS v4 + CSS 变量 token | 4.x | 设计稿 token 化（背景/卡片/边框/强调/字体阶梯）为 24 个变量，Tailwind 只消费变量；避免 class 名与设计值双写 |
| 组件原语 | Radix UI primitives + 自建 shadcn 风格组件 | — | 键盘可达与无障碍由 Radix 保证，视觉由自建样式保证（避免默认主题与 Supabase 风格冲突） |
| 代码编辑器 | `@monaco-editor/react`（只读 + decorations） | 4.x | 需要行级 decoration、行内 widget、折叠、minimap 与 token 高亮；CodeMirror 6 亦可行但行内 widget 与多文件 tab 的成熟度不如 Monaco |
| 播放器 | 自建 timeline 引擎（`requestAnimationFrame` + `<audio>`） | — | 讲解、代码高亮、架构图元素三者必须按同一时间轴同步，现成播放器无法承载"锚点即时间"的语义 |
| 后端框架 | FastAPI + Pydantic v2 | FastAPI 0.115+ | 异步 IO、自动 OpenAPI（作为前后端契约唯一来源）、SSE 易实现 |
| ORM / 迁移 | SQLAlchemy 2.0 async + Alembic | 2.0.x | 同步/异步双栈成熟，Alembic 保证可回滚 |
| 数据库 | SQLite（WAL）默认，PostgreSQL 可选 | — | 默认零依赖即可跑；`JSON` 列与自增锁策略保持方言中立（§6.7） |
| 工作流 | LangGraph（`langgraph`，含 `SqliteSaver` checkpoint） | 0.2.x | 任务书点名；checkpoint 是"分钟级长任务可断点续跑"的关键 |
| Agent 能力 | `@aragon-agent/core`（Kernel 内） | 0.2.63 | 任务书点名"使用这个组件 core"；Kernel 通过内部 HTTP 暴露能力，Python 侧不被 Node 绑定 |
| 任务队列 | 数据库队列 + 原子 claim（`jobs` 表） | — | 不引入 Redis；`UPDATE ... WHERE status='queued'` 的 rowcount 判定给出跨方言的原子性（§3.11.2） |
| TTS | 豆包（火山引擎）语音合成 HTTP/WS 双通道 | — | 任务书点名；失败可降级为"无配音 + 字幕" |
| 图表 | Mermaid 渲染为 SVG（服务端/客户端同一 DSL） | 11.x | 架构图既要进页面也要进 PDF，DSL 可缓存、可比对、可版本化 |

### 2.4 Gate 0：外部依赖可用性校验（v2 新增，P0-6）

> "稳健可靠顶级"的第一层含义不是降级写得多，而是**在开工前就知道哪些能力在这个环境里真实存在**。v1 把三个关键依赖当作既成事实，其中任何一个在 Windows 上装不上，§3.4 的 N4/N5/N6/N7 与 §8 的多条门禁就一起失效。v2 把它们变成可执行的前置闸门。

`scripts/check_env.ps1` 在"安装依赖"之前依次执行下面三条探测，结果写进 `.run/preflight.json`，并由 `start.ps1` 汇总打印、由 `/healthz` 与设置页 Doctor 面板读取：

| Gate | 探测命令 | 通过意味着 | 不通过时的降级（必须明示给用户） |
|---|---|---|---|
| G1 · Agent 内核 | `npm view @aragon-agent/core version`（配好 registry 与凭证）；随后 `node -e "import('@aragon-agent/core').then(m=>console.log(Object.keys(m)))"` 打印导出面 | N5/N6/N7 走 Kernel Agent 主路径 | 若包不可获取：直接进入 **模板降级**（`quality_report.degraded=true`），设置页显示"Agent 内核不可用：课程为简化版生成"，`start.ps1` 打印可选的私有 registry 配置方法。**不冒充"CLI 兜底可用"**（见 P1-8） |
| G2 · PDF 引擎 | `python -m playwright install --dry-run chromium` 或已装则 `playwright chromium --version` | 书籍 PDF 可生成并做页数/文本层断言 | 降级为"打印优化 HTML + 浏览器打印"（`pdf_exports.engine='browser-print'`），P10 页面把"下载 PDF"改为"打开打印视图"，不再提供伪造的 PDF 文件 |
| G3 · 语法分析 | `python -c "import tree_sitter_language_pack as p; print(p.get_languages())"`（**固定用 `tree-sitter-language-pack`**，它提供 Windows 预编译轮子；`tree-sitter-languages` 在 Windows 上需 MSVC 编译，不作为依赖） | N4 产出真实符号/调用边，锚点置信度高 | 退化为正则抽取 + `ANALYSIS_DEGRADED` 警告（§3.4 N4 已有此路径），课程仍可生成，但 `quality_report.anchor_confidence="low"` |

**规则**：Gate 0 的结论必须在**首次启动的输出里**就看得见（一行一条，`G1 ok / G2 degraded / G3 ok`），而不是等用户点了"生成课程"才发现没有配音、没有 PDF、没有调用链。任何 Gate 不通过都不阻断启动——阻断启动的只有"node/python 版本不足"这类无法运行的前提（T-SCR-4）。

---

## 3. 技术设计（Technical design）

### 3.1 进程拓扑与目录布局

```
┌───────────────────────────────────────────────────────────────────────────┐
│ 浏览器                                                                    │
│  Next.js 15 App Router (apps/web, :3000)                                  │
│    RSC 外壳 + Client 岛屿；Route Handler 只做 cookie 会话与 SSE 透传      │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ HTTPS / fetch(cookie) / SSE(Last-Event-ID)
┌───────────────▼───────────────────────────────────────────────────────────┐
│ FastAPI (apps/api, :8000)                                                 │
│   /v1/* 公开 REST        /v1/jobs/{id}/events SSE        /healthz         │
│   Settings/Onboarding · Courses · Lessons · Books · Progress · Notes      │
│   ┌─────────────────────────────────────────────────────────────────┐     │
│   │ 领域层: repo_ingest · knowledge_graph · curriculum · course      │     │
│   │         lesson · trace · quiz · book · pdf · audio · cache       │     │
│   └─────────────────────────────────────────────────────────────────┘     │
│   ┌──────────────────────────┐   ┌──────────────────────────────────┐     │
│   │ Job Runner (asyncio)     │   │ LangGraph 课程生成图              │     │
│   │ claim → run → event log  │──▶│ 9 节点 + checkpoint(SqliteSaver) │     │
│   └──────────────────────────┘   └──────────────┬───────────────────┘     │
│                                                 │ AgentRuntime 协议       │
│                          ┌──────────────────────▼─────────────────────┐   │
│                          │ HttpKernelRuntime（主）│ ExecCliRuntime（备）│   │
│                          └──────────────────────┬─────────────────────┘   │
└─────────────────────────────────┬───────────────┼─────────────────────────┘
                                  │               │ POST /v1/run (SSE)
┌─────────────────────────────────▼───┐   ┌───────▼─────────────────────────┐
│ SQLite/PG  var/data/repolearn.db    │   │ agent-kernel (services/         │
│ object store var/objects/           │   │ agent-kernel, :8787)            │
│   audio/ pdf/ diagrams/ mirrors/    │   │  @aragon-agent/core Agent       │
└─────────────────────────────────────┘   │  tools: repo_read/grep/tree/... │
                                          │  provider registry + budgets    │
                                          └─────────────────────────────────┘
```

**拓扑的两条铁律（v2 明确，P0-2）**

1. **浏览器只认识 `:3000`**。图中的 `:8000` 与 `:8787` 都是回环地址上的内部端口：FastAPI 以 `--host 127.0.0.1` 启动，Kernel 同此。因此"跨源 cookie 丢失 / CSRF 双提交失效 / SSE 无法鉴权 / 音频 `Range` 被拒"这一整类问题在设计上就不存在，而不是靠 CORS 白名单去救。
2. **BFF 只做三件事**：转发请求（附带内部服务令牌 `X-Internal-Token`、`X-Request-Id`、`X-CSRF-Token`）、透传流（SSE 与 `Range`，约束见 §3.3）、把上游结构化错误体原样交给前端（不吞错、不改写成 500）。BFF **不做**业务判断、**不缓存**业务数据、**不聚合**多个上游请求——一旦它开始做这些，它就变成了第二个后端，两端契约会立刻分叉。

**目录布局（新仓库，全部由本方案定义）**

```
repolearn/
├─ apps/
│  ├─ web/                     # Next.js 15 前端（含 middleware.ts 与 BFF Route Handlers）
│  ├─ api/                     # FastAPI 后端（Job Runner 随 lifespan 启动）
│  └─ worker/                  # 【M6 之后】可选独立 worker 进程（同一份 api 代码的 entrypoint）
├─ services/
│  └─ agent-kernel/            # Node 20 sidecar，包装 @aragon-agent/core
├─ packages/
│  └─ contracts/               # openapi.json + JSON Schema + 生成的 TS 类型
├─ scripts/                    # 启停、契约导出、数据回填、夹具生成
├─ tests/
│  ├─ e2e/                     # Playwright
│  └─ fixtures/                # 录制好的 GitHub 响应与生成产物黄金样本
├─ docs/
│  ├─ plans/repo-learn-platform/spec.md   # 本文件
│  └─ runbook.md               # 运维/排错手册（开发节点产出）
├─ var/                        # 运行时数据（gitignore）
│  ├─ data/ repolearn.db, uploads/
│  ├─ objects/{audio,pdf,diagrams,mirrors,artifacts}/
│  └─ logs/{api,kernel,web}.log
├─ .run/                       # PID 与端口文件（gitignore）
├─ start.ps1  stop.ps1
├─ .env.example  .env   (不入库)
├─ pnpm-workspace.yaml  package.json  # 前端 workspace（web + contracts）
├─ pyproject.toml       # uv/pip 项目（apps/api）
└─ README.md
```

> 为什么 Node 与 Python 各自一个 workspace/项目根：Kernel 是 ESM-only 需要 Node 工程；Python 需要 `pyproject.toml`。二者互不侵入，`start.ps1` 分别安装、分别拉起。

### 3.2 `apps/api` 内部分层

```
apps/api/
├─ repolearn/
│  ├─ main.py                  # FastAPI 应用工厂，lifespan 内启动 Job Runner
│  ├─ core/
│  │  ├─ config.py             # pydantic-settings；REPOLEARN_* 环境变量
│  │  ├─ db.py                 # async engine/session；WAL pragma；get_session 依赖
│  │  ├─ security.py           # Fernet 密钥信封、CSRF 双提交、请求 ID
│  │  ├─ errors.py             # AppError(code, message, hint, retryable, details)
│  │  ├─ logging.py            # structlog JSON 行日志 + 请求上下文
│  │  ├─ clock.py              # utcnow() 单点，便于测试注入
│  │  └─ ids.py                # 前缀 ID（crs_/lsn_/stp_/job_/ver_/bok_）
│  ├─ models/                  # SQLAlchemy 2.0 声明式模型（一表一文件）
│  ├─ schemas/                 # Pydantic v2 请求/响应模型（与 §5 一一对应）
│  ├─ routers/                 # 按 §5 的路径分组
│  ├─ services/                # 领域服务（无 HTTP 依赖，可被 worker 直接调用）
│  ├─ providers/               # LLM/音频适配层（§3.8、§3.9）
│  ├─ workflow/                # LangGraph 图、节点、状态、prompts
│  ├─ jobs/                    # 队列、runner、事件流、取消
│  ├─ ingest/                  # GitHub 抓取、tarball 解包、镜像、安全过滤
│  ├─ analysis/                # tree-sitter 符号/调用边、知识图、代表性链路挑选
│  ├─ rendering/               # Mermaid→SVG、PDF 排版、书籍模板
│  └─ cli.py                   # `python -m repolearn.cli ...`（迁移/回填/夹具）
├─ migrations/                 # Alembic
└─ tests/                      # pytest（单元 + ASGI 集成）
```

分层规则（评审时需要检查的硬约束）：

- `routers/` **不得**直接访问数据库会话以外的服务内部状态，只调用 `services/`；
- `services/` **不得**导入 `routers/`；可被 worker 与 CLI 复用；
- `workflow/` 节点只依赖 `services/`、`providers/`、`AgentRuntime` 协议，不直接发 SQL；
- 所有对外 JSON 由 `schemas/` 定义，任何字段变更必须先改 schema 再改实现（契约优先）。

### 3.3 `apps/web` 结构

```
apps/web/src/
├─ app/
│  ├─ layout.tsx                # 全局 Provider（QueryClient, Toast, ThemeProvider）
│  ├─ page.tsx                  # P01 首页（RSC 取热门课程 + 最近学习）
│  ├─ setup/page.tsx            # 首启 AI 服务配置引导（§3.7，多步向导）
│  ├─ repo/[owner]/[name]/page.tsx        # P02 课程准备/概览
│  ├─ course/[courseId]/
│  │  ├─ layout.tsx             # 工作台外壳：顶部三段进度 + 左大纲 + 右 Momo
│  │  ├─ overview/page.tsx      # 第一层（P03）
│  │  ├─ walkthrough/page.tsx   # 第二层（P04）
│  │  ├─ deep-dive/page.tsx     # 第三层（P05）
│  │  └─ recap/page.tsx         # P08 完课与书籍生成
│  ├─ book/[bookId]/page.tsx    # P09 在线课程书籍
│  ├─ book/[bookId]/pdf/page.tsx# P10 PDF 预览/下载
│  ├─ settings/page.tsx         # AI 服务、模型角色、费用与版本回滚
│  └─ api/                      # BFF Route Handlers：转发、SSE 代理、二进制 Range 代理
├─ middleware.ts                # 首启守卫（§3.6.1）：只读 cookie 标记，API 不可达时 fail-open
├─ components/
│  ├─ shell/                    # AppShell, TopProgress, OutlineRail, MentorRail
│  ├─ ide/                      # CodePane(Monaco), FileTree, Breadcrumb, HighlightLayer
│  ├─ player/                    # TimelineProvider, TransportBar, SubtitleView, SpeedMenu
│  ├─ learning/                 # StepHeader, ConceptCard, ArchitectureCanvas, TraceStrip,
│  │                            #   PredictionQuiz, InlineAsk, VariablePanel, CertaintyBadge
│  ├─ book/                     # BookReader, ChapterNav, SearchPanel, PdfPreview
│  ├─ setup/                    # WizardShell, ProviderSelect, ProbeResultCard, VoicePicker
│  └─ ui/                       # Button, Card, Sheet, Dialog, Toast, Skeleton, Tabs…
├─ lib/
│  ├─ api/                      # client.ts（fetch 包装 + 错误映射 + 重试）+ 生成类型
│  ├─ sse/                      # useEventStream（fetch + ReadableStream + 断线续传）
│  ├─ player/                   # timeline 计算、字幕分段、倍速、锚点索引
│  ├─ format/                   # 时长、字数、文件大小、相对时间
│  └─ env.ts                    # 运行时配置（API base、是否 mock）
├─ styles/tokens.css            # 24 个设计 token（§7.1）
└─ stores/                      # zustand：playerStore, ideStore, setupWizardStore
```

前端与后端的对接方式（v2 细化为四条契约，P0-2 / P1-5）：

- **类型契约**：**由 FastAPI 的 OpenAPI 生成 TS 类型**（`packages/contracts`），前端只经由 `lib/api/client.ts` 访问网络；任何响应形状改动都会在 `pnpm typecheck` 时变成编译错误，这是"前后端对接"的第一道护栏。
- **事件契约**：SSE 事件信封（§5.5）的 `type` / `schemaVersion` 在契约包里集中定义；前端对未知 `type` 只记日志不崩，保证后端加事件时前端不会白屏（向后兼容）。
- **传输契约**：浏览器**只请求同源的 `/api/*`**，由 BFF 转到 `http://127.0.0.1:8000/v1/*`。BFF 必须满足四条硬要求，否则流式与音频会**静默**坏掉（v1 完全没写，P1-5）：
  1. `export const runtime = "nodejs"` 与 `export const dynamic = "force-dynamic"`（否则构建期被静态化或落到没有流式能力的 runtime）；
  2. 响应头带 `Cache-Control: no-cache, no-transform`、`Content-Type: text/event-stream`、`X-Accel-Buffering: no`；
  3. 用 `ReadableStream` 逐 chunk `enqueue`，**禁止** `await res.text()`——那会把整条流缓冲到结束，用户体感是"卡 30 秒后一次性出现"；
  4. 二进制代理（音频/PDF）原样转发 `Range` 并回传 `206/416`、`Content-Range`、`Accept-Ranges`、`ETag`，否则音频拖动定位与 PDF 分段加载失效。
- **错误契约**：上游错误体（§5.6）**原样透传**，由 `lib/api/errors.ts` 映射成用户可读提示；BFF 不允许把上游错误改写成 500 或吞掉 `hint`。

### 3.4 课程生成工作流（LangGraph）

**图定义**：`workflow/course_graph.py::build_course_graph()` 返回编译后的 `CompiledStateGraph`。

**执行模型的三条硬约束（v2 修订，P0-1）** —— v1 在这里写错了，照做在第一次 `ainvoke` 就会失败：

1. **checkpointer 必须是异步实现**：`AsyncSqliteSaver`（来自 `langgraph.checkpoint.sqlite.aio`，依赖 `aiosqlite`），在 `async with AsyncSqliteSaver.from_conn_string(...)` 上下文内构建图并在 `lifespan` 期间持有。同步的 `SqliteSaver` 与 `graph.ainvoke()` 组合会在 checkpoint 写入时抛"不能在事件循环里调用同步 IO"一类错误。若切 PostgreSQL，用 `AsyncPostgresSaver`（同一套 async 语义）。
2. **checkpoint 库与业务库物理隔离**：LangGraph checkpoint 写在 `var/data/langgraph.sqlite`，业务数据在 `var/data/repolearn.db`。两者都是 SQLite 时，最危险的情况是同一个文件里的写锁争用：LangGraph 每个 superstep 都提交一次 checkpoint，会与业务写入互相把对方推到 `busy_timeout`。物理分文件是零成本的隔离。
3. **并行分支必须声明 reducer**：N6 用 `Send` 扇出、N7/N8 再扇出，多个分支会在**同一个 superstep** 返回对同名键的部分更新。没有 reducer，LangGraph 抛 `InvalidUpdateError`（"expected one value, got N"）。reducer 表即契约：

| state 键 | reducer | 为什么 |
|---|---|---|
| `lessons` / `traces` / `narration` | `merge_dict`（`lambda a, b: {**a, **(b or {})}`） | 每个课时分支返回 `{lesson_key: value}`，键互不重叠，浅合并即正确 |
| `failed_lessons` | `operator.add`（并去重） | 多分支各自追加失败项，顺序无关 |
| `warnings` | `operator.add` | 同上；warning 是日志式数据，天然可追加 |
| `budget` | `merge_budget`（逐字段取 `max(used)`、保留 `deadline_ms`） | 并行分支各自累加用量，简单求和会重复计入同一次调用 |
| 其余（`repo/commit/tree/knowledge_graph/curriculum/mirror_dir`） | 无（默认 `LastValue`） | 只有一个产生者，出现第二个写入者就是设计错误，应当报错而不是静默覆盖 |

**状态体积预算（P0-1 附带）**：单次 checkpoint 序列化后 **≤ 256 KB**。这不是风格问题：state 每推进一个 superstep 就要整份序列化落盘，若把 `tree`（2000 条）、`knowledge_graph`、12 份完整 lesson 与 trace 都塞进去，一次课程生成会产生数十次 MB 级写入，SQLite 直接被拖成瓶颈，且 checkpoint 表在几轮之后就不再适合 `VACUUM`。因此：

- state 里**只放引用与小摘要**：`tree` 裁剪为"核心 200 条 + 目录骨架"；`knowledge_graph` 只保留节点/边计数与 `key_chains` 的 id 列表；
- 大体量产物（完整 lesson 文档、trace 明细、narration 分段）在节点出口就写入 `var/objects/artifacts/<job_id>/<node>/<key>.json` 并在 state 里留 `{"key": "...", "artifact": "artifacts/<job_id>/n6/3.1.json"}`，N9 发布时按引用读取；
- 测试里加一条断言（并入 T-GRAPH-1）：任一 checkpoint 的 `state` JSON 字节数 ≤ 256 KB。

`interrupt_before=[]`（不依赖人工批准），`recursion_limit=80`（9 个节点 + 扇出分支的安全上界；超限说明图里出现了意外循环）。

**`CourseGenState`（TypedDict，全部字段可 JSON 序列化）**

| 字段 | 类型 | 产生者 → 消费者 | 说明 |
|---|---|---|---|
| `job_id` / `course_id` | str | 入口 → 全部 | 幂等键的一部分 |
| `repo` | dict | N1 | `{full_name, default_branch, license, stars, language, description}` |
| `commit` | dict | N2 | `{sha, committed_at, tarball_bytes, file_count}` |
| `mirror_dir` | str | N3 | 只读镜像绝对路径（沙箱根） |
| `tree` | list[dict] | N3 | `{path, size, lang, is_core}`，**state 内上限 200 条核心文件 + 目录骨架**；完整列表落 `artifacts/<job>/n3/tree.json` |
| `knowledge_graph` | dict | N4 | state 内只放 `{node_count, edge_count, entrypoints[], chain_ids[]}` 摘要；完整图落 artifact |
| `curriculum` | dict | N5 | `{sections[{key,title,minutes,lessons[{key,title,goal,anchor_refs[]}]}]}`（小体量，直接入 state） |
| `lessons` | dict[str, dict] | N6 | key → `{artifact, anchors[], quiz_artifact, warnings[]}` 的**引用条目**，不是 lesson 全文（reducer = `merge_dict`） |
| `traces` | dict[str, dict] | N7 | 同上的引用条目（reducer = `merge_dict`） |
| `quizzes` | dict[str, list] | N6 | 题面与选项体量小，直接入 state（reducer = `merge_dict`） |
| `narration` | dict[str, dict] | N8（synthesize_audio） | key → `{segment_count, audio{url,duration_ms}|null, timing_source}`（reducer = `merge_dict`） |
| `budget` | dict | 全部 | `{max_tokens, used_tokens, max_usd, used_usd, deadline_ms}`（reducer = `merge_budget`，见 §3.4 三级预算表） |
| `warnings` | list[dict] | 全部 | `{code, message, severity, node}`，最终进 `course_version.warnings`（reducer = `operator.add`） |
| `failed_lessons` | list[str] | N6/N7 | 部分失败的课时 key（允许降级发布，reducer = `operator.add`） |

**九个节点（顺序 + 并行）**

| # | 节点 | 类型 | 主要动作 | 失败策略 |
|---|---|---|---|---|
| N1 | `normalize_repo` | 纯 Python | 解析 URL（支持 `https://github.com/o/r`、`o/r`、带 `.git`/`/tree/ref`），GitHub REST 取元数据与默认分支，写 `repositories` | 404/403 直接 `AppError(REPO_NOT_FOUND/REPO_FORBIDDEN)`，不重试 |
| N2 | `resolve_commit` | 纯 Python | 取 HEAD sha（或用户指定 ref），命中缓存键则标记 `reused=true` | 网络错误退避重试 3 次（1/2/4s），再失败 `PROVIDER_UNAVAILABLE` |
| N3 | `fetch_repo` | 纯 Python | 下载 tarball（上限 60 MB，超限用 Git Trees API 按路径挑取），解包到 `var/objects/mirrors/<sha8>/`，`ingest/guard.py` 做路径穿越/符号链接/二进制/体积过滤 | 超限则降级为"核心文件子集"，写 warning；解包失败重试 1 次 |
| N4 | `analyze_repo` | 纯 Python（tree-sitter） | 符号、导入、调用边、入口点、许可证与依赖清单；产出 `knowledge_graph` 与"代表性调用链"候选（按入度/入口可达性/教学价值打分） | 无 tree-sitter 语言包时退化为正则抽取，warning 标记 `ANALYSIS_DEGRADED` |
| N5 | `plan_curriculum` | **Kernel Agent**（role=`planner`） | 以 KG 摘要为输入，产出 4 章节 / 10–12 课时的课程骨架，并显式选出一条代表性链路 | 结构化校验失败 → 修复提示重试 2 次 → 退化为确定性模板（fixed skeleton），warning |
| N6 | `write_lessons` | **Kernel Agent**（role=`writer`），按 lesson 并行（并发 3） | 每课时产出 `narration.segments`、`focus`、`code_notes`、`board`、`quiz` 草案；引用的锚点必须来自 N4 提供的候选集 | 单课时失败进 `failed_lessons`，不阻塞整体；重试 1 次 |
| N7 | `simulate_trace` | **Kernel Agent**（role=`critic`）+ 纯 Python 校验 | 沿代表性链路生成 trace 步骤（每步带 `certainty` 与 `evidence`），Python 侧校验 evidence 锚点真实存在于镜像文件 | 校验失败逐步标记为 `teaching_simulation` 或删除该步 |
| N8 | `synthesize_audio` | 纯 Python（豆包 TTS） | 按 `narration.segments` 逐段合成，`text_hash` 命中缓存直接复用；合成失败降级为字幕（`audio=null`） | 3 次退避后降级，warning `TTS_DEGRADED` |
| N9 | `publish_course` | 纯 Python | 事务内写 `course_versions` + `lessons` + `anchors` + `traces` + `quiz_items` + `audio_assets`，置 `status=ready`，计算 `quality_report`（锚点覆盖率、课时完整率、题量） | 事务失败整体回滚，Job 置 `failed` 可重试 |

**图内边**：`N1→N2→N3→N4→N5→(N6 fan-out)→(N7, N8 per lesson in parallel 2)→N9`。N7 与 N8 都只依赖 N6 的产出，因此在 LangGraph 里用 `Send` 扇出，N9 用 `add_edge([...], N9)` 汇聚。N9 之后不再有节点，质量不达标只在 `quality_report` 里体现并由前端提示"内容可能不完整，可重建"。

**预算与超时**（防"跑飞"，v2 重写为三级，P0-4）：v1 把"单次 run"写上 `maxTokens=180000`，而一次课程约有 23 次 run（1×N5 + 12×N6 + 12×N7），照此配置单 run 就能吃满整个 job 预算，超支要等到最后一刻才暴露。正确做法是把预算切成三级，**每一级都有独立闸门，先到的那个生效**：

| 层级 | 默认值 | 闸门位置 | 超限行为 |
|---|---|---|---|
| **Job 级**（总闸） | 180k tokens / 0.35 USD / 25 分钟（`REPOLEARN_JOB_DEADLINE_MS`） | `workflow/budget.py::JobBudget`，由 runner 持有并在每个节点出口检查 | 抛 `BudgetExceeded` → Job `failed_budget`；已发布课时保留，`course_version.status=partial` |
| **节点级**（分闸） | N5 `plan_curriculum` 20k；N6 每课时 9k；N7 每课时 2k；N8 不计 token（只计合成次数）；预留 28k 给重试与修复 | 每个节点的 Kernel 调用前按剩余额度下发 `maxTokens` | 只让**该课时**失败并进 `failed_lessons`，不拖垮整门课程 |
| **Run 级**（Kernel 内部） | 跟随节点下发（9k–20k），`maxTurns=16`，`deadlineMs=节点剩余时间 ∩ 600000` | `services/agent-kernel/src/budget.ts` | Kernel 主动 abort 并回 `budget_exceeded{kind,used,limit}`，Python 侧据此决定重试或降级 |

- 语言模型侧的用量以**真实 usage 回报**累加（provider 返回的 `usage` 或缺省估值），无法回报时按 `estimatePromptTokens`（4 字符/token）估并标 `usage_source="estimated"`，写进 `cost_ledger`。
- 成本换算只用 `model_catalog.price_in/price_out`，**没有价格的模型记 0 并在 `warnings` 里带 `PRICE_UNKNOWN`**——不猜价格，否则"≤0.35 USD"这个门禁会变成假数据。
- 节点内每完成一次 Kernel 调用即累加 usage；`deadline_ms` 用单调时钟（`time.monotonic`）而非墙钟，避免系统时间跳变导致预算瞬间失效。
- 课程生成的最小可发布阈值：4 个章节全有、有效课时 ≥ 8、锚点覆盖率 ≥ 80%（三条同时满足才允许 `ready`，否则 `partial`）。

**为什么用 Kernel 而不是 Python 直接调模型 SDK**：任务书要求"结合 AragonAgent 作为节点的基础 Agent 能力"。Kernel 提供的是 **Agent**（工具循环、上下文压缩、重试阶梯、输出上限学习、结构化工具调用），不是裸 LLM 客户端；课程生成需要"读文件 → grep → 再读 → 产出 JSON"这种多轮取证，裸 chat 调用无法完成取证闭环。把 Agent 放在 Node 进程内可完整复用 core 的 retry/compaction/output-limit 逻辑，避免在 Python 侧重新实现一遍。

### 3.5 `services/agent-kernel`（AragonAgent core 集成）

#### 3.5.1 职责

Kernel 是一个**只对内网暴露**的 HTTP 服务（默认 `127.0.0.1:8787`），把 `@aragon-agent/core` 的 `Agent` 封装成"一次性、可流式、带预算、带工具白名单"的运行单元。它不持有任何业务数据，不写数据库，不认识课程概念——只有 prompt 进、事件流出。

#### 3.5.2 内部代码要点

- `src/server.ts`：Fastify 实例，`logger: { redact: ['req.body', 'req.headers.authorization'] }` 且 **`disableRequestLogging: true`**（P1-14：请求体里有明文 API Key，默认请求日志会把它写进 `var/logs/kernel.log`）；`@fastify/cors` **不启用**（浏览器不该直连，见约束 6）；`preHandler` 校验 `X-Internal-Token`；路由见 §5.4。
- `src/runtime.ts`：`AgentRuntime` 单例持有 `ProviderRegistry`（`initProviders()`），按 `profileId` 创建/复用 `Agent`；每种 provider 的 API key 由 Python 侧随请求下发（内存中仅存活单次 run 的闭包，`finally` 里显式置空），**Kernel 不落盘密钥、不缓存密钥**。
- `src/tools/repo.ts`：`repo_list_tree` / `repo_read_file` / `repo_grep` / `repo_file_outline`。全部以 `mirrorDir` 为根做 `path.resolve` 后必须 `startsWith(root)`（防路径穿越），单文件读取上限 256 KB，`grep` 结果上限 200 条，输出统一截断并标注 `truncated: true`。
- `src/tools/emit.ts`：`emit_course_json` / `emit_trace` / `emit_lesson` —— 每个都是"结构化产出"工具，参数用 zod schema 校验，通过后写入 run 的结果槽；Agent 必须调用它来交付，避免从自然语言里抠 JSON。
- `src/contracts/schema.ts`：zod 定义的课程骨架/课时/trace schema（与 `packages/contracts/schemas/*.json` 同源，用 `zod-to-json-schema` 导出，Python 侧用同一份 JSON Schema 做二次校验）。**一处定义、两侧校验**是本方案防止"模型输出漂移"的核心机制。
- `src/budget.ts`：每次 run 记录 `turns/tokens/usd`，超过 `budget` 或 `deadlineMs` 主动 abort 并返回 `budget_exceeded`。
- `src/events.ts`：把 core 的事件（`message_update`、工具调用、thinking）映射为统一信封（§5.5）。
- `src/health.ts`：`/healthz` 返回 `{ok, coreVersion, providers, uptimeMs}`；Kernel 启动时打印解析到的 `@aragon-agent/core` 版本，供 `start.ps1` 校验。

#### 3.5.3 Python 侧 `AgentRuntime` 协议（`apps/api/repolearn/providers/agent_runtime.py`）

```
class AgentRuntime(Protocol):
    async def run(self, req: AgentRunRequest) -> AsyncIterator[AgentEvent]: ...
    async def cancel(self, run_id: str) -> None: ...
```

- `AgentRunRequest`：`run_id, profile(provider/protocol/model/base_url/api_key_ref), role, system_prompt, messages, tools[], json_schema_ref, budget{max_turns,max_tokens,max_usd,deadline_ms}, metadata(job_id, lesson_key)`。
- 两个实现：
  - `HttpKernelRuntime`（默认）：POST `http://127.0.0.1:8787/v1/run`（带 `X-Internal-Token`），解析 NDJSON/SSE 事件流，映射为 Python dataclass。
  - `ExecCliRuntime`（**条件性兜底**）：`subprocess.exec([npx, aragon, exec, --output-format, stream-json, --permission-mode, plan, ...])`，逐行读 stdout JSON 事件；同样带超时与 kill。
- **失败域必须写清楚（v2 修正，P1-8）**：v1 把 `ExecCliRuntime` 描述成"Kernel 不可用时的降级路径"，但 `aragon` CLI 与 `@aragon-agent/core` **来自同一个包、同一个 registry**。于是"包拉不下来"这一最可能发生的事故里，两条路会同时失效——降级链给的是假的安全感。真实可用的判断是三分支：

| 状态 | 判据 | 走哪条路 | 用户看到 |
|---|---|---|---|
| A · 正常 | `/healthz` 通 且 `coreVersion` 匹配 | `HttpKernelRuntime` | 无提示 |
| B · 包在但 Kernel 挂了 | `node -e "import('@aragon-agent/core')"` 成功，`/healthz` 2 秒不通 | `ExecCliRuntime` | 设置页"Agent 内核：降级（CLI 直连）"，job 事件记 `runtime_degraded` |
| C · 包不可用 | Gate 0 的 G1 失败 | **模板降级**（不尝试 exec） | 设置页"Agent 内核：不可用 · 课程为简化版"，P02 顶部常驻提示 |

  选择策略：`REPOLEARN_AGENT_RUNTIME=kernel|exec|template|auto`（v2 增加显式 `template`）。`auto` 按 A→B→C 顺序判定，并把判定结果缓存在进程内 60 秒（避免每课时都探测一次），状态变化时写一条 `job_event` 便于事后归因。

#### 3.5.4 Kernel 的健康与降级

Kernel 不可用时**不是**整个生成停摆：N5/N6/N7 按上表 A→B→C 逐级降级。C 状态（模板降级）的产出规则必须写死，否则"简化版课程"会变成无意义的占位文本：N5 用确定性骨架（按目录深度与入度选出 4 章节 12 课时），N6 从每个课时的代表文件里抽取"文件头注释 + 顶层符号签名 + 被调用次数最高的 3 个函数"，用固定话术模板串成讲解与板书，N7 只输出 `static_inference` 级别的调用链（不编造 `source_fact`），`quality_report.degraded=true` 且 `anchor_confidence` 直接标 `low`。这条路径必须在测试里被覆盖（§8.2 T-DEG-1），因为它是"稳健可靠"的底线而不是例外。

### 3.6 首启 AI 服务配置引导（Onboarding）

#### 3.6.1 状态判定与首启守卫（v2 重写，P1-6）

`GET /v1/setup/state` 返回 `{required: bool, steps_done: [...], active_profile_id, next_step, gates{...}}`。判定 `required=true` 的条件：不存在 `active=true` 的 LLM profile，或该 profile 的 `last_probe.ok == false`。

**v1 的做法不可行，已废弃**：v1 让 `app/layout.tsx` 的服务端组件"带 300ms 超时调用该接口，`required=true` 就 `redirect('/setup')`"。三个问题：① RSC 里没有"超时后仍返回"的能力（`AbortSignal.timeout` 会让整个渲染抛错，等于白屏）；② API 尚未就绪时，`/setup` 自身也会被重定向到 `/setup`，形成 302 循环；③ 每次导航都在服务端同步打一次 API，把首屏时间绑在后端可用性上。

**v2 的守卫设计**（三条规则，任何一条都不允许把用户卡在死循环里）：

1. **`apps/web/src/middleware.ts` 做纯 cookie 判定，不打网络**：`POST /v1/setup/commit` 成功后由 BFF 写 `rl_setup=1`（`HttpOnly; SameSite=Lax; Path=/`）。中间件只读这个 cookie：没有它、且路径不在 `/setup` / `/api/*` / `/_next/*` / `favicon` 白名单内 → 307 到 `/setup?next=<原路径>`。判定是**纯内存操作**，无网络、无超时问题。
2. **向导页自己校验真实状态**：`/setup` 的客户端组件挂载后调 `GET /api/setup/state`；若 `required=false`（例如 cookie 被手工清掉但服务端已配好）则显示"已配置完成 · 回首页"，并补写 cookie。**不重定向**，避免 `middleware` 与页面互相打回。
3. **API 不可达时 fail-open**：`/setup` 的 `state` 请求失败 → 渲染"后端未就绪"专用页，内容为可直接执行的排错步骤（`.\start.ps1` 的日志位置、`:8000/healthz`、Doctor 面板入口），并提供"重试"按钮。**既不放行也不踢人**：放行会让人以为配置成功，踢人会造成循环。

cookie 是"提示"而非"权限"：任何写接口仍由 API 侧独立判定 `active profile` 是否存在（缺则 `SETUP_REQUIRED` 428），因此手工伪造 cookie 只能看到界面、不能生成课程。

#### 3.6.2 五步向导（`components/setup/WizardShell.tsx` 驱动）

| 步 | 标题 | 关键交互 | 落点接口 |
|---|---|---|---|
| S1 | 选择模型服务 | 卡片式选择 `Anthropic` / `OpenAI` / `Google` / `自定义（OpenAI 兼容）` / `自定义（Anthropic 兼容）` / `自定义（Gemini 兼容）`；协议不同则表单字段不同（`base_url` 仅在自定义协议出现） | `POST /v1/setup/llm/probe` |
| S2 | 连通性与模型发现 | 输入 API Key → 点击"测试连接" → 展示延迟、可用模型列表（带 context window、模态徽标 text/vision/audio/tool/json）、错误按 `hint` 给出可操作建议 | 同上（`probe` 返回 `models[]`） |
| S3 | 语音服务（豆包 TTS，可跳过） | 火山 `appid` + `access_token` + 集群 + 音色下拉（试听 3 秒样例） | `POST /v1/setup/tts/probe` |
| S4 | 角色与默认模型 | 六个角色（planner/writer/critic/vision/quiz/embed）逐个赋模型，带"按能力自动分配"按钮；无多模态模型时 `vision` 角色显示"将退化为文本启发式" | `POST /v1/setup/commit` |
| S5 | 完成 | 展示所建 profile 摘要、写入 `settings_revisions`、跳转首页；同时给出"随时可在设置里切换/回滚"的提示 | `POST /v1/setup/commit` |

向导全程支持"返回上一步不丢输入"（zustand 持久化到 `sessionStorage`）、"跳过音频"、"导入 `.env` 中的现成 Key"（若服务端环境变量已有 Key，S2 直接展示"检测到已配置密钥，可直接测试"）。**任何一步失败都不锁死向导**，`probe` 的失败是数据不是异常。

#### 3.6.3 密钥处理

- 落库为 `llm_profiles.api_key_ciphertext`：Fernet（`REPOLEARN_SECRET_KEY`，32 字节 urlsafe base64）加密，AAD 绑定 `profile_id`，防跨行搬运。
- 出站 API 只返回 `api_key_last4` 与 `has_key`，永不回传明文。
- 密钥轮换：`POST /v1/settings/rotate-secret` 用新 Key 重加密全部行（同一事务）；失败回滚。
- 日志过滤器对 `sk-`/`Bearer` 形状做全量脱敏（`core/logging.py::redact`），并在测试里断言（§8.2 T-SEC-1）。
- 未配置 `REPOLEARN_SECRET_KEY` 时，`start.ps1` 生成一次随机 Key 写入 `.env`（首次运行），避免"开发机必须手工造密钥"。

### 3.7 多协议 LLM 适配与多模态能力

#### 3.7.1 适配层

`providers/llm/` 下每个协议一个适配器，统一接口：

```
class LlmAdapter(Protocol):
    async def probe(self, cfg: LlmConfig) -> ProbeResult          # 连通性 + 模型列表
    async def list_models(self, cfg: LlmConfig) -> list[ModelInfo] # 模态/上下文/价格
    async def complete(self, req: CompletionRequest) -> CompletionResult
    async def stream(self, req: CompletionRequest) -> AsyncIterator[Chunk]
```

`protocol` 取值与实现：

| protocol | 目标 | 关键差异 |
|---|---|---|
| `anthropic_messages` | Anthropic 官方 / Anthropic 兼容网关 | `/v1/messages`，`system` 独立字段，`max_tokens` 必填，图片走 `image` block（base64 或 url），支持 `thinking` |
| `openai_chat` | OpenAI 官方 / Azure / 兼容网关 | `/v1/chat/completions`，多模态走 `content` 数组 `image_url` |
| `openai_responses` | OpenAI 新 Responses API | 工具调用与流事件形状不同，单独适配，避免主机型升级时被动 |
| `google_generate` | Gemini | `generateContent`，图片走 `inline_data`，`safetySettings` 显式关闭教学场景误伤（仅当 provider 支持） |
| `*_compatible` | 任意自定义网关 | 复用上表实现，仅 `base_url` 与少量字段名覆盖（`providers/llm/compat_map.py`） |

**模型能力探测（模态）**：`ModelInfo.capabilities = {text, vision, audio_in, audio_out, tools, json_mode, streaming, thinking, context_window, price_in, price_out}`。来源优先级：① provider `/models` 返回的元数据；② 内置 `model_catalog.py` 静态表（覆盖主流型号，随代码更新）；③ 探测性调用（仅当用户在向导里点"自动检测"，发一张 32×32 纯色图判断是否支持图片输入，失败也只是一次失败记录）。**探测结论缓存到 `model_catalog` 表**，7 天过期，避免每次启动打一遍 provider。

#### 3.7.2 多模态在业务里的三处真实用途（不是摆设）

1. **README 图表理解**：仓库 README 常带架构图/流程图。若 `vision` 角色有模型，`analyze_repo` 末段把 README 中的图片（上限 6 张、每张 ≤ 4 MB、格式 png/jpg/gif/webp）交给 vision 模型，产出 `diagram_notes[]`（图里出现的模块名、数据流向），作为 N5 规划章节的提示。没有 vision 模型时跳过并记 `VISION_SKIPPED`。
2. **讲解配图的可读性校验**：生成 Mermaid 后渲染为 SVG，若文本溢出或空图，用 vision 模型复核一次（可选开关 `REPOLEARN_VISION_QA=1`）。
3. **PDF 排版回归**：书籍导出前，把首章渲染成 PNG 交 vision 模型判断"是否有溢出/重叠"，作为质量门（默认关闭，避免成本）。

#### 3.7.3 角色路由与降级

```
resolver.resolve(role) → [(model, weight)]   # 主模型 + 备用链
```

- 每个角色主模型失败（`LLMError.retryable` 重试后仍失败）时切备用；备用也未配置则抛 `NO_MODEL_FOR_ROLE`，由节点决定降级路径（§3.4 的失败策略）。
- 成本守卫：`providers/budget_guard.py` 在每次调用前估算 prompt 规模（`estimatePromptTokens` 同口径：4 字符/token），超单次上限直接拒绝并记 `budget_warning`，避免一条超长 prompt 打穿预算。

### 3.8 音频 TTS（豆包 / 火山引擎）

- 适配器 `providers/tts/doubao.py`：优先 HTTP 一次性合成（`/api/v1/tts`，`cluster=volcano_tts`）以简化错误处理，长文本（> 800 字）按句切分并发 2 路合成后拼接；同时实现 WS 流式通道（`wss://openspeech.bytedance.com/api/v1/tts/ws_binary`）用于"边合成边播"的预览。
- 参数：`voice_type`（音色）、`speed_ratio`（默认 1.0，播放器倍速是客户端行为，不重合成）、`emotion`（可选）、`format=mp3`、`sample_rate=24000`。
- 缓存键：`sha256(provider + voice + speed + text)` → `var/objects/audio/<hh>/<hash>.mp3` + `audio_assets` 行（`duration_ms`、`bytes`、`text_hash`）。**同一句话在 10 个课时里只合成一次**，这是成本控制的关键。
- 时长获取：解析 mp3 帧头估算（`mutagen` 可选依赖，缺失时用 24 kbps 恒定码率近似并标 `duration_source="estimated"`）。时间轴用它换算每个 segment 的起止毫秒。
- 失败降级：连续 3 次失败 → 该课时 `audio=null`，前端播放器切换为"字幕自动推进"模式（`timing_source="estimated"`，按 4.2 字/秒推进）。**这保证没有音频服务也能完课**。
- 版权与合规：TTS 只读课程文案（我们自己生成的文本），不合成用户仓库原文整段代码注释以外的内容；每段音频资产在 `audio_assets` 记录来源 profile，便于切换音色后按需重合成。

### 3.9 关键操作时序

**S1｜首次启动进入配置引导**

```
浏览器 → web(SSR) : GET /
web → api : GET /v1/setup/state            (required=true)
web → 302 /setup
用户选 Anthropic → 输入 Key → 测试
web → api : POST /v1/setup/llm/probe {protocol:"anthropic_messages", api_key, base_url?}
api → provider : GET /v1/models (+ 1 次 8-token 试调用)
api → web : {ok, latency_ms, models:[{id, capabilities, context_window}]}
web → api : POST /v1/setup/commit {llm, tts?, roles}
api : 加密写入 llm_profiles + settings_revisions(rev+1) + active=true
web → / : 首页
```

**S2｜导入仓库并生成课程**

```
web → api : POST /v1/courses {repo_url}      (Idempotency-Key: 客户端 UUID)
api : normalize → 查 course_versions 缓存键(hash, sha, policy_version, lang)
  命中 → 200 {course_id, reused:true}  (不建 Job)
  未命中 → 事务内: create repositories/commits/course_versions(status=generating)
          + dedupe lock(generation_locks) + jobs(status=queued) → 202 {job_id, course_id}
web : EventSource /v1/jobs/{job_id}/events
worker : claim → LangGraph.ainvoke(state, config{thread_id:job_id})
  每个节点完成 → INSERT job_events(node, status, progress, message)
  关键节点 → 推送 SSE（骨架就绪即可让用户在 P02 看到章节列表）
完成 → course_versions.status=ready + quality_report → SSE `job.completed`
```

**S3｜播放一步课程（前端时间轴）**

```
web: GET /v1/courses/{id}/lessons/{key}/playback
api: 返回 lesson + steps[{focus{file,line_start,line_end}, segments[{text,start_ms,end_ms}],
        audio_url, board, quiz, code_notes}]   (一次拉全，避免播放中请求)
web: <audio> 播放 → raf 循环 → 当前 ms → 二分定位到 segment
     → highlightLayer 更新 Monaco decorations（只增删变化行）
     → board 组件按 segment.board_actions 高亮节点
     → subtitle 字幕滚动（不打断阅读）
```

**S4｜行内提问**

```
web : 选中行 103 → 点击"解释这行"
web → api : POST /v1/courses/{id}/questions {file, lines:[103,107], question, layer:"deep_dive"}
api : 组装上下文（当前 lesson 摘要 + 该文件对应源码片段 + 锚点表 + 用户历史 3 轮）
   → Kernel Agent role=critic，tools=[repo_read_file, repo_grep]
   → 流式 SSE 返回（边出边渲染）
api : 落库 questions(id, course_version_id, anchor, question, answer_md, evidence[], tokens)
web : 展示答案 + 证据列表（文件:行 → 点击跳转并高亮）
```

**S5｜完课 → 生成书籍 → PDF**

```
web → api : POST /v1/courses/{id}/books {preset:"standard"|"deep", include_audio:false}
api : 幂等键 (course_version_id, preset, template_version) → 命中则直接返回
  未命中 → Job(kind=book) → 复用课程资产分章 → Kernel role=writer 逐章扩写
   → 章节 JSON 落 book_chapters → 在线可读(status=ready)
web → api : POST /v1/books/{id}/pdf → Job(kind=pdf) → 服务端渲染 HTML→PDF
   → var/objects/pdf/<book>-<preset>-<template>.pdf
web : P10 展示页数/大小/生成时间 + 下载链接 + 源 Commit
```

### 3.10 缓存、幂等与去重

| 层 | 键 | 存储 | 失效条件 |
|---|---|---|---|
| 课程复用 | `sha256(repo_full_name, commit_sha, policy_version, language)` | `course_versions.cache_key`（唯一索引） | `policy_version` 提升；手动"重建" |
| 生成去重锁 | 同上 cache_key | `generation_locks(cache_key PK, job_id, expires_at)` | Job 终态或 30 分钟超时 |
| AI 产物 | `sha256(prompt_version, model_id, inputs_digest)` | `ai_cache(key, response_json, created_at)` | 7 天或模型/版本变更 |
| 音频 | `sha256(provider, voice, speed, text)` | `var/objects/audio/...` + `audio_assets` | 永久（音色变更即新键） |
| 书籍 | `sha256(course_version_id, preset, template_version)` | `book_versions.cache_key` | 课程新版本 / 模板升级 |
| PDF | `sha256(book_version_id, pdf_engine_version)` | `var/objects/pdf/...` | 书籍新版本 |
| 仓库数据 | `sha` | `var/objects/mirrors/<sha8>/` | 永不过期，LRU 2 GB 清理由 CLI 完成 |

`POST /v1/courses` 的 `Idempotency-Key` 请求头做**请求级**幂等（同键 10 分钟内返回同一个 Job），`cache_key` 做**内容级**复用。两者缺一不可：前者防用户连点两次，后者防"同一仓库第二次访问还花一遍 Token"。

**发布的事务边界**：N9 在单个事务里创建 `course_version`→`lessons`→`anchors`→`traces`→`quiz_items`，并用 `course_versions.status` 作为对外可见开关（只有 `ready`/`partial` 的版本可被读取）。任何中途失败，事务回滚，用户看不到半成品课程；`generating` 状态的版本只用于前端展示"生成中"。

### 3.11 可靠性与降级

1. **进程级**：三个进程各自 `/healthz`；`start.ps1` 按依赖顺序起（kernel → api → web），每个都轮询健康检查（超时 60s 报错并 dump 日志尾部），并校验 `X-Internal-Token` 能通。任一进程退出，`stop.ps1`/重启用同一份 PID 文件收尾，不残留孤儿。
2. **Job 级**：状态机 `queued → claimed → running → (ready|partial|failed|failed_budget|cancelled)`；每次节点推进写 `job_events`（含 `node`、`progress`、`message`）。
   - **节点执行期间必须持续心跳（v2 新增，P1-1）**：v1 只在"节点推进"时写 `heartbeat_at`，但 N6 单节点跑 10 分钟以上是常态（12 个课时 × 每课时多轮取证）。若回收阈值仍是 90 秒，就会出现"任务正跑得好好的被自己判死"——后果不是一次报错，而是**重复执行并重复烧 token**。v2 规定：runner 在每个节点内启动一个 15 秒周期的后台心跳任务（`asyncio.create_task`），节点结束即取消；回收阈值只在心跳本身也停更时才生效。
   - **僵尸版本回收（v2 新增，P1-13）**：v1 只管 Job，没人管 `course_versions.status='generating'` 的行。API 一旦在 N9 之前重启（开发期每天都在发生），这些行就永久停在"生成中"：用户在 P02 看到永远转圈的进度条，而同一 `cache_key` 的新请求又被 `generation_locks` 挡住，于是这个仓库从此无法再生成课程。v2 增加 **reaper**：API 启动时立即跑一次、之后每 60 秒跑一次，把"`status='generating'` 且 `updated_at` 早于 `now - job_deadline - 5min` 且没有对应活跃 Job"的版本置为 `failed`，`warnings` 追加 `{code:"ORPHANED_GENERATION"}`，并删除其 `generation_locks` 行。reaper 的判定必须**先删锁再改状态**（反序会留下"状态已失败的锁"，同样卡住重建）。
3. **调用级**：所有出站 HTTP（GitHub / provider / TTS）统一 `httpx` 客户端，`timeout=(5, 60)`、连接池上限、`Retry-After` 尊重、指数退避 + 抖动、按 provider 熔断（连续 5 次失败 → 打开 30 秒）。
4. **并发度（v2 统一，P1-2）**：`REPOLEARN_MAX_CONCURRENT_JOBS`，**默认 1**。这不是保守，是 SQLite 单写者的物理限制：并发 2 时两个 Job 的写入会互相触发 `busy_timeout`，表现为"偶发的 5 秒卡顿"，比串行更慢且更难查。用 PostgreSQL 时可设为 2–4（`docker-compose.yml` 样例里已如此配置）。v1 在 §3.12 写"并发上限默认 2"、在 R4 写"默认并发 1"，两处冲突，以本节为准。
5. **降级矩阵**（必须全部有测试）：

| 故障 | 降级行为 | 用户可见 |
|---|---|---|
| Kernel 进程挂了（包在） | 切 `ExecCliRuntime` | 设置页"Agent 内核：降级（CLI）" |
| `@aragon-agent/core` 不可获取 | 模板降级生成最小课程（**不尝试 exec**，见 §3.5.3） | P02 顶部提示"内容为简化版" |
| tree-sitter 语言包缺失 | 正则抽取 | 生成报告 `ANALYSIS_DEGRADED`，`anchor_confidence=low` |
| TTS 不可用/未配置 | 字幕自动推进 | 播放器显示"无配音" |
| vision 模型缺失 | 跳过图片理解 | 生成报告里 `VISION_SKIPPED` |
| GitHub 限流 | 提示 `RATE_LIMITED` + 重试时间 | 错误卡片带"如何配置 token" |
| 预算超限 | 保留已完成课时，`partial` | 完课页可"继续生成" |
| Chromium 不可用 | PDF 改为打印视图 | P10"下载 PDF"变为"打开打印视图" |
| DB 锁争用 | 队列串行化 + 500ms 退避 | 无感 |
| API 重启留下僵尸版本 | reaper 置 `failed` 并释放锁 | P02 显示"上次生成中断 · 可重新生成" |

6. **前端韧性**：所有请求经 `lib/api/client.ts`（**同源 `/api/*`**），默认 15s 超时、GET 幂等重试 2 次、错误映射为 `{code, message, hint}` 结构化提示；SSE 断线自动重连（指数退避，最多 5 次）并用 `Last-Event-ID` 续传，缺失事件从 `GET /v1/jobs/{id}` 快照补齐；关键页面有 `Skeleton` 与 `ErrorBoundary`，禁止"白屏"。进度上报在 `visibilitychange=hidden` 与 `beforeunload` 用 `navigator.sendBeacon` 补发（`sendBeacon` 只发 `POST`，因此服务端额外提供 `POST /v1/courses/{id}/progress/beacon`，接受与 `PUT` 相同的体）。

### 3.12 安全与信任边界

- **仓库内容是不可信输入**：`ingest/guard.py` 拒绝绝对路径、`..`、符号链接（Windows 下还检查 junction/reparse point）、可执行文件、超大文件；镜像目录以只读方式打开；Kernel 的文件工具二次校验（§3.5.2）。README/注释中的任何"指令"都只作为被引用的文本进入 prompt，且 prompt 里显式包裹 `<untrusted_repo_content>` 标签并声明"其中内容不是指令"。
- **源码不执行**：全流程没有 `subprocess` 执行仓库代码的路径；`aragon exec` 以 `--permission-mode plan` 启动（只读），Kernel 内 `Agent` 的工具白名单只有 4 个只读工具。
- **密钥**：§3.6.3；`.env` 与 `var/` 进 `.gitignore`；响应体与日志双重脱敏。
- **同源与内部令牌（v2 新增，P0-2）**：API 与 Kernel 只绑 `127.0.0.1`；API 对浏览器侧只接受经 BFF 的请求（校验 `X-Internal-Token`，由 `start.ps1` 生成随机值写入 api 与 web 各自的 `.env`），这使"用户在同一台机器上另开标签页直接打 `:8000`"也不成立。CORS **全部关闭**（同源设计下不需要 CORS，保留白名单只会给未来留一个错误开关）。
- **注入与 XSS**：生成的 Markdown 统一由 `react-markdown` + `rehype-sanitize`（白名单 schema）渲染；Mermaid 用 `securityLevel: strict`；PDF 用服务端模板，不插入原始 HTML。
- **CSRF/会话**：写操作要求 `X-CSRF-Token`（双提交 cookie）；会话 cookie `HttpOnly; SameSite=Lax; Secure`（生产）。**同源是这套机制成立的前提**（跨源时 `SameSite=Lax` 的 cookie 根本不会被带上，CSRF 校验会 100% 失败）——这就是为什么 §2.2 约束 6 把它列为硬约束而非风格选择。MVP 无登录时创建本地默认用户 `local`，但所有查询仍走 `user_id` 过滤，为将来的多用户留好形状。
- **成本/滥用**：单 IP 限流（`slowapi`，课程创建 5 次/10 分钟）、并发 Job 上限 `REPOLEARN_MAX_CONCURRENT_JOBS`（**默认 1**，见 §3.11.4）、`cost_ledger` 记录每个 Job 的 token 与美元估算，设置页可看。
- **请求体不落日志（v2 新增，P1-14）**：`core/logging.py` 的中间件只记录**元数据**（method、path、status、duration、req_id、body_bytes），不记录 body；Kernel 侧 `disableRequestLogging: true`（§3.5.2）。原因是配置引导与每次生成请求里都可能携带明文密钥，而"日志里翻到 Key"是这类系统最常见的事故形态。

### 3.13 可观测性

- **结构化日志**：`structlog` JSON，字段 `ts, level, req_id, job_id, course_id, node, event, duration_ms`；`var/logs/api.log` 轮转（10 MB × 5）。
- **请求追踪**：`X-Request-Id` 全链路透传（web → api → kernel），响应头回显；前端报错弹窗带 `req_id` 方便对日志。
- **作业面板**：`GET /v1/jobs?status=running` + `/settings` 的"任务"页签，展示进度条、当前节点、耗时、token 消耗。
- **指标**：`GET /v1/metrics`（JSON，非 Prometheus 依赖）返回 Job 成功率、P50/P95 时长、缓存命中率、provider 错误率；PRD §6 的四项指标在这里可读。
- **质量报告**：`course_versions.quality_report` 记录锚点覆盖率、课时完成率、trace 的 certainty 分布，前端在 P02 与 P08 以"内容可信度"面板展示（教学场景里这是信任来源）。

---

## 4. 文件 / 模块变更计划

> 全部为**新建**（仓库当前只有 `doc/` 与 `.agentmesh/`）。"工作量"列是相对权重，用于开发节点排期；"验收关联"指向 §8 的用例编号。

### 4.1 根与工程化（14 个文件）

| 文件 | 变更 | 意图 | 验收关联 |
|---|---|---|---|
| `README.md` | 新建 | 一页跑通：前置依赖、`.\start.ps1`、配置引导、常见问题、架构图 | 人工 |
| `.gitignore` | 新建 | 忽略 `.env`、`var/`、`.run/`、`node_modules`、`.venv`、`*.db`、`dist/`、`.next/`、`test-results/` | 人工 |
| `.env.example` | 新建 | 全部 `REPOLEARN_*` 变量与注释，作为配置唯一说明 | T-CFG-1 |
| `start.ps1` | 新建 | 一键启动：环境探测 → **Gate 0 依赖探测（§2.4）** → 安装依赖 → 迁移 → 起 kernel/api/web → 健康轮询 → 打印地址与 Gate 结论。支持 `-SkipInstall`、`-NoWeb`、`-Port` 与 **`-Prod`**（v2 定义，P2-4：`next build && next start` + `REPOLEARN_ENV=production` + 关闭热重载） | T-SCR-1/2 |
| `stop.ps1` | 新建 | 读 `.run/*.pid` 逐进程 `taskkill /T /F`，再按端口兜底清理，最后删 PID 文件；幂等可重复执行 | T-SCR-3 |
| `scripts/check_env.ps1` | 新建 | 被 `start.ps1` 复用：校验 node ≥ 20、pnpm、python ≥ 3.11，并执行 §2.4 的 Gate 0 三条探测，产出 `.run/preflight.json`；**版本不足**才以非 0 退出，Gate 失败只降级不阻断 | T-SCR-4 / M0 |
| `scripts/export_contracts.py` | 新建 | 导出 `openapi.json` 与 JSON Schema；`--check` 模式在 CI 里校验漂移 | T-CON-1 |
| `scripts/gen_fixtures.py` | 新建 | 生成/刷新测试夹具（GitHub 响应、黄金课程 JSON） | T-TEST-1 |
| `scripts/backfill_quality.py` | 新建 | 回填历史课程的 `quality_report` 与锚点覆盖率 | 人工 |
| `scripts/prune_objects.py` | 新建 | 镜像 LRU 清理 + 孤儿音频/PDF 清理 | T-OPS-1 |
| `pnpm-workspace.yaml` | 新建 | 声明 `apps/web`、`packages/contracts`、`services/agent-kernel` | T-SCR-1 |
| `package.json`（根） | 新建 | 根脚本：`dev`、`build`、`test`、`typecheck`、`contracts`，用 `pnpm -r` 串起子包 | T-SCR-1 |
| `pyproject.toml` | 新建 | Python 项目（根即项目根，包在 `apps/api/repolearn`）：依赖、`[tool.ruff]`、`[tool.pytest.ini_options]`、`[tool.mypy]`。**必须显式声明打包范围**，否则 `python -m repolearn.cli` 不可用（P0-5）：见下方"Python 入口的落地方式" | T-SCR-1 / M0 |
| `docker-compose.yml` | 新建（**M6 之后，非 MVP**） | 可选：PostgreSQL + MinIO + api/worker/web 的生产样例（不参与默认开发流，见 §11 第 19 项） | 人工 |

**Python 入口的落地方式（v2 新增，P0-5）**

v1 的布局是"根 `pyproject.toml` + `apps/api/repolearn/` 包"，但从未说明这个包怎么变得可导入，而 §10 步骤 1 的完成判据恰恰是 `python -m repolearn.cli --help`。v2 把它写死为一条可执行路径：

```toml
# pyproject.toml（根）
[project]
name = "repolearn"
requires-python = ">=3.11"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["apps/api/repolearn"]      # 关键：把 apps/api 下的包纳入 wheel

[tool.pytest.ini_options]
pythonpath = ["apps/api"]              # 不装包也能跑测试/直接 import
testpaths = ["apps/api/tests", "tests"]
```

- **开发流程**：`python -m venv .venv` → `.venv\Scripts\pip install -e .`（`-e` 即可编辑模式，改代码不必重装）。`start.ps1` 在首次运行时完成这两步，之后只在 `pyproject.toml` 的哈希变化时重装。
- **兜底**：即使 `pip install -e .` 因网络失败，`pytest` 仍靠 `pythonpath` 工作，`python -m repolearn.cli` 也可用 `PYTHONPATH=apps/api` 前缀运行——脚本必须在报错信息里给出这一行，而不是只报"模块不存在"。

### 4.2 `services/agent-kernel`（11 个文件）

| 文件 | 变更 | 意图 | 验收关联 |
|---|---|---|---|
| `package.json` | 新建 | `"type": "module"`、依赖 `@aragon-agent/core@^0.2.63`、`fastify`、`zod`、`zod-to-json-schema`；`start`/`test` 脚本 | T-KRN-1 |
| `tsconfig.json` | 新建 | Node20/ESM/`verbatimModuleSyntax`、`noUncheckedIndexedAccess` | T-KRN-1 |
| `src/server.ts` | 新建 | Fastify 实例、路由注册、`X-Request-Id` 透传、优雅关闭（`SIGINT` 时 abort 全部在跑 run） | T-KRN-2 |
| `src/runtime.ts` | 新建 | `initProviders()` 单例、`Agent` 构建与复用、API Key 内存传入、run 生命周期表 | T-KRN-2 |
| `src/events.ts` | 新建 | core 事件 → 统一信封（§5.5）的映射器 | T-KRN-3 |
| `src/budget.ts` | 新建 | turns/tokens/usd 计量与主动 abort | T-KRN-4 |
| `src/tools/repo.ts` | 新建 | 4 个只读仓库工具 + 根目录 jail + 截断策略 | T-KRN-5 |
| `src/tools/emit.ts` | 新建 | 3 个结构化产出工具（zod 校验，失败把校验错误回灌给 Agent） | T-KRN-6 |
| `src/contracts/schema.ts` | 新建 | 课程骨架/课时/trace/quiz 的 zod schema（与 `packages/contracts/schemas` 同源导出） | T-CON-2 |
| `src/health.ts` | 新建 | `/healthz` + `/v1/capabilities`（可选 provider、core 版本、工具清单） | T-KRN-2 |
| `test/*.test.ts` | 新建 | `node --test`：假 provider 驱动的事件映射、预算中断、路径穿越、schema 拒绝 | T-KRN-3/4/5/6 |

### 4.3 `packages/contracts`（6 个文件）

| 文件 | 变更 | 意图 | 验收关联 |
|---|---|---|---|
| `package.json` | 新建 | `gen`（openapi-typescript）、`check` | T-CON-1 |
| `openapi.json` | 生成 | FastAPI 导出的唯一契约来源（入库，CI 校验） | T-CON-1 |
| `schemas/course.json` `lesson.json` `trace.json` `book.json` | 生成 | 由 zod 导出的 JSON Schema，Python 侧 `jsonschema` 复用 | T-CON-2 |
| `src/index.ts` | 新建 | 导出生成的 `paths`/`components` 类型 + 事件信封类型 + 错误码枚举 | T-CON-1 |

### 4.4 `apps/api`（约 100 个文件，按目录）

**入口与核心（9）**

| 文件 | 变更 | 意图 |
|---|---|---|
| `repolearn/main.py` | 新建 | `create_app()`；lifespan 内初始化 DB/迁移检查/Job Runner/Kernel 健康探测；挂载 routers 与 CORS |
| `repolearn/core/config.py` | 新建 | `Settings`（pydantic-settings）：`database_url, secret_key, object_root, github_token, kernel_url, agent_runtime, job_deadline_ms, tts_*, vision_qa, cors_origins` |
| `repolearn/core/db.py` | 新建 | async engine、`async_session_maker`、`get_session`、SQLite WAL/`foreign_keys=ON`/`busy_timeout=5000` |
| `repolearn/core/security.py` | 新建 | Fernet 封装（加解密 + AAD）、CSRF 校验依赖、`mask_key` |
| `repolearn/core/errors.py` | 新建 | `AppError` + **19 个错误码常量**（§5.6 定稿数量）+ 全局异常处理器（输出 §5.6 形状） |
| `repolearn/core/logging.py` | 新建 | structlog 配置、`redact()`、请求上下文中间件 |
| `repolearn/core/ids.py` / `core/clock.py` | 新建 | 前缀 ID 生成、可注入时钟 |
| `repolearn/cli.py` | 新建 | `migrate`/`seed-demo`/`export-openapi`/`prune`/`requeue-stale` 子命令 |

**数据模型（27 个文件 = 26 表 + `__init__.py`，一表一文件；v2 补齐 P0-3）**：`models/{repository,commit,course_version,lesson,step,source_anchor,simulated_trace,quiz_item,quiz_attempt,book_version,book_chapter,pdf_export,user,user_progress,note,question,job,job_event}.py`，另有 `models/{llm_profile,model_catalog,setting_revision,ai_cache,generation_lock,idempotency_key,cost_ledger,audio_asset}.py` 与 `models/__init__.py`（详见 §6 表清单；v1 漏掉了 `pdf_export` 与 `quiz_attempt`，导致 §6.2 有表而 §4.4 无文件）。

**Pydantic schema（9）**：`schemas/{setup,course,lesson,playback,book,progress,note,question,job}.py`。

**路由（11）**：`routers/{setup,settings,repos,courses,lessons,playback,questions,books,progress,notes,jobs}.py` + `routers/health.py`。

**服务（14）**：`services/{setup_service,settings_service,repo_service,course_service,lesson_service,question_service,book_service,pdf_service,progress_service,note_service,job_service,quality_service,object_store,event_bus}.py`。

**Provider（7）**：`providers/{base,registry,compat_map,budget_guard}.py`、`providers/llm/{anthropic_adapter,openai_adapter,openai_responses_adapter,google_adapter,model_catalog}.py`、`providers/tts/doubao.py`（合并计 7 个模块文件 + 5 个 LLM 适配器）。

**工作流（7）**：`workflow/{course_graph,state,prompts,parsing,repair,simulation_guard,publish}.py`。

**任务（4）**：`jobs/{queue,runner,handlers,events}.py`。

**摄取与解析（6）**：`ingest/{github,tarball,guard,mirror}.py`、`analysis/{symbols,callgraph,knowledge_graph,key_chain}.py`。

**渲染（3）**：`rendering/{mermaid,pdf,book_layout}.py`。

**迁移（1 目录）**：`migrations/versions/0001_initial.py`（覆盖 §6 全部表）、`alembic.ini`、`migrations/env.py`。

**测试（约 22 个文件）**：见 §8.2。

### 4.5 `apps/web`（46 个文件）

| 文件/目录 | 变更 | 意图 |
|---|---|---|
| `next.config.ts`、`tsconfig.json`、`postcss.config.mjs`、`tailwind.config.ts`、`eslint.config.mjs` | 新建 | 工程配置（App Router、严格 TS、Tailwind v4 token） |
| `src/styles/tokens.css` | 新建 | §7.1 的 24 个设计变量 + 基础排版 + 焦点环 |
| `src/app/layout.tsx` | 新建 | 字体、Provider、`/setup` 重定向守卫、Toast 容器 |
| `src/app/page.tsx` + `components/home/{HeroImport,HotCourses,RecentLearning,FeatureGrid}.tsx` | 新建 | P01 首页（对齐设计稿：搜索式 URL 输入、热门课程卡、四宫格能力说明） |
| `src/app/setup/page.tsx` + `components/setup/{WizardShell,ProviderSelect,CredentialsForm,ProbeResultCard,ModelRoleMatrix,TtsStep,FinishStep}.tsx` | 新建 | §3.6 五步向导 |
| `src/app/repo/[owner]/[name]/page.tsx` + `components/prepare/{PrepareProgress,CourseBlueprint,QualityPanel}.tsx` | 新建 | P02 课程准备/概览（含 SSE 进度） |
| `src/app/course/[courseId]/layout.tsx` + `components/shell/{TopProgress,OutlineRail,MentorRail,CourseHeader}.tsx` | 新建 | P03–P05 共用工作台外壳（对齐设计稿左侧大纲 + 顶部三段 + 右侧 Momo） |
| `.../overview/page.tsx` + `components/learning/{ArchitectureCanvas,ConceptCard,DualPane}.tsx` | 新建 | 第一层宏观架构 |
| `.../walkthrough/page.tsx` + `components/learning/{TraceStrip,StepNarration,PredictionQuiz,VariablePanel}.tsx` | 新建 | 第二层全局走读 |
| `.../deep-dive/page.tsx` + `components/learning/{InlineAsk,CodeNoteCard,CallChainSheet}.tsx` | 新建 | 第三层深入源码 |
| `components/ide/{CodePane,FileTree,Breadcrumb,HighlightLayer,ReadOnlyBadge}.tsx` | 新建 | 只读 IDE（Monaco + decoration） |
| `components/player/{TransportBar,SubtitleView,SpeedMenu,CaptionsToggle}.tsx` + `lib/player/{timeline,subtitles}.ts` | 新建 | 教学播放器与时间轴引擎 |
| `src/app/course/[courseId]/recap/page.tsx` + `components/recap/{KnowledgeReview,QuizReview,AbilityRadar,CompletionCard}.tsx` | 新建 | P08 完课总结（对齐设计稿第 6 张） |
| `src/app/book/[bookId]/page.tsx` + `components/book/{BookReader,ChapterNav,SearchPanel,SourceJump}.tsx` | 新建 | P09 在线书籍 |
| `src/app/book/[bookId]/pdf/page.tsx` + `components/book/{PdfPreview,ExportCard}.tsx` | 新建 | P10 PDF 预览/下载 |
| `src/app/settings/page.tsx` + `components/settings/{ProfileList,RoleMatrix,RevisionTimeline,CostPanel,DoctorPanel}.tsx` | 新建 | 设置：模型角色、版本回滚、成本、诊断 |
| `src/app/api/**/route.ts`（5 个） | 新建 | BFF：会话/CSRF、`/api/sse/jobs/[id]` 代理、图片与音频同源代理 |
| `src/lib/api/{client.ts,errors.ts}`、`src/lib/sse/useEventStream.ts`、`src/stores/{player,ide,setupWizard}.ts` | 新建 | 网络层、SSE 续传、播放器状态机 |
| `src/lib/api/schema.d.ts` | 生成 | openapi-typescript 产物 |
| `e2e/*.spec.ts`（4 个） | 新建 | 见 §8.3 |

### 4.6 文档（3）

| 文件 | 意图 |
|---|---|
| `docs/runbook.md` | 启动排错、端口占用、Kernel 降级、TTS 排查、Job 卡住如何回收、数据备份 |
| `docs/architecture.md` | 由本 spec §3 精简出的长期架构文档（评审后同步） |
| `docs/api.md` | 由 OpenAPI 说明补充的分页/SSE/错误码约定（避免读者去读 3 个 router） |

**文件总量**：约 180 个新增文件（含生成的契约与测试），实现顺序见 §10。

---

## 5. 接口设计

### 5.1 通用约定

- Base：`/v1`（**只能从 BFF 或本机 CLI 访问**；浏览器侧统一是 `/api/*`，见 §2.2 约束 6）。所有响应 `application/json; charset=utf-8`，SSE 为 `text/event-stream`。
- 请求头：`X-Request-Id`（可选，缺失则生成）、写操作必须 `X-CSRF-Token`、课程/书籍创建必须 `Idempotency-Key`、BFF 与内部调用必须带 `X-Internal-Token`。
- 分页：`?limit=20&cursor=<opaque>`，响应 `{items, next_cursor, total?}`。游标是不透明 base64（`created_at|id`），不用 offset 防跳页。
- 时间：全部 UTC ISO-8601（`2026-11-06T10:00:00Z`）。
- 成功：2xx + 资源体；创建异步任务：`202 {job_id, course_id, status_url}`。
- 失败：统一错误体（§5.6），HTTP 状态与 `code` 双语义。唯一例外是 `probe` 类"测量接口"（§5.2）。
- 幂等：`Idempotency-Key` 落在 `idempotency_keys(scope, key)`（**按路径模板分作用域**，§6.2），10 分钟内同键同体返回首次响应的快照；同键不同体 → 422 `IDEMPOTENCY_MISMATCH`。
- 版本协商：响应头 `X-API-Version: 1`；破坏性变更必须升 `/v2`。

### 5.2 公开 REST 一览

**配置引导与设置**

| 方法 | 路径 | 请求 | 响应 | 备注 |
|---|---|---|---|---|
| GET | `/v1/setup/state` | — | `{required, next_step, steps_done[], active_profile{id,provider,models}, kernel{ok,runtime}, gates{g1,g2,g3}}` | 守卫用；`middleware.ts` 只看 cookie，本接口由 `/setup` 页在客户端调用（§3.6.1） |
| POST | `/v1/setup/llm/probe` | `{provider, protocol, base_url?, api_key, org?}` | `{ok, latency_ms, models:[{id, display_name, capabilities{}, context_window, price}], error?}` | 失败也是 200，`ok=false`。**这是 §5.1 错误体约定的唯一例外**（P2-1）：`probe` 是"测量接口"，被测量的对象失败本身就是它的正常返回；但 `error` 字段仍用 `{code,message,hint,retryable}` 同一形状，前端的错误渲染逻辑不需要分叉 |
| POST | `/v1/setup/tts/probe` | `{provider:"doubao", app_id, access_token, cluster, voice_type}` | `{ok, latency_ms, sample_audio_url, duration_ms}` | 合成"你好，这里是 RepoLearn" |
| POST | `/v1/setup/commit` | `{llm:{...}, tts?:{...}, roles:{planner,writer,critic,vision?,quiz,embed?}}` | `{profile_id, revision, warnings[]}` | 事务内建 profile + revision + active |
| GET | `/v1/settings/profiles` | — | `{items:[{id,label,provider,protocol,base_url,model_count,api_key_last4,active,last_probe,created_at}]}` | 密钥只回 last4 |
| POST | `/v1/settings/profiles/{id}/activate` | — | `{active_profile_id, revision}` | 切换即新 revision |
| PATCH | `/v1/settings/roles` | `{roles:{...}}` | `{revision}` | 部分更新，校验模型能力 |
| GET | `/v1/settings/revisions` | `?limit` | `{items:[{id, rev, created_at, author, summary, changes[]}]}` | 版本时间线 |
| POST | `/v1/settings/revisions/{rev}/rollback` | — | `{revision}` | 生成新 revision 指向旧内容 |
| POST | `/v1/settings/rotate-secret` | `{new_secret}` | `{rotated: n}` | 重加密全部密钥 |
| GET | `/v1/settings/doctor` | — | `{checks:[{name,status,detail,hint}]}` | DB/kernel/TTS/GitHub/磁盘/密钥 |

**仓库与课程**

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/v1/repos/resolve` | `{repo_url}` | `{full_name, description, stars, license, default_branch, head_sha, existing_course?}` |
| POST | `/v1/courses` | `{repo_url, ref?, language?, policy_version?}` | `202 {job_id, course_id}` 或 `200 {course_id, reused:true}` |
| GET | `/v1/courses` | `?status&owner&q&limit&cursor` | `{items:[CourseListItem], next_cursor}`；列表项含 `id, repo{full_name,stars}, title, summary, lesson_count, minutes, status, quality{anchor_coverage}, updated_at, cover_palette` |
| GET | `/v1/courses/{id}` | — | `CourseDetail`（含 `sections[], blueprint, repo, commit, quality_report, warnings`） |
| POST | `/v1/courses/{id}/rebuild` | `{reason, from?:"curriculum"|"lessons"|"audio"}` | `202 {job_id}` |
| DELETE | `/v1/courses/{id}` | — | `204`（软删，用户私有标记） |
| GET | `/v1/courses/{id}/lessons` | — | `{sections:[{key,title,minutes,lessons:[{key,title,status,minutes,step_count}]}]}` |
| GET | `/v1/courses/{id}/lessons/{key}` | — | `LessonDetail`（steps + anchors + board + quiz，用于预取） |
| GET | `/v1/courses/{id}/lessons/{key}/playback` | — | `PlaybackBundle`（§5.3） |
| GET | `/v1/courses/{id}/files` | `?path=&commit_sha` | `{path, lang, line_count, content, truncated}`；`Cache-Control: private, max-age=3600`；路径必须在镜像白名单内 |
| GET | `/v1/courses/{id}/anchors` | `?file=` | `{items:[{id,file,symbol,line_start,line_end,kind}]}`（书架/证据跳转用） |

**提问、进度、笔记、完课**

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/v1/courses/{id}/questions` | `{file, line_start, line_end, question, layer, lesson_key?}` | SSE 流（`question.delta` → `question.completed{answer_md,evidence[],tokens}`） |
| GET | `/v1/courses/{id}/questions` | `?lesson_key` | `{items:[Question]}` |
| PUT | `/v1/courses/{id}/progress` | `{lesson_key, step_index, position_ms, percent}` | `{progress, course_percent}` |
| POST | `/v1/courses/{id}/progress/beacon` | 同上（`sendBeacon` 专用，`text/plain` 或 `Blob`） | `204`（无体，浏览器不读） |
| POST | `/v1/courses/{id}/quiz/{item_id}/answer` | `{choice_id}` | `{correct, explanation_md, evidence[], replayed}`（幂等键 `(user_id, quiz_item_id)`，见 §6.2 `quiz_attempts`） |
| GET | `/v1/courses/{id}/recap` | — | `{knowledge_points[], call_chain, pitfalls[], quiz_stats, next_steps[], ability{scores}}` |
| POST | `/v1/notes` `PATCH /v1/notes/{id}` `DELETE /v1/notes/{id}` | `{course_version_id?, anchor?, body_md, tags[]}` | `Note` |

**书籍与 PDF**

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/v1/courses/{id}/books` | `{preset:"standard"\|"deep", include_audio?:false}` | `202 {job_id, book_id}` / `200 {book_id, reused:true}` |
| GET | `/v1/books/{id}` | — | `{id, course_version_id, preset, status, chapters:[{key,title,words}], toc, quality}` |
| GET | `/v1/books/{id}/chapters/{key}` | — | `{key, title, blocks:[{type:"md"\|"code"\|"figure"\|"table", ...}], source_refs[]}` |
| POST | `/v1/books/{id}/pdf` | `{engine?:"chromium"}` | `202 {job_id}`（完成事件带 `pdf_url, pages, bytes`） |
| GET | `/v1/books/{id}/pdf` | — | `{status, pdf_url?, pages?, bytes?, generated_at?, commit_sha}` |

**任务与系统**

| 方法 | 路径 | 响应 |
|---|---|---|
| GET | `/v1/jobs` | `?status=&kind=&limit=` → `{items:[Job]}` |
| GET | `/v1/jobs/{id}` | `{id, kind, status, progress, node, message, course_id?, book_id?, started_at, finished_at, error?, cost{tokens,usd}}` |
| GET | `/v1/jobs/{id}/events` | SSE（§5.5） |
| POST | `/v1/jobs/{id}/cancel` | `{status:"cancelling"}` |
| POST | `/v1/jobs/{id}/retry` | `202 {job_id}`（新 Job，继承 cache_key） |
| GET | `/v1/metrics` | 聚合指标 JSON |
| GET | `/v1/objects/{kind}/{name}` | 二进制代理（`kind ∈ audio\|pdf\|diagrams`），支持 `Range`（音频拖动/PDF 流式）与 `ETag`；越界或未登记对象返回 `OBJECT_MISSING`。**内部端点**：浏览器不直接访问，统一经 BFF 的 `/api/objects/{kind}/{name}`（§5.3） |
| GET | `/healthz` | `{ok, db, kernel, migration, version, gates{g1,g2,g3}}` |

> **对象的 Range/ETag 契约（v2 补充，P1-4/P1-5）**：`Accept-Ranges: bytes` 恒返回；`Range: bytes=a-b` → `206` + `Content-Range: bytes a-b/total`；区间非法 → `416` + `Content-Range: bytes */total`；`If-None-Match` 命中 → `304`。`ETag` 取对象内容的 sha256 前缀（内容寻址存储天然满足"内容变则 ETag 变"）。BFF 必须**原样**转发这四个头，否则播放器 seek 会退化为"从头重新加载"，音频每次拖动都卡一次——这是"能否当作正式播放器"的分界线。

### 5.3 `PlaybackBundle`（播放器的唯一数据源）

```
{
  "course_id": "crs_01H...", "commit_sha": "9f3c...", "lesson": {"key":"3.1","title":"generate_reply 详解","layer":"deep_dive","minutes":6},
  "steps": [{
    "index": 0, "title": "构造 prompt",
    "duration_ms": 48200,
    "timing_source": "tts",                  // tts | estimated
    "audio": {"url": "/api/objects/audio/ab/abc.mp3", "duration_ms": 48200, "voice":"zh_female_..."},
    "segments": [
      {"id":"s0","text":"这里先把对话历史整理成 prompt。","start_ms":0,"end_ms":8400,
       "focus":{"file":"autogen/agentchat/agent.py","line_start":99,"line_end":100},
       "board_actions":[{"op":"highlight","node":"agent"}],
       "subtitle_style":"normal"}
    ],
    "board": {"kind":"architecture","mermaid":"flowchart LR ...","nodes":[{"id":"agent","label":"Agent","source":{"file":"...","line":88}}]},
    "code_notes": [{"file":"...","line":99,"text":"把 messages 规范化成模型输入"}],
    "quiz": [{"id":"qz_1","stem":"...","choices":[{"id":"a","text":"..."}],"answer_id":"b","explanation_md":"...","evidence":[...]}],
    "certainty_legend": {"source_fact":"源码事实","static_inference":"静态推断","teaching_simulation":"教学模拟"}
  }],
  "files": [{"path":"autogen/agentchat/agent.py","content_ref":"/v1/courses/{id}/files?path=...","lang":"python","line_count":412}],
  "trace": {"id":"trc_1","steps":[{"index":0,"title":"接收请求","certainty":"source_fact","evidence":[...],"variables":[{"name":"message","value":"\"帮我总结一下 AutoGen 是什么？\"","note":"示例值"}]}]}
}
```

- `code` 内容不内联到 playback（体积大），由 `GET /v1/courses/{id}/files?path=` 按需拉取并缓存（`Cache-Control: private, max-age=3600`，内容随 `commit_sha` 不变）。
- `segments` 必须覆盖 `[0, duration_ms]` 且不重叠（服务端校验，违反则不发布）。
- **对象 URL 的统一写法（v2 修正，P1-4）**：API 返回的所有二进制地址一律是**同源**的 `/api/objects/<kind>/<name>`，由 BFF 转到 `/v1/objects/<kind>/<name>`。v1 在示例里写 `/objects/audio/...`、在路由表里写 `/v1/objects/...`，两处都不是浏览器能直接用的地址（前者没有这个路由，后者跨源且不带 cookie），前端照抄必然 404。三种写法只允许存在于各自的位置：契约里永远是 `/api/objects/...`；BFF 里出现 `/v1/objects/...`；磁盘布局里出现 `var/objects/...`。

### 5.4 Kernel 内部 API（`services/agent-kernel`，仅内网）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/healthz` | — | `{ok, coreVersion, providers[], uptimeMs, activeRuns}` |
| GET | `/v1/capabilities` | — | `{tools[], schemaVersion, maxConcurrentRuns}` |
| POST | `/v1/run` | `{runId, role, provider{id,protocol,baseUrl,apiKey,modelId}, systemPrompt, messages[], tools[], schemaRef?, budget{maxTurns,maxTokens,maxUsd,deadlineMs}, workspace{mirrorDir}, metadata{}}` | `text/event-stream` 事件流（§5.5）；结束时 `run.completed{result, usage}` |
| POST | `/v1/run/{runId}/cancel` | — | `{cancelled:true}` |
| GET | `/v1/run/{runId}` | — | `{status, usage, result?}` |
| GET | `/v1/schemas/{name}` | — | JSON Schema（供 Python 侧校验） |

请求体大小上限 2 MB（`messages` 里不要塞整个文件，Agent 用工具读）。**单次 run 的上限跟随节点下发（v2 修正，P0-4）**：`maxTokens` 9k–20k、`maxTurns=16`、`deadlineMs = min(节点剩余时间, 600000)`——v1 在这里写死 `maxTokens=180000`，与 §3.4 的 job 级 180k 总闸冲突（一次课程约 23 次 run，单 run 即可吃满全局预算）。Kernel 只接受**不高于**Python 侧下发值的上限；请求里出现超过 200k 的值直接 422，防止上层算错预算时把闸门抬高。

Kernel 还须遵守三条**密钥与日志硬规则**（v2 新增，P1-14）：① Fastify 以 `disableRequestLogging: true` 启动，**任何情况下不记录请求体**；② 错误序列化只允许 `{code, message, runId, detail?}` 白名单字段（`apiKey` 即使出现在异常对象里也不会被序列化）；③ `provider.apiKey` 只存在于单次 run 的内存闭包中，在 `run.completed` / `run.failed` 时立即置空，不做任何形式的缓存、不写临时文件。所有内部端点额外要求 `X-Internal-Token`（由 `start.ps1` 生成并写进 api 与 kernel 各自的 `.env`），缺失即 401——即使有人把 8787 端口转发出去，也无法直接消费它。

### 5.5 事件信封（Kernel 与公开 SSE 共用形状）

```
{ "schemaVersion": 1, "type": "step.delta", "seq": 12, "ts": 1762437600123,
  "jobId": "job_...", "runId": "run_...", "data": { ... } }
```

| type | data 要点 | 出现于 |
|---|---|---|
| `system.init` | `{model, permissionMode, tools}` | Kernel |
| `agent.thinking` | `{text}` | Kernel |
| `agent.text.delta` | `{delta}` | Kernel/提问 |
| `tool.start` | `{name, argsPreview, callId}` | Kernel |
| `tool.end` | `{callId, ok, bytesOut, truncated}` | Kernel |
| `step.delta` | `{text}` | 提问流 |
| `question.delta` / `question.completed` | `{delta}` / `{answerMd, evidence[], tokens}` | 提问 |
| `job.phase` | `{node, phase, progress}` | Job |
| `node.completed` | `{node, durationMs, warnings[]}` | Job |
| `job.completed` | `{status, courseId?, bookId?, pdfUrl?}` | Job |
| `job.failed` | `{code, message, retryable}` | Job |
| `run.completed` | `{result, usage{turns,tokens,usd}}` | Kernel |
| `budget.exceeded` | `{kind:"turns"\|"tokens"\|"usd"\|"deadline", used, limit}` | 两者 |

SSE 帧格式：`id: <seq>\nevent: <type>\ndata: <json>\n\n`，每 15 秒发一次 `: keepalive` 注释帧。客户端用 `Last-Event-ID` 续传，服务端保留最近 500 条事件（`job_events`）可补发。

**v2 补充的四条流式规则（P1-5）**：
1. `seq` 必须**每一条事件单调递增且从 1 开始**（`job_events.seq`），断线重连靠它精确续传；不允许"按时间戳近似"（同毫秒多事件会丢帧）。
2. `Last-Event-ID` 超出保留窗口（`seq < min(seq)`）时，服务端**不补发**，直接发一帧 `job.snapshot`（含 `GET /v1/jobs/{id}` 的完整快照），前端据此重建 UI 而不是从中间态硬拼。
3. 未知 `type` 前端必须**忽略并继续读流**（只打日志），否则后端新增事件类型会让旧前端整条流失效。
4. 整个链路（API → BFF → 浏览器）禁用任何缓冲：`X-Accel-Buffering: no`、`Content-Encoding` 不压缩 SSE、BFF 不用 `Transfer-Encoding: chunked` 之外的处理。

### 5.6 错误码（`core/errors.py`）

| code | HTTP | 含义 | 前端提示要点 |
|---|---|---|---|
| `REPO_NOT_FOUND` | 404 | 仓库不存在/非公开 | 检查拼写与可见性 |
| `REPO_FORBIDDEN` | 403 | 私有或已封禁 | 私有仓库不在 MVP 范围 |
| `RATE_LIMITED` | 429 | GitHub/Provider 限流 | 显示重试时间 + 配置 token 指引 |
| `REPO_TOO_LARGE` | 422 | 超过体量上限 | 建议换轻量仓库或等增量分析 |
| `NO_MODEL_FOR_ROLE` | 409 | 角色未配置模型 | 跳转设置 |
| `SETUP_REQUIRED` | 428 | 未完成配置引导 | 跳 `/setup` |
| `INVALID_KEY` | 401 | 密钥无效 | 回到向导 S2 |
| `PROVIDER_UNAVAILABLE` | 503 | Provider 5xx/超时 | 可重试 + 切模型建议 |
| `BUDGET_EXCEEDED` | 402 | 预算耗尽 | 可"继续生成"（追加预算） |
| `JOB_NOT_FOUND` | 404 | 任务不存在 | — |
| `JOB_CONFLICT` | 409 | 同 cache_key 已有任务 | 返回已有 job_id 直接跳转 |
| `COURSE_NOT_READY` | 409 | 版本未 ready | 显示进度 |
| `ANCHOR_STALE` | 409 | 锚点与 commit 不匹配 | 提示重建 |
| `OBJECT_MISSING` | 404 | 音频/PDF 丢失 | 可重新生成 |
| `INGEST_BLOCKED_PATH` | 422 | 仓库含可疑路径 | 记录并跳过，不中断 |
| `CONTRACT_VIOLATION` | 502 | Kernel 产出不合 schema | 内部重试后仍失败 |
| `IDEMPOTENCY_MISMATCH` | 422 | 同 `Idempotency-Key` 但请求体不同 | 客户端 bug，需换新键（v2 新增，P1-12） |
| `PROFILE_CONFLICT` | 409 | 并发激活 profile 撞上部分唯一索引 | 重试即可（v2 新增，P1-12） |
| `INTERNAL` | 500 | 兜底 | 带 `req_id` |

> **错误码总数（v2）**：19 个。§8.1 的门禁表述随之改为"每个错误码至少有 1 条断言"，不再写"22 个"（v1 的数字从未与表对应过）。

错误体：`{error:{code, message, hint?, retryable:bool, details?, req_id}}`；`message` 面向用户（中文），`hint` 是**可执行下一步**（"去设置里为 writer 角色选一个模型"），这是"稳健"在 UX 上的体现。

### 5.7 契约生成与漂移防护

`python -m repolearn.cli export-openapi` → `packages/contracts/openapi.json` → `pnpm -F @repolearn/contracts gen` 生成 `apps/web/src/lib/api/schema.d.ts`。CI 中 `--check` 重新导出并比较哈希，不一致即失败（阻止"改了后端忘了前端"）。JSON Schema 由 Kernel 的 zod 与 Python 的 Pydantic 双向对齐：zod 为源，Pydantic 通过 `tests/test_contracts.py::test_course_schema_parity` 用同一份 JSON Schema 校验黄金样本。

---

## 6. 数据模型

### 6.1 设计约定

- **课程聚合根（v2 澄清，P0-3）**：不存在独立的 `courses` 表。一门"课程"就是 `course_versions` 的一行（版本化即课程本身），因此 API 里的 `course_id` **恒等于** `course_versions.id`，`/v1/courses/{id}` 直接按 `course_versions.id` 查询。这样做的原因是：PRD 要求"仓库更新后旧课程仍可学"，如果 `courses` 与 `course_versions` 分成两级，"同一仓库的第 2 个版本"就必须在 URL、权限、进度、书籍、笔记之间全部做一次重映射，而 PRD 从没有"跨版本的同一门课"这个概念。代价是"同一仓库的多版本"在列表里表现为多条（这是正确的：它们确实是不同的课程内容），前端以 `repo.full_name + commit_sha` 做分组展示。
- 主键：字符串前缀 ID（`crs_` `lsn_` `stp_` `anc_` `trc_` `qz_` `bok_` `chp_` `job_` `usr_` `ver_` `prf_`），生成器为 ULID（字典序即时间序，便于游标分页）。
- 时间：`created_at`/`updated_at` 均为 UTC `TIMESTAMP`，应用层写入（不用 DB 默认函数，SQLite/PG 一致）。
- 软删：`deleted_at` 用于 `course_versions`（即"课程"）/`notes`/`questions`；**所有读取路径必须带 `deleted_at IS NULL`**，由 `services/` 层的统一查询助手保证，而不是各 router 各写一遍。
- JSON 列：`sa.JSON`（SQLite 存 TEXT，PG 存 JSONB 需在迁移里用 `with_variant`），**仅用于不可查询的载荷**（prompt、board、quality_report），需要过滤的字段一律独立成列。
- 外键全部 `ON DELETE CASCADE`（除 `user_progress` 对 `course_versions` 用 `RESTRICT`，防止误删在用版本）。
- 索引：每个列表查询都有对应复合索引，`EXPLAIN` 断言写进测试（§8.2 T-DB-2，**仅覆盖游标分页主查询**）。

### 6.2 表清单与关键列

> **26 张表**（v2 计数，P0-3）。v1 在此处有 `pdf_exports` 表却在 §4.4 没有对应模型文件，且 §5.2 的答题接口与 T-QUIZ-1 的"重复提交幂等"没有任何表承载——v2 补齐 `pdf_export` 与 `quiz_attempt`，并把幂等键从 `jobs` 里抽成独立的 `idempotency_keys`（P1-12）。

**`users`**：`id, handle(uniq), display_name, is_local(bool), created_at`。MVP 自动创建 `usr_local`。

**`repositories`**：`id, full_name(uniq), owner, name, description, stars, license_spdx, primary_language, default_branch, html_url, is_public, created_at, updated_at`。

**`commits`**：`id, repository_id(FK), sha, committed_at, file_count, tarball_bytes, license_note, UNIQUE(repository_id, sha)`。

**`course_versions`**：`id, repository_id, commit_sha, cache_key(uniq), policy_version, language, title, subtitle, summary_md, status(enum: generating|ready|partial|failed|archived), sections(JSON), quality_report(JSON), warnings(JSON), blueprint(JSON), cover_palette, lesson_count, total_minutes, owner_user_id, visibility(public|private), created_at, published_at, deleted_at`。
索引：`(status, created_at desc)`、`(repository_id, created_at desc)`、`cache_key` 唯一。

**`lessons`**：`id, course_version_id, section_key(enum: overview|walkthrough|deep_dive|recap), key("3.1"), title, goal, minutes, order_index, status(draft|ready|failed), playback_meta(JSON), created_at`。`UNIQUE(course_version_id, key)`。

> **单一真源约束（v2 修正，P1-3）**：v1 让 `lessons.playback(JSON)` 存"课时主体"（含 steps），同时 `steps` 表又把 `playback.steps` 拆行——同一批数据两处写，没有任何同步规则，第一个修 bug 的人就会让两者分叉，而分叉的表现是"播放到第 3 步后跳回第 1 步"这类极难定位的问题。v2 规定：**步骤数据唯一真源是 `steps` 表**；`lessons.playback_meta` 只保留不含步骤的部分（`files[]`、`trace_key`、`certainty_legend`、`board_theme`）。`PlaybackBundle` 由 `lessons.playback_meta` + `steps` 按 `order_index` 拼装，拼装是**只读**操作，永远不回写。

**`steps`**：`id, lesson_id, order_index, title, duration_ms, timing_source(tts|estimated), audio_asset_id, focus_file, focus_line_start, focus_line_end, segments(JSON), board(JSON), code_notes(JSON), certainty(JSON), UNIQUE(lesson_id, order_index)`。索引 `(lesson_id, order_index)`（播放时按序读全部步骤）。

**`steps`**：见上（v2 已把它提升为步骤数据的单一真源）。

**`source_anchors`**：`id, course_version_id, lesson_id?, file, symbol, line_start, line_end, commit_sha, kind(definition|call_site|config|test), snippet_hash, created_at`。索引 `(course_version_id, file)`、`(lesson_id)`。**锚点是可追溯性的唯一凭据**：任何讲解若引用了一个不存在的锚点，发布前校验即失败（§3.4 N9）。

**`simulated_traces`**：`id, course_version_id, lesson_id?, key, title, entry_anchor_id, steps(JSON), certainty_summary(JSON), created_at`。每个 step 结构：`{index, title, certainty, evidence[], variables[], note}`。

**`quiz_items`**：`id, course_version_id, lesson_id?, stem, choices(JSON), answer_id, explanation_md, evidence(JSON), difficulty(1-3), kind(prediction|recall|trace), created_at`。

**`quiz_attempts`**（v2 新增，P0-3）：`id, user_id, quiz_item_id, course_version_id, choice_id, correct(bool), submitted_at`。`UNIQUE(user_id, quiz_item_id)` —— **这条唯一约束就是 T-QUIZ-1 "重复提交幂等"的实现**：重复提交走 `INSERT ... ON CONFLICT DO NOTHING` 后读回首次结果并返回 `replayed:true`。为什么必须落表而不是靠前端去重：`recap` 页的"答题统计"、`/v1/metrics` 的"正确率"、能力雷达三项都从这张表聚合，前端去重会让统计随刷新而漂移。`quiz_item_id` 只有 `CASCADE` 语义（课程删则记录删），不因题库重发而失联。

**`audio_assets`**：`id, provider, voice, speed, text_hash, object_key, duration_ms, duration_source, bytes, created_at, UNIQUE(provider, voice, speed, text_hash)`。

**`book_versions`**：`id, course_version_id, cache_key(uniq), preset(standard|deep), template_version, title, status(generating|ready|failed), word_count, chapter_count, quality(JSON), created_at`。

**`book_chapters`**：`id, book_version_id, key, title, order_index, blocks(JSON), source_refs(JSON), word_count, UNIQUE(book_version_id, key)`。

**`pdf_exports`**：`id, book_version_id, cache_key(uniq), engine(chromium|browser-print), object_key, pages, bytes, status(queued|generating|ready|failed), error(JSON), created_at`。

**`user_progress`**：`id, user_id, course_version_id, current_lesson_key, current_step_index, position_ms, percent, completed_at?, updated_at, UNIQUE(user_id, course_version_id)`。

**`notes`**：`id, user_id, course_version_id?, lesson_id?, anchor_id?, body_md, tags(JSON), created_at, updated_at, deleted_at`。

**`questions`**：`id, user_id, course_version_id, lesson_id?, file, line_start, line_end, layer, question, answer_md, evidence(JSON), runtime(kernel|exec|template), tokens_in, tokens_out, created_at`。

**`jobs`**：`id, kind(course|book|pdf|rebuild|backfill), status(queued|claimed|running|ready|partial|failed|failed_budget|cancelled), priority, payload(JSON), course_version_id?, book_version_id?, cache_key?, worker_id, attempts, progress(0-100), node, message, error(JSON), heartbeat_at, run_after, started_at, finished_at, created_at`。索引 `(status, priority, created_at)`、`(cache_key)`。

> **幂等键已从本表移出（v2 修正，P1-12）**：v1 在 `jobs` 上建 `idempotency_key` 的**全局唯一**索引，但 `POST /v1/courses` 与 `POST /v1/books` 都会带 `Idempotency-Key`——客户端若复用了同一个 UUID（同一次"点两下"里很常见），两个不同的资源创建会互相踩成 409，而报错信息还指向"任务冲突"，极难排查。幂等的作用域永远是"同一路径模板"，所以键必须含 scope。

**`idempotency_keys`**（v2 新增，P1-12）：`id, scope, key, request_hash, response_snapshot(JSON), job_id?, created_at, expires_at`。`UNIQUE(scope, key)`。
- `scope` 取路径模板（`courses.create` / `books.create` / `pdf.create`），不是完整 URL（路径里的 id 会让同一逻辑操作被算成不同 scope）。
- `request_hash` = 请求体规范化后的 sha256：同键不同体直接 422 `IDEMPOTENCY_MISMATCH`（这是幂等键的经典陷阱：静默返回首次结果会掩盖调用方的 bug）。
- `expires_at = created_at + 10 分钟`，由 `scripts/prune_objects.py` 清理；过期后同键视为新请求。
- `response_snapshot` 存首次响应体，保证"重放"返回**逐字节相同**的结果（而不是重新查一遍库，那样状态可能已变）。

**`job_events`**：`id, job_id, seq, type, data(JSON), created_at`。`UNIQUE(job_id, seq)`，保留最近 500 条（清理在 CLI）。

**`generation_locks`**：`cache_key(PK), job_id, acquired_at, expires_at`。

**`llm_profiles`**：`id, label, provider, protocol, base_url, api_key_ciphertext(BLOB), api_key_last4, org, active(bool), last_probe(JSON), created_at, rotated_at`。

> **`active` 必须由数据库保证唯一（v2 修正，P1-12）**：v1 只写了 `active(bool)`，没有任何约束。而 `POST /v1/settings/profiles/{id}/activate` 与 `POST /v1/setup/commit` 是两条并发可达的路径，两者交错就会留下**两个 `active=true` 的行**——此时 `GET /v1/setup/state` 的判定、`resolver` 取哪个 profile、Doctor 面板显示哪个都会变成"看查询顺序"。约束用**部分唯一索引**：SQLite 写 `CREATE UNIQUE INDEX ux_llm_profiles_active ON llm_profiles(active) WHERE active = 1`（PG 是 partial unique index，同一句 SQL）。激活操作在同一事务内先 `UPDATE ... SET active=0` 再置目标行 `active=1`，靠这个索引在并发下把一个事务拒掉并返回 409 `PROFILE_CONFLICT`，而不是留下坏状态。

**`model_catalog`**：`id, provider, model_id, display_name, capabilities(JSON), context_window, price_in, price_out, probed_at, UNIQUE(provider, model_id)`。

**`setting_revisions`**：`id, rev(int, uniq), summary, changes(JSON), payload(JSON), author, created_at, is_active`。回滚 = 插入新 rev，`payload` 复制旧 rev。

> **`payload` 不含任何密文（v2 明确，P2-2）**：它只存 `{profile_id, provider, protocol, base_url, model_id, roles{...}}` 这类**引用与分配**，密钥永远只在 `llm_profiles.api_key_ciphertext` 一处。否则"回滚到 rev 3"会把 rev 3 当时那把已经轮换掉的密钥重新写回生效位——这在轮换密钥（§3.6.3）之后是真实的安全回退。

**`ai_cache`**：`key(PK), response_json, tokens_in, tokens_out, model_id, created_at, expires_at`。

**`cost_ledger`**：`id, job_id, role, provider, model_id, tokens_in, tokens_out, usd, created_at`。索引 `(job_id)`、`(created_at)`。

**`models` 与 `schemas` 的关系**：Pydantic schema 与表结构**不共享命名**（`CourseDetail` vs `course_versions`），映射在 `services/*_service.py` 里显式完成——这一层"多写一点代码"换来的是"数据库可以重构而不破坏 API 契约"，对本项目（后期要加私有仓库/多人协作）是必要投资。

### 6.3 Lesson/Step JSON 形状（校验依据）

```
LessonPlayback = {
  key, title, layer: "overview"|"walkthrough"|"deep_dive",
  minutes, steps: Step[], files: FileRef[], trace_key?: string
}
Step = {
  index, title, duration_ms, timing_source: "tts"|"estimated",
  audio: {url, duration_ms, voice} | null,
  segments: [{id, text, start_ms, end_ms, focus?: {file, line_start, line_end}, board_actions?: [], subtitle_style?}],
  board?: {kind:"architecture"|"flow", mermaid, nodes:[{id,label,source:{file,line}}]},
  code_notes?: [{file, line, text}],
  quiz?: [QuizItem], certainty_legend?
}
```

约束（服务端发布前校验，违反则 N9 失败并进 `warnings`）：
① `segments` 时间连续且覆盖整段；② 每个 `focus` 的 `file` ∈ 镜像文件集合且行号在文件行数内；③ 每个 `code_notes.line` 落在某个 `focus` 区间或其所在文件内；④ `quiz` 每题恰好一个 `answer_id` 且 `evidence` 非空；⑤ `duration_ms` 与音频时长偏差 < 8%（有音频时）。

### 6.4 Trace 的"三种确定性"（诚信约束）

`certainty` 三值：`source_fact`（代码里能直接读到的调用/定义）、`static_inference`（由调用图与签名推断，如"该参数会流到 X"）、`teaching_simulation`（为了让流程可讲而补的示例值）。规则：

- `source_fact` 必须带 `evidence`（文件 + 行 + 一句原文引用）；
- `teaching_simulation` 的变量值必须带 `note:"示例值，非真实运行结果"`；
- 前端对 `teaching_simulation` 用不同底色 + 角标，且页面固定位置展示 PRD 要求的"模拟执行·教学推演"标识；
- `publish.py` 统计 `certainty_summary`，若 `source_fact` 占比 < 40% 则 `quality_report.trace_quality="weak"`，前端提示"本课时的执行链以推演为主"。

### 6.5 迁移与种子

- `migrations/versions/0001_initial.py` 一次建全表（含索引与唯一约束）；后续每个结构变更一个迁移文件，`downgrade` 必须可执行（CI 跑 `upgrade head` → `downgrade base` → `upgrade head`）。
- `python -m repolearn.cli seed-demo` 插入一条**离线演示课程**（内置夹具仓库 `microsoft/autogen` 的片段 + 预生成 lesson），用于：无网络/无 Key 时前端仍可完整演示三层学习与书籍阅读。这是"顶级产品"的必要兜底，也是 E2E 测试的稳定基础。
- `settings_revisions` 初始 rev=1（`payload` 为默认角色分配）。

### 6.6 存储对象布局

```
var/objects/
├─ mirrors/<sha8>/            # 只读仓库镜像（LRU 2GB）
├─ audio/<hh>/<hash>.mp3      # 按内容寻址
├─ diagrams/<course>/<key>.svg
└─ pdf/<book>/<preset>-v<template>.pdf
```

`object_store.py` 统一 `put/get/url/exists/size`，`file://` 存储默认，S3 通过 `REPOLEARN_OBJECT_STORE=s3` 切换（boto3 可选依赖）。URL 走 `/v1/objects/{kind}/{name}` 代理，避免暴露物理路径并支持 `Range`（音频拖动播放需要）。

### 6.7 跨数据库方言要点

| 关注点 | SQLite | PostgreSQL | 处理 |
|---|---|---|---|
| 并发写 | 单写者 | 行级 | WAL + `busy_timeout`；队列 claim 用条件 UPDATE + rowcount |
| JSON | TEXT | JSONB | `sa.JSON().with_variant(JSONB, "postgresql")` |
| 大小写 | 不支持 `ILIKE` | 支持 | 搜索统一 `LOWER(col) LIKE LOWER(?)` |
| 时间精度 | 秒 | 微秒 | 应用层统一 `datetime(..., tzinfo=utc)` |
| 迁移 | 有限 ALTER | 完整 | 仅用 add column / create index，不改列类型 |

---

## 7. 前端实现规格

### 7.1 设计 token（`styles/tokens.css`，24 个变量）

```
--bg: #0B0F0E;          --bg-elevated: #111715;   --surface: #161D1B;
--surface-2: #1B2320;    --border: #2A3330;       --border-strong: #3A4642;
--accent: #3ECF8E;       --accent-strong: #2FB37A;--accent-soft: rgba(62,207,142,.12);
--text: #E6EDEA;         --text-muted: #9FB0AA;   --text-dim: #6D837C;
--warn: #E8B44A;         --danger: #E5645C;       --info: #6CA8F5;
--code-bg: #0F1513;      --code-line-hl: rgba(62,207,142,.10);
--radius-sm: 8px;        --radius: 12px;          --radius-lg: 18px;
--shadow-soft: 0 8px 24px rgba(0,0,0,.35);
--font-ui: Inter, "PingFang SC", "Microsoft YaHei", system-ui;
--font-mono: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
```

排版阶梯：`12/13/14/16/18/22/28/36`；行高正文 1.65、代码 1.55；代码字号可调（12–16，存 localStorage）。所有交互元素 ≥ 32×32 命中区，`:focus-visible` 使用 `outline: 2px solid var(--accent); outline-offset: 2px`。`prefers-reduced-motion` 时全部过渡降为 `0.01ms`。

### 7.2 组件与页面映射（对齐 7 张设计稿）

| 设计稿 | 路由 | 关键组件组合 | 必须存在的细节 |
|---|---|---|---|
| 首页 | `/` | `HeroImport`（大输入框 + "生成学习课程"按钮 + 示例仓库 chips）+ `FeatureGrid`（分层学习/交互式走读/随时提问/课程可复用）+ `HotCourses`（4 张卡：仓库名、一句话描述、标签、stars、预计时长、播放按钮）+ `RecentLearning` | 输入框粘贴即解析、非法 URL 即时内联报错、回车提交、`⌘K` 全局搜索 |
| 宏观架构 | `/course/{id}/overview` | `TopProgress`（①②③④ 分段+对勾）+ `OutlineRail`（4 章 / 每章子节 + 学习目标 + 勾选态）+ `ArchitectureCanvas`（mermaid + 节点可点）+ `ConceptCard`（关键概念）+ `CodePane`（少量入口代码，行 9 高亮）+ `PredictionQuiz` + `MentorRail` | 架构节点点击 → 编辑器跳到对应锚点并高亮；目标条目随播放置勾 |
| 全局走读 | `.../walkthrough` | `TraceStrip`（4 步横向：接收请求→创建 Agent→调用工具→生成回复，当前步高亮）+ `CodePane`（自动跳文件/行）+ `VariablePanel`（关键变量，标注"示例"）+ `PredictionQuiz` + `MentorRail` | "查看调用链"按钮弹出 `CallChainSheet`；模拟标识常驻顶部；步骤切换带 200ms 交叉淡入 |
| 深入源码 | `.../deep-dive` | `CodePane`（主视觉，多 tab、面包屑 `pkg > module.py > Class > func`、只读徽标）+ `ExecutionPanel`（执行模拟 / 变量状态 双 tab）+ `CodeNoteCard`（行内浮层）+ `PredictionQuiz` + `MentorRail` | 行 103 的绿色左边条 + 断点圆点；浮层指向行（引导线）；字幕/音频与高亮同步 |
| 行内提问 | `.../deep-dive`（同一路由，交互态） | 选中行 → 浮动工具条（解释这行 / 为什么这样实现？/ 有什么替代方案？/ …）→ 展开答案面板（参数说明表、执行流程简图、对比示例）→ `MentorRail` 呈现问答对话 | 答案带证据列表（文件:行 → 点击跳转）；流式输出有光标；可"继续追问"；答案区可复制 |
| 课程总结 | `.../recap` | `CompletionCard`（100% 进度）+ `KnowledgeReview`（勾选式知识点）+ `QuizReview`（3/3 正确态）+ `AbilityRadar`（五维进度）+ `NextSteps`（进阶推荐）+ 底部"生成学习报告 / 继续进阶" | 完课时间、答题明细、"生成课程书籍"入口（P09） |
| （PRD P09/P10） | `/book/{id}`、`/book/{id}/pdf` | `BookReader` + `ChapterNav` + `SearchPanel` + `PdfPreview` | 目录、全文搜索、书签、代码复制、图表放大、字号/主题、"在课程中查看此代码"、PDF 页数/大小/Commit |

### 7.3 播放器状态机（`lib/player/timeline.ts`）

状态：`idle → loading → ready → playing → paused → ended`，附加 `seeking`。规则：

1. **单一时间源**：`audio.currentTime`（有音频）或 `performance.now() - startedAt`（无音频估算）。字幕、高亮、板书三者只读该时间，不各自计时。
2. **segment 定位**：`segments` 按 `start_ms` 升序，定位用二分；切换 segment 才更新 decoration（避免每帧重建 Monaco 视图）。
3. **预取**：进入 step 即预取下一 step 的 playback bundle 与首段音频（`preload="auto"`）。
4. **持久化**：每 2 秒节流 `PUT /progress`（含 `position_ms`），页面 `visibilitychange=hidden` 与 `beforeunload` 各补发一次（`navigator.sendBeacon`）。
5. **键盘**：`Space` 播放/暂停，`←/→` 前后 5 秒，`J/K` 上下一步，`C` 字幕，`[`/`]` 倍速，`?` 快捷键面板。焦点在 Monaco 时快捷键让位给编辑器。
6. **倍速**：0.75/1.0/1.25/1.5/2.0，只改 `playbackRate`，不重算时间轴。

### 7.4 只读 IDE（`CodePane`）

- Monaco `readOnly: true`、`domReadOnly: true`、`fontFamily: var(--font-mono)`、`minimap.enabled` 在窄屏关闭、`renderLineHighlight: "none"`（高亮由 decoration 提供）。
- 数据：`GET /v1/courses/{id}/files?path=` 懒加载单文件内容（带行号偏移真值），`files` 数组来自 playback。
- 装饰：`HighlightLayer` 计算 `deltaDecorations`——`focus` 区间（整行底色 + 左侧 3px 强调条）、`code_notes`（行尾图标，点击弹 `CodeNoteCard`）、`trace.evidence`（波浪下划虚线）。
- 面包屑来自 `analysis` 阶段的符号栈（`pkg/module.py > Class > func`），点击可上钻。
- 选区提问：`onDidChangeCursorSelection` → 若选区非空显示浮动工具条（Portal 定位，避免被编辑器裁剪）。
- 只读徽标 + 顶部提示"这是只读的教学视图，不会执行仓库代码"。

### 7.5 状态与数据获取

- **网络层只有一个入口（v2 确认，P0-2）**：`lib/api/client.ts` 的 `baseUrl` 恒为**同源相对路径** `""`，即调用 `/api/v1/courses`（BFF 再转到 `http://127.0.0.1:8000/v1/courses`）。**禁止**在浏览器侧出现绝对地址（`http://127.0.0.1:8000`）——一旦出现，就会同时丢掉 cookie、`SameSite` 保护与 SSE 缓冲控制。`lib/env.ts` 只允许 BFF（服务端）读取 `REPOLEARN_API_BASE`，不允许把它导出到客户端组件。
- **TanStack Query**：服务端数据（课程、书籍、任务、设置）；`staleTime`：课程详情 5 分钟、列表 60 秒、任务详情 0。
- **zustand**：播放器、IDE 选区/打开文件、向导草稿。播放器状态**不入 query cache**（高频变更）。
- **SSE hook**：`useEventStream(jobId, onEvent)`——`fetch('/api/sse/jobs/<id>')` + `ReadableStream`（同源，cookie 自动携带），断线指数退避重连（1/2/4/8/16s，最多 5 次），用最后事件 `seq` 回填 `Last-Event-ID`；页面隐藏时暂停重连，恢复时先 `GET /api/v1/jobs/{id}` 对齐快照再连。**不用原生 `EventSource`**：它不能带 `X-CSRF-Token`、不能自定义头、而且在部分浏览器里对 `Last-Event-ID` 的手动设置受限，`fetch` + `ReadableStream` 是唯一可控路径。
- **乐观更新**：进度、笔记、答题提交（失败回滚 + toast）；课程创建不做乐观更新（有真实 Job 成本）。

### 7.6 无障碍与空态（"人机交互最佳实践"的具体落点）

- 所有面板可键盘到达；`MentorRail` 是 `aria-live="polite"` 区域，讲解更新时朗读摘要而非全文。
- 代码高亮同时提供"当前行"文本说明（色弱用户不能只靠颜色）。
- 答题后立刻给 `aria-live` 反馈（正确/错误 + 一句解释）。
- 空态四类都要写文案：无课程（引导导入 + 示例仓库）、生成中（进度 + 预计时间 + "可以先去逛逛"）、生成失败（错误原因 + 重试按钮 + 提示"内容过长时可分段重建"）、无音频（"本节暂无配音，已切换字幕模式"）。
- 窄屏（< 1100px）：`OutlineRail` 折叠为抽屉，`MentorRail` 变为底部可拖拽面板，`CodePane` 占满宽度。

---

## 8. 测试与验收标准

### 8.1 分层测试策略

| 层 | 工具 | 覆盖目标 | 门禁 |
|---|---|---|---|
| Python 单元 | pytest + `pytest-asyncio` | services / providers / workflow 节点 / guard | 行覆盖 ≥ 80%（`workflow`、`providers`、`ingest` ≥ 85%） |
| Python 集成 | `httpx.ASGITransport` + 临时 SQLite | 每个 router 的主路径 + 错误码 | **19 个错误码每个至少被断言一次**（§5.6 的实际数量） |
| Kernel | `node --test` + 假 provider | 事件映射、预算、工具、schema | 全绿 |
| 契约 | `jsonschema` + 黄金样本 | 课程/课时/book JSON 双向一致 | 双向校验通过 |
| 前端单元 | vitest + testing-library | timeline 计算、字幕分段、错误映射、进度节流 | 全绿 |
| E2E | Playwright（**离线为主**：`page.route` 拦截；另 1 条真后端冒烟，见 §8.3） | 4 条主流程 | 全绿且 < 3 分钟 |
| 性能 | 自测基准脚本 + `pytest-benchmark` | API p95、长任务 | 见 §8.4（**不进 CI 硬门禁**） |

### 8.2 关键测试清单（编号供实现节点勾选）

| 编号 | 断言 |
|---|---|
| T-CFG-1 | `.env` 缺省 + 无 Key 启动：`/v1/setup/state.required === true`；前端 `/` 命中 302 → `/setup` |
| T-SETUP-1 | `probe` 对 4 种协议各用 `respx` 模拟成功/401/超时，返回 `ok/latency/models` 且错误有 `hint` |
| T-SETUP-2 | `commit` 写入后 `api_key_ciphertext` 非明文，任何响应与日志都不含明文（含 `docs`/`errors` 字段） |
| T-SETUP-3 | 向导中途返回上一步不丢输入（vitest 交互测试） |
| T-SETUP-4 | 回滚到上一 revision 后 `active_profile` 与角色分配同时回退（原子） |
| T-JOB-1 | 并发 5 次 `POST /v1/courses` 同仓库：仅 1 个 Job，其余返回 `JOB_CONFLICT` 且带同一 `job_id` |
| T-JOB-2 | 命中 `cache_key` 时返回 `200 reused:true` 且**不**创建 Job、不消耗 token（断言 `cost_ledger` 为空） |
| T-JOB-3 | worker 被 kill 后 90 秒内 Job 被回收并从 checkpoint 续跑（断言 N1–N4 不重复执行：`job_events` 无重复 `node.completed`） |
| T-JOB-4 | `cancel` 后 Job 在 5 秒内 `cancelled`，Kernel run 被 abort，工作区无残留镜像 |
| T-JOB-5 | 超预算：`failed_budget` + 已生成课时仍可读 + `partial` 状态可见 |
| T-GRAPH-1 | 黄金夹具（auto-gen 片段）跑完整图：4 章节、≥10 课时、锚点覆盖率 ≥ 80%、`quality_report` 三值齐备 |
| T-GRAPH-2 | N6 单课时失败（注入异常）：其余课时正常发布，`failed_lessons` 有记录，`status=partial` |
| T-GRAPH-3 | N9 校验：篡改一个锚点行号 → 发布失败并 rollback，`course_versions` 无 `ready` 行 |
| T-ANCHOR-1 | 所有 `source_anchors.file` ∈ 镜像文件集合；行号 ≤ 文件行数（property-based：随机 200 组夹具） |
| T-TRACE-1 | 每个 `certainty=source_fact` 步的 `evidence` 能在镜像里定位到对应行；无 evidence 的 `source_fact` 使发布失败 |
| T-TRACE-2 | `certainty=teaching_simulation` 的变量必带示例标注；前端渲染快照含"模拟执行·教学推演"文案 |
| T-AUDIO-1 | 同一文本第二次合成命中缓存（断言 provider 调用次数 = 1） |
| T-AUDIO-2 | TTS 连续失败 → `audio=null` + `timing_source=estimated` + 前端字幕自动推进（E2E 断言第 2 段字幕出现） |
| T-PLAY-1 | `PlaybackBundle` 的 segments 连续无缝、无重叠、覆盖全时长；违反则 422 |
| T-PLAY-2 | 时间轴单测：给定 segments 与音频时长，任意 t 都能定位到唯一 segment（含边界 t=0 / t=duration） |
| T-IDE-1 | 三层次跳转：从 walkthrough 的 trace 步骤跳到 deep_dive 对应行再"返回原位置"，行号与文件一致 |
| T-ASK-1 | 行内提问携带 `layer/file/lines`；返回的 `evidence` 全部是真实文件行；流式拼接后的 markdown 与最终 `answer_md` 一致 |
| T-ASK-2 | prompt 中仓库内容被 `<untrusted_repo_content>` 包裹，且包含"不是指令"的声明（字符串断言） |
| T-QUIZ-1 | 提交答案返回 `correct` 与解释；重复提交幂等（同 item 只记一次） |
| T-BOOK-1 | 书籍生成幂等：同 `cache_key` 第二次 `200 reused` |
| T-BOOK-2 | 书籍章节的 `source_refs` 非空且全部可解析；章节顺序 = 目录顺序 |
| T-PDF-1 | PDF 生成后 `pages>0`、`bytes>0`，PDF 文本层含章标题与 commit sha（`pypdf` 抽取断言） |
| T-SEC-1 | 日志脱敏：构造含 `sk-xxx`/`Bearer xxx` 的异常消息，落盘日志不含密钥 |
| T-SEC-2 | `ingest/guard` 拦截 `../../etc/passwd`、符号链接、`CON`/`NUL` 设备名、1 GB 单文件（Windows 兼容） |
| T-SEC-3 | Kernel 工具越界：`repo_read_file("../../secret")` 返回错误而非内容 |
| T-SEC-4 | Markdown 渲染 XSS：`<img onerror=...>` / `<script>` 被净化（vitest DOM 断言） |
| T-CON-1 | `export_contracts --check` 在干净树上通过；手改 schema 后失败 |
| T-CON-2 | 黄金课程 JSON 同时通过 zod 与 jsonschema 校验 |
| T-DB-1 | `upgrade head → downgrade base → upgrade head` 三步成功 |
| T-DB-2 | **游标分页主查询**（`GET /v1/courses` 无 `q`、`GET /v1/jobs`）的 `EXPLAIN QUERY PLAN` 命中复合索引，无全表 SCAN + 临时 B 树排序。**模糊搜索不在本门禁内**（v2 修正，P1-9）——见下方"搜索的索引策略" |
| T-DB-3 | 部分唯一索引生效：并发两次 `activate` 只成功一次，另一个拿到 `PROFILE_CONFLICT`（v2 新增，P1-12） |
| T-DB-4 | reaper：构造一行超期 `generating` 且无活跃 Job，60 秒内被置 `failed` 且 `generation_locks` 已释放（v2 新增，P1-13） |
| T-IDEM-1 | 同 `Idempotency-Key` 分别请求 `POST /v1/courses` 与 `POST /v1/books` 互不影响（scope 隔离）；同键异体 → 422 `IDEMPOTENCY_MISMATCH`（v2 新增，P1-12） |
| T-DEG-1 | 三分支降级各自可测：A 正常用 Kernel；B（包在、Kernel 挂）走 `ExecCliRuntime`；C（包不可用）**直接模板降级且不尝试 exec**，`quality_report.degraded=true`、`anchor_confidence=low`（v2 细化为三条断言，P1-8） |
| T-DEG-2 | Gate 0 三态：`.run/preflight.json` 记录 g1/g2/g3 状态，`/healthz.gates` 与设置页 Doctor 显示一致；任一 Gate 失败时启动仍成功（v2 新增，P0-6） |
| T-E2E-1 | BFF 透传：SSE 首帧 200ms 内到达（不是等结束一次性返回）、音频 `Range` 请求返回 `206` 且 `Content-Range` 正确、上游错误体原样透传（v2 新增，P0-2/P1-5） |
| T-E2E-2 | 首启守卫不死循环：清 cookie 访问 `/course/x` → 307 `/setup`；API 不可达时 `/setup` 显示"后端未就绪"而非重定向（v2 新增，P1-6） |
| T-SCR-1 | 干净环境下 `.\start.ps1 -SkipInstall` 在 90 秒内三端口就绪并打印 URL |
| T-SCR-2 | 端口被占用时 `start.ps1` 给出明确提示并以非 0 退出，不留下半启动进程 |
| T-SCR-3 | `.\stop.ps1` 两次连续执行均成功（幂等），且之后三端口均不可连接 |
| T-SCR-4 | 缺 node/python 时 `check_env.ps1` 失败并给出安装指引 |
| T-OPS-1 | `prune_objects` 只删未被引用的对象；被引用的镜像/音频保留 |
| T-TEST-1 | `gen_fixtures` 在离线环境可运行（不触网），产出确定（二次运行字节一致） |
| T-JOB-6 | 心跳：注入一个耗时 5 分钟的节点，期间 `heartbeat_at` 每 15 秒更新，Job 不被自己回收（v2 新增，P1-1） |
| T-SEC-5 | Kernel 与 API 的日志文件里不出现请求体：构造带 `sk-test-` 的 probe 与 run 请求，grep 全部 `var/logs/*.log` 为空命中（v2 新增，P1-14） |
| T-SEC-6 | 内部令牌：不带 `X-Internal-Token` 直接请求 `:8000/v1/*` 与 `:8787/v1/*` 均 401（v2 新增，P0-2） |
| T-QUIZ-2 | 幂等写表：同一 `quiz_item` 提交 3 次，`quiz_attempts` 只有 1 行，第 2/3 次返回 `replayed:true` 且内容与首次一致（v2 新增，P0-3） |
| T-GRAPH-4 | 状态体积：完整跑一遍黄金夹具，遍历 `checkpoints` 表断言每条 `state` JSON ≤ 256 KB（v2 新增，P0-1） |

**搜索的索引策略（v2 新增，P1-9）**：v1 让 T-DB-2 覆盖"列表查询"，但 `GET /v1/courses?q=` 用的是 `LOWER(col) LIKE LOWER('%kw%')` —— 前缀通配符下**任何 B 树索引都无法生效**，这条门禁永远不可达成，最后的结果只会是"测试被 skip 或断言被改成恒真"。v2 明确分层：

- **默认（不启 FTS）**：`q` 走全表扫描，但**强制 `limit ≤ 50`、服务端 300 ms 超时**（超时返回已匹配部分 + `truncated:true`）。理由是开发机课程量在数百到数千级，全扫 50 行是毫秒级；为它引入 FTS 反而增加迁移与一致性负担。
- **启用 FTS（`REPOLEARN_SEARCH=fts`）**：SQLite 建 `course_fts`（FTS5，`title`/`summary_md`/`repo_full_name`），PG 用 `tsvector` + GIN 索引；此模式下 T-DB-2 扩展为断言 FTS 查询命中虚表索引。
- 这条策略写进 `.env.example` 注释与 Doctor 面板（"搜索模式：scan / fts"），让"为什么搜索慢"有确定答案。

### 8.3 E2E 四条主流程（Playwright）

**E2E 策略（v2 统一，P1-10）**：v1 在 §8.1 写"起真实三进程，或用种子课程 mock"，在 §8.3 写"一律离线"，两处冲突，且"播放器 ≥55fps 用 `requestAnimationFrame` 计数断言"在无头 CI 上不可复现（会变成随机红灯，最终被 skip）。

v2 定为 **两层**：

- **离线 E2E（CI 主门禁，4 条流程）**：一律用 `page.route` 拦截 `/api/*`，后端完全不参与。保证稳定、可在任何机器复现、< 3 分钟。
- **real-backend 冒烟（独立 CI 作业，1 条）**：真起三进程 + 种子课程，只跑"首页 → 导入（拦截 GitHub）→ 用 `seed-demo` 课程打开第一层 → 播放 5 秒 → 回到首页"，允许 1 次重试。它证明"脚本 + 三进程 + 种子数据"这条链路没断，而不是证明 UI 细节。

四条离线主流程：

1. **首启配置**：`/` → 被重定向到 `/setup` → 选 Anthropic + 假 Key（拦截 `probe`）→ 跳过 TTS → 完成 → 回首页看到"已配置"。
2. **导入并生成**：首页粘贴 URL（拦截 `POST /v1/courses` 返回 mock Job + SSE 脚本）→ P02 看到 4 章节逐步点亮 → 点"开始学习"进第一层。
3. **三层走读**：第一层点架构节点跳代码；第二层按 4 步前进查看变量面板与模拟标识；第三层选中行提问（mock SSE 流）→ 看到证据 → 截图对比快照。
4. **完课与书籍**：走完课程 → P08 显示 100%/答题统计 → 生成书籍 → P09 阅读两章 → 请求 PDF（mock 完成）→ P10 显示页数与下载。

E2E 一律**离线**（`page.route` 拦截后端），保证 CI 稳定；真实后端联调靠 §8.1 的集成测试。

### 8.4 性能与质量门禁

**门禁分两类（v2 修正，P1-10）**：能稳定复现的进 CI，受机器/显示环境影响的不进 CI（只作为本地基准脚本 + 人工抽检报告）。v1 把帧率这类指标写成 CI 硬门禁，结果只会是"随机红灯 → 被 skip → 门禁形同不存在"。

**A. CI 硬门禁（必须每次绿）**

| 指标 | 目标 | 测量 |
|---|---|---|
| API p95（本地 SQLite，课程详情） | < 300 ms | 集成测试内 100 次采样 |
| 单课程生成成本（参考仓库 auto-gen 片段） | **job 级** ≤ 0.35 USD 且 ≤ 180k tokens | `cost_ledger` 按 `job_id` 汇总断言（v2 明确为 job 级，P0-4） |
| 检查点体积 | 每条 ≤ 256 KB | T-GRAPH-4 |
| SSE 首帧延迟 | < 200 ms（经 BFF） | T-E2E-1 |

**B. 本地基准 / 人工抽检（不进 CI）**

| 指标 | 目标 | 测量 |
|---|---|---|
| 页面 LCP（Course 工作台，本地） | < 1.5 s | `scripts/bench_web.md` 记录 Playwright `performance` 输出 |
| 播放时主线程长任务 | 无 > 50 ms 的长任务 | Chrome trace 抽检（`performance` 面板 + `long-tasks`） |
| 播放器帧率 | 目标 ≥ 55 fps（1080p，有 GPU） | 手动录制 + 帧率叠加显示，**不做自动化断言** |
| 首次 `start.ps1` 冷启动（已装依赖） | < 60 s 全部就绪 | T-SCR-1 已有断言（保留，因为它可复现） |

---

## 9. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **AragonAgent core 为闭源 npm 包，内部行为不可改** | 事件形状/预算语义升级可能与 Kernel 假设不一致 | Kernel 启动校验 `coreVersion` 并写入 `/healthz`；`events.ts` 做防御性映射（未知事件丢弃并计数，不崩）；锁定 `^0.2.63` 并记录升级检查清单；`ExecCliRuntime` 作为第二通道 |
| R2 | **生成质量依赖模型，可能产出幻觉锚点** | 课程"可追溯"承诺失效 | 双保险：Kernel zod 校验 + Python `source_anchors` 存在性/行号校验（T-ANCHOR-1、T-GRAPH-3）；`certainty` 三值 + 前端显式标识；低 `source_fact` 占比降级标注 |
| R3 | **tarball 下载在 Windows 上的文件名/权限问题** | 解包失败、中文文件名乱码、长路径 | 解包时统一 sanitize（保留 `[A-Za-z0-9._-]`，其余转义）；路径长度限制 180 字符；用 `tarfile` 的流式读取（避免 seek 问题）；CI 上跑 Windows runner |
| R4 | **SQLite 并发写排队导致 Job 慢** | 多个 Job 时吞吐下降 | 单 worker + 串行 claim（`REPOLEARN_MAX_CONCURRENT_JOBS` **默认 1**，与 §3.11.4 一致）；WAL + `busy_timeout`；密集写批量提交；PG 作为可选升级路径（并发 2–4） |
| R5 | **TTS 配额/网络不稳定** | 无配音，体验下降 | 内容寻址缓存、失败降级字幕、设置页可换音色重合成、`TTS_DEGRADED` 明示 |
| R6 | **生成一次消耗大量 token（成本失控）** | 用户账单 | 预算守卫（`budget_guard` + Job 预算 + Kernel 预算三层）；`ai_cache`；课程内容级复用；未命中时才生成；设置页展示成本 |
| R7 | **PRD 的"三层"交互复杂度高，容易做成三个独立页面** | 用户迷路，违反 PRD"同一工作台" | 共享 `course/[id]/layout.tsx`（外壳常驻、Tab 切换不卸载播放器）；`returnTo` 记忆：下钻记录来源 `(layer, lesson, step, line)`，返回按钮精确还原（T-IDE-1） |
| R8 | **Monaco 体积大，首屏变慢** | LCP 超标 | `dynamic(() => import(...), {ssr:false})` + 骨架；只加载用到的语言；`monaco-editor` worker 走本地打包而非 CDN |
| R9 | **生成内容涉及许可证/版权** | 合规风险 | 镜像时记录 `license_spdx`；书籍与 PDF 页脚固定标注源仓库、Commit、License；超过单章 30% 的原文引用被禁止（长度检查） |
| R10 | **未知仓库语言（tree-sitter 无该语言包）** | 分析退化 | 正则退化 + `ANALYSIS_DEGRADED` 警告 + 课程降级为"文本走读"模式（仍可用） |
| R11 | **start.ps1 在 PowerShell 5.1 上因编码/语法失败** | 一键启动不可用 | 只用 5.1 语法；脚本保存为 UTF-8 BOM；所有路径用 `Join-Path`；CI 用 Windows + `powershell.exe` 跑冒烟（T-SCR-1..4） |
| R12 | **端口冲突（8000/3000/8787 常被占用）** | 启动失败 | `check_env.ps1` 预检 + `-Port` 参数 + `.run/ports.json`；`stop.ps1` 按端口兜底清理 |
| R13 | **前端与后端契约漂移** | 运行时 undefined/500 | OpenAPI 生成类型 + CI `--check` + 事件 `schemaVersion` |
| R14 | **`SameSite=Lax` + 跨源 = 会话/CSRF/SSE 全体失效**（v2 新增，P0-2 的风险侧） | 表现为"登录态随机丢失""音频拖不动"，且极难归因 | 架构上不许跨源（§2.2 约束 6）；T-SEC-6 断言不带内部令牌的直接访问被拒；T-E2E-1 断言 BFF 透传 SSE/Range |
| R15 | **LangGraph checkpoint 撑爆 SQLite**（v2 新增，P0-1 的风险侧） | 生成中途 DB 膨胀、写入超时、Job 全盘失败 | 状态体积预算 256 KB + 产物外置（§3.4）；T-GRAPH-4 断言；checkpoint 库与业务库分文件 |
| R16 | **Gate 0 依赖在目标机器不可获取**（v2 新增，P0-6 的风险侧） | 功能静默缺失（无调用链/无 PDF/无 Agent） | 启动即打印三态并进 `/healthz.gates` 与 Doctor；T-DEG-2 断言三态一致 |
| R17 | **`generate` 阶段耗时导致开发反馈慢**（v2 新增） | 每改一处都要等生成 | `seed-demo` 离线课程 + 夹具黄金样本，让 90% 的前端与接口开发不必真跑生成（§6.5） |

---

## 10. 实施顺序（给下游开发节点）

**v1 的排期问题（P1-11）**：16 个步骤按"模块层"平铺（先 core、再 ingest、再 providers、最后 web），中间没有任何一次"端到端能跑起来"的检查点。这种排期最典型的失败形态是：到第 11 步才发现 BFF 的 SSE 不是流式的、或 N4 的分析输出形状喂不进 N5 的 prompt，而那时已经写了 120 个文件。180 个文件的项目**必须在第 20 个文件时就拥有一个能启动、能点、能看的最小纵切**。

v2 改为**里程碑制**：每个里程碑结束时仓库必须处于"可启动、可演示、测试绿"的状态；下一个里程碑只允许在上一个的验收项全绿后开始。M0 是这一切的前提。

| 里程碑 | 内容（对应 §4 的文件） | 必须满足的验收（Demoable 判据） |
|---|---|---|
| **M0 · Walking Skeleton**（约 30 文件） | 根工程化全套（§4.1）+ `core/`（config/db/errors/logging/ids/security）+ `0001_initial` 全部 26 表 + 首批模型（`user`/`llm_profile`/`job`/`course_version`/`lesson`/`step`）+ `/healthz` + `setup` 与 `settings/profiles` 两个 router + Kernel 的 `server.ts`/`health.ts`（`/v1/run` 先返回 stub 事件）+ `apps/web` 骨架（tokens、layout、`middleware.ts`、`/setup` 五步向导、`lib/api/client.ts`）+ BFF 转发（含 SSE 与 Range 的最小实现）+ `start.ps1`/`stop.ps1`/`check_env.ps1` | **`.\start.ps1` 一条命令拉起三进程；浏览器打开 `http://localhost:3000` 被引导到 `/setup`，用假 Key 走完五步并落库；`/healthz` 三处全绿。** T-DB-1、T-CFG-1、T-SCR-1、T-SCR-3、T-SEC-6、T-E2E-2 通过。**这一步就钉死 P0-2（同源/BFF 透传）与 P0-5（Python 入口）**——它们是最容易在后期返工的两件事 |
| **M1 · 数据与治理**（约 25 文件） | 剩余模型与迁移字段、`services/{setup,settings,job,quality,object_store,event_bus}`、`jobs/{queue,runner,events}`、`providers/{base,registry,budget_guard}`、`providers/llm/*` 四适配器 + `model_catalog`、`tts/doubao`、设置页（profile/角色/revision 回滚/成本/doctor） | T-SETUP-1/2/4、T-JOB-1..6、T-AUDIO-1、T-DB-3、T-IDEM-1、T-SEC-1/5 通过；设置页可真实切换模型并回滚 |
| **M2 · 摄取与分析** | `ingest/*`（github/tarball/guard/mirror）、`analysis/*`（symbols/callgraph/knowledge_graph/key_chain）、Gate 0 的 G3 接线 | T-SEC-2、T-ANCHOR-1 通过；CLI 可对夹具仓库产出 KG 与关键链路（**不需要任何 AI**） |
| **M3 · 生成工作流** | `workflow/*` 九节点 + prompts/parsing/repair/simulation_guard/publish + Kernel 的 `runtime/tools/emit/budget/contracts` + 契约包 | T-GRAPH-1..4、T-TRACE-1/2、T-DEG-1/2、T-CON-1/2 通过；CLI 可对夹具仓库跑完整生成并发布 `ready` |
| **M4 · 学习工作台** | P01/P02（首页、课程准备、SSE 进度）+ 工作台外壳 + `CodePane`/`HighlightLayer` + 播放器时间轴 + 三层页面 + 行内提问 + 答题 + 笔记 + 进度 | T-PLAY-1/2、T-IDE-1、T-ASK-1/2、T-QUIZ-1/2、T-E2E-1、E2E 流程 2/3 通过 |
| **M5 · 完课 · 书籍 · PDF** | `recap` 页 + `services/{book,pdf}_service` + `rendering/*` + P09/P10 + `scripts/gen_fixtures.py` | T-BOOK-1/2、T-PDF-1、E2E 流程 4 通过；Chromium 缺失时降级为打印视图且 UI 一致 |
| **M6 · 收尾** | `seed-demo` 种子课程、`scripts/{backfill_quality,prune_objects}`、`docs/{runbook,architecture,api}.md`、`docker-compose.yml`、`apps/worker`、指标聚合、全量测试与构建 | §8 全部编号绿；`start.ps1` 冷启动 < 60 s；README 一页跑通 |

**为什么 M0 必须包含 `/setup` 与 `start.ps1`，而不是放到最后**：任务书把"项目启动时有 AI 服务配置引导"和"根目录要有 start.ps1 / stop.ps1"列为硬要求。它们是**验证成本最低、但耦合面最广**的两件事——`start.ps1` 决定三进程怎么起（进而决定同源通路与内部令牌），`/setup` 决定配置模型与密钥落地（进而决定所有 provider 调用）。放到最后做，等于把两个"影响全局结构"的东西当收尾工作，几乎必然返工。

**旧排期（v1 的 16 步）与里程碑的映射**（供对照，避免漏项）：步 1–2 → M0；步 4、7、8、14 → M1；步 3 → M2；步 5、6 → M3；步 9–12 → M4；步 13 → M5；步 15–16 → M0 与 M6 分摊。

**提交策略（不变）**：以 `feat:` 前缀一次提交该步涉及的具体文件路径（禁止 `git add -A`）；迁移与脚本单独提交；生成物（`openapi.json`、`schema.d.ts`）与其源改动同一提交，避免 CI 漂移。

---

## 11. 用户未提及但本方案补齐的设计（"我没考虑到的，你来考虑完善"）

| # | 补齐项 | 为什么必须 |
|---|---|---|
| 1 | **离线种子课程**（`seed-demo`） | 没有 Key/没网络时产品完全不可演示；也是 E2E 与新人上手的前提 |
| 2 | **配置引导的失败体验**（probe 失败是数据不是异常，带可执行 hint） | 首启体验决定留存；"测试连接"失败必须告诉人下一步做什么 |
| 3 | **密钥加密与轮换**（Fernet + AAD + 日志脱敏） | 存明文 Key 是安全事故的种子；轮换能力是长期可用的前提 |
| 4 | **Job 状态机 + 心跳回收 + 断点续跑** | 分钟级生成任务的必然要求，否则一次崩溃就要从头烧钱 |
| 5 | **内容级缓存 + 请求级幂等 + 生成锁** | PRD 明确要求复用；三次不同实现（缓存/幂等/锁）缺一即出现重复烧 token |
| 6 | **预算三层守卫 + 成本账本** | 防止一条长 prompt 打穿账单；也是"单课程生成成本"指标的计量基础 |
| 7 | **契约生成与漂移检测** | 前后端对接的工程保证，比口头约定可靠 |
| 8 | **确定性标注（certainty）+ 发布前校验** | PRD §5 的"源码事实/静态推断/教学模拟"如果不进代码就是口号 |
| 9 | **降级矩阵与可观测性**（Doctor 面板、metrics、request_id） | "稳健可靠顶级"必须能被验证；出问题时要能自证哪里坏了 |
| 10 | **锚点与 commit 绑定 + 版本化复用/增量重建入口** | 仓库更新后旧课程仍可学（PRD 要求），且新版本可比较 |
| 11 | **书籍与 PDF 的缓存与模板版本** | 避免重复排版与重复 AI 生成（PRD 明确） |
| 12 | **只读沙箱与路径守卫（Windows 兼容）** | 仓库是不可信输入，Windows 的设备名/链接点比 POSIX 更坑 |
| 13 | **成本与用量的用户可见面板** | 用户需要知道"这次生成花了多少"，产品才可信 |
| 14 | **无障碍与降级动效** | 教学产品必须可长时间阅读；色弱/键盘用户不应被排除 |
| 15 | **许可证信息随课程/书籍流转** | 分析开源仓库并输出成书，必须标注来源与许可 |
| 16 | **结构化日志与排错 runbook** | 单机开发也要能定位"卡在哪个节点" |
| 17 | **CI 冒烟（Windows PowerShell + 迁移往返 + 契约检查）** | 一次机器迁移就失效的脚本不算"能启动" |
| 18 | **`/v1/jobs` 面板与重试/取消入口** | 用户对长任务的控制感，是"顶级"与"能跑"的分界线 |
| 19 | **明确"不做"的边界（v2 新增，P1-11）** | v1 把四件事写成了要交付的内容，但它们都不是 MVP 的必要组成，反而稀释注意力。v2 显式 defer 并给出理由：① `docker-compose.yml`（默认开发流不需要容器，写了也无人验证）→ M6；② 豆包 WS 流式试听（HTTP 一次性合成已满足"能听"，WS 只在"边生成边播"时有意义）→ 观察后再做；③ PDF 视觉回归（用 vision 模型判溢出/重叠，成本与稳定性都不划算）→ 保留开关默认关闭；④ 独立 `apps/worker` 进程（单机单用户下与 API 同进程足够）→ M6 之后。**"没做的事写清楚"比"什么都做一半"更接近顶级** |
| 20 | **同源通路与内部令牌**（v2 新增，P0-2） | 把"浏览器只认识 :3000"变成架构约束，否则会话、CSRF、SSE、音频 Range 会在集成阶段一起出问题，且每个都像独立 bug |
| 21 | **Gate 0 依赖探测**（v2 新增，P0-6） | 闭源 npm 包 / Chromium / tree-sitter 轮子各有一种"装不上"的方式；开工前就知道降级到什么程度，是唯一诚实的做法 |

---

## 12. PRD 对齐矩阵（评审用）

| PRD 条目 | 本方案落点 |
|---|---|
| §3.1 仓库接入/版本化课程/缓存键/增量重建 | §3.10 缓存键、`course_versions.cache_key`、`POST /rebuild` |
| §3.2 三层学习、同一工作台、一键下钻/返回 | §7.2 映射表 + `course/[id]/layout.tsx` + R7 的 `returnTo` |
| §3.3 播放器/模拟/AI 问答/预测题 | §7.3 时间轴、§6.4 certainty、§5.2 questions、`PredictionQuiz` |
| §3.4 完课总结 + 图文书籍 + 在线阅读 + PDF | §5.2 recap/books/pdf、§4.5 P08–P10 组件 |
| §4 视觉规范（Supabase 风格/Momo/折叠调用链） | §7.1 token、§7.2 组件、`MentorRail`、`TraceStrip` |
| §5 数据对象/信任边界/异步去重/独立资源缓存 | §6、§3.12、§3.10、`audio_assets`/`pdf_exports` |
| §6 MVP 验收（缓存命中/模拟标识/定位返回/PDF 一致） | T-JOB-2、T-TRACE-2、T-IDE-1、T-PDF-1 |
| §6 指标（成功率/命中率/成本/完成率/正确率/导出率） | §3.13 `/v1/metrics` + `cost_ledger` + `user_progress`/`quiz_items` |
| 任务书：配置引导（多协议 LLM + 多模态 + 豆包 TTS） | §3.6、§3.7、§3.8、§5.2 setup 组 |
| 任务书：LangGraph + AragonAgent core | §3.4、§3.5 |
| 任务书：Next.js + React + Python 对接 | §3.1–§3.3、§5.7 契约 |
| 任务书：start.ps1 / stop.ps1 | §4.1、§8.2 T-SCR-*、§10 步 15 |

---

## 13. 待评审确认的开放问题（v2 已给出默认决策）

> v2 立场：开放问题不能无限期开放——**每个问题在此给出"默认怎么做"和"改变它的条件"**，这样开发节点不必等待决策即可推进，评审者只需关注条件是否成立。

1. **登录与多用户**：MVP 用本地单用户 `usr_local` + 全查询带 `user_id`。**默认不引入 GitHub OAuth**；改变条件：需要部署到公网给多人用时（此时 §6 的 `user_id` 形状已就位，只需加认证层）。
2. **PDF 引擎**：**MVP 唯一引擎 = Chromium**（`playwright install chromium`，由 `start.ps1` 的 G2 Gate 负责）。v1 曾把 `weasyprint` 写成兜底——它在 Windows 需要手工装 GTK/Pango，实际不可用，**已删除该选项**（P1-7）。兜底改为"打印优化 HTML + 浏览器打印"（`pdf_exports.engine='browser-print'`）。
3. **tree-sitter 语言集**：MVP 固定 `python/javascript/typescript/go/java/rust`，依赖固定为 `tree-sitter-language-pack`（有 Windows 预编译轮子；`tree-sitter-languages` 在 Windows 需 MSVC 编译，**不作为依赖**）。`c/cpp` 暂不追加；改变条件：用户导入的仓库中 C/C++ 占比成为主流入口。
4. **豆包 TTS 通道**：**默认 HTTP 一次性合成**；WS 流式仅用于设置页试听，MVP 之后再看。若产品要"边生成边播"，需要把音频资产改为字节区间（`audio_assets` 增加 `chunk_manifest`），这是独立一次演进。
5. **增量重建范围**：本方案只提供 `POST /rebuild`（重跑受影响节点）与 `from` 参数；"按 diff 只重建受影响课时"列为 P1（PRD 亦将章节级增量放 P1）。
6. **搜索模式（v2 新增）**：默认全表扫描 + `limit ≤ 50` + 300ms 超时；`REPOLEARN_SEARCH=fts` 时启用 FTS5/`tsvector`（§8.2 末）。改变条件：课程量超过 ~5000 条或用户反馈搜索慢。
7. **并发度（v2 新增）**：默认 1（SQLite 单写者）。改变条件：切 PostgreSQL（`docker-compose.yml` 样例已设 2–4）。

---

## 评审结论（Review Verdict）

**结论：有条件通过（Approved with Conditions）。**

### 判断依据

这份方案在"产品理解"与"技术判断"两件事上是可靠的：三进程拓扑（web / api / kernel）是针对"Node ESM 内核 + Python 长任务"这一约束的正确解法，而不是为了时髦的分层；"锚点即凭据 + certainty 三值"把 PRD 里容易被写成口号的可追溯性变成了发布前的校验门禁；配置引导、LangGraph + AragonAgent core、前后端契约、启停脚本这四项任务书硬要求都有明确落点与测试编号。因此不需要重写方案，只需修正其中的执行性缺陷。

v1 的问题不是"想得不够多"，而是**有 6 处在照做后会直接失败的写法**（P0）：同步 checkpointer 配异步图、跨源架构下的 cookie/CSRF/SSE、数据模型与文件清单对不上、三层预算量级打架、Python 入口不可达、三个外部依赖没有前置校验。这些缺陷的共同特征是"在纸面上读不出问题，在集成时才会集中爆发"，也正是设计评审应当拦截的那一类。它们已在 v2 正文就地修复，并且每条都配了可执行的验证落点（新增测试编号 T-DB-3/4、T-IDEM-1、T-GRAPH-4、T-DEG-2、T-E2E-1/2、T-SEC-5/6、T-JOB-6、T-QUIZ-2）。

### 通过条件（进入开发前必须满足，全部已在 v2 正文落实）

| # | 条件 | 状态 |
|---|---|---|
| C1 | 架构上禁止跨源：浏览器只经 BFF 访问，API/Kernel 只绑 `127.0.0.1` 且要求 `X-Internal-Token`（§2.2 约束 6、§3.1、§3.3、§3.12） | ✅ 已写入 |
| C2 | LangGraph 使用 `AsyncSqliteSaver`、显式 reducer 表、checkpoint ≤ 256 KB 且产物外置（§3.4；T-GRAPH-4） | ✅ 已写入 |
| C3 | 数据模型定稿为 **26 表 / 27 模型文件**，补 `quiz_attempts`、`pdf_exports`、`idempotency_keys`；`llm_profiles.active` 有部分唯一索引（§6；T-DB-3、T-QUIZ-2） | ✅ 已写入 |
| C4 | 预算三级（job / 节点 / run）且 §5.4 的单 run 上限不再写死 180k（§3.4、§5.4、§8.4） | ✅ 已写入 |
| C5 | Python 打包范围显式声明，`python -m repolearn.cli --help` 在 M0 即通过（§4.1 的 pyproject 片段） | ✅ 已写入 |
| C6 | Gate 0 三条依赖探测进 `start.ps1` 与 `/healthz.gates`，任何 Gate 失败只降级不阻断启动（§2.4；T-DEG-2） | ✅ 已写入 |
| C7 | 实施顺序改为里程碑制，M0 必须是"能启动、能走完向导"的 walking skeleton（§10） | ✅ 已写入 |
| C8 | 首启守卫改为 `middleware.ts` 纯 cookie 判定 + API 不可达时 fail-open，不得出现 302 循环（§3.6.1；T-E2E-2） | ✅ 已写入 |
| C9 | 心跳、僵尸版本 reaper、并发默认值统一为 1（§3.11.1–3.11.4；T-JOB-6、T-DB-4） | ✅ 已写入 |
| C10 | CI 门禁只保留可复现项；帧率与 LCP 降为本地基准；`EXPLAIN` 门禁收窄到分页主查询并单列搜索策略（§8.2、§8.4） | ✅ 已写入 |

### 进入开发（Subtask #2）时的以下三条纪律

1. **严格按 §10 的里程碑推进，先把 M0 跑通再写第二批模型**。M0 的验收不是"文件都在"，而是"`.\start.ps1` 能起、浏览器能走完 `/setup`、`/healthz` 三处绿"。若为了赶进度跳过 M0，后面每加一个模块都在往一个无法启动的仓库里堆代码。
2. **任何与本文件不一致的实现选择，必须先改本文件再改代码**（尤其是状态形状、表结构、事件信封）。本文件的 §4/§5/§6 是三方（开发、Review、测试）唯一的共同依据，一旦允许"以代码为准"，契约漂移就无人可挡。
3. **新增的测试编号不得删改，只允许追加**。T-* 编号是跨节点传递的验收凭据（开发节点勾选、Review 节点复跑）；改名即等于丢失历史。

### 遗留风险（不阻塞通过，但必须被持续观察）

- R1（闭源 npm 包行为不可控）与 R16（依赖在某台机器上不可获取）是**外部事实**，本方案只能做到"探测 + 降级 + 明示"，无法消除。
- R2（模型幻觉锚点）由"Kernel zod + Python 存在性校验 + certainty 标注"三重防线压制，但 `teaching_simulation` 的占比仍然取决于模型质量，不作质量承诺。
- 成本门禁（job 级 ≤ 0.35 USD）依赖 `model_catalog` 的价格数据；**未收录价格的模型会被记为 0**，因此这条门禁只在已收录模型上有效（§3.4 已注明 `PRICE_UNKNOWN`）。

**评审人**：评审节点（资深评审，Anthropic 工程视角） · **日期**：2026-11-06 · **文档版本**：v2

---

**（文档结束 · v2 · 已评审 · 有条件通过）**


---

## 实施过程发现的方案缺陷

> 本节由开发节点在实现 §4 的 180 个文件过程中追加（spec 第 2 条纪律：任何与本文件
> 不一致的实现选择，必须先改本文件再改代码）。每条都是**照做会失败或会静默出错**的
> 缺陷，不是风格分歧；每条都已按"修正后的口径"落地，并补了防回归测试。

| # | 缺陷（本文件原口径） | 后果 | 实施时的修正 | 防回归 |
|---|---|---|---|---|
| **D1** | §4.1 的 `pyproject.toml` 片段只写了 `[tool.hatch.build.targets.wheel] packages = ["apps/api/repolearn"]`，没有 `sources` 映射 | `pip install -e .` **报成功**，但产出的是空的 editable 安装：`import repolearn` / `python -m repolearn.cli` 全部 `ModuleNotFoundError`。这正是 P0-5 想修的问题，却因为少了一行而原样复发 | 补 `[tool.hatch.build.targets.wheel.sources] "apps/api/repolearn" = "repolearn"`；`start.ps1` 失败时要打印 `PYTHONPATH=apps/api` 兜底一行 | `test_contracts_cli_migration.py::test_pyproject_declares_packaging_for_cli`、`cli --help` 冒烟 |
| **D2** | §6.1/§6.2 声明所有时间列为 UTC `TIMESTAMP`，但没写清 SQLite **不保存时区** | 读回来是 naive datetime，于是所有 `row.expires_at < utcnow()` 比较都抛 `can't compare offset-naive and offset-aware datetimes`。命中位置恰好是幂等键过期、生成锁过期、心跳回收、僵尸版本回收——**全部可靠性逻辑** | 在模型层加 `UtcDateTime`（TypeDecorator）：写入去 tzinfo（内容仍是 UTC）、读出补 UTC。一次修在类型层，而不是在 8 个比较点各写一次 `as_utc()` | `test_books_api.py::test_create_book_is_idempotent`（走幂等键过期路径）、`test_jobs_queue.py`（锁/心跳/reaper） |
| **D3** | §4.4 把 `idempotency_keys` 描述为"10 分钟内同键同体返回首次响应快照"，但没说重复提交时**创建类接口**该返回什么状态码 | 同键第二次请求会返回快照里的 `202 + job_id`，前端据此以为"又建了一个 Job"，而实际语义是"重放"。两种幂等（请求级重放 vs 内容级复用）在响应形状上不可区分 | 明确：**请求级重放**返回首次响应的**逐字节快照**（含 job_id、`reused=false`，状态码 200）；**内容级命中**由 `cache_key` 决定，返回 `200 reused=true` 且不带 job_id。二者分别断言 | `test_books_api.py::test_create_book_is_idempotent`（两种幂等各断言一次） |
| **D4** | §3.4/N5 只写"结构化校验失败 → 修复提示重试 2 次 → 退化为确定性模板"，没说模板降级是否还需要模型配置 | 状态 C（Agent 内核不可用）下 `run_course_job` 仍以 `SETUP_REQUIRED` 拒绝执行，于是"没有 Key 的新克隆"连简化版课程都生成不出来——而那正是 Gate 0 失败时唯一的可用路径 | 模板降级**不需要**任何 LLM 配置：`runtime.mode == "template"` 时跳过 profile 校验，用空 resolver 走静态分析 | `test_pipeline.py::test_full_pipeline_publishes_ready_course`（无 profile 跑完整链路并发布） |
| **D5** | §3.5.4 只说"模板降级产出规则必须写死"，没写模板**用什么路径**做锚点 | 实现时用了"模块 key"（`pkg/sub`），而它是目录前缀不是文件。发布前锚点校验因此报"锚点文件不存在"→ 整门课程回滚（`ANCHOR_STALE`）。单目录仓库测不出来，多级目录必然触发 | 模板骨架改用**真实文件路径**（按模块内符号数排序），并把行区间 clamp 到文件行数内 | `test_pipeline.py`（多级目录夹具）、`test_workflow.py::test_template_lesson_has_contiguous_segments` |
| **D6** | §3.4 的 `CourseGenState` 字段表里没有 `current_lesson`，但同节的边定义用 `Send("write_lessons", {...})` 按课时扇出 | LangGraph 拒绝更新 schema 之外的键（`InvalidUpdateError`），扇出分支根本跑不起来 | 在 `CourseGenState` 显式声明 `current_lesson: dict` 并写明原因 | `test_pipeline.py`（真实图路径，非降级路径） |
| **D7** | §3.5.3 的判据写"`node -e "import('@aragon-agent/core')"` 成功"，§2.4 G1 写"`npm view` + `node -e` 打印导出面" | 三种写法都会把"装好了"误判为"没装"：① `require('@aragon-agent/core/package.json')` 抛 `ERR_PACKAGE_PATH_NOT_EXPORTED`（exports 未暴露 package.json）；② 包是 ESM-only，`createRequire().resolve()` 无 `require` 条件可用；③ 裸 `import()` 相对**脚本文件**解析，不是 cwd。误判的后果是整门课程静默降级为模板版 | 探测逻辑收进单一文件 `scripts/probe_core.mjs`（走 node_modules 目录查找 + 读 exports['.'].import 再 import），PowerShell（G1）与 Python（运行时三分支）都调它 | `scripts/check_env.ps1` 实跑输出 `G1 ok :: @aragon-agent/core 0.2.66`；`probe_core_package()` 单点调用 |
| **D8** | §4.2 的 Kernel 依赖清单里只有 `langgraph`，没有 `langgraph-checkpoint-sqlite` | `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` 直接 `ModuleNotFoundError`，而 §3.4 把 `AsyncSqliteSaver` 写成硬约束——即"照文档写就装不起来" | `pyproject.toml` 补 `langgraph-checkpoint-sqlite>=2.0`；`build_course_graph` 捕获 `GraphUnavailable` 后**顺序执行同一批节点**（这条降级路径也在测试里） | `test_pipeline.py::test_run_graph_falls_back_when_langgraph_missing` |
| **D9** | §3.2 的分层规则只写"`services/` 不得导入 `routers/`"，没写包级 `__init__` 的再导出约定 | `services/__init__.py` 里批量 `from . import x` 会与 `ingest.mirror → services.object_store → course_service → ingest.mirror` 形成循环导入，报 `cannot import name ... from partially initialized module`，且**报哪一行取决于导入顺序** | `services/__init__.py` 只留文档，不做批量再导出；调用方显式 `from repolearn.services import course_service` | 全量 pytest（任何循环都会在收集期炸） |
| **D10** | §5.2 的分组只列了 `/v1/courses` 等接口，§3.3 只说"BFF Route Handler 转发"，没说 **catch-all 不匹配集合路径** | 前端调 `GET /api/courses`、`POST /api/courses`、`GET /api/jobs` 时命中 Next 的 404 **页面**（返回 HTML），浏览器侧表现为"接口返回了一段 HTML"，极易误判为后端故障。而这两个调用正是产品的入口（首页列表 + 创建课程） | 为每个集合路径补 `app/api/<name>/route.ts`（与 `[...path]` 并存），并在 BFF 说明里写清"catch-all 只覆盖子路径" | `apps/web/src/app/api/__tests__/collections.test.ts`（断言集合路由文件存在） |
| **D11** | §4.1 说 Graph 的 checkpoint 值"≤256KB"，但没规定 `steps.audio_asset_id`/`playback_meta` 只能存引用 | 实施时差点把整段 lesson JSON 塞进 `playback_meta`；一旦如此，播放接口的响应会随课时增大到数百 KB，而 §5.3 的"一次拉全"就变成一次拉几 MB | 保持 v2 的单一真源约束（步骤在 `steps`，`playback_meta` 只放 files/trace_key/legend/narration 引用），并在 `test_workflow.py` 里用 12 课时断言 state 体积 | `test_workflow.py::test_state_with_many_lessons_stays_under_budget` |
| **D12** | §5.5 的事件信封没有 `job.snapshot` 之外的"服务端主动结束流"约定 | BFF/浏览器会一直挂着连接直到超时；SSE 端点无法在 `job.completed` 后自然收尾 | 明确：服务端在写出 `job.completed` / `job.failed` 后**关闭连接**；客户端据此停止重连（重连只在传输层错误时发生） | `test_jobs_objects_progress_api.py`（事件补发/SSE 头）、手工 `curl --max-time` 实跑 |

| **D13** | §4.1 的 `start.ps1` 只写"起 kernel/api/web"，没写 **Windows 上怎么起一个包管理器脚本** | `Start-Process -FilePath "pnpm"` 在 Windows 上必然失败（`%1 不是有效的 Win32 应用程序`）：pnpm 是 `pnpm.cmd` / `pnpm.ps1` 垫片，不是 PE 文件。表现是"三个进程只起了两个，前端永远不在"，而 `start.ps1` 只在日志里留下一条难懂的 Win32 错误 | 先用 `Get-Command pnpm` 定位垫片（优先 `.cmd`），再经 `cmd.exe /c "<shim> dev --port N"` 启动 | `test_scripts_and_seed.py::test_start_ps1_launches_pnpm_through_cmd` |
| **D14** | §2.2 硬约束 3 只写"Windows 优先 / PowerShell 5.1"，没提 **机器上已有全局 `NODE_ENV`** 的情况 | 开发机常见全局 `NODE_ENV=production`（本机就是）：`next dev` 报 "non-standard NODE_ENV"，且 edge middleware 沙箱直接 `EvalError: Code generation from strings disallowed for this context` ——**每个请求 500**，而现象只表现为"web 未健康" | `start.ps1` 在启动 web 前显式钉住 `NODE_ENV`（dev → development，`-Prod` → production），不继承机器环境 | `test_scripts_and_seed.py::test_start_ps1_pins_node_env`、`docs/runbook.md` §1 |
| **D15** | §4.1 的 `seed-demo` 只写"插入一条离线演示课程"，没规定 **重复执行的语义** | 第二次执行直接报 `UNIQUE constraint failed: repositories.full_name`。而 `start.ps1` 与用户都会反复跑它；"重跑一次准备命令却报错"会被当成环境坏了 | `seed-demo` 改为幂等：已存在则复用 repository/commit，并重建该演示课程（先删后建） | `test_scripts_and_seed.py::test_seed_demo_is_idempotent`、`::test_seed_demo_creates_exactly_one_demo_course` |
| **D16** | §8.2 的 T-SCR-1/3 只写"90 秒内三端口就绪""stop 幂等"，没说 **验证方式** | 手工"看起来起来了"与"真的能开页面"差别很大：D13/D14 两个缺陷在文件清单上完全看不出来 | 增加 `scripts/parse_check.ps1`（用真实 PS 5.1 解析器做语法门禁）与实跑验证：`start.ps1 -SkipInstall` 退出码 0 且三端口 200 / `/` → 307 `/setup`、`/setup` → 200；`stop.ps1` 连跑两次且之后三端口均不可连接 | `test_scripts_and_seed.py::test_scripts_are_parseable_by_powershell_51` |


### 评审节点补记的缺陷（D17–D28，逐条已修 + 已补防回归）

> 本节由**评审/提交节点**追加。与 D1–D16 的区别：那些是"照文档写就会失败"，
> 这些是"代码写完了、测试全绿、但某条路径其实没生效"——即**静默失效**。
> 它们全都无法由类型检查或既有单测发现（既有测试走的是另一条分支），因此每条
> 都补了能咬住它的测试，否则下一次重构会原样复发。

| # | 缺陷（实态） | 后果 | 修正 |
|---|---|---|---|
| **D17** | `jobs/queue.py::acquire_lock` / `store_idempotency` 在 `IntegrityError` 时调 `session.rollback()` | 把同一请求事务里刚创建的 repo/commit/course/job **一起回滚**，接口仍返回 `202 + job_id`；用户打开进度页拿到 404。这是"并发同仓库"下最难归因的一类假象 | 改为 SAVEPOINT（`session.begin_nested()`），只回滚该条 INSERT |
| **D18** | `services/course_service.py::create_course` 从不抛 `JOB_CONFLICT` | T-JOB-1（并发 5 次只应产生 1 个 Job）的语义形同虚设：第二个请求会排第二个 Job，两条流同时写同一个 `course_version` | 入队前用 `queue.active_lock_job()` 判定，命中即 `409 JOB_CONFLICT`（带 `job_id`）；`acquire_lock` 返回 False 也转 409 |
| **D19** | 软删课程（`deleted_at` 非空）占用唯一 `cache_key`，但复用查询带 `deleted_at IS NULL` | 删除过的课程**再也生成不出来**：INSERT 撞唯一约束 → 500 INTERNAL | 复用查询不再过滤软删；命中的软删行走"复活"分支（清 `deleted_at`、`visibility=public`） |
| **D20** | `services/book_service.py::create_book` 只复用 `ready/generating` | 生成失败的书第二次请求直接 500（同一 `cache_key` 插第二行） | 复用同一行并把状态重置为 `generating` |
| **D21** | `services/setup_service.py::rotate_secret` 只用新密钥重加密，**不落地新密钥** | 轮换"成功"之后所有 API Key 都解不开 → 所有模型调用带着空 Key 出站，症状是"模型全挂了"，而不是"密钥轮换失败" | 重加密 → 显式 commit → 切换内存 `settings.secret_key` → 写回 `.env`（旧值进 `SECRET_KEY_PREVIOUS` 供重试分支） |
| **D22** | `core/config.py::fernet_key` 在未配置密钥时**每次调用都重新随机** | 加密与解密用的 key 永远不同：库里只剩无法解开的密文 | 进程内固定兜底密钥 + 启动告警（`_ephemeral_key()`） |
| **D23** | `jobs/queue.py::request_cancel` 只把状态改成 `cancelling`，无人消费 | 取消按钮无效：排队中的任务永远停在"取消中"、运行中的任务跑完后把状态覆盖成 `ready` | `queued` 当场终结并释放锁；`claimed/running` 由 `runner._heartbeat_loop` 观察到后 cancel 掉 asyncio 任务；收尾时以 `cancelling` 为准 |
| **D24** | `CourseGenState` 没有 `publish` 键，而 `run_course_job` 从 `final["publish"]` 取发布结果（并且多解了一层） | LangGraph 静默丢弃未声明的键：**每一次成功生成都上报 `partial`**、`quality_report` 永远为 null、完成消息里的课时数永远是 0 | state 声明 `publish`（`merge_dict` reducer）；消费侧只解一层 |
| **D25** | `_Ctx.run` 用 `schema=` 当节点名查 `NODE_BUDGETS` | 每个节点都落回 8k 默认额度：`plan_curriculum` 该 20k 只拿到 8k，`simulate_trace` 该 2k 却给了 8k，28k 的"预留给后续课时"从不生效 | 增加 `node=` 参数，`schema=` 只用于 Kernel 结构化校验；N6/N7 传 `per_lesson=True` |
| **D26** | `providers/registry.py` 从不填 `ModelCandidate.capabilities` | `price_in/price_out` 恒为 0 → `job_max_usd` 成本闸门永不触发、`cost_ledger.usd` 恒为 0（成本面板成了装饰） | 在 `resolve()` 里带出 `model_catalog.capabilities_for(...).as_dict()` |
| **D27** | TTS 一条课时只交付"第一段的 url + 全课总时长"，且课时级 audio 被复制到每一个 step | 播放器以为音轨有 3 分钟、实际 8 秒就静音；切步时把音频拨回开头，字幕与声音错位 | N8 按步合成、按步拼接（`providers/tts/join.py`，帧级拼接 + 去 ID3），`narration.steps[index]` 存每步音轨；`lesson_service.playback` 按步取用并保留课时级兼容分支 |
| **D28** | Kernel `runtime.ts` 把 `req.tools` 当**完整**工具白名单；`turn_end` 的 usage 被丢弃；`budget.record` 的 `usd` 用 `+=` 累加累计值 | ① Python 只下发 4 个 repo 工具 → `emit_*` 被过滤 → Agent 无法交付结构化产出，带真实模型的生成**必然** `CONTRACT_VIOLATION`；② `tokensIn` 恒为 0，长 prompt 短回答完全逃过预算；③ 多轮之后 usd 记成 2~3 倍，成本闸门提前触发 | ① `resolveAllowedTools()` 总是并入 `emit_*`（未知名字仍记进 `failures`）；② 真实 usage 落到 `record()`；③ `usd = computeUsd()`（赋总价而非累加） |

**评审同时补齐的"计划有、实现无"三项**（§4 覆盖率）：

- `packages/contracts/src/index.ts`（§4.3）：导出生成的 `paths/components` + `EventEnvelope` + 19 个错误码；
  `scripts/gen.mjs` 现在同时产出 `apps/web/src/lib/api/schema.d.ts` 与 `packages/contracts/src/types.ts`，
  `--check` 两个文件都比对（Windows 上改用 `node <cli.js>` + 临时文件，不再依赖 `/dev/stdout`）。
- `apps/web/e2e/*.spec.ts`（§8.3 离线层，14 条）：首启守卫/后端未就绪、首页导入四态
  （成功 / 非法 / `JOB_CONFLICT` / `REPO_FORBIDDEN`）、课程卡片进工作台、第一层字幕、
  播放器切步、只读 IDE（Monaco 真挂载且无降级横幅）、答题解释与 `replayed` 提示、完课页与生成书籍。
- `apps/web/src/lib/api/schema.d.ts`：由 `pnpm contracts` 生成并入库；`pnpm contracts:check` 做漂移门禁。

**仍与 §4 清单不一致的两处（有意，不是遗漏）**

- `apps/api/repolearn/services/pdf_service.py` —— 未单独建模块。PDF 编排实际落在
  `services/book_service.py::create_pdf`（缓存键、`browser-print` 降级判断）+
  `jobs/book_jobs.py::run_pdf_job`（队列执行）+ `rendering/pdf.py`（引擎能力探测与渲染），
  三层各守一件事；再插一个只做转发的 `pdf_service` 只会增加一层间接。
  `POST /v1/books/{id}/pdf`、`GET /v1/books/{id}/pdf` 与 T-BOOK-2 的降级断言均已覆盖。
- §8.3 的**第二层**（real-backend 冒烟：真起三进程跑一条主流程）未进本次提交。
  离线层 14 条已覆盖前端契约；三进程链路由 `start.ps1` 实跑（三端口 200、
  `/` → 307 `/setup`、BFF 透传 200）与 197 条 pytest 覆盖。把 real-backend 冒烟固化成
  CI 作业需要独立的 ports/db 隔离与 1 次重试策略，留给后续专门一轮，避免把
  "每提交都跑一次三进程"变成不可维护的门禁。

### 对 §10 里程碑的实际完成情况（与 v2 排期的偏差）

- M0–M6 的**文件清单已全部落地**，但顺序上做了两处调整，理由都是"先让链路可跑"：
  1. 先实现 `services/object_store` + `event_bus`（v2 把它们排在 M1），因为 Job Runner、
     发布事务、问答流都依赖它们；后做会让 M0 的 walking skeleton 缺一条腿。
  2. 把 `scripts/probe_core.mjs` 提前到 M0（v2 未列该文件）：Gate 0 的 G1 判据本身有
     缺陷（见 D7），先修判据再谈"降级可见"才有意义。
- `docker-compose.yml`、豆包 WS 流式、PDF 视觉回归、独立 `apps/worker` 仍按 §11 第 19 项
  维持 defer，未实现。
- PDF 视觉回归与帧率基准按 §8.4-B 保持"本地基准/人工抽检"，未进 CI。

### 未在本轮实现、但已在代码里留好接缝的项

| 项 | 现状 | 接缝位置 |
|---|---|---|
| FTS 搜索（`REPOLEARN_SEARCH=fts`） | 只有 scan 模式（limit≤50 + 300ms 语义在 service 注释里） | `services/course_service.py::list_courses` |
| 豆包 WS 流式合成 | 只有 HTTP 一次性合成 | `providers/tts/doubao.py::DoubaoTts._synth_once` |
| 多用户认证 | 单用户 `usr_local`，但所有查询都带 `user_id` | `services/progress_service.py::ensure_local_user`、各 service 的查询条件 |
| S3 对象存储 | 只有本地 `file://` 存储 | `services/object_store.py`（`put/get/read_range` 三个入口） |
| 增量重建（按 diff 只重建受影响课时） | 只有 `POST /rebuild` + `from` 参数 | `jobs/handlers.py::run_course_job` 的 `payload["from"]` |
