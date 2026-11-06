# RepoLearn M7–M10 · 从"实现了"到"可证明"（spec.md）

> **文档版本**：**v3**（v2 → v3 的差异全部来自文末 §交付前复审记录：6 条 P0 + 8 条 P1 已就地修正，1 条登记不修；v1 → v2 的差异来自 §评审记录，共 4 条 P0 + 11 条 P1 + 11 条 P2）
> **状态**：**已复审 · 实现通过**（评审与复审的结论分别见文末 §评审结论 与 §交付前复审记录；方法沿用 `docs/plans/repo-learn-platform/spec.md` 的四维：可行性 / 完备性 / 一致性 / 规模匹配）
> **日期**：2026-11-06
> **作者**：方案架构节点（Anthropic 工程视角，资深架构）；**评审**：资深评审节点（v1 → v2）
> **前序交付**：`docs/plans/repo-learn-platform/spec.md`（平台件方案，M0–M6 已全部落地；提交 `2f195d4`；197 pytest / 37 kernel / 62 vitest / 14 playwright 全绿）
> **需求来源**：本轮任务书「当前阶段」+ 全局目标「完成对应开发，顶级产品」
> **交付物**：本文件。下游开发节点以 §4 的「文件 / 模块变更计划」为唯一工作量清单，以 §9 的实施顺序推进，以 §7 的测试编号为验收凭据。

> **称呼约定（v2 新增，避免两个 v2 打架）**：本文件自身版本从 v3 起记为 **v3**（v2 是实现依据，v3 = 实现复查后的状态）；而 `docs/plans/repo-learn-platform/spec.md` 在 v1 里一直被称作"v2"（因为它是那份文档的 v2 版）。两份都叫 v2 会让"凡与 v2 冲突之处以本文为准"这类句子失去意义，因此从 v2 起，**该文档在本文件里统一改称「平台件」**，本文自身则自称"本文 / 本文件"。下文所有"平台件 §x / 平台件 Dx / 平台件纪律第 x 条"都是对它的引用。

> **一句话版**：上一轮把产品**做出来了**（三进程能起、三层课程能学、书能导、脚本能开关）；这一轮要做的是让它**可证明、可维护、可交付**——补上缺失的 CI 门禁与真后端端到端、把"配置里承诺了但代码里没生效"的搜索真正接通、把窄屏/触屏/无障碍从"看起来能缩放"做到"可被自动化门禁证明"，并补上仓库更新后"只重讲被改动的课时"这条版本化能力。**不新增一次性的花活**，每一条都要有能咬住它的测试。

---

## 评审记录（v1 → v2）

> **评审方法**：四维（可行性 / 完备性 / 一致性 / 规模匹配），沿用 `repo-learn-platform/spec.md` 的同一套判据。
> **评审依据**：不是通读印象。每条结论都落在**一次实读（文件:行号）**或**一次实跑**之上；"文档说的"与"仓库是的"不一致处，一律以仓库为准。
> **结论先给**：4 条 P0 + 11 条 P1 **全部就地修正**；11 条 P2 中 **10 条已修正、1 条明确不修**（P2-10，理由写在条目内）。正文即最终版（v2），改过的段落末尾不再单独标注。

### A. 评审用的实证清单（本次实读 / 实测，可复现）

| # | 实证 | 证据位置 | 它推翻了什么 / 支撑了什么 |
|---|---|---|---|
| E1 | `migrations/env.py` **已开启 `render_as_batch=True`**；SQLite 的 batch 重建 = 建临时表 → 拷数据 → **DROP 原表** → 改名 | `apps/api/migrations/env.py`（`context.configure(..., render_as_batch=True)`） | 推翻"0003 只是加一列、与搜索无关"的隐含假设 |
| E2 | 实测（SQLite 3.49.1）：`ALTER TABLE t RENAME` + 重建 + `DROP t_old` 之后，`sqlite_master` 里该表上的触发器**归零**；反之 `AFTER UPDATE OF <列>` 只在被列出的列变化时触发（无关列变化不触发），行为符合预期 | 本次实跑临时脚本 | 证明"迁移正常跑完、搜索从此悄悄不再更新"是**真实可能**的静默失效（P0-1） |
| E3 | 实测：`fts5(..., tokenize='trigram')` 可用；`MATCH '"Ag"'`（2 字符）返回 0 行**且不报错**；`MATCH '"缓存策"'`（3 字符）命中；`NEAR(...)`/`a*`/`a-b` 加引号后全部退化为字面量；**`MATCH` 与 `bm25()` 的参数必须写表名，写别名 `s` 会 `no such column: s`** | 本次实跑临时脚本 | 复核 F15 成立（trigram + 短查询回落是唯一正确解）；并补一条实现契约（已写入 §3.4.3） |
| E4 | `ERRORS` 只有 **19** 个码，`ERROR_CODE_COUNT = 19`；`AppError` 对**未知码静默降级为 `INTERNAL`（500，`retryable=True`）** | `apps/api/repolearn/core/errors.py` L28–66、L82–88 | 推翻 §3.4.4 / §5.1.1 里引用的 `VALIDATION_FAILED`（它不存在，见 P0-4） |
| E5 | 代码编辑器由 **AMD loader 远端拉取**（文件注释自述"离线开发机上永远解析不到"），`code-pane.tsx` 用 `MONACO_LOAD_TIMEOUT_MS = 4500` 超时回落 `PlainCodeView` | `apps/web/src/components/ide/monaco-editor-pane.tsx` L12–17、`code-pane.tsx` L19/L70–83 | 推翻 §3.3.3 "离线层零网络"对 deep-dive 的适用性；新增 a11y/mobile 用例的行为会随网络在两态间漂移（P1-7/P1-8） |
| E6 | `/healthz.gates` 读 `settings.run_dir / "preflight.json"`；`run_dir` 是**固定** `REPO_ROOT/.run`（无环境变量可改），该文件**只由 `scripts/check_env.ps1`（PowerShell）写**；**PDF 的门是 `g2`**（G1=agent core / G2=chromium / G3=tree-sitter） | `core/config.py` L127–129、`routers/health.py` L28–40、`scripts/check_env.ps1` | 推翻 T-E2E-R3 的可实现性：e2e-real 里 `gates` 恒为 `unknown`，"PDF 按钮与 gates 一致"没有参照物（P1-5） |
| E7 | `apps/web/next.config.ts` 无 `distDir` → 两台 `next dev`（`start.ps1` 的 3000 与 e2e-real 的 3100）写**同一份 `.next`** | `apps/web/next.config.ts` | e2e-real 与 `start.ps1` 并存会互相破坏构建缓存（P1-4） |
| E8 | 根 `packageManager` = `pnpm@12.18.0`，`pnpm-lock.yaml` = `lockfileVersion: '9.0'` 且含 `packageManagerDependencies`；kernel 的 `test` 是 `node --experimental-strip-types --test`（需 Node ≥ 22.6；本机 `v22.23.3`） | `package.json`、`pnpm-lock.yaml`、`services/agent-kernel/package.json` | 推翻 CI 表 `kernel` job 的 `setup-node 20`：`npm test` 会因未知开关直接失败（P1-2） |
| E9 | 前端是 TanStack Query **v5**（对象式 `useQuery({...})`，`@tanstack/react-query ^5.62.7`），v5 **已移除** `keepPreviousData` 选项 | `apps/web/src/lib/api/hooks.ts`、`apps/web/package.json` | 推翻 §3.4.4 的 `keepPreviousData: true`（P1-1） |
| E10 | `seed-demo` 的仓库名是 `microsoft/autogen (demo)`（与真导入的 `microsoft/autogen` **不同 identity**），且每次运行都删掉该仓库下已有 `CourseVersion` | `apps/api/repolearn/cli.py`（`DEMO_REPO_FULL_NAME`、`_seed_demo`） | 原疑虑不成立（夹具不会与真链路互相覆盖）；但把"夹具只读"写成显式约束 |
| E11 | 工具条的锚点**从不来自选区**：Monaco 分支 `onSelect={(next) => handleSelect(next, null)}` → anchor 恒为 `paneRect.top+44 / left+24`；`{top:96, left:320}` 只在 `paneRef` 为空时命中 | `code-pane.tsx` L105–126 / L237、`selection-toolbar.tsx` L34–40 | 修正 D29 的病因：不是"选区靠右"，而是**工具条与选区位置无关**；同时给出确定性测试缝（P1-6） |

### B. 分级总表

| ID | 维度 | 严重度 | 一句话 | 处置 |
|---|---|---|---|---|
| P0-1 | 完备性 | **P0** | `0003` 迁移（`render_as_batch=True`）会**静默删掉** `0002` 的 4 个 FTS 触发器，搜索从此不更新 | 已修正（§3.4.2 / §6.1 / §6.5 / T-SEARCH-9） |
| P0-2 | 可行性 | **P0** | SQLite < 3.34（或无 trigram）时 `0002` 的 DDL **直接失败** → `migrate` 崩、`conftest` 导入期跑迁移 → 全量 pytest 起不来；而文档承诺的是"降级 + 明示" | 已修正（§3.4.2 能力探测 / §3.4.3 / §5.1.3 / T-SEARCH-10） |
| P0-3 | 完备性（安全） | **P0** | 不可信端点返回的 `html_url` / 重定向 / tarball 体积**未做约束** → 存储型 XSS + SSRF + DoS，与 §3.2.1 自己写的 SSRF 红线相矛盾 | 已修正（§3.2.1 / §3.2.2 / §3.2.6 / T-GH-4..6） |
| P0-4 | 一致性 | **P0** | 引用了**不存在**的错误码 `VALIDATION_FAILED`；`AppError` 对未知码静默降级为 `INTERNAL(500, retryable)` → 用户输错参数得到"可重试的服务内部错误" | 已修正（新增第 20 个码并升级门禁；§5.1.1 / §7.4 / §10） |
| P1-1 | 可行性 | P1 | `keepPreviousData: true` 在 TanStack Query v5 上不存在 → 选项被忽略（或 TS 报错），输入时列表闪烁 | 已修正（§3.4.4） |
| P1-2 | 可行性 | P1 | CI `kernel` job 固定 Node 20，而 `npm test` 用 `--experimental-strip-types`（≥22.6）→ 该 job 必红 | 已修正（§3.2.4） |
| P1-3 | 一致性 | P1 | 新增 devDependency 与 `--frozen-lockfile` 的原子性、pnpm 版本来源未写；`pnpm-lock.yaml` 不在工作量清单里 | 已修正（§3.2.4 / §4.6 / T-CI-5） |
| P1-4 | 可行性 | P1 | e2e-real 的 `next dev` 与 `start.ps1` 共用 `.next` → 并发写坏构建缓存 | 已修正（`next.config.ts` + `REPOLEARN_NEXT_DIST_DIR`；§3.2.3 / §3.2.6） |
| P1-5 | 完备性 | P1 | `/healthz.gates` 在真链路层恒为 `unknown`（`run_dir` 固定、preflight 只由 PowerShell 写），且 PDF 门是 `g2` 而非 `g3` → T-E2E-R3 无参照物 | 已修正（`REPOLEARN_RUN_DIR` + `scripts/probe_gates.mjs`；§3.2.3 / §7.2） |
| P1-6 | 规模匹配 | P1 | D29 病因写错（锚点与选区无关），且 `code-pane.tsx` **不在 §4 清单**里——工具条定位只能在那里算 | 已修正（§3.3.2 / §4.6） |
| P1-7 | 可行性 | P1 | `T-TOUCH-4`「所有 `button`/`a` ≥ 44px」在 deep-dive 上必红：Monaco 注入自己的 16–22px 控件，且大量不可见元素 `height=0`；桌面上既有 `size="sm"` 按钮本就 ~28px | 已修正（§3.3.1 / §7.3 收窄范围） |
| P1-8 | 完备性 | P1 | axe 门禁对第三方 DOM（Monaco）断言 "serious=0" 在构造上不可能；且"离线零网络"与 E5 矛盾 → 新增用例行为随网络漂移 | 已修正（§3.3.3 排除第三方子树 + 钉定代码视图） |
| P1-9 | 完备性 | P1 | `plan_upgrade` 的 `total_files` 语义未定义；`carry_forward` 的 `percent` 公式未定义 → 两个实现会得到不同结果 | 已修正（§3.5.1 / §3.5.3） |
| P1-10 | 规模匹配 | P1 | `dry_run` 会**整包下载并解包**（可能是 100MB+），无体积上限、无缓存、无耗时承诺，用户点一下"检查更新"就是一次全量下载 | 已修正（§3.5.2） |
| P1-11 | 一致性 | P1 | `T-DOC-1` 要求 README 四个数字与实测"容差 0"，但 pytest 计数依赖平台（Windows 跑 PowerShell 门禁、Linux skip）→ 同一条门禁在两种 runner 上不同结论 | 已修正（§7.2 限定 api job + 同平台比对） |
| P2-1 | 一致性 | P2 | §4 规模行（75 行 / 68 唯一 / 33+32+3）与表格实际**对不上**（复用 5 处 → 70 唯一）；且变更记录写"28 条新测试编号"而实际是 **38** 条 | 已修正（改为机械计算 + `T-DOC-2`；编号数在变更记录里据实改为 47） |
| P2-2 | 完备性 | P2 | §5.1.1 写 `q ≤ 120`，但现有 router 的 `q: str \| None` 无约束 | 已修正（`max_length=120` 落到 Query） |
| P2-3 | 完备性 | P2 | `Segment` 类型在 §3.4.3/§3.4.4 被使用但从未定义 | 已修正（给出 dataclass） |
| P2-4 | 完备性 | P2 | Doctor 的"搜索"项如何判定真实能力没说（只看配置值就会重演"谎报 ok"） | 已修正（§5.1.3 给探测语句） |
| P2-5 | 完备性 | P2 | `T-SEARCH-5` 用"逐字段快照比对"，但 `CourseListItem` 本轮新增 `highlights` → 快照必然过期 | 已修正（只比对 id 集合 + 顺序键） |
| P2-6 | 规模匹配 | P2 | e2e-real 的日志与 `var/e2e/` 目录无上限、无轮转 | 已修正（保留最近 5 轮 + 单文件 5MB 截断） |
| P2-7 | 一致性 | P2 | §9 S4 说 search-parity "先按 scan 断言"，§7.2 的 T-E2E-R4 却已写死 fts 对照 | 已修正（标注两阶段） |
| P2-8 | 完备性 | P2 | `--rate-limit-first N` 与 httpx 重试的关系未说明，限流分支可能被自动重试掩盖 | 已修正（§3.2.2 明确 fake 端不做重试、客户端只对 5xx 重试） |
| P2-9 | 规模匹配 | P2 | 未说明"移动端命中区 ≥44"是否适用于桌面（若不适用，必须写清，否则实现者会去改桌面上 40 处 `size="sm"`） | 已修正（§3.3.1 只约束触屏视口） |
| P2-10 | 可行性 | P2 | 深拷贝课时会让 `steps`/`lessons` 行数翻倍，但未给"旧版本保留几代"的可操作上限 | **不修**：本轮只记录不自动删（R9 已写），加自动 prune 会引入删除用户数据的风险，与"零数据丢失"相冲突 |
| P2-11 | 一致性 | P2 | **评审自己引入的问题**：本文升到 v2 后，与"一直被称为 v2 的平台件"重名，而全文有 21 处 `v2` 指的是平台件——"凡与 v2 冲突之处以本文为准"直接变成自指矛盾 | 已修正（全文改称「平台件」并在文首声明称呼约定；夹具名 `tiny_v2`/`snapshot-v2` 不受影响） |

### C. P0 / P1 逐条说明（问题 → 证据 → 修法）

**P0-1 · `0003` 会删掉 FTS 触发器**
* 问题：§6.1 让 `0003_course_upgraded_from` 用 `batch_alter_table`。`env.py` 已全局 `render_as_batch=True`，而 SQLite 上的 batch 操作 = 建临时表 → 拷数据 → **DROP 原表** → 改名。DROP 原表会连带删掉 `0002` 建在 `course_versions` 上的 3 个触发器之一二。迁移"成功"，`alembic_version` 前进，`/healthz.ok` 为真，但 `course_search` 从此不再随 `course_versions` 更新——**用户搜不到刚生成的课**，而 3 条 Doctor 检查全绿。
* 证据：E1 + E2。
* 修法（三处，缺一不可）：① `0003` 的 **upgrade 走原生 `op.add_column`**（SQLite ≥ 3.2 支持 ADD COLUMN，不需要重建表），只有 **downgrade** 走 batch，且 downgrade 结束后**必须重建 4 个触发器**；② 触发器 DDL 收敛到单一常量 `services/search_ddl.py::TRIGGERS_SQL`，由 `0002`、`0003`、`reindex-search` **共用**（三份手抄的 DDL 迟早漂移）；③ `0002` 的 downgrade 用 `DROP TRIGGER IF EXISTS`（否则先回滚 `0003` 再回滚 `0002` 会撞 `no such trigger`）。新增 `T-SEARCH-9` 用 `sqlite_master` 断言"迁移往返后触发器恰好 4 个"。

**P0-2 · 老 SQLite 上迁移直接失败**
* 问题：§3.4.1 的 `sqlite_too_old` 回落只存在于**查询期**（`plan_search(sqlite_version)`），而 `0002` 的 DDL 无条件执行 `tokenize='trigram'`。SQLite < 3.34 抛 `no such tokenizer: trigram` → `alembic upgrade head` 失败 → `conftest` 在**导入期**跑迁移（`_alembic_upgrade()` 在模块级调用）→ **整仓 pytest 一条都跑不了**，`start.ps1` 的迁移步骤也会中止。文档承诺的是"降级 + 明示"（§2.3 硬约束 4），实现却会是"直接不可用"。
* 证据：E3（trigram 是可选的编译/版本能力）+ `conftest.py` L35–51（模块级 `_alembic_upgrade()`）。
* 修法：`0002` 先做**能力探测**（`sqlite_version_info >= (3,34)` 且用一个内存/临时表试建一次 trigram 表，`try/except`），不支持则**不建表、不建触发器**，把结论写成 `services/search.py::fts_capability()` 的返回值；`list_courses` 在表不存在时按 `sqlite_too_old` 回落 `scan`；Doctor 用它给出 `degraded`；`reindex-search` 在不支持时打印一行并 `exit 0`（幂等、不炸 CI）。新增 `T-SEARCH-10` 用 monkeypatch 伪造低版本，断言"迁移成功 + 查询回落 + Doctor degraded + reindex 不炸"。

**P0-3 · 不可信端点的返回值被当成可信数据**
* 问题：§3.2.1 只约束了"base 只能来自环境变量"（防 `POST {api_base: 169.254.169.254}`），但漏了**出站响应的内容**：`fetch_repo_meta` 把端点返回的 `html_url` 直接入库并在前端当链接渲染（`javascript:` 即存储型 XSS）；`download_tarball` 跟随重定向（httpx 默认），恶意/被投毒的端点可把请求转去内网；tarball 体积只看 `/repos` 返回的 `size` 字段（端点可说 1KB 实发 1GB）。
* 证据：`ingest/github.py` L125–145、L171；§3.2.1 自己的红线段。
* 修法：① `html_url` 仅接受 `http(s)` 且 host ∈ 端点白名单，否则**回退到配置的 web base 拼装**；`clone_url`/`archive_url`/`avatar_url` 一律不落库；② 重定向：保留 `follow_redirects`，但用 `httpx` 的 `response.history` 校验**每一跳**的 host ∈ 白名单，最多 3 跳，越界即 `REPO_NOT_FOUND`；③ 体积：同时校验 `Content-Length` 与解包后的累计字节，超 `REPOLEARN_MAX_REPO_MB` → `REPO_TOO_LARGE`；④ fake GitHub 增 `--evil-html-url`、`--oversize-tarball`、`--redirect-to <url>` 三个开关，新增 `T-GH-4..6` 断言"入库值被替换 / 越界重定向被拒 / 超限被拒"。

**P0-4 · `VALIDATION_FAILED` 不存在，且未知码会变成 500**
* 问题：§3.4.4 与 §5.1.1 两处要求"非法组合 → `VALIDATION_FAILED`"。`errors.py` 里没有这个码，且 `AppError("VALIDATION_FAILED")` 会**静默降级**为 `INTERNAL`（500、`retryable=True`）——用户把 `offset` 填成 999，得到的是"服务内部错误，可重试"，前端还会贴心地给一个重试按钮。这同时违反"契约唯一真源"与"不新增错误码"两条自我约束：§5.1.2 明确写"不新增错误码（19 个足够）"。
* 证据：E4。
* 修法（评审裁决，登记进 §10）：**新增第 20 个码** `VALIDATION_FAILED(422, retryable=false)`，`ERROR_CODE_COUNT` 从 19 → 20，前端 `errors.ts` 加映射，`test_models_and_errors.py` 的数量断言同步；并顺手修掉 `AppError` 的静默降级——未知码**在开发/测试环境直接抛 `AssertionError`**，生产环境仍降级为 `INTERNAL` 且记 `error_code_unknown` 日志。理由：与其借一个语义错误的码，不如让"码表是定稿"这件事有门禁保护；让未知码静默变成 500 的做法，本身就是本产品要消灭的那类缺陷。

**P1-1 · `keepPreviousData`（v4 选项）**
* 修法：改为 `placeholderData: keepPreviousData`（从 `@tanstack/react-query` 引入 `keepPreviousData`）；`useCourseSearch` 的 `staleTime: 0` 保留。

**P1-2 · CI 的 Node 版本**
* 修法：`kernel` / `web` / `e2e-offline` / `e2e-real` 四个 job 统一 `node-version: 22.x`（`--experimental-strip-types` 需要 ≥22.6），并在 `services/agent-kernel/package.json` 加 `"engines": {"node": ">=22.6"}`；`test_ci_and_docs.py` 增断言"workflow 里不出现 `node-version: 20`"。

**P1-3 · lockfile 与 pnpm 版本**
* 修法：CI 用 `pnpm/action-setup@v4`，显式 `version: 12.18.0`（与根 `packageManager` 一致），不依赖 runner 的 corepack 猜测；新增 devDependency 与 `pnpm-lock.yaml` 的更新必须**同一个提交**，否则 `--frozen-lockfile` 立即失败；`pnpm-lock.yaml` 进 §4.6 清单（生成物）；新增 `T-CI-5` 断言 lockfile 里出现 `@axe-core/playwright`。

**P1-4 · `.next` 目录冲突**
* 修法：`next.config.ts` 增 `distDir: process.env.REPOLEARN_NEXT_DIST_DIR ?? '.next'`；`e2e-real.mjs` 在启动 web 前设为 `.next-e2e`（**固定值**而非按 runId，避免磁盘堆积；但清理时先删），并在第 8 步只清理该目录、不碰 `.next`。这样 `start.ps1` 与 e2e-real 可以真的并存。

**P1-5 · `gates` 在真链路层没有意义**
* 修法：`core/config.py` 增 `REPOLEARN_RUN_DIR`（默认 `REPO_ROOT/.run`，`run_dir` 属性读它）；新增 `scripts/probe_gates.mjs`（Node 版三态探测，输出与 `check_env.ps1` **同一 JSON 形状**，并与它共用同一组探针常量；PowerShell 版继续服务 `start.ps1`）；`e2e-real.mjs` 第 5.5 步跑它并写入 `<runDir>/preflight.json`，把 `run_dir` 指到 `var/e2e/<runId>/run`；`book-and-degrade.spec.ts` 改为断言 **`g2`**（PDF/chromium）而非笼统的 `gates`，且**先断言 `g2 !== "unknown"`**——探测失效必须红，而不是让"降级分支"靠 `unknown` 蒙过去。

**P1-6 · 工具条锚点与清单缺口**
* 修法：D29 的修法补一条真实病因——Monaco 分支的锚点恒为面板左上角偏移，与选区无关；正确做法是在 `onDidChangeCursorSelection` 里用 `editor.getScrolledVisiblePosition({lineNumber, column})` + `editor.getDomNode().getBoundingClientRect()` 算出**相对视口的真实 rect** 再交给 `clampToolbarPosition`。并把 `code-pane.tsx` 补进 §4.6（工具条定位、视图钉定、44px 都落在它身上）。

**P1-7 · 44px 断言的适用范围**
* 修法：`T-TOUCH-4` 只对**我们自己的主要动作**（导航、播放器、选区工具条、表单提交、抽屉触发器）断言，选择器用 `[data-rl-tap]`（本轮给这些元素打标），且只取 `isVisible()` 的元素、只在 390×844 与 768×1024 两个视口跑；同时**排除** Monaco 子树。桌面不要求 44px（既有 `size="sm"` 是 ~28px），但 §3.3.1 增加一条下限："桌面可点元素不得 < 28px"。

**P1-8 · a11y 与第三方 DOM / 视图漂移**
* 修法：`AxeBuilder.exclude('.monaco-editor')`（并在 `a11y-baseline.json` 登记 `reason: "第三方编辑器内部控件，不可控"`）；`mobile/keyboard/a11y` 三条用例统一经 `?code=plain` 打开 deep-dive（`code-pane.tsx` 支持该深链，忽略 `?code` 的旧行为在 `≥xl` 保留），使"离线两侧行为一致"成为**可断言的前提**；再单列一条 `T-A11Y-4`：当 `?code=monaco` 且编辑器确实就绪时，只断言"工具条/大纲/播放器"范围的 axe，不把第三方 DOM 计入。

**P1-9 · 两个未定义的量**
* 修法：`total_files` 定义为"**旧镜像中被 `analysis` 收录的可分析文件数**，与 `Commit.file_count` 同源"；`carry_forward` 给出确定性算法（伪代码进 §3.5.3），并要求 `T-UPG-6` 断言与公式一致而不仅是"不为 0"。

**P1-10 · `dry_run` 的成本**
* 修法：加三道闸——① tarball 体积上限复用 `REPOLEARN_MAX_REPO_MB`/`REPO_TOO_LARGE`；② `UpgradePlan` 按 `(old_sha8, new_sha8, policy_version)` 缓存到 `var/objects/upgrade-plan/<old8>-<new8>.json`，命中时响应头 `X-Upgrade-Plan: cached`；③ 同步路径有 20s 预算，超时返回 `202` + `job_id`（`kind="upgrade-plan"`），UI 显示"正在检查更新…"而不是转圈到底。

**P1-11 · `T-DOC-1` 的容差 0**
* 修法：该测试只在 `api` job（`windows-latest`）计数，非 Windows 平台 `pytest.skip`（与既有 `test_scripts_and_seed.py` 同一策略）；README 的数字改为"本机/该 runner 实测值"，并要求同一次运行内比对，不跨平台比对。

### D. 修正落点索引（便于逐条复核）

| 条目 | 落在本文哪几处 |
|---|---|
| P0-1 | §3.4.2（触发器单一来源）· §6.1（迁移表）· §6.5（回滚顺序）· §7.4 `T-SEARCH-9` · §4.6 |
| P0-2 | §3.4.2（能力探测）· §3.4.3 · §5.1.3（Doctor）· §7.4 `T-SEARCH-10` |
| P0-3 | §3.2.1（出站校验/重定向/体积）· §3.2.2（三个开关）· §3.2.6（失败域）· §7.2 `T-GH-4..6` |
| P0-4 | §5.1.1 · §7.4 `T-CONTR-1` · §10（偏离登记）· §4.6（`errors.py`/`errors.ts`） |
| P1-1 | §3.4.4 |
| P1-2 | §3.2.4（Node 22）+ `T-CI-6` |
| P1-3 | §3.2.4（pnpm pin）· §4.6（lockfile）· `T-CI-5` |
| P1-4 | §3.2.3（第 6 步）· §3.2.6 · §4.6（`next.config.ts`） |
| P1-5 | §3.2.3（第 5.5 步）· §7.2 `T-E2E-R3` · §4.6（`probe_gates.mjs`/`config.py`） |
| P1-6 | §3.3.2（D29）· §4.6（`code-pane.tsx`） |
| P1-7 | §3.3.1（命中区）· §7.3 `T-TOUCH-4` |
| P1-8 | §3.3.3 · §7.3 `T-A11Y-1/4` |
| P1-9 | §3.5.1 · §3.5.3 |
| P1-10 | §3.5.2 |
| P1-11 | §7.2 `T-DOC-1` |

---

## 0. 阅读指南

| 读者 | 只读这些就够 | 为什么 |
|---|---|---|
| **评审者** | §评审记录（实证清单 + 逐条结论）、§2（现状核实与缺口）、§7（测试与验收）、§8（风险）、§10（不采纳与偏离） | 判断"这四条缺口是不是真的、修法会不会失败、验收是否可执行"，以及**上一轮评审的意见有没有真的改掉** |
| **实现工程师** | §3（技术设计）→ §4（文件清单）→ §5（接口）→ §6（数据模型）→ §9（顺序） | §3 给机制，§4 给落点，§5/§6 给契约，§9 给先后。**任何本文未定义的决策不要临场发明**，回评审节点补 |
| **维护者** | §3.2.6（失败域）、§3.3.1（断点契约）、§3.4.1（为什么 trigram）、§6.4（回滚与幂等） | 这几条决定了"改代码前能不能先想到它会怎么坏" |

**与前序文档的关系（必读）**

1. `docs/plans/repo-learn-platform/spec.md`（下称 **平台件**）定义的产品边界、三进程拓扑、26 表数据模型、19 个错误码、Gate 0 三态、降级矩阵**全部继续有效**，本文不重复、不推翻。
2. 本文只做四件事：**补外环门禁**（M7）、**补窄屏与无障碍**（M8）、**兑现搜索**（M9）、**补版本升级**（M10）。凡与平台件冲突之处，以本文为准并在 §10 登记。
3. 编号纪律（继承平台件评审结论第 3 条）：`T-*` 测试编号只允许追加，不允许改名或删除；本文新增编号从 `T-CI-1`、`T-A11Y-1`、`T-SEARCH-1`、`T-UPG-1` 起，**不要复用平台件的编号**。

---

## 1. 概述（Overview）

RepoLearn 在上一轮已经是一个**功能完整**的产品：粘贴一个 GitHub 仓库地址，得到一门"宏观架构 → 全局走读 → 深入源码"的三层带读课程，每一步讲解都能落回 `文件:行号`，学完能生成可在线读、可导 PDF 的课程书；三进程（web:3000 / api:8000 / kernel:8787）由 `start.ps1` / `stop.ps1` 一键开关；`/setup` 五步引导能配好四类 LLM 协议与豆包 TTS；课程生成跑在 9 节点 LangGraph 上，节点能力来自 `@aragon-agent/core`；197 条 pytest、37 条 kernel、62 条 vitest、14 条 playwright 全绿。这意味着**产品的主干不缺**，缺的是"主干为什么值得信"的证据链。

这一轮的判断依据来自四个**实测事实**，而不是主观遗憾。第一，仓库里**没有任何 CI**（`.github/` 不存在），所有门禁都只活在某台开发机的命令行里——包括契约漂移门禁、PowerShell 语法门禁、以及启动脚本"真的能起三个端口"这条最贵的验证。第二，平台件 的 §8.3 把 E2E 分成"离线层 + real-backend 冒烟"两层，离线层 14 条已交付，**第二层至今为空**：前端契约与后端行为之间那条最容易断的缝，只能靠人手工跑一次 `start.ps1` 来赌。第三，`REPOLEARN_SEARCH` 这个配置项接受 `fts` 并且 Doctor 面板"状态 ok、detail: fts"地把它显示给用户，但 `services/course_service.py::list_courses` 里只有 `LIKE` 扫描分支，**`fts` 是一个骗过所有人的开关**——这正是本项目在 平台件 里明确拒绝的"静默失效"形态。第四，前端 70 个 tsx 里只有 45 处断点类，深度源码页在 `<xl` 时把代码、执行面板、注释、提问全部纵向堆叠，选中代码后弹出的浮动工具条用 `fixed` + `left: Math.max(8, position.left)`、默认 `left: 320`，**在 390px 视口上直接出屏**；无障碍层面有 246 个 `aria-*` 属性与一个手写焦点陷阱，但没有任何自动化 axe/键盘门禁，任何一次重构都能无声退化。

所以本轮不追求"再做一个大功能"，而是把这四条缝补成**可被机器反复证明的规则**：让 CI 承担门禁（M7），让三进程链路被真实浏览器自动化跑通（M7），让搜索开关名副其实（M9），让窄屏、触屏、键盘、读屏四类用户路径进入门禁（M8），并顺手补上数据模型早就为之设计、但一直没实现的那条能力——仓库更新后只重讲被改动的课时，形成一个新版本而不是重画一门课（M10）。四条都做完，产品才配得上"顶级"这个词里的**确定性**：不是"它在我机器上能跑"，而是"它每提交一次都被证明能跑，且证不出问题时我们知道是哪一层没被覆盖"。

---

## 2. 现状核实与缺口

### 2.1 已核实事实（全部来自本仓库实读，不是推测）

| # | 事实 | 证据（文件 / 命令） |
|---|---|---|
| F1 | **没有 CI**：仓库根 `.github/` 不存在，只有 `.agentmesh/.env/.git/.gitattributes/.gitignore/.npmrc/.pytest_cache/.run/.venv` | `python -c "import os;print([n for n in os.listdir('.') if n.startswith('.')])"` |
| F2 | 所有门禁都是手工命令，散落在 README §5 的代码块里 | `README.md` L104–127 |
| F3 | 平台件 §8.3 的第二层（real-backend 冒烟）**未落地**，且已在 平台件 文末登记为有意偏差 | `docs/plans/repo-learn-platform/spec.md` L1580–1584 |
| F4 | 离线 E2E 只有一层配置，`webServer` 自起 `next dev`，不涉后端 | `apps/web/playwright.config.ts` L35–46 |
| F5 | `settings.search` 接受 `scan|fts`，但 `fts` 无任何实现；`list_courses` 只有 `LIKE` 分支 | `apps/api/repolearn/core/config.py` L73/L102–107；`services/course_service.py` L108–118/L429–430 |
| F6 | Doctor 面板把 `search` 当"ok"直接回显给用户 | `apps/api/repolearn/services/setup_service.py` L595–602 |
| F7 | GitHub 五个出站点全部写死常量 `API = "https://api.github.com"`（L25），`parse_repo_url` 只认 `github.com` / `www.github.com`（L76）；五个出站 URL 在 L125 / L148 / L171 / L198 / L211 | `apps/api/repolearn/ingest/github.py` |
| F8 | 前端 70 个 tsx 共 45 处断点类，深度源码双栏只在 `xl` 生效，窄屏纵向堆叠且代码区 `min-h-[480px]` | `apps/web/src/app/course/[courseId]/deep-dive/page.tsx` L137–148 |
| F9 | 选中代码工具条 `fixed` 定位、只有下界 clamp、默认 `left: 320`、无 `max-width` | `apps/web/src/components/ide/selection-toolbar.tsx` L34–40 |
| F10 | 无障碍基座已存在：`role="dialog"` + 焦点陷阱 + Esc 关闭 + 焦点归还；`Tabs` 已是 `role="tablist"` | `apps/web/src/components/ui/overlay.tsx` L40–88、L136–174 |
| F11 | 没有 axe / 键盘 / 多视口自动化门禁 | 没有任何 `e2e/*a11y*`、`e2e/*keyboard*`、`e2e/*mobile*` 文件 |
| F12 | `prefers-reduced-motion` 已实现（在 `tokens.css`），但**没有任何断言**，重构可直接删掉 | `apps/web/src/styles/tokens.css` L146–150 |
| F13 | 数据模型早为"跨 commit 版本"设计（`cache_key = sha256(repo, commit_sha, policy, language)`、`course_versions.commit_sha`），但只有 `POST /rebuild {from}`，会从某阶段**整门重跑** | `services/course_service.py` L48–55、L360–378 |
| F14 | `user_progress` 以 `(user_id, course_version_id)` 唯一，换版本即失联 | `apps/api/repolearn/models/user_progress.py` L14–17 |
| F15 | 本机 SQLite 3.49.1，FTS5 `trigram` 可用；`MATCH 'Ag'`（2 字符）**静默返回 0 行**，不报错 | 实测：`python -c "import sqlite3;..."`（见 §3.4.1） |
| F16 | 契约是生成物：`export-openapi` 出 `packages/contracts/openapi.json`，`pnpm contracts` 出 `schema.d.ts` / `types.ts`，`--check` 比对 | `apps/api/repolearn/cli.py` L453–476；`README.md` L119–121 |
| F17 | 夹具由 `scripts/gen_fixtures.py` 确定性生成（禁网络、禁 `time.time()`、二次运行字节一致） | `scripts/gen_fixtures.py` L1–9 |
| F18 | 测试清库逻辑遍历 `Base.metadata.sorted_tables`，**看不到 FTS5 虚拟表**（它不进 metadata） | `apps/api/tests/conftest.py` L67–81 |

### 2.2 由此推出的四个缺口

| 缺口 | 描述 | 用户的真实感受 | 归属里程碑 |
|---|---|---|---|
| **G1 门禁在本地** | 没有 CI；契约漂移、PowerShell 语法、脚本真跑、三层测试全靠人记得敲 | "上次是谁改了契约？"——没人知道，直到发布前才发现 | M7 |
| **G2 链路没被证明** | 三进程链路的自动化覆盖为零，BFF ↔ FastAPI ↔ 数据库 ↔ Job 队列的接缝只有手工验证 | 一次改 BFF 透传就可能让音频拖动/SSE 静默失效，而 14 条离线 E2E 全绿 | M7 |
| **G3 承诺没兑现** | `REPOLEARN_SEARCH=fts` 不生效且 Doctor 报 ok；窄屏工具条出屏；无障碍仅靠人工 | 配了开关没变化（且被系统告知"已生效"）；手机上一选中代码就找不到按钮 | M9 / M8 |
| **G4 版本能力缺口** | 仓库往前走了，用户只有"整门重跑"可选，且新版本会丢掉学习进度 | "我就想看它改的那两个文件" → 却要为 12 个课时重新付费、重新等 | M10 |

### 2.3 硬约束（继承 平台件，本轮不得违反）

1. **单一同源通路**：浏览器只与 Next 同源 `/api/*` 通信；API/Kernel 只绑 `127.0.0.1` 并要求 `X-Internal-Token`。本轮新增的任何端点、脚本、E2E 都不得绕开 BFF 直连 API（`scripts/e2e-real.mjs` 里的健康检查除外，那是运维通道）。
2. **零依赖拉起**：新增能力不得引入需要编译的原生依赖；FTS5 用 SQLite 内置（3.34+ 的 `trigram`），不引入 Meilisearch/ES。
3. **契约唯一真源**：任何响应字段变化必须先改 Python schema，再 `export-openapi` → `pnpm contracts`，再改前端；`packages/contracts` 与 `schema.d.ts` 是生成物，**禁止手改**。
4. **降级可见**：任何新增能力在依赖缺失时必须"降级 + 明示"，不得静默换路径（平台件 §2.4 Gate 0 的同一原则）。
5. **Windows 优先**：脚本必须能被 PowerShell 5.1 解析（`scripts/parse_check.ps1` 门禁）；新增 Node 脚本必须在 Windows/cmd 下可跑。
6. **不新增一次性的性能/视觉门禁**：帧率、LCP、PDF 视觉回归仍是本地基准（平台件 §8.4-C），本轮不进 CI。

---

## 3. 技术设计（Technical design）

### 3.1 总体：不改拓扑，长出一个"可验证的外环"

```
                ┌─────────────────── CI（M7，新增） ───────────────────┐
                │  api(pytest+ruff+契约) │ kernel │ web(tsc+vitest+build)│
                │  e2e-offline(14 → 22+) │ e2e-real(0 → 4)             │
                └───────────────┬───────────────────────┬──────────────┘
                                │                       │
   ┌─────────────┐   ┌──────────▼─────────┐   ┌─────────▼──────────┐
   │ fake_github │──▶│  apps/api (:8100)  │◀──│ apps/web (:3100)   │
   │  (:9911)    │   │  uvicorn+FastAPI    │   │ BFF + RSC          │
   └─────────────┘   │  runtime=template  │   └────────────────────┘
                     └──────────┬─────────┘
                                │ var/e2e/<runId>/{db,objects,logs}
                                ▼
                     playwright.real.config.ts（e2e-real/*.spec.ts）
```

三处新增、一处未动：

* **新增**可配置的 GitHub 接入点（§3.2.1）——它是"离线假 GitHub"能被产品代码接受的前提，同时把 GitHub Enterprise 支持捎带实现。
* **新增** fake-GitHub 进程与 real-backend 编排器（§3.2.2 / §3.2.3），把三进程链路变成一次 `node scripts/e2e-real.mjs` 即可复现的实验。
* **新增** CI 流水线（§3.2.4），把已有门禁 + 新门禁全部纳入"每提交必跑"。
* **未动**课程生成工作流（9 节点）、数据模型主干（26 表）、BFF 契约转发规则、`start.ps1`/`stop.ps1` 语义——本轮不碰它们，任何"顺手重写"都视为越界。

### 3.2 M7 · 交付门禁闭环

#### 3.2.1 GitHub 接入点可配置（兼得 GHE 支持）

**问题（F7）**：`ingest/github.py` 里 `API = "https://api.github.com"` 是模块常量，五个出站点（repo meta / commits / tarball / trees / contents raw）全部拼在它上面；`parse_repo_url` 的 host 白名单硬编码 `github.com`。后果有两个：① 无法指向任何自建端点，**离线 E2E 就永远只能绕过"导入"这条主入口**；② 企业自建 GHE 用户根本无法使用本产品，而"支持自定义协议/自定义端点"本来就是任务书点名要的取向。

**设计**：

```python
# apps/api/repolearn/core/config.py
github_api_base: str = "https://api.github.com"   # GHE: https://<host>/api/v3
github_web_base: str = "https://github.com"       # GHE: https://<host>

@field_validator("github_api_base", "github_web_base")
@classmethod
def _check_http_url(cls, v: str) -> str:
    v = (v or "").strip().rstrip("/")
    if not v.startswith(("http://", "https://")):
        raise ValueError("REPOLEARN_GITHUB_*_BASE 必须是 http(s) URL")
    return v

@property
def github_api(self) -> str: return self.github_api_base.rstrip("/")

@property
def github_web(self) -> str: return self.github_web_base.rstrip("/")
```

`ingest/github.py` 的改法（**逐点，不要遗漏**）：

| 位置（现行行号） | 现状 | 改为 |
|---|---|---|
| L25 模块常量 `API` | `API = "https://api.github.com"` | 删除常量；新增 `def _api() -> str: return settings.github_api`（保留函数形式，便于测试 monkeypatch） |
| L76 `parse_repo_url` | `parsed.netloc.lower() not in ("github.com", "www.github.com")` | 允许集合 = `{urlparse(settings.github_web).netloc.lower(), urlparse(settings.github_api).netloc.lower(), "github.com", "www.github.com"}`；`scheme` 由配置决定是否允许 `http`（默认只允许 `https`；**仅当** `settings.env == "test"` 或 web base 本身就是 `http://` 时放行 `http`，否则报 `REPO_NOT_FOUND` + hint"只接受 https，或在 .env 配置 github_web_base"） |
| L125 `fetch_repo_meta` | `f"{API}/repos/{ref.full_name}"` | `f"{_api()}/repos/{ref.full_name}"`；L139 的 `html_url` 兜底改为 `f"{settings.github_web}/{ref.full_name}"` |
| L148 `resolve_commit` | `f"{API}/repos/{...}/commits/{target}"` | `f"{_api()}/repos/{...}/commits/{target}"` |
| L171 `download_tarball` | `f"{API}/repos/{...}/tarball/{sha}"` | 同上 |
| L198 `list_tree` | `f"{API}/repos/{...}/git/trees/{sha}?recursive=1"` | 同上 |
| L211 `fetch_raw_file` | `f"{API}/repos/{...}/contents/{path}?ref={sha}"` | 同上 |
| `rate_limit_hint` | 只提 token | 追加 endpoint：`f"端点 {settings.github_api}；未配置 REPOLEARN_GITHUB_TOKEN 时限流 60 次/小时"` |

**安全红线（必须写进代码注释）**：`github_api_base` **只允许来自服务端环境变量**，任何请求体/查询参数都不得覆盖它。否则 `POST /v1/courses {repo_url, api_base: "http://169.254.169.254"}` 就是一个 SSRF 洞。因此本轮**不新增任何接收 base 的参数**，`CourseCreateRequest` 保持不变。

**安全红线 B（v2 补，评审 P0-3）：端点返回的内容同样不可信。** 允许用户把端点指向自建实例，等于允许一个**会返回任意 JSON 的服务器**参与产品链路。三条必须做的校验：

1. **出站字段白名单**——`fetch_repo_meta` 只从响应里取 `full_name/owner.login/name/description/stargazers_count/language/license.spdx_id/default_branch/size/private`，**其余字段一律丢弃**。`html_url` 单独处理：scheme 必须 ∈ `{http, https}` **且** host ∈ 端点白名单，否则**丢弃并从配置拼装** `f"{settings.github_web}/{ref.full_name}"`。理由：`html_url` 会被前端渲染成 `<a href>`，一个返回 `"javascript:alert(1)"` 的端点就是一条存储型 XSS（`clone_url`/`archive_url`/`avatar_url` 同理，本轮**不落库**）。
2. **重定向逐跳校验**——保留 `follow_redirects=True`（真实 GitHub 的 tarball 会 302 到 codeload），但用 `response.history` 检查**每一跳**的 host ∈ 白名单、跳数 ≤ 3；越界抛 `REPO_NOT_FOUND`，hint 写清"重定向到未配置的域"。
3. **体积双检**——`Content-Length`（有则必查）与解包时累计字节都不得超过 `REPOLEARN_MAX_REPO_MB`；超限 `REPO_TOO_LARGE`。不能只信 `/repos` 返回的 `size` 字段（端点可以声称 1KB 实际发 1GB）。

| 出站函数 | 从响应里读什么（白名单） | 额外校验 |
|---|---|---|
| `fetch_repo_meta` | 上列 10 个字段 | `html_url` scheme+host，失败即回退拼装 |
| `resolve_commit` | `sha`（必须 40 或 64 位十六进制）、`commit.author.date` | `sha` 用 `re.fullmatch(r"[0-9a-f]{40,64}", sha)`，否则 `PROVIDER_UNAVAILABLE` |
| `download_tarball` | 字节流 | 逐跳 host + `Content-Length` + 解包累计 |
| `list_tree` | `tree[].path` / `tree[].type` / `tree[].sha` | 路径过既有 `ingest` 路径守卫（`INGEST_BLOCKED_PATH`） |
| `fetch_raw_file` | 原文 | 单文件 > `REPOLEARN_MAX_FILE_KB` 时截断（与既有解析上限一致） |


**Doctor 面板**（`setup_service.py`）在"GitHub 凭据"之后追加：

```python
{"name": "GitHub 接入点", "status": "ok",
 "detail": f"{settings.github_api} · token={'是' if settings.github_token else '否'}",
 "hint": None if settings.github_api == "https://api.github.com" else "已指向自定义端点（GHE/镜像）"}
```

`.env.example` 追加两行（含注释与 GHE 示例），`README.md` §2 增加一句"企业自建 GHE：设置 `REPOLEARN_GITHUB_API_BASE=https://<host>/api/v3`"。

#### 3.2.2 离线假 GitHub（`scripts/fake_github.py`）

只用标准库（`http.server.ThreadingHTTPServer` + `json` + `tarfile`），**不新增依赖**。用途：给 real-backend E2E 提供"一个真实的 HTTP 服务"，让产品走完整导入链路，而不是在测试里打桩内部函数（打桩等于测了自己的桩）。

```
python scripts/fake_github.py --port 9911 --fixture tests/fixtures/github \
  --snapshot tests/fixtures/repos/tiny_v1 --owner microsoft --name autogen --sha <40 hex>
```

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/healthz` | `{"ok":true,"sha":...}`（编排器等待就绪用） |
| GET | `/repos/{o}/{r}` | 返回 `repo.json` 夹具，`full_name/owner.login/name/default_branch/html_url` 按参数注入 |
| GET | `/repos/{o}/{r}/commits/{ref}` | 返回 `commit_v1.json`（`sha` 固定为夹具 sha，`commit.author.date` 固定，`files` 列表来自快照清单） |
| GET | `/repos/{o}/{r}/tarball/{sha}` | **现造** `{owner}-{name}-{sha}/` 前缀的 `.tar.gz`（内容 = 快照目录），`Content-Length` 正确 |
| GET | `/repos/{o}/{r}/git/trees/{sha}?recursive=1` | 快照清单转 blob 列表（`list_tree` 用得到） |
| GET | `/repos/{o}/{r}/contents/{path}?ref={sha}` | 返回快照中该文件原文（`Accept: application/vnd.github.raw`） |
| — | 任一不匹配 | `404 {"message":"Not Found"}`（让 `_map_github_error` 走 `REPO_NOT_FOUND`） |

开关：`--rate-limit-first N`（前 N 次返回 403 + `"API rate limit exceeded"`，供 `RATE_LIMITED` 的可操作错误断言用，默认 0）；`--second-commit <sha> --snapshot-v2 <dir>`（M10 增量升级 E2E 用：让 `/commits/main` 指向 v2，`/tarball/<v2sha>` 出 v2 快照）。

**对抗性开关（v2 补，评审 P0-3；只用于测试不可信端点的三类攻击面）**：

| 开关 | 行为 | 对应断言 |
|---|---|---|
| `--evil-html-url javascript:alert(1)` | `/repos/{o}/{r}` 的 `html_url` 返回该值 | `T-GH-4`：入库/对外返回的 `html_url` **必须**是配置 web base 拼装值，且不含 `javascript:` |
| `--redirect-to <url>` | `/tarball/<sha>` 302 到该地址 | `T-GH-5`：跨域重定向被拒（`REPO_NOT_FOUND`），同域 302 正常跟随（`--redirect-tarball` 走同域） |
| `--oversize-tarball` | 无视 `--snapshot`，直接流式吐 2× `REPOLEARN_MAX_REPO_MB` 的字节 | `T-GH-6`：`REPO_TOO_LARGE`，且错误信息里的实测体积与上限都可读 |

> **P2-8（评审）**：`--rate-limit-first` 只有在"客户端不自动重试 4xx"时才测得到限流分支。本轮明确：`ingest/github.py` 的 httpx 调用**只对 5xx/超时重试**（4xx 一律直接映射错误码），并在 `T-FGX-2` 里把这一点写成注释——否则将来给 429 加上重试，这条用例会变成"绿得没有意义"。


就绪信号：打印一行 `fake-github listening on http://127.0.0.1:<port> (sha=<sha>)` 到 stdout，编排器按此行 + `/healthz` 双条件判定（只认其中一条会在慢机器上假就绪）。

#### 3.2.3 real-backend E2E 编排（`scripts/e2e-real.mjs`）

**为什么是 Node 脚本而不是 PowerShell**：`start.ps1` 已经证明了 PowerShell 5.1 能起三进程，但它依赖 `.env` 与固定端口；E2E 需要**每次跑都隔离**（端口、DB、对象目录、日志）且**跑完必须清理**。Node 脚本在 Windows/cmd、Linux、CI 三处行为一致，且已有先例（`scripts/gen.mjs`、`scripts/probe_core.mjs`）。

**固定八步（每步失败即退出并清理，退出码非 0）**：

1. **参数与端口**：默认 `E2E_WEB_PORT=3100`、`E2E_API_PORT=8100`、`E2E_FAKE_GH_PORT=9911`；全部可用环境变量覆盖。`--keep` 保留目录，`--spec <file>` 只跑一条。
2. **端口占用探测**：用 `net.createServer().listen(port)` 逐个试探；**占用即失败**并提示 `.\stop.ps1`（不自动改端口——自动改端口会让"为什么 CI 跑的是 3101"变成新的谜）。
3. **隔离目录**：`var/e2e/<yyyyMMdd-HHmmss>/`，内含 `db.sqlite`（`REPOLEARN_DATABASE_URL`）、`langgraph.sqlite`、`objects/`、`logs/`、**`run/`**（v2 补，评审 P1-5：`REPOLEARN_RUN_DIR` 指到这里，让 `preflight.json` / `ports.json` 随 run 隔离，不去读写开发机上的 `.run/`）。**夹具只读**（评审 E10）：`seed-demo` 每次运行都会删掉 `microsoft/autogen (demo)` 下已有课程，因此本层不得修改或删除夹具课程，只允许读。
4. **环境变量集合（显式 11 个，不继承开发机的 `.env` 业务值）**：
   `REPOLEARN_ENV=test`、`REPOLEARN_DATABASE_URL`、`REPOLEARN_CHECKPOINT_DB`、`REPOLEARN_OBJECT_ROOT`、`REPOLEARN_SECRET_KEY=<随机>`、`REPOLEARN_INTERNAL_TOKEN=<随机>`、`REPOLEARN_AGENT_RUNTIME=template`、`REPOLEARN_GITHUB_API_BASE=http://127.0.0.1:<fake>`、`REPOLEARN_GITHUB_WEB_BASE=http://127.0.0.1:<fake>`、`REPOLEARN_RUN_DIR=<runDir>/run`、`REPOLEARN_NEXT_DIST_DIR=.next-e2e`。
   > `runtime=template` 是关键：它让整条生成链路在**没有 LLM Key**的机器上可跑（平台件 D4 已把"模板降级不需要 profile"写进实现），因此这条 E2E 在任何 CI/任何新克隆上都能跑，而不会因为没 Key 变成 always-skip。
5. **准备数据**：`python -m repolearn.cli migrate` → `python -m repolearn.cli seed-demo`（幂等，平台件 D15）。
5.5 **写本轮的 Gate 0 结论**（v2 补，评审 P1-5）：`node scripts/probe_gates.mjs --out <runDir>/preflight.json`。必须由**本轮**写入而不是继承开发机的 `.run/preflight.json`：`gates` 是"这台机器上 chromium / tree-sitter / agent core 到底在不在"的事实，跨 run 复用等于用旧事实解释新行为，而 `book-and-degrade.spec.ts` 正是拿它当参照物。探测必须是 Node 而不是 PowerShell：CI 的 `e2e-real` 跑在 `ubuntu-latest`，没有 `pwsh` 之外可靠的 `powershell.exe`。
6. **起三进程**（顺序 fake-gh → api → web）：
   * fake：`python scripts/fake_github.py ...`
   * api：`.venv/Scripts/python.exe -m uvicorn repolearn.main:app --host 127.0.0.1 --port <api>`（Windows）／`python3`（POSIX），工作目录 `apps/api`，`PYTHONPATH=apps/api` 兜底（v2 D1）
   * web：`npx next dev --port <web>`，env 加 `NODE_ENV=development`（平台件 D14 的坑：机器全局 `NODE_ENV=production` 会让 edge middleware 直接 500）、`REPOLEARN_API_BASE=http://127.0.0.1:<api>`、`REPOLEARN_INTERNAL_TOKEN=<同值>`、`REPOLEARN_NEXT_DIST_DIR=<repo>/.next-e2e`（平台件 补，评审 P1-4：`next dev` 的构建目录必须与 `start.ps1` 的 `.next` 分开，否则两个 `next dev` 同写一份构建缓存会互相破坏；`next.config.ts` 增 `distDir: process.env.REPOLEARN_NEXT_DIST_DIR ?? '.next'`）
7. **等就绪**：api `/healthz.ok === true` 且 `kernel` 可为 false（本轮不依赖 Agent 内核）、fake `/healthz`、web `GET /` 返回 3xx/200。任一超时（api 90s / web 120s）→ 打印该进程最近 80 行日志后退出。
8. **跑用例**：`npx playwright test --config playwright.real.config.ts`，把 `E2E_WEB_URL`、`E2E_FAKE_GH_URL`、`E2E_API_URL` 传入；结束后 `taskkill /pid <pid> /T /F`（Windows）或 `process.kill(-pid)`（POSIX）收整棵子树，收集 `var/e2e/<runId>/logs/*` 与 `playwright-report/` 供 CI artifact，写 `var/e2e/last-run.json`（`{runId, ports, specs, passed, failed, durationMs}`）。

   **P2-6（评审）：磁盘与日志必须有上限**，否则 CI 上 `var/e2e/` 按天增长、artifact 动辄几百 MB。规则：① 每个进程日志写入前用 `>>` 追加但**每轮开跑时截断**；② 单文件超过 **5 MB** 时在第 5 MB 处写一行 `[truncated]` 后停止写入（`--keep` 也遵守）；③ 每次开跑先删掉**除最近 5 轮之外**的 `var/e2e/*` 目录；④ `--keep` 只影响"本轮目录是否删除"，不影响 ②③。

**`apps/web/playwright.real.config.ts`**：

```ts
export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,      // 共享一个 DB，串行
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,          // 真生成链路（template runtime）比离线层慢
  expect: { timeout: 30_000 },
  use: { baseURL: process.env.E2E_WEB_URL ?? 'http://127.0.0.1:3100',
         trace: 'retain-on-failure', screenshot: 'only-on-failure',
         locale: 'zh-CN', timezoneId: 'Asia/Shanghai' },
  projects: [{ name: 'chromium-real', use: { ...devices['Desktop Chrome'] } }],
  // 注意：不配置 webServer —— 三进程由 scripts/e2e-real.mjs 管，
  // 否则 Playwright 的 webServer 生命周期与我们的清理逻辑会打架。
});
```

**`apps/web/e2e-real/fixtures.ts`**（三条共用能力，都是为了"失败时能定位"）：

* `test.extend` 提供 `seededCourse`：直接调 `python -m repolearn.cli seed-demo` 已在编排阶段跑过，所以这里只读 `GET /api/courses` 拿 `microsoft/autogen (demo)` 那门课的 id（**不走 UI**，避免把"导入"与"读课"两条链路的失败混在一起）。
* `bypassSetup(context)`：`context.addCookies([{name:'rl_setup', value:'1', domain:'127.0.0.1', path:'/'}])`——首启守卫已有离线层用例（T-E2E-2）覆盖，真链路层不该被它拦。
* `waitForJob(page, jobId)`：轮询 `GET /api/jobs/{id}` 直到 `status ∈ {ready, partial, failed}`，失败时把 `warnings`/`error` 打进 `testInfo.attach`。

**四条用例（P0，缺一不可）**：

| 文件 | 覆盖 | 关键断言（必须"会失败"的断言，不是走过场） |
|---|---|---|
| `import-to-lesson.spec.ts` | 导入 → Job → 准备页 SSE → 工作台 → 首步播放 | ① 粘贴 `http://127.0.0.1:<fake>/microsoft/autogen` 后**必须** 202 并跳到准备页；② SSE 至少收到 3 个不同 `node` 的进度事件（证明 BFF 逐 chunk 透传，不是最后一坨）；③ 完成后 `/course/<id>/overview` 出现课时标题；④ 播放器时间轴 `steps ≥ 1` 且首步 `durationMs > 0` |
| `quiz-and-recap.spec.ts` | 答题 → 解释 + evidence → 重放幂等 → 完课页 | ① 选中答案后出现解释与"证据"链接，点进后跳到工作台且 `?file=`/`?line=` 生效；② 同题二次提交返回 `replayed=true` 且不重复计数（真后端幂等键）；③ 完课页展示 `percent` 与已学课时数一致 |
| `book-and-degrade.spec.ts` | 生成书籍 → 阅读器 → PDF 入口 | ① `POST /api/books` → Job → 阅读器正文非空且章节数 ≥ 1；② **PDF 按钮状态必须与 `/healthz.gates` 的 `g2` 一致**（评审 P1-5：PDF 的门是 **`g2`**（chromium），G1=agent core / G3=tree-sitter 与 PDF 无关；并且**先断言 `g2 !== "unknown"`**——读到 `unknown` 直接判失败，否则这条断言会靠"什么都不知道"蒙过去）：有 Chromium → 可下载且 `content-type: application/pdf`；无 → 页面显示"打印视图"入口且不出现假可点的下载按钮。（禁止写成"有就断言下载、无就跳过"——那等于把 Gate 0 的降级可见性测成空转） |
| `search-parity.spec.ts` | 真后端搜索（与 M9 联动） | 同一关键词在 `mode=scan` 与 `mode=fts` 下 `items` 的 **id 集合相同**（允许顺序不同）；且响应 `mode` 字段与实际生效模式一致（证明"开关真的生效"）。**P2-7（评审）：这是终态断言**——S4 阶段只跑 `mode=scan` 的自身一致性（同一查询两次结果相同），`scan` vs `fts` 的 id 集合对照在 M9（S6）落地后补上，S8 起才是完整形态 |

#### 3.2.4 CI 流水线（`.github/workflows/ci.yml`）

**六个 job，全部"可复现"**；性能/视觉基准留在本地（平台件 §8.4-C 继续有效）。

| job | runner | 步骤（顺序即依赖） | 超时 |
|---|---|---|---|
| `api` | `windows-latest`（**必须 Windows**：`test_scripts_and_seed.py` 要真的调 PowerShell 5.1 解析 `start.ps1`） | checkout → setup-python `[3.11, 3.12]` 矩阵 → 缓存 pip → `pip install -e ".[dev,analysis]"` → `python -m ruff check .` → `python -m pytest -q` → `python -m repolearn.cli export-openapi --check` | 20 min |
| `kernel` | `ubuntu-latest` | setup-node **22**（`--experimental-strip-types` 需要 Node ≥ 22.6；20 会让 `npm test` 直接失败）→ `npm ci` → `npm test` → `npm run typecheck` | 10 min |
| `web` | `ubuntu-latest` | setup-node + pnpm（缓存 store）→ `pnpm install --frozen-lockfile` → `pnpm contracts:check` → `npx tsc --noEmit` → `npx vitest run` → `npx next build` | 15 min |
| `e2e-offline` | `ubuntu-latest` | node + pnpm → 缓存 `~/.cache/ms-playwright` → `npx playwright install --with-deps chromium` → `npx playwright test` → 失败时 `upload-artifact`（report/trace） | 15 min |
| `e2e-real` | `ubuntu-latest`，`needs: [api, web]` | python + node + pnpm → playwright chromium → `node scripts/e2e-real.mjs` → `upload-artifact var/e2e/**/logs` + `apps/web/playwright-report`（失败时） | 25 min |
| `gates` | `ubuntu-latest`，`needs: [api, kernel, web, e2e-offline, e2e-real]` | 只做一件事：全部成功则 `exit 0`；作为唯一 required status check（分支保护只需勾这一个，新增 job 不会漏配） | 1 min |

公共约定：`concurrency: {group: ci-${{ github.ref }}, cancel-in-progress: true}`；`permissions: contents: read`；所有 job `fail-fast: false`（矩阵里 3.11 挂了不该掩盖 3.12 的信号）。

**版本纪律（v2 补，评审 P1-2 / P1-3，任何一条不满足 CI 首跑就会红）**：

1. **Node 一律 22**：`kernel` / `web` / `e2e-offline` / `e2e-real` 四个 job 用 `node-version: 22.x`；`services/agent-kernel/package.json` 补 `"engines": { "node": ">=22.6" }`。`api` job 与 Node 无关，不设 `setup-node`。
2. **pnpm 版本必须显式 pin**：根 `package.json` 的 `packageManager` 是 `pnpm@12.18.0`，`pnpm-lock.yaml` 是 `lockfileVersion: '9.0'` 且带 `packageManagerDependencies`。CI 用 `pnpm/action-setup@v4` + `version: 12.18.0`，**不要**依赖 runner 的 corepack 自行猜测——猜测失败的表现是 `--frozen-lockfile` 报"lockfile 版本不兼容"，与代码无关，非常挫伤信任。
3. **lockfile 与 devDependency 必须同一次提交**：本轮要加 `@axe-core/playwright`，若只改 `package.json` 而不重新生成 `pnpm-lock.yaml`，`--frozen-lockfile` 立即失败。`pnpm-lock.yaml` 因此是 §4.6 里的一行**生成物**。
4. 这三个事实各配一条文本门禁：`T-CI-5`（lockfile 含 `@axe-core/playwright`）、`T-CI-6`（workflow 中不出现 `node-version: 20`，且出现 `version: 12.18.0`）。

**为什么 CI 不跑"起三进程 + 手工 curl"**：那是 e2e-real 的职责；同一条链路的两种验证方式会让"哪一条是真门禁"长期模糊，最后两条都松。

#### 3.2.5 关键序列（导入主链路，real-backend）

```
浏览器            apps/web(BFF)            apps/api                 fake_github       Job Runner
  │  POST /api/courses │                       │                        │                 │
  ├──────────────────▶ │ POST /v1/courses (X-Internal-Token, CSRF)      │                 │
  │                    ├──────────────────────▶│ parse_repo_url         │                 │
  │                    │                       ├──GET /repos/o/r───────▶│                 │
  │                    │                       ├──GET /commits/main────▶│                 │
  │                    │                       │ 建 course_version + job│                 │
  │                    │                       ├──enqueue───────────────────────────────▶│
  │  202 {job_id}      │◀──────────────────────┤                        │                 │
  │◀───────────────────┤                       │                        │                 │
  │  GET /api/sse/jobs/<id>                   │                        │                 │
  ├───────────────────▶├────GET /v1/jobs/<id>/events (stream)───────────▶│                 │
  │◀─ job.event ×N ────┤◀───── 逐 chunk（no-transform / X-Accel-Buffering: no）────────────┤
  │                    │                       │                        │  tarball ◀──────┤
  │                    │                       │                        │  N1..N9 模板链路 │
  │                    │                       │◀──发布 ready ───────────────────────────┤
  │◀── job.completed ──┤◀──────────────────────┤（服务端主动关流，平台件 D12）                │
  │  GET /course/<id>  │                       │                        │                 │
```

#### 3.2.6 失败域（新引入的三处，逐条给处置）

| 故障 | 行为 | 用户/开发者看到 |
|---|---|---|
| `github_api_base` 不可达（fake 没起） | `fetch_repo_meta` 抛 `PROVIDER_UNAVAILABLE`，hint 带端点地址 | 首页红色 toast "GitHub 端点不可达：http://127.0.0.1:9911"；E2E 第 7 步就超时，不会跑到用例里变成莫名 500 |
| fake 起了但版本不匹配（sha 与快照不符） | `/commits/main` 返回的 sha 与 tarball 前缀不一致 → `extract_tarball` 解出的文件数为 0 → 发布校验 `ANCHOR_STALE` | Job 失败并 `warnings` 记 `EMPTY_MIRROR`；E2E 断言"失败信息里必须出现 EMPTY_MIRROR"而不是只看红色 |
| e2e-real 端口被占 | 第 2 步立即失败，退出码 2（与用例失败 1 区分） | CI 面板能一眼区分"环境没清干净"与"产品坏了" |
| 机器无 Python 虚拟环境 | 编排器检查 `.venv/Scripts/python.exe` 存在，否则提示 `.\start.ps1 -SkipInstall` 建环境 | 不静默回退到系统 python（那会污染开发机全局包） |
| 端点返回的重定向指向白名单外的 host | 拒绝该跳，抛 `REPO_NOT_FOUND`（hint 含"重定向到未配置的域"） | Job 失败且错误信息里能看到被拒的 host，不是一句"网络错误" |
| 端点声称的体积与实际不符（`--oversize-tarball`） | 解包累计字节超 `REPOLEARN_MAX_REPO_MB` → `REPO_TOO_LARGE` | 提示里同时给出实测体积与上限，用户知道该改哪个开关 |
| `gates` 读不到（`preflight.json` 缺失/损坏） | `gates` 全 `unknown`；`book-and-degrade` 因此在第一个断言就失败 | 失败信息指向"第 5.5 步没跑"，而不是让人怀疑 PDF 功能坏了 |
| `start.ps1` 与 e2e-real 同时跑 | 构建目录已隔离（`.next` vs `.next-e2e`），互不影响；但端口仍冲突时第 2 步即失败 | 提示 `.\stop.ps1`，而不是出现"页面白屏/500 随机漂移" |

### 3.3 M8 · 窄屏 / 触屏 / 无障碍

#### 3.3.1 断点契约（先把语义定死，再谈改哪些文件）

沿用 Tailwind 默认值（**不新造断点**，新造断点会让 45 处既有断点的语义漂移）：

| 断点 | 宽度 | 这个宽度下**必须成立**的布局规则 |
|---|---|---|
| base | < 640px | 单栏；大纲/Momo 只在 `Overlay` 里；播放器工具条两行；所有**主要动作**（导航、播放器、选区工具条、表单提交、抽屉触发器）命中区 ≥ 44×44（触屏）；正文与代码块不产生横向滚动（`scrollWidth ≤ clientWidth + 1`） |
| sm | ≥ 640px | 顶部层级徽标显示；播放器单行但音量隐藏 |
| md | ≥ 768px | 表格 → 卡片列表（设置/角色矩阵）；书籍阅读器仍单栏 |
| lg | ≥ 1024px | 大纲栏（248px）常驻；书籍阅读器左右双栏 |
| xl | ≥ 1280px | Momo 栏（280px）常驻；深度源码页"代码 + 执行"双栏 |

**唯一允许的"隐藏"形态**：功能在 `Overlay` 里有等价入口且该入口可键盘到达。凡是被 `hidden` 且没有等价入口的功能，视为缺陷。

**命中区契约（v2 补，评审 P1-7 / P2-9）——先把"谁必须 44px"钉死，否则实现者会去改桌面上 40 处 `size="sm"`**：

| 场景 | 要求 | 理由 |
|---|---|---|
| 触屏视口（390×844、768×1024）上的**主要动作** | `min-height ≥ 44`、`min-width ≥ 44` | 手指命中率；这是 M8 的真实收益点 |
| 桌面（≥1024）上的主要动作 | `≥ 28px`（现有 `size="sm"` 已满足，**不改**） | 鼠标精度足够；把桌面按钮全改成 44px 会让工具栏变成一堵墙 |
| 第三方 DOM（Monaco 的查找窗/折叠箭头等） | **不在门禁范围**，且 `T-TOUCH-4` 必须显式排除 | 我们控制不了它的尺寸；把它算进来等于让门禁在第一天就红 |
| 装饰性图标按钮（如 `收起工具条` 的 ✕） | 视觉可 16px，但**命中区**用 `::after` 扩到 44 | 视觉密度与可点性并不冲突 |

实现约定：主要动作元素加 `data-rl-tap`，`T-TOUCH-4` 只遍历 `[data-rl-tap]:visible`——这样"哪些元素进了门禁"是**显式登记**的，而不是靠一个 CSS 选择器碰运气。

#### 3.3.2 三个具体缺陷与修法（本轮 M8 的 P0）

**D29 · 选中代码工具条越界（F9）**

* 现象：`position = anchor ?? {top: 96, left: 320}`，`style={{left: Math.max(8, position.left)}}`；在 390×844 视口下，工具条宽约 300–340px，`left=320` 时右半截在视口外，三个动作按钮点不到。
* **评审修正（P1-6，v2）——真实病因比"选区靠右"更基础**：`code-pane.tsx` 的 Monaco 分支是 `onSelect={(next) => handleSelect(next, null)}`，`rect` 恒为 `null`，于是 `anchor` 恒为 `paneRect.top + 44 / paneRect.left + 24`——**工具条与选区位置完全无关**，在桌面上也永远贴在面板左上角（用户会以为它坏了）；只有 `paneRef` 为空的极端情况才落到 `{top:96, left:320}`。所以 D29 不只是"clamp 不够"，而是"锚点根本是错的"。移动端出屏只是这个错误在窄视口下的可见后果。
* 修法（**新增纯函数 + 渲染期测量 + 真实锚点**，三层都要）：

```ts
// apps/web/src/lib/ide/toolbar-position.ts  （纯函数，可单测）
export interface Rect { top: number; left: number }
export interface Size { width: number; height: number }
export interface Viewport { width: number; height: number }
export const TOOLBAR_MARGIN = 8;
export const TOOLBAR_GAP = 6;
/** 先水平 clamp，再决定放选区上方还是下方（下方不够就翻上去）。 */
export function clampToolbarPosition(anchor: Rect, size: Size, viewport: Viewport): Rect;
```

  渲染侧：`useLayoutEffect` 里读 `ref.current.getBoundingClientRect()` 拿真实尺寸 → `clampToolbarPosition` → `style`；外层加 `max-w-[calc(100vw-16px)] flex-wrap`，保证极端窄屏（320px）下按钮换行而不是溢出；`aria-label` 保留。

  **锚点修正（P1-6）**：`MonacoEditorPane` 的 `onSelect` 改为回传真实 rect——在 `onDidChangeCursorSelection` 里
  `const pos = editor.getScrolledVisiblePosition({ lineNumber: sel.startLineNumber, column: sel.startColumn })`，
  再与 `editor.getDomNode().getBoundingClientRect()` 相加得到**视口坐标**；`PlainCodeView` 继续用它已有的 `Range` rect。
  `SelectionToolbar` 内部仍用"测量 → clamp"做最后一道保险（尺寸只有渲染后才知道），
  但**不许**再用"面板左上角 + 固定偏移"当锚点：那是这个缺陷的成因，不是它的修法。
  对应文件：`components/ide/selection-toolbar.tsx`、`components/ide/monaco-editor-pane.tsx`、`components/ide/code-pane.tsx`（**§4.6 补入**）。

* 断言：`T-TOUCH-1`（390×844 下工具条 `boundingBox` 完全落在视口内，且三个按钮依次 `click()` 都成功）+ **同一条用例里的第二条断言**：工具条顶边在**选区底边下方 ≤ 120px**（证明它跟着选区走，而不是像现在这样贴着面板左上角——这是"修好了"与"看起来能点"的分界线）。

**D30 · 深度源码页在窄屏"只有代码没有讲解"（F8）**

* 现象：`<xl` 时 `grid` 退化为单列纵向堆叠，首屏被 `min-h-[480px]` 的代码区占满；`InlineAsk` 在页面最底部，用户选中代码后既看不到工具条（D29）也不知道可以问。
* 修法（新增 `components/ide/pane-switcher.tsx`，复用既有 `Tabs`）：

```
<xl：三段「代码 / 执行 / 提问」，默认「代码」，Tabs 固定在工作区顶部（sticky）
      · 切到「提问」时自动 focus 输入框；`?ask=1` 深链直接落到「提问」页
      · 代码页高度 min-h-[52vh] xl:min-h-[620px]
≥xl：维持现状双栏（代码 + 执行/注释/提问竖排）
```

  实现要点：切换只在 `<xl` 生效（用 `matchMedia('(min-width: 1280px)')` 的 `useSyncExternalStore` 版本，SSR 安全、不引入 `window` 在服务端崩溃）；`≥xl` 时**不得**多渲染一个 Tabs（会让 `getByRole('tab')` 命中歧义，直接破坏既有 `learning.spec.ts`）。

**D31 · 书籍阅读器与设置表格在窄屏溢出**

* `book-reader.tsx` / `chapter-nav.tsx`：`<lg` 时目录进 `Overlay variant="sheet"`（标题"目录"），正文单栏 `max-w-[min(92vw,68ch)]`；代码块与表格包 `overflow-x-auto` 且 `-webkit-overflow-scrolling: touch`。
* `settings-view.tsx` / `role-matrix.tsx`：`<md` 时宽表改为卡片列表（新增 `components/ui/table.tsx`：`responsive` 属性，`<md` 渲染 `definition list`，`≥md` 渲染 `<table>`）；卡片形态下每个字段必须有 `<dt>` 语义（读屏可读）。

#### 3.3.3 无障碍与动效门禁

* **新增 devDependency**：`@axe-core/playwright@^4.10`（只进 devDeps，不进产物 bundle）。
* `e2e/a11y.spec.ts`：对 6 条路由跑 `AxeBuilder.withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa'])`：`/`、`/setup`、`/settings`、`/course/<demo>/overview`、`/course/<demo>/deep-dive`、`/book/<demo>`（全部在**离线层**，用 `page.route` 夹具，零后端）。**评审 P1-8 修正**：`/course/<demo>/deep-dive` 的代码面板由 AMD loader 远端加载 Monaco，离线时 4.5s 后回落 `PlainCodeView`（见评审实证 E5）——**同一份断言会在两种 DOM 下得出不同结论**。因此本用例统一经 `?code=plain` 打开该路由（`code-pane.tsx` 支持该深链），把"离线层零网络"变成可断言的前提；同时 `AxeBuilder.exclude('.monaco-editor')`——第三方编辑器的内部控件（对比度、`aria-*`）不归我们修，把它算进 "serious = 0" 等于让门禁在构造上永远红，最后一定被人删掉。排除项在 `a11y-baseline.json` 里写 `reason: "第三方编辑器内部控件，不可控；已在 T-A11Y-4 单独覆盖我们自己的控件"`。断言：严重度 `serious|critical` 计数为 **0**；`moderate|minor` 允许存在但**必须**登记到 `e2e/a11y-baseline.json`（`{"rule":"color-contrast","selector":"...","reason":"..."}`），未登记的 moderate 也判失败——否则"基线"会变成垃圾桶。
* `e2e/keyboard.spec.ts`（键盘全链路，6 步）：① `Tab` 依次可达"导入框 → 开始生成"；② 工作台里 `Tab` 能进大纲、`Enter` 切换课时；③ `Escape` 关闭 sheet 后焦点**回到触发按钮**（`expect(trigger).toBeFocused()`）；④ 播放器 `Space` 播放/暂停、`J/K` 切步；⑤ 深度源码里 `Tab` 能进代码区且不与页面快捷键打架（**同样经 `?code=plain` 钉定**——Monaco 是否就绪取决于网络，焦点顺序在两种 DOM 下不同，把两态混进一条门禁等于随机红；现有 `SHORTCUTS` 说明承诺了这一点）；⑥ 全程无 `page.locator(':focus')` 落在 `body` 上（焦点丢失）。
* `e2e/mobile.spec.ts`：三个视口 `390×844`（iPhone 12）、`768×1024`（iPad 竖）、`1024×768`（笔记本）各跑一次"首页 → 课程 → 首步 → 深度源码 → 选中代码 → 提问"。断言：`document.documentElement.scrollWidth <= clientWidth + 1`（无横向滚动）、工具条在视口内（D29）、**主要动作命中区 ≥ 44（仅遍历 `[data-rl-tap]:visible`，见 §3.3.1 的命中区契约；评审 P1-7——遍历"所有 `button`/`a`"会把 Monaco 注入的 16px 控件和 `height=0` 的隐藏元素算进来，门禁第一天就红）**。深度源码用 `?code=plain` 打开，避免 Monaco 的两态漂移。
* **动效**：`apps/web/src/styles/tokens.test.ts` 静态断言 `tokens.css` 里 `@media (prefers-reduced-motion: reduce)` 块存在且包含 `animation-duration` / `transition-duration` 两条 `!important`（当前已满足，加断言防删）。**不做** Playwright 的计算样式断言——`0.01ms` 与浏览器取整在不同引擎上不一致，会变成噪声门禁。

### 3.4 M9 · 搜索真正生效（FTS5 trigram）

#### 3.4.1 为什么是 trigram，以及为什么"短查询必须回落"

实测（F15）：`sqlite3` 3.49.1，`CREATE VIRTUAL TABLE t USING fts5(title, tokenize='trigram')` 后，`MATCH '"Agent"'` 命中，`MATCH '"演示课"'` 命中（中文 3 字），而 `MATCH '"Ag"'` 与 2 字中文查询**返回 0 行且不报错**。

这三行实测决定了整个设计：

1. `unicode61` 分词器对中文只能按整段切，`MATCH '缓存'` 永远 0 行；`trigram` 是唯一"不引入外部扩展、又能做中文子串"的内置方案。
2. trigram 的匹配单位是 3 字符，**2 字查询是本产品最高频的中文查询形态**（"缓存""异步""入口"）。若直接把用户输入丢给 FTS，用户会得到"结果为空"——而库里有匹配的课程。这是比"慢"严重一个数量级的错误（静默错误答案 > 明确慢）。
3. 因此规则必须是**按查询长度分流**，并且分流结果要能在 Doctor 与响应里看见。

#### 3.4.2 索引与一致性

迁移 `0002_course_search_fts.py`（手写 DDL；**Alembic autogenerate 看不到虚拟表**，`env.py` 无需改）：

**P0-2 · 先探测能力，再决定建不建（评审修正，v2）**。`trigram` 是 FTS5 的可选能力：SQLite < 3.34 或编译期未带它时，`CREATE VIRTUAL TABLE ... tokenize='trigram'` 会抛 `no such tokenizer: trigram`。而 `conftest.py` 在**模块导入期**就跑 `alembic upgrade head`——一旦这里抛异常，**整仓 pytest 一条都跑不了**，`start.ps1` 的迁移步骤也会中止。这与 §2.3 硬约束 4「降级可见，不得静默换路径」的方向正好相反（不是静默降级，是直接爆炸）。因此迁移的第一步必须是探测，而不是 DDL：

```python
# 0002 的 upgrade() 开头
def _trigram_ok(conn) -> bool:
    if sqlite3.sqlite_version_info < (3, 34):
        return False
    try:
        conn.exec_driver_sql("CREATE VIRTUAL TABLE temp.__probe USING fts5(x, tokenize='trigram')")
        conn.exec_driver_sql("DROP TABLE temp.__probe")
        return True
    except Exception:          # noqa: BLE001 - 任何失败都等价于"不支持"
        return False
```

不支持时：**不建表、不建触发器、不抛异常**，只写一行 `log.warning("fts_unavailable", sqlite=sqlite3.sqlite_version)` 后 `return`；`alembic_version` 仍然前进（迁移是"已执行"的，只是能力不具备）。查询侧由 `services/search.py::fts_capability()`（同样以 `sqlite_master` 里有没有 `course_search` 为准，而不是只看版本号）判定，返回 `sqlite_too_old` 并回落 `scan`。这样"老机器上功能少一半"与"老机器上什么都起不来"是两件完全不同的事。


```sql
CREATE VIRTUAL TABLE course_search USING fts5(
    course_version_id UNINDEXED,
    title,
    summary,
    repo_full_name,
    tokenize = 'trigram'
);

-- 回填（迁移内一次性）
INSERT INTO course_search (course_version_id, title, summary, repo_full_name)
SELECT c.id, COALESCE(c.title,''), COALESCE(c.summary_md,''), r.full_name
FROM course_versions c JOIN repositories r ON r.id = c.repository_id;

-- 维护：三个触发器。FTS5 行不能用 UPDATE 改内容列，统一 delete + insert。
CREATE TRIGGER trg_course_search_ai AFTER INSERT ON course_versions BEGIN
  INSERT INTO course_search (course_version_id, title, summary, repo_full_name)
  SELECT NEW.id, COALESCE(NEW.title,''), COALESCE(NEW.summary_md,''),
         (SELECT full_name FROM repositories WHERE id = NEW.repository_id);
END;

CREATE TRIGGER trg_course_search_au AFTER UPDATE OF title, summary_md ON course_versions BEGIN
  DELETE FROM course_search WHERE course_version_id = NEW.id;
  INSERT INTO course_search (course_version_id, title, summary, repo_full_name)
  SELECT NEW.id, COALESCE(NEW.title,''), COALESCE(NEW.summary_md,''),
         (SELECT full_name FROM repositories WHERE id = NEW.repository_id);
END;

CREATE TRIGGER trg_course_search_ad AFTER DELETE ON course_versions BEGIN
  DELETE FROM course_search WHERE course_version_id = OLD.id;
END;

-- repository 改名（罕见但要覆盖）
CREATE TRIGGER trg_repo_search_au AFTER UPDATE OF full_name ON repositories BEGIN
  DELETE FROM course_search WHERE course_version_id IN
    (SELECT id FROM course_versions WHERE repository_id = NEW.id);
  INSERT INTO course_search (course_version_id, title, summary, repo_full_name)
  SELECT c.id, COALESCE(c.title,''), COALESCE(c.summary_md,''), NEW.full_name
  FROM course_versions c WHERE c.repository_id = NEW.id;
END;
```

**触发器 DDL 只有一份（评审 P0-1，v2）**：上面 4 个 `CREATE TRIGGER` 的**文本**必须放在 `apps/api/repolearn/services/search_ddl.py::TRIGGERS_SQL`（一个常量），由三处共用：`0002` 的 upgrade、`0003` 的 downgrade（见 §6.5）、`cli reindex-search`。理由不是洁癖——**SQLite 的 batch 重建会把触发器连同原表一起 DROP 掉**（评审实证 E2；而 `migrations/env.py` 已经全局 `render_as_batch=True`，实证 E1）。三份手抄的 DDL 会在"某次只改了一处"之后悄悄漂移，而漂移的表现正是本产品最不能接受的那种：迁移绿、健康检查绿、搜索悄悄不再更新。

`IF NOT EXISTS` / `DROP TRIGGER IF EXISTS` 是**必须**的：先回滚 `0003`、再回滚 `0002` 时，触发器可能已经被前者删掉；没有 `IF EXISTS` 的 `DROP TRIGGER` 会抛 `no such trigger`，让"降级"这条逃生通道本身不可用。

downgrade：`DROP TRIGGER IF EXISTS` ×4 → `DROP TABLE IF EXISTS course_search`（顺序不可反：先删表会让触发器指向不存在的表，之后任何 `course_versions` 写入都会报 `no such table: course_search`）。

**软删除语义**：`course_versions.deleted_at` 非空仍留在索引里，但查询侧一律 `JOIN course_versions ... WHERE deleted_at IS NULL`（与 scan 分支同一条 where 子树），**不**在触发器里删行——否则"恢复软删"要重建索引，还得为它写一条恢复触发器。

**回填/修复入口**：`python -m repolearn.cli reindex-search`（drop & rebuild，幂等），用于：迁移前的老库、触发器被误删、以及 CI 的一致性断言（`T-SEARCH-6`）。

**测试清库**（F18）：`apps/api/tests/conftest.py::clean_db` 追加 `DELETE FROM course_search`（在清业务表之后，`try/except` 容忍迁移未跑时表不存在），否则 FTS 行会跨用例泄漏，产生"单独跑绿、全量跑红"的经典幻觉。

#### 3.4.3 查询构造与排序

新增 `apps/api/repolearn/services/search.py`（**纯函数，不碰 IO**，这是能被单测咬住的关键）：

```python
MIN_TRIGRAM = 3

@dataclass(frozen=True)
class Segment:
    """高亮片段：`marked=True` 的片段由前端渲染成 `<mark>`（**不返回 HTML**）。"""
    text: str
    marked: bool

@dataclass(frozen=True)
class SearchPlan:
    mode: Literal["none", "scan", "fts"]
    tokens: tuple[str, ...]
    fts_expression: str | None      # '"缓存"' AND '"命中"'
    like_pattern: str | None        # '%缓存%'（已 lower）
    fallback_reason: str | None     # "query_too_short" / "sqlite_too_old" / None

def plan_search(raw: str | None, *, configured: str, sqlite_version: str) -> SearchPlan
def highlight_segments(text: str, tokens: Sequence[str], *, max_len: int = 120) -> list[Segment]
```

规则表（**这是契约，实现不得偏离；不得"优化"成别的**）：

| `q` | `REPOLEARN_SEARCH` | 生效模式 | 排序 | 分页 | `fallback_reason` |
|---|---|---|---|---|---|
| 空/纯空白 | 任意 | `none` | `created_at DESC, id DESC` | keyset 游标 | — |
| 1–2 字符 | `fts` | **`scan`（回落）** | `created_at DESC` | keyset 游标 | `query_too_short` |
| 1–2 字符 | `scan` | `scan` | 同上 | keyset 游标 | — |
| ≥3 字符 | `fts` | `fts` | `bm25(course_search) ASC, created_at DESC, id DESC` | **offset**（上限 200） | — |
| ≥3 字符 | `scan` | `scan` | `created_at DESC` | keyset 游标 | — |
| 任意 | `fts` 但 `sqlite_version < 3.34` | `scan` | — | keyset | `sqlite_too_old` |

`fts_expression` 构造（防注入 + 防语法错）：按空白切 token → 每个 token 用双引号包裹并把内部 `"` 双写 → `' AND '.join(...)`。这样 `NEAR(`, `*`, `-`, `:` 全部退化为字面量；**禁止**把用户输入直接拼进 `MATCH`（FTS5 的 `MATCH` 是表达式语言，`-` 是 NOT、`*` 是前缀）。

`fts` 分支的 SQL 形状（SQLAlchemy 2.0 风格，`course_search` 用 `text()` 拼，字段名常量不可拼接用户输入）：

```sql
SELECT c.id
FROM course_search s
JOIN course_versions c ON c.id = s.course_version_id
JOIN repositories r ON r.id = c.repository_id
WHERE course_search MATCH :expr
  AND c.deleted_at IS NULL
  [AND c.status = :status] [AND r.owner = :owner]
ORDER BY bm25(course_search), c.created_at DESC, c.id DESC
LIMIT :limit OFFSET :offset
```

**三条实测得到、必须照做的 SQL 细节（评审 E3，v2）**：

1. `MATCH` 与 `bm25()` 的**参数只能写表名** `course_search`，写别名（`s MATCH ...` / `bm25(s)`）会得到 `no such column: s`。所以 §3.4.3 的形状里 `WHERE course_search MATCH :expr` / `ORDER BY bm25(course_search)` 是**有意为之**，不是笔误；SQLAlchemy 侧用 `text()` 拼接时也不要为了"好看"改成别名。
2. `bm25()` 返回负数（越小越相关），升序即"最相关在前"；两个文档同分时才轮到 `created_at DESC, id DESC` 兜底——所以三重排序键不是凑数。
3. 2 字符查询在 trigram 下**返回 0 行且不报错**（这正是 G3 最难被发现的原因）：任何"把用户输入直接交给 MATCH"的实现都必须先过 `len(strip) >= MIN_TRIGRAM` 这道闸，且闸门结果要能回显（`mode` / `fallback_reason`）。

`offset` 上限 200（`limit ≤ 50` 时最多 4 页）：FTS 的 `bm25` 是浮点分数，做 keyset 游标需要在游标里编码浮点并在下一页做 `(bm25, created_at, id) < (...)`，索引一变游标即失效；对一个课程库而言，用户不会翻到第 5 页。**这个取舍要写进代码注释，否则下一个人会"顺手把 fts 也改成游标分页"并引入幽灵重复行。**

`highlight_segments`：服务端对命中文本做**安全切段**（`[{text, marked}]`），不返回 HTML。理由：返回 `<mark>` 字符串会诱导前端 `dangerouslySetInnerHTML`，而 `title`/`summary` 来自 LLM 生成内容，注入面是真实存在的（平台件 §3.12 已把"LLM 输出不可信"列为硬规则）。

#### 3.4.4 契约变化与前端

`CourseListResponse` 变为：

```jsonc
{
  "items": [
    {
      "id": "course_version_01J...",
      "title": "AutoGen 带读：Agent 如何对话",
      "summary": "…",
      "highlights": {                       // 新增；未搜索时为 null
        "title":  [{"text": "AutoGen 带读：", "marked": false}, {"text": "Agent", "marked": true}],
        "summary": null,
        "repo":   null
      },
      "…其余字段不变…"
    }
  ],
  "mode": "fts",            // 新增：none | scan | fts（实际生效模式，不是配置值）
  "fallback_reason": null,  // 新增："query_too_short" | "sqlite_too_old" | null
  "next_cursor": null,      // fts 模式恒为 null
  "next_offset": 20,        // 新增：fts 模式的下一页；其他模式为 null
  "total": null             // 新增：fts 模式给 COUNT(*)（小库可接受）；scan 为 null
}
```

`GET /v1/courses` 新增两个查询参数：`mode: "auto" | "scan" | "fts" = "auto"`（`auto` 跟随 `settings.search`；显式传值用于 `search-parity.spec.ts` 的对照实验）、`offset: int = Query(0, ge=0, le=200)`（仅 `mode` 生效为 `fts` 时允许非 0，其他模式传非 0 报 **`VALIDATION_FAILED`**）。

> **P0-4（评审修正）**：`VALIDATION_FAILED` 是 v1 凭空引用的码——`core/errors.py` 里只有 19 个码，而 `AppError` 遇到未知码会**静默降级成 `INTERNAL`（500，`retryable=True`）**（评审实证 E4）。也就是说用户把 `offset` 填成 999，会看到"服务内部错误，可重试"并得到一个重试按钮——一个确定性的参数错误被说成了可恢复的服务故障。修正：**新增第 20 个码** `VALIDATION_FAILED(422, retryable=false, hint="offset 范围是 0–200；只有 fts 模式支持分页，scan 模式请用 cursor")`，`ERROR_CODE_COUNT` 19 → 20，前端 `errors.ts` 同步；并顺手堵住降级：未知码在 `env in {"test","dev"}` 下直接抛 `AssertionError`，生产环境才降级为 `INTERNAL` 并记 `error_code_unknown`。这条偏离"19 个码是定稿"的决定登记在 §10。`q` 同时补 `Query(None, max_length=120)`（P2-2：§5.1.1 早就写了 ≤120，但 `routers/courses.py` 里没有任何约束）。

前端：

* `apps/web/src/components/home/course-search.tsx`（新）：受控输入 + `useDeferredValue` 300ms 防抖 + `/` 快捷键聚焦 + `aria-live="polite"` 播报"找到 N 门课"；`mode` 与 `fallback_reason` 在输入框下方以小字提示（"按创建时间列出（查询少于 3 个字，索引不适用）"）。
* 高亮渲染：`<mark>` 由 React 元素生成（`segments.map(s => s.marked ? <mark>…</mark> : s.text)`），**全仓禁止**为搜索引入 `dangerouslySetInnerHTML`。
* `hooks.ts` 新增 `useCourseSearch(q, mode)`（`useQuery`，`staleTime: 0`，**`placeholderData: keepPreviousData`** 避免输入时列表闪烁）。**评审 P1-1**：v1 写的是 `keepPreviousData: true`，那是 TanStack Query **v4** 的选项；本项目是 v5（`hooks.ts` 用对象式 `useQuery({...})`，`@tanstack/react-query ^5.62.7`，评审实证 E9），v5 里该选项**不存在**——写上去的后果是"TS 报错"或"悄悄被忽略、输入时列表闪成空态"，两种都不是我们想要的。正确写法是 `import { keepPreviousData } from '@tanstack/react-query'` 并传 `placeholderData: keepPreviousData`。

### 3.5 M10 · 仓库更新后的增量升级

#### 3.5.1 纯函数 `analysis/diff.py`

```python
Status = Literal["added", "modified", "removed"]

@dataclass(frozen=True)
class FileDelta:
    path: str
    status: Status
    old_sha: str | None
    new_sha: str | None

def diff_snapshots(old_root: Path, new_root: Path) -> list[FileDelta]
# 按录制清单（mirror index）比对 path + sha256，不用 git：我们手里只有两份镜像，
# 且不执行任何用户代码/命令（产品边界），因此内容哈希是唯一可靠依据。

@dataclass(frozen=True)
class LessonRef:
    key: str
    files: tuple[str, ...]     # anchors ∪ steps.focus_file ∪ code_notes.file ∪ playback_meta.files

@dataclass(frozen=True)
class UpgradePlan:
    mode: Literal["none", "partial", "full"]
    affected_keys: tuple[str, ...]
    reasons: tuple[str, ...]   # 机器可读 + 人类可读，直接进 UI
    stats: dict[str, int]      # {"files_added":..,"files_modified":..,"files_removed":..,"lessons_total":..}

def plan_upgrade(lessons: Sequence[LessonRef], deltas: Sequence[FileDelta], *,
                 total_files: int, old_mirror_ok: bool = True) -> UpgradePlan
```

判定顺序（**命中即返回，顺序不可调换**——顺序本身就是语义）：

1. `not old_mirror_ok` → `full`，`reasons=("old_mirror_missing",)`。旧镜像被 LRU 清掉时，我们无法判断"哪些没变"，只能全量。
2. `affected_keys` 为空 → `none`，`reasons=("no_changes",)`。**这里必须是 none 而不是 partial**：没有受影响课时却建一个新版本，等于凭空多一门课、多一次发布、多一份数据；用户点"检查更新"会得到"新版本"，而版本内容与旧版逐字节相同。
3. `affected / total > 0.6` → `full`，`reasons=("curriculum_shift",)`。受影响的超过六成时，复制省下的工作量已小于合并成本，且大纲本身大概率要变。
4. `files_added ≥ max(3, ceil(total_files * 0.10))` → `full`，`reasons=("many_new_files",)`。新文件通常意味着新模块/新入口，N5（课程大纲）需要重排——只补课时会得到"大纲里没有的那一半代码"。
5. 否则 `partial`，`affected_keys` 为受影响课时 key 的升序元组。

`affected` 的判定是**保守**的：只看"课时引用的文件是否出现在 delta 里"，不做函数级 diff。函数级 diff 需要 tree-sitter 双版本符号树比对，收益（少重建 1–2 个课时）远小于风险（漏判导致讲解与代码不一致，而这是产品的核心承诺）。**明确不做**，写进 §10。

**`total_files` 的定义（评审 P1-9，v2）**：v1 在第 3、4 条里用了 `total_files` 却从未定义它，而"分母取镜像里的全部文件"与"只取被 analysis 收录的可分析文件"会让同一份 delta 得到不同的 `mode`——同一次升级在开发机上判 `partial`、在 CI 上判 `full`，而两边都"有测试"。定死为：**旧镜像中被 `analysis` 收录、并计入 `Commit.file_count` 的可分析文件数**，不含 `.md`/图片/二进制/被路径守卫跳过的文件。理由：`files_added` 的阈值问的是"新代码占比是否已经大到需要重排大纲"，被跳过的文件从来不进大纲，把它们算进分母只会让阈值失效。

#### 3.5.2 事务与执行

`services/upgrade_service.py::start_upgrade(session, course_id, *, ref=None, dry_run=False)`：

1. 读旧版本（`status ∈ {ready, partial}`，否则 `COURSE_NOT_READY`）。
2. `resolve_commit`（走 M7 的可配置端点）拿新 sha；若 `new_sha == old.commit_sha` → `{"mode": "none", "reasons": ["already_latest"]}`（200，不建 Job）。
3. 新 `cache_key` 已存在 → 200 `{"mode":"reused", "course_id": existing.id}`（内容级复用，平台件 幂等纪律）。
4. 下载新 tarball → 解包到新镜像（复用 N3）；`diff_snapshots(旧镜像, 新镜像)` → `plan_upgrade`。
5. `dry_run=True` → 直接返回 `UpgradePlan`（200，含受影响课时标题，供 UI 抽屉展示）；**不写库**。

   > **P1-10（评审修正，v2）：`dry_run` 不是免费的。** 走到这一步已经**下载并解包了整包 tarball**（第 4 步）——对一个 50 MB 的仓库，用户点一下"检查更新"就是一次 50 MB 下载 + 一次全量解包，而且"不写库"意味着**再点一次要再下一遍**。三条闸必须同时存在：
   > ① **体积**：`Content-Length` 与解包累计都受 `REPOLEARN_MAX_REPO_MB` 约束，超限 `REPO_TOO_LARGE`（不是"先下完再说"）。
   > ② **缓存**：`UpgradePlan` 按 `(old_sha8, new_sha8, policy_version)` 落盘 `var/objects/upgrade-plan/<old8>-<new8>.json`；命中时直接返回并带响应头 `X-Upgrade-Plan: cached`。用户连点两次不应该有第二次网络 IO。
   > ③ **预算**：同步路径的上限是 **20s**；超时改为 `202 {job_id}`（`kind="upgrade-plan"` 入既有队列表），UI 显示"正在检查更新…"并在 Job 完成事件里拿结果。对一个"点了按钮没反应"的界面，20 秒已经很长了；不设上限则大仓库上会出现"转圈直到浏览器超时"。
6. `mode == "none"` → 200；`mode == "full"` → 委托既有 `create_course` 语义建新版本（`upgraded_from_id` 指向旧版）；`mode == "partial"` → 建占位 `CourseVersion(status="generating", committed_sha=新, upgraded_from_id=旧, blueprint={"upgrade": {...}})` + 入队 `kind="upgrade"`。
7. 并发：`generation_locks` 锁**新 cache_key**；命中活跃 Job → `409 JOB_CONFLICT`（带 `job_id`）。旧版本**全程保持可读**（不置 `generating`），这是与 `/rebuild` 的关键区别。

`jobs/upgrade_jobs.py::run_upgrade_job(ctx)`：

```
N1 normalize → N2 resolve（已知新 sha）→ N3 fetch → N4 analyze（复用既有节点）
  ↓
copy_lessons(旧版本, 新版本, keep=不受影响集合)      # 深拷贝，见 §3.5.3
  ↓
N6 write_lessons(affected)  →  N7 simulate_trace(affected)  →  N8 synthesize_audio(affected)
  ↓
N9 publish（部分发布：已存在的课时不重写，见 §3.5.3）
  ↓
progress_service.carry_forward(旧, 新)
```

`jobs/handlers.py` 注册 `"upgrade": run_upgrade_job`（与 `"course"`/`"book"`/`"pdf"` 同一张表，**不要**新开队列）。

**失败语义**：任一受影响课时失败 → 版本置 `partial`，已复制/已生成的课时保留，`warnings` 追加 `{code:"UPGRADE_PARTIAL", lessons:[...]}`；旧版本不变。这与 平台件 的"预算超限保留已完成课时"是同一形态，用户可在完课页看到"继续生成"。

#### 3.5.3 深拷贝、部分发布、进度迁移

**`copy_lessons(session, src_version, dst_version, keep_keys)`**（放 `services/lesson_service.py`，因为它是"课程内容读写"的归属地）：

* 复制 `lessons`（新 id、`playback_meta.copied_from = 源 lesson id`）、`steps`（新 id，`order_index` 保留）、`simulated_traces`（按 `key` 复制，供 trace 面板继续可用）、`quiz_items`（新 id，`evidence` 原样）、`source_anchors`（新 id，行号指向旧 commit —— **必须**同时写入 `anchor_commit_sha`，让 UI 能标注"此锚点来自上一版"）。
* **不复制** `user_progress`（见下）、`quiz_attempts`（答题记录属于用户历史，跨版本合并会污染正确率统计）、`notes`（笔记绑定课时 id，跨版本合并会让"我当时的笔记"漂移到别的代码行）。

**`workflow/publish.py` 的部分发布**：现有实现按"整门课发布"校验锚点/段落连续性并在一个事务里写。新增 `publish_partial(new_version, existing_lesson_ids, regenerated)`：

* 质量门禁按**合并后**的课时集合计算（不能只看本次生成的 2 个课时——`min_lessons_to_publish=8` 会直接判失败）；
* 锚点存在性校验对"复制来的课时"用**旧 commit 的镜像**校验（镜像仍在 `var/objects/mirrors/<sha8>`），否则新镜像里找不到旧行号会全员 `ANCHOR_STALE`，这是最容易踩的一个坑；
* `quality_report.upgrade = {"from_sha":…, "to_sha":…, "mode":"partial", "affected":[…], "copied":N, "anchor_origin":"mixed"}`，前端据此显示"本版本 8/12 课时沿用上一版 @abc1234"。

**`progress_service.carry_forward(old, new)`**（F14）：

* 取旧版本该用户的 `user_progress`；若 `current_lesson_key` 在新版本里仍存在 → 原样复制（含 `current_step_index`、`percent`）；不存在 → `current_lesson_key = 最近的前一个仍存在的 key`（按旧版本的 `order_index` 往前找），并按**下面的公式**等比下调 `percent`，`current_step_index = 0`。

**`percent` 的确定算法（评审 P1-9，v2）**——v1 只说"等比下调"，那不是规格，是留给实现者的自由发挥。定死为：

```
old_lessons = 旧版本课时数, new_lessons = 新版本课时数
kept        = 旧版本中 key 仍存在于新版本的课时数
lesson_ratio = kept / old_lessons                  # 学过的内容里有多少还在
percent_new  = floor(old_percent * lesson_ratio)   # 只降不升
percent_new  = min(percent_new, floor(100 * kept / new_lessons))  # 且不得超过"已学课时占新版课时数"的上限
percent_new  = max(0, percent_new)
```

两条不变式必须写进 `carry_forward` 的文档字符串并各有断言：**① 只降不升**（否则用户会看到完成度突然跳回 90% 而自己什么都没做）；**② 不超过按新课时数重算的上限**（否则新版本课时变多时，用户会显示"已学完 8/12"却只点开过 3 个课时）。`T-UPG-6` 因此断言的是**公式结果**，不只是"不为 0"。
* 若双方都有记录：**新版本已有的记录优先**（用户可能已经在新版本里学了一会儿），只补空字段。

#### 3.5.4 与 `/rebuild` 的语义区分（必须写进 UI 文案与文档，否则两个按钮会被用混）

| | `POST /v1/courses/{id}/rebuild {from}` | `POST /v1/courses/{id}/upgrade {}` |
|---|---|---|
| 触发理由 | 生成质量不满意、策略版本变更 | 仓库有新的 commit |
| commit | **同一个** sha | **新的** sha |
| 影响范围 | 从某阶段起重跑本版本内容 | 只重讲被改动文件涉及的课时，其余复制 |
| 旧数据 | 被覆盖（同一版本内） | 旧版本**原样保留**，生成新版本 |
| 学习进度 | 不变（同一版本） | 迁移到新版本 |
| 成本 | 可能全门重跑 | 与受影响课时数成正比（UI 在 dry_run 里显示课时数） |

UI 入口：`components/shell/update-banner.tsx` 挂在 `course/[courseId]/layout.tsx` 顶部，按钮文案 **"检查更新"**（不是"重新生成"）；dry_run 结果以 `Overlay variant="bottom"` 展示受影响课时清单（可点跳转），主按钮"生成新版本（仅重讲 N 个课时）"。`partial` 时显示黄色提示条；`full` 时文案改为"大纲将重建，全部课时重新生成"，并要求二次确认。

---

## 4. 文件 / 模块变更计划（File / module change plan）

> 这是**唯一工作量清单**。每行一个文件，一行意图；"新"=新建，"改"=修改，"生成"=由命令产出（禁止手改）。
> 若实现时发现必须新增本表之外的文件，先在本文追加一行再写代码（平台件 纪律第 2 条）。

### 4.1 M7 · 交付门禁闭环（18 个文件）

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 1 | `apps/api/repolearn/core/config.py` | 改 | 新增 `github_api_base` / `github_web_base` + URL 校验 + `github_api()` / `github_web()` 派生属性 |
| 2 | `apps/api/repolearn/ingest/github.py` | 改 | 五个出站点改为读配置；`parse_repo_url` 接受配置 host；`html_url` 用配置 web base；hint 带端点 |
| 3 | `apps/api/repolearn/services/setup_service.py` | 改 | Doctor 增「GitHub 接入点」；搜索项改为**真实生效模式**（与 M9 联动，见 §3.4） |
| 4 | `.env.example` | 改 | 两个新键 + GHE 示例注释 |
| 5 | `scripts/fake_github.py` | 新 | 标准库假 GitHub（5 端点 + 现造 tarball + 限流开关），离线可测 |
| 6 | `scripts/e2e-real.mjs` | 新 | 三进程 + 隔离 DB/对象/日志 + 端口探测 + 清理 + 报告 |
| 7 | `apps/web/playwright.real.config.ts` | 新 | 真链路层配置（串行、120s、无 webServer） |
| 8 | `apps/web/e2e-real/fixtures.ts` | 新 | `seededCourse` / `bypassSetup` / `waitForJob` 三条共用能力 |
| 9 | `apps/web/e2e-real/import-to-lesson.spec.ts` | 新 | 导入 → SSE 进度 → 工作台 → 首步播放（T-E2E-R1） |
| 10 | `apps/web/e2e-real/quiz-and-recap.spec.ts` | 新 | 答题 → evidence 跳转 → 重放幂等 → 完课（T-E2E-R2） |
| 11 | `apps/web/e2e-real/book-and-degrade.spec.ts` | 新 | 书籍生成 + PDF 入口与 Gate 一致（T-E2E-R3） |
| 12 | `apps/web/e2e-real/search-parity.spec.ts` | 新 | 真后端 scan/fts 结果集一致（T-E2E-R4） |
| 13 | `.github/workflows/ci.yml` | 新 | 六个 job + 缓存 + 并发取消 + artifact + 唯一 required check |
| 14 | `scripts/gen_fixtures.py` | 改 | 新增 `repos/tiny_v1`、`repos/tiny_v2` 双版本快照 + `github/commit_v1.json`、`github/commit_v2.json` + 清单哈希（确定性，二次运行字节一致） |
| 15 | `apps/api/tests/test_github_endpoints.py` | 新 | 配置端点/`respx` 断言五个出站 URL 与错误映射（T-GH-1..3） |
| 16 | `apps/api/tests/test_fake_github.py` | 新 | 线程内起 `fake_github`，断言 5 条路由形状 + 限流开关（T-FGX-1/2） |
| 17 | `apps/api/tests/test_ci_and_docs.py` | 新 | CI 必备 job/步骤/artifact 的文本断言 + README 测试矩阵一致性（T-CI-1..4、T-DOC-1） |
| 18 | `apps/api/tests/conftest.py` | 改 | 追加 `REPOLEARN_GITHUB_API_BASE` / `REPOLEARN_GITHUB_WEB_BASE` 指向 `http://127.0.0.1:9911`（任何漏 mock 的出站调用当场连接失败，而不是悄悄打到真实 GitHub 把 CI 变成网络依赖）+ 在 `clean_db` 里清 `course_search`（§3.4.2）；`parse_repo_url` 允许集合仍含 `github.com`，故既有用例里的 `https://github.com/...` 不受影响 |

### 4.2 M8 · 窄屏 / 触屏 / 无障碍（18 个文件）

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 19 | `apps/web/src/lib/ide/toolbar-position.ts` | 新 | `clampToolbarPosition` 纯函数（水平 clamp + 上下翻转） |
| 20 | `apps/web/src/lib/ide/toolbar-position.test.ts` | 新 | 8 个边界用例（含 390×844、320×568、选区贴右/贴底） |
| 21 | `apps/web/src/components/ide/selection-toolbar.tsx` | 改 | 渲染期测量尺寸 + 用 clamp + `max-w-[calc(100vw-16px)] flex-wrap` + 44px 命中区 |
| 22 | `apps/web/src/components/ide/pane-switcher.tsx` | 新 | `<xl` 三段切换（代码/执行/提问），复用 `Tabs` |
| 23 | `apps/web/src/app/course/[courseId]/deep-dive/page.tsx` | 改 | `<xl` 走 pane-switcher，`≥xl` 保持双栏；代码区 `min-h-[52vh] xl:min-h-[620px]` |
| 24 | `apps/web/src/lib/ui/use-media-query.ts` | 新 | `useSyncExternalStore` 版 `matchMedia`（SSR 安全，先返回 `false`） |
| 25 | `apps/web/src/lib/ui/use-media-query.test.ts` | 新 | SSR 首帧不变形 / 订阅 / 解绑 三断言 |
| 26 | `apps/web/src/components/book/book-reader.tsx` | 改 | `<lg` 目录进 sheet、正文单栏、代码块横滚 |
| 27 | `apps/web/src/components/book/chapter-nav.tsx` | 改 | 抽出可复用导航体（栏内 + sheet 内共用） |
| 28 | `apps/web/src/components/ui/table.tsx` | 新 | `responsive` 表格：`<md` 卡片（`<dl>`）/ `≥md` `<table>` |
| 29 | `apps/web/src/components/settings/settings-view.tsx` | 改 | 表格改用 `table.tsx`，去掉横向溢出 |
| 30 | `apps/web/src/components/settings/role-matrix.tsx` | 改 | 角色矩阵窄屏转卡片 + 每项显式 `aria-label` |
| 31 | `apps/web/src/components/player/transport-bar.tsx` | 改 | 窄屏两行布局、按钮 44px、进度条独占一行 |
| 32 | `apps/web/src/styles/tokens.css` | 改 | 新增 `--tap-target: 44px`、`-webkit-tap-highlight-color`、安全区 `env(safe-area-inset-*)` |
| 33 | `apps/web/src/styles/tokens.test.ts` | 新 | 静态断言 reduced-motion 块与 tap-target token 存在（T-RM-1） |
| 34 | `apps/web/e2e/a11y.spec.ts` | 新 | 6 路由 axe 门禁（serious/critical = 0，moderate 需登记基线） |
| 35 | `apps/web/e2e/a11y-baseline.json` | 新 | 已知例外白名单（每条带 `reason`） |
| 36 | `apps/web/e2e/keyboard.spec.ts` | 新 | 键盘全链路 6 步（T-A11Y-2） |
| 37 | `apps/web/e2e/mobile.spec.ts` | 新 | 三视口无横向滚动 + 工具条在视口内 + 命中区 ≥44（T-TOUCH-1..4） |
| 38 | `apps/web/package.json` | 改 | 新增 devDep `@axe-core/playwright`、脚本 `e2e:real` |

### 4.3 M9 · 搜索真正生效（17 个文件）

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 39 | `apps/api/migrations/versions/0002_course_search_fts.py` | 新 | FTS5 trigram 表 + 4 触发器 + 回填 + 完整 downgrade |
| 40 | `apps/api/repolearn/services/search.py` | 新 | `plan_search` / `build_fts_expression` / `highlight_segments` 纯函数 |
| 41 | `apps/api/repolearn/services/course_service.py` | 改 | `list_courses` 接 `mode`/`offset`，按 `SearchPlan` 分流；fts 分支查询 |
| 42 | `apps/api/repolearn/schemas/course.py` | 改 | `CourseListResponse` 增 `mode`/`fallback_reason`/`next_offset`/`total`；`CourseListItem` 增 `highlights` |
| 43 | `apps/api/repolearn/routers/courses.py` | 改 | `mode`/`offset` 查询参数 + 非法组合 → `VALIDATION_FAILED` |
| 44 | `apps/api/repolearn/cli.py` | 改 | 新增 `reindex-search` 子命令（幂等 drop & rebuild） |
| 45 | `apps/api/tests/test_search.py` | 新 | T-SEARCH-1..7（含触发器一致性、注入、短查询回落、scan 回归） |
| 46 | `packages/contracts/openapi.json` | 生成 | `export-openapi` |
| 47 | `packages/contracts/src/types.ts` | 生成 | `pnpm contracts` |
| 48 | `apps/web/src/lib/api/schema.d.ts` | 生成 | 同上 |
| 49 | `apps/web/src/components/home/course-search.tsx` | 新 | 搜索框（`/` 快捷键、防抖、`aria-live`、模式提示、高亮片段） |
| 50 | `apps/web/src/app/page.tsx` | 改 | 首页挂载搜索（HeroImport 与 HotCourses 之间） |
| 51 | `apps/web/src/components/home/course-sections.tsx` | 改 | 接搜索态：结果/空态/回退提示，高亮用 React 元素 |
| 52 | `apps/web/src/lib/api/hooks.ts` | 改 | 新增 `useCourseSearch(q, mode)`（`keepPreviousData`） |
| 53 | `apps/web/e2e/search.spec.ts` | 新 | 离线层：输入命中/空态/`<3` 字提示/键盘 `/`（T-SEARCH-8） |
| 54 | `apps/api/repolearn/services/setup_service.py` | 改 | （与 #3 同一文件）Doctor 搜索项显示实际模式 + 回退原因 |
| 55 | `README.md` | 改 | 检索能力与"短查询回落"的用户可见说明（与 #74 合并执行） |

### 4.4 M10 · 增量升级（17 个文件）

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 56 | `apps/api/repolearn/analysis/diff.py` | 新 | `diff_snapshots` + `plan_upgrade` 纯函数（判定顺序即语义） |
| 57 | `apps/api/repolearn/services/upgrade_service.py` | 新 | `start_upgrade`（dry_run / 幂等 / 锁 / 三模式分流） |
| 58 | `apps/api/repolearn/jobs/upgrade_jobs.py` | 新 | `run_upgrade_job`（N1–N4 → 复制 → N6–N8 → 部分发布 → 进度迁移） |
| 59 | `apps/api/repolearn/jobs/handlers.py` | 改 | 注册 `kind="upgrade"` |
| 60 | `apps/api/repolearn/services/lesson_service.py` | 改 | `copy_lessons` 深拷贝（lessons/steps/traces/quiz/anchors） |
| 61 | `apps/api/repolearn/services/progress_service.py` | 改 | `carry_forward`（key 存活/等比下调/新版本优先） |
| 62 | `apps/api/repolearn/workflow/publish.py` | 改 | `publish_partial`：合并后门禁 + 旧镜像校验锚点 + `quality_report.upgrade` |
| 63 | `apps/api/repolearn/models/course_version.py` | 改 | 新增 `upgraded_from_id`（自引用 FK，`ON DELETE SET NULL`） |
| 64 | `apps/api/migrations/versions/0003_course_upgraded_from.py` | 新 | 加列 + 索引 + downgrade |
| 65 | `apps/api/repolearn/schemas/course.py` | 改 | `UpgradeRequest` / `UpgradePlanResponse` / `UpgradeStartedResponse`（与 #42 同文件） |
| 66 | `apps/api/repolearn/routers/courses.py` | 改 | `POST /v1/courses/{id}/upgrade`（与 #43 同文件） |
| 67 | `apps/api/tests/test_upgrade.py` | 新 | `plan_upgrade` 6 场景 + 幂等 + dry_run 不写库（T-UPG-1..3） |
| 68 | `apps/api/tests/test_upgrade_pipeline.py` | 新 | 双 commit 夹具端到端：只重建受影响课时、未受影响逐字节相同（T-UPG-4..6） |
| 69 | `apps/web/src/components/shell/update-banner.tsx` | 新 | "检查更新" → dry_run 抽屉 → "生成新版本（仅重讲 N 课时）" |
| 70 | `apps/web/src/app/course/[courseId]/layout.tsx` | 改 | 挂 `update-banner` |
| 71 | `apps/web/src/lib/api/hooks.ts` | 改 | `useUpgrade(courseId)`（与 #52 同文件） |
| 72 | `apps/web/e2e/upgrade.spec.ts` | 新 | 离线层：banner 三态（none/partial/full）与二次确认 |

### 4.5 文档收敛（3 个文件）

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 73 | `README.md` | 改 | 新增"CI 门禁 / 真链路 E2E / GHE / 搜索模式 / 增量升级"四节；测试矩阵改为实际数字（T-DOC-1） |
| 74 | `docs/runbook.md` | 改 | 新增排错条目：e2e-real 端口占用、假 GitHub 不通、fts 回落、升级后进度偏移 |
| 75 | `docs/architecture.md` | 改 | 新增 §9 搜索（trigram + 短查询回落）、§10 版本升级（复制/重建/进度迁移）、§11 CI 分层 |

### 4.6 评审补充（v2 新增，10 个文件）

> 这 10 个文件是 §评审记录 里 4 条 P0 与 11 条 P1 的**落点**，v1 的清单里没有它们，不补就会出现"方案写了、工具清单没有 → 实现时被当成可选项"。编号续 4.4 的 75。

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 76 | `apps/api/repolearn/services/search_ddl.py` | 新 | 虚拟表 + 4 个触发器的唯一 DDL 常量，`0002` / `0003` / `reindex-search` 三处共用（P0-1/P0-2） |
| 77 | `apps/api/repolearn/core/errors.py` | 改 | 新增第 20 个码 `VALIDATION_FAILED`；未知码在 `test`/`dev` 直接断言，不再静默变 500（P0-4） |
| 78 | `apps/web/src/lib/api/errors.ts` | 改 | 前端错误码 → 文案映射补 `VALIDATION_FAILED`（P0-4；漏掉会落到通用兜底文案） |
| 79 | `apps/api/tests/test_models_and_errors.py` | 改 | `ERROR_CODE_COUNT` 19 → 20 + 新码字段断言（P0-4） |
| 80 | `apps/web/src/components/ide/code-pane.tsx` | 改 | 工具条真实锚点、`?code=plain\|monaco` 深链钉定代码视图、主要动作打 `data-rl-tap`（P1-6/P1-7/P1-8） |
| 81 | `apps/web/src/components/ide/monaco-editor-pane.tsx` | 改 | `onSelect` 回传选区**真实视口 rect**（`getScrolledVisiblePosition` + `getDomNode().getBoundingClientRect()`）（P1-6） |
| 82 | `apps/web/next.config.ts` | 改 | `distDir: process.env.REPOLEARN_NEXT_DIST_DIR ?? '.next'`（P1-4） |
| 83 | `scripts/probe_gates.mjs` | 新 | Node 版 Gate 0 三态探测，输出与 `scripts/check_env.ps1` **同一 JSON 形状**，供 e2e-real 与 CI 使用（P1-5） |
| 84 | `services/agent-kernel/package.json` | 改 | `engines.node >= 22.6`（`--experimental-strip-types` 的真实下限）（P1-2） |
| 85 | `pnpm-lock.yaml` | 生成 | 新增 `@axe-core/playwright` 后重新生成，与 `package.json` 同一次提交（P1-3） |
| 86 | `scripts/count_workfiles.py` | 新 | 解析本文件 §4 的六张表，输出 `rows/unique/新建/修改/生成` 五个数；`T-DOC-2` 用它断言"文档数字 == 表格实际"（P2-1） |

同文件追加（不新增行）：`apps/api/repolearn/core/config.py`（#1）再补 `REPOLEARN_RUN_DIR` 覆盖；`.env.example`（#4）补该键的说明；`apps/api/tests/test_search.py`（#45）追加 `T-SEARCH-9/10`；`apps/api/tests/test_ci_and_docs.py`（#17）追加 `T-CI-5/6`。

### 4.7 交付前复审新增（9 个文件）

> 这 9 个文件是 `## 交付前复审记录` 里 P0-7 ~ P0-10、P1-17、P1-19 的落点。按 §4 自己的纪律（"实现了才发现必须动本表之外的文件，先追加一行再写代码"），此处补齐。

| # | 文件 | 类型 | 一行意图 |
|---|---|---|---|
| 87 | `apps/api/repolearn/main.py` | 改 | 注册 `RequestValidationError` → `VALIDATION_FAILED` 信封（不然 `offset=999` 仍是 422 + 没有 `error.code`，P0-7） |
| 88 | `apps/api/repolearn/rendering/pdf.py` | 改 | `chromium_available_async()`：sync playwright API 在事件循环里恒失败（R16 真病因，P0-10） |
| 89 | `apps/api/repolearn/services/book_service.py` | 改 | `create_pdf` 改用 async 判据（否则装了 Chromium 也永远降级成打印视图，P0-10） |
| 90 | `apps/api/repolearn/rendering/__init__.py` | 改 | 导出 `chromium_available_async`，避免下一个调用方又摸回 sync 版（P0-10） |
| 91 | `apps/api/tests/test_books_api.py` | 改 | 退化的替身改为 async 判据 + 新增"事件循环里同源"用例（P0-10 的回归钉） |
| 92 | `apps/web/src/components/book/book-view.tsx` | 改 | 把 `book/activeKey/onSelectChapter` 交给 `BookReader`（`<lg` 完全无法换章，P0-8） |
| 93 | `apps/web/src/components/shell/course-shell.tsx` | 改 | 抽屉触发器登记 `data-rl-tap` 并给触屏 44px 命中区（P1-17） |
| 94 | `apps/web/tsconfig.json` | 改 | include 增 `.next-e2e/types`；清掉实验残留 `.next-m8a` 与全局重排（P1-19） |
| 95 | `.gitignore` | 改 | 忽略 `.next-e2e/`（真链路独立构建目录，P1-19） |

**规模**：**95 行 / 90 个唯一文件**（5 处跨里程碑复用：`setup_service.py` #3/#54、`schemas/course.py` #42/#65、`routers/courses.py` #43/#66、`hooks.ts` #52/#71、`README.md` #55/#73）。按类型：**新建 39、修改 52、生成 4**（39+52+4 = 95；95 − 5 = 90 ✔）。

> 这组数字是**脚本算出来的**，不是手写的：`python scripts/count_workfiles.py docs/plans/repo-learn-hardening/spec.md` → `rows=86 unique=81 新=39 改=43 生成=4`。`T-DOC-2` 在日常门禁里跑同一条命令并比对本节数字，任何一次"加了文件忘了改数字"当场红（与 `T-DOC-1` 对 README 测试矩阵做的是同一件事）。

> **口径（P2-1 评审修正）**：v1 写"75 行、约 68 个唯一文件、新建 33 / 修改 32 / 生成 3"，但表内实际有 **5 处跨里程碑复用**（`setup_service.py` #3/#54、`schemas/course.py` #42/#65、`routers/courses.py` #43/#66、`hooks.ts` #52/#71、`README.md` #55/#73），因此 75 − 5 = 70 ≠ 68；而 33+32+3 = 68 又与行数不自洽。三处数字互相矛盾，读者无法判断"到底要动几个文件"。**v2 的处理不是改成另一个手写数字，而是给出唯一算法**：`pnpm files:count`（或等价的 `python scripts/count_workfiles.py docs/plans/repo-learn-hardening/spec.md`）解析本节六张表，输出 `rows / unique / 新建 / 修改 / 生成` 五个数并写回本节末行；`T-DOC-2` 断言"文档里的数字 == 脚本算出的数字"，与 `T-DOC-1`（README 数字）同一形态。这样下一次补文件时，数字要么自动同步，要么门禁红。

---

## 5. 接口设计（Interface design）

### 5.1 变更/新增 REST

#### 5.1.1 `GET /v1/courses`（变更）

```
GET /v1/courses?q=缓存&mode=auto&limit=20&offset=0&status=ready&owner=microsoft
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `q` | string(≤120) | — | 关键词；`len(strip) < 3` 时 fts 模式自动回落 scan |
| `mode` | `auto\|scan\|fts` | `auto` | `auto` 跟随 `REPOLEARN_SEARCH` |
| `limit` | int(1..50) | 20 | 沿用 `clamp_limit` |
| `offset` | int(0..200) | 0 | **仅 `mode` 生效为 `fts` 时允许非 0**；越界或与 `scan` 组合 → `VALIDATION_FAILED`（**422 + `retryable=false`**，hint 明确写"fts 用 offset，scan 用 cursor"；评审 P0-4：v1 引用的这个码当时并不存在，现已作为第 20 个码落地） |
| `cursor` | string | — | keyset 游标（scan 模式） |

响应（200）见 §3.4.4 的 JSON；新增字段全部有默认值，**老前端不受影响**（向后兼容）。

#### 5.1.2 `POST /v1/courses/{course_id}/upgrade`（新增）

```jsonc
// 请求（dry_run 默认 false）
{ "ref": "main", "dry_run": true }

// 200 dry_run / mode=none
{ "mode": "none", "reasons": ["no_changes"], "stats": {"files_modified": 0, "lessons_total": 12},
  "affected_lessons": [], "course_id": "course_version_...", "from_sha": "abc1234", "to_sha": "abc1234" }

// 200 dry_run / mode=partial
{ "mode": "partial", "reasons": ["5 files changed, 2 lessons affected"], "stats": {"files_modified": 5, "files_added": 0, "files_removed": 1, "lessons_total": 12},
  "affected_lessons": [{"key":"2.3","title":"send → receive 的一次往返"},{"key":"3.1","title":"generate_reply 的三种返回"}],
  "course_id": "course_version_...", "from_sha": "abc1234", "to_sha": "def5678" }

// 202 真正开始
{ "job_id": "job_...", "course_id": "course_version_new", "mode": "partial" }
```

错误：`COURSE_NOT_READY`（404/409）、`JOB_CONFLICT`（409，带 `job_id`）、`REPO_NOT_FOUND`、`RATE_LIMITED`、`PROVIDER_UNAVAILABLE`、`REPO_TOO_LARGE`。**不新增错误码**（19 个足够，扩码会让前端的 `errors.ts` 映射表与文档同时漂移）。

#### 5.1.3 Doctor（`GET /v1/setup/state` 内 `checks`）

新增一项（顺序在"GitHub 凭据"之后）：

```jsonc
{ "name": "GitHub 接入点", "status": "ok", "detail": "https://api.github.com · token=否", "hint": null }
```

搜索项改为真实能力（**这是 G3 的闭合点**）。**评审 P2-4：判定必须"看库"而不是"看配置"**——v1 的三态只看 `settings.search` 与版本号，而 `settings.search` 正是那个"说了 fts 却没人实现"的开关，照抄它就是把谎言换个地方说。判定顺序固定为：

```
table_ok = SELECT count(*) FROM sqlite_master WHERE type='table' AND name='course_search'
cap_ok   = (sqlite3.sqlite_version_info >= (3,34))      # 与迁移里的探测同一判据
effective = "fts" if (table_ok and cap_ok and settings.search == "fts") else "scan"
```

```jsonc
// REPOLEARN_SEARCH=fts 且 SQLite ≥ 3.34
{ "name": "搜索", "status": "ok", "detail": "fts（trigram，中文 ≥3 字）", "hint": "1–2 字查询自动回落 LIKE" }
// REPOLEARN_SEARCH=fts 但 SQLite < 3.34
{ "name": "搜索", "status": "degraded", "detail": "scan（SQLite 3.31 不支持 trigram）", "hint": "升级 Python/SQLite 后自动启用 fts" }
// REPOLEARN_SEARCH=scan
{ "name": "搜索", "status": "ok", "detail": "scan（LIKE，limit ≤ 50）", "hint": "课程量 > 5000 时设 REPOLEARN_SEARCH=fts" }
```

### 5.2 契约产物与生成命令（顺序不可颠倒）

```powershell
# 1) Python 侧改了 schema 之后
.\.venv\Scripts\python.exe -m repolearn.cli export-openapi

# 2) 再由 openapi.json 生成前端类型
pnpm contracts

# 3) 门禁（CI 与本地都必须绿）
.\.venv\Scripts\python.exe -m repolearn.cli export-openapi --check
pnpm contracts:check
```

### 5.3 CLI（新增两个子命令）

| 命令 | 参数 | 行为 |
|---|---|---|
| `python -m repolearn.cli reindex-search` | `--batch 500` | drop & rebuild `course_search` + **重建 4 个触发器**（DDL 来自 `search_ddl.py`，与迁移同一份）；打印 `indexed=N dropped=M triggers=4`；迁移后老库修复、触发器被 batch 重建误删时的后悔药、CI 一致性断言都用它。**评审 P0-2：不支持 trigram 的运行时打印 `fts unavailable (sqlite X.Y.Z), nothing to do` 并 `exit 0`**——一条维护命令在"能力本来就没有"的机器上变红，只会训练人忽略它 |
| `python -m repolearn.cli e2e-report` | `--json` | 读 `var/e2e/last-run.json` 打印最近一次真链路结果摘要（CI artifact 之外的人读入口） |

### 5.4 脚本接口

```
node scripts/e2e-real.mjs [--keep] [--spec <file>] [--web-port 3100] [--api-port 8100] [--fake-port 9911]
  退出码：0 全绿 / 1 有用例失败 / 2 环境不可用（端口占用、venv 缺失）

python scripts/fake_github.py --port 9911 --fixture tests/fixtures/github \
  --snapshot tests/fixtures/repos/tiny_v1 [--snapshot-v2 ... --second-commit <sha>] \
  [--owner microsoft --name autogen --sha <40hex>] [--rate-limit-first N]
  退出码：0 正常 / 3 参数非法（夹具缺失、sha 长度错）
```

---

## 6. 数据模型（Data model）

### 6.1 迁移清单

| 迁移 | 内容 | 可否 downgrade | 触及表 |
|---|---|---|---|
| `0002_course_search_fts` | **能力探测**（P0-2）→ FTS5 虚拟表 + 4 触发器 + 回填；不支持 trigram 时**什么也不建**并记一行 warning | 可（`DROP TRIGGER IF EXISTS` ×4 → `DROP TABLE IF EXISTS`，数据可由 `reindex-search` 重建） | 新增 `course_search` |
| `0003_course_upgraded_from` | `course_versions.upgraded_from_id` + 索引。**upgrade 用原生 `op.add_column`**（SQLite ≥3.2 支持，**不重建表**，因此不会碰到触发器）；**downgrade 只能用 `batch_alter_table`**（SQLite 的 `DROP COLUMN` 在 batch 里就是重建表），因此 downgrade 末尾**必须重放 `search_ddl.TRIGGERS_SQL`** | 可（删列；顺带重建触发器） | `course_versions` |

> **P0-1（评审）：这张表原来那句"`0003` 用 `batch_alter_table`"是整个方案里最危险的一行。** `migrations/env.py` 已全局 `render_as_batch=True`，而 SQLite 的 batch 语义是**重建表**——重建 = DROP 原表 + 改名，触发器不跟着走（评审实证 E1/E2）。后果不是"迁移失败"（那还好，至少你会知道），而是**迁移成功、健康检查全绿、搜索从此不再更新**：新生成的课程永远搜不到，改了标题的课程搜到的还是旧词，而 `/healthz.ok` 一直是 `true`。修法有两条，两条都要：**① 能不用 batch 就不用**（加列走原生 `add_column`）；**② 只要发生了一次重建，就以同一份 `TRIGGERS_SQL` 重放触发器**，并用 `T-SEARCH-9` 断言"迁移往返后触发器恰好 4 个"。

### 6.2 `course_search` 与触发器

DDL 全文见 §3.4.2。要点复核：

* 表**不进** `Base.metadata`（虚拟表无法被 SQLAlchemy 建模），因此：`clean_db` 要显式清理（§3.4.2）、`create_all` 不会误建、`alembic check` 不会报漂移。
* `course_version_id` 用 `UNINDEXED`（trigram 索引列只放真正要匹配的文本），它是回查 join 的键。
* 触发器的 `COALESCE(...,'')` 不是洁癖：`NULL` 进 FTS 行会让 `bm25` 出现 `NULL` 排序键，排序结果随机。

### 6.3 `course_versions.upgraded_from_id`

```python
upgraded_from_id: Mapped[str | None] = mapped_column(
    String(40),
    ForeignKey("course_versions.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
```

`ON DELETE SET NULL` 而不是 `RESTRICT`：旧版本被 `prune`/软删清理时，新版本不该跟着删，也不该阻止清理；链式追溯在 UI 只需一层（"基于 abc1234 升级"）。

### 6.4 JSON 形状契约（新增，全部向后兼容）

```jsonc
// course_versions.quality_report.upgrade（仅升级产生的版本有）
{
  "from_sha": "abc1234...", "to_sha": "def5678...",
  "mode": "partial",                    // partial | full
  "affected": ["2.3", "3.1"],           // 重讲的课时 key
  "copied": 10,                         // 复用的课时数
  "anchor_origin": "mixed"              // mixed | new（mixed 表示含上一版锚点）
}

// course_versions.blueprint.upgrade（生成期占位，发布成功后以 quality_report 为准）
{ "plan": "partial", "affected_keys": ["2.3"], "started_at": "2026-11-06T10:00:00Z" }

// lessons.playback_meta.copied_from（复制来的课时）
"copied_from": "lesson_01J..."          // 源课时 id，便于排错与"内容未变"断言
```

### 6.5 回滚与幂等

* 迁移回滚顺序：**先** `downgrade 0003`（删列）**再** `downgrade 0002`（删 FTS）——反序会让触发器在 FTS 表已删后仍被 `course_versions` 写入触发，报 `no such table: course_search`。
* **`0003` 的 downgrade 结束前必须重放触发器**（评审 P0-1）：它走 batch 重建，会静默丢掉 `0002` 建的 4 个触发器；不重放的话，`downgrade 0003` 之后、`downgrade 0002` 之前的那段窗口里搜索已经完全失效，而任何"降级检查一下"的人正好落在这个窗口里。重放后再 `downgrade 0002` 的 `DROP TRIGGER IF EXISTS` 才不会抛错。
* **`upgrade` 之后必须自检**：`0003` 的 upgrade 与 `reindex-search` 都以 `SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='course_versions'` 收尾，数量 ≠ 4 直接抛异常（宁可迁移红，也不要静默生效一半）。
* `reindex-search` 幂等：`DROP TABLE IF EXISTS` → 重建 → 全量回填，任一步失败整体回滚（单事务）。
* `start_upgrade` 幂等：`(repo, to_sha, policy, language)` → `cache_key` 唯一；同 sha 重复请求返回 `mode:"none"`（`already_latest`）或 `reused`（版本已存在），**永不产生第二个版本**。

---

## 7. 测试与验收标准（Testing & acceptance criteria）

### 7.1 分层策略（本轮把第二层补上）

| 层 | 载体 | 数量目标 | 依赖 |
|---|---|---|---|
| L1 单测 | pytest / vitest | pytest 197 → **≥ 233**（含评审新增的 T-GH-4..6 / T-CI-5/6 / T-DOC-1·2 / T-SEARCH-9·10 共 8 条）、vitest 62 → **≥ 72** | 无 |
| L2 API 集成 | pytest + `httpx.ASGITransport` | 含在 L1 总数里 | 临时 SQLite |
| L3 契约 | `export-openapi --check` + `contracts:check` | 2 条 | 无 |
| L4 **离线 E2E** | playwright（`e2e/`） | 14 → **≥ 23**（评审新增 T-A11Y-4） | 无网络、无后端 |
| L5 **真后端 E2E（新增）** | playwright（`e2e-real/`） | 0 → **4** | 三进程 + fake GitHub + 临时 DB |
| L6 脚本门禁 | pytest（`test_scripts_and_seed.py` + `test_ci_and_docs.py`） | 含在 L1 | PowerShell 5.1 |
| L7 内核 | `node --test` | 37（不变） | 无 |

### 7.2 M7 测试

| 编号 | 位置 | 断言 | 失败意味着 |
|---|---|---|---|
| `T-GH-1` | `test_github_endpoints.py::test_all_outbound_calls_use_configured_base` | monkeypatch `settings.github_api`，用 `respx` 记录：五个函数各命中一次、且 URL 前缀均为配置值 | 有站点写死了常量 |
| `T-GH-2` | `::test_parse_repo_url_accepts_configured_host` / `::test_png_rejects_unknown_host` | 配置 host 可解析；`https://evil.example/o/r` 仍 `REPO_NOT_FOUND` | 放宽成"任意 host 都行"（SSRF 前兆） |
| `T-GH-3` | `::test_rate_limit_error_mentions_endpoint` | `RATE_LIMITED` 的 `hint` 含配置端点 | 用户看不到"到底打的是哪个端点" |
| `T-GH-4` | `::test_evil_html_url_is_sanitised` | 端点返回 `html_url: "javascript:alert(1)"` 时，落库与对外返回的 `html_url` **必须**是配置 web base 拼装值（且以 `http` 开头） | 存储型 XSS（评审 P0-3） |
| `T-GH-5` | `::test_cross_host_redirect_rejected` | `--redirect-to http://169.254.169.254/` 时抛 `REPO_NOT_FOUND`；同域 `--redirect-tarball` 正常解包 | SSRF 经由 302（评审 P0-3） |
| `T-GH-6` | `::test_oversize_tarball_rejected` | `--oversize-tarball` 时在解包过程中抛 `REPO_TOO_LARGE`，且**未**把超限内容写进 `var/objects` | 只信 `/repos.size` 会被端点骗（评审 P0-3） |
| `T-FGX-1` | `test_fake_github.py::test_routes_shape` | 5 条路由的状态码 + JSON 关键字段；`/tarball/<sha>` 解压后文件数 = 快照文件数 | 假端点在 CI 与本地行为不同 |
| `T-FGX-2` | `::test_rate_limit_switch` | `--rate-limit-first 1` 时第一次 403 且 body 含 `rate limit` | 限流分支无法测 |
| `T-CI-1` | `test_ci_and_docs.py::test_ci_workflow_has_required_jobs` | 文本含 `api`/`kernel`/`web`/`e2e-offline`/`e2e-real`/`gates` 六个 job key | CI 少一个门禁（最容易被悄悄删掉的就是 e2e-real） |
| `T-CI-2` | `::test_ci_runs_all_gates` | 含 `export-openapi --check`、`contracts:check`、`tsc --noEmit`、`vitest run`、`playwright test`、`node scripts/e2e-real.mjs` | 门禁写了但没接进流水线 |
| `T-CI-3` | `::test_ci_uploads_artifacts_and_cancels` | 含 `actions/upload-artifact`、`concurrency`、`cancel-in-progress` | 失败时无 trace 可查 / 重复跑堆积 |
| `T-CI-4` | `::test_ci_required_gate_job` | `gates` job 的 `needs` 覆盖其余五个 | required check 漏配 → 幽灵绿灯 |
| `T-CI-5` | `::test_lockfile_has_new_devdep` | `pnpm-lock.yaml` 里出现 `@axe-core/playwright`，且 `apps/web/package.json` 的 devDependencies 与之一致 | 加了依赖没更新 lockfile → `--frozen-lockfile` 首跑即红（评审 P1-3） |
| `T-CI-6` | `::test_ci_node_and_pnpm_pinned` | workflow 里**不出现** `node-version: 20`，且出现 `version: 12.18.0`（pnpm）与 `node-version: 22` | kernel job 用 Node 20 必挂（评审 P1-2） |
| `T-E2E-R1..R4` | `e2e-real/*.spec.ts` | 见 §3.2.3 表 | 三进程链路断 |
| `T-DOC-1` | `::test_readme_test_matrix_matches_repo` | README 里的四个数字与 `pytest --collect-only -q` / kernel / vitest / playwright 的 `--list` 计数一致。**评审 P1-11：必须在同一次运行、同一平台上比对**——pytest 的收集数依赖平台（`test_scripts_and_seed.py` 在非 Windows 上 skip），跨平台"容差 0"是伪命题。因此本测试只在 `api` job（`windows-latest`）执行，非 Windows 直接 `pytest.skip`（与既有脚本门禁同一策略），并且 README 的数字注明"由本机实测填写" | 文档说谎（本项目最不能接受的一类） |
| `T-DOC-2` | `test_ci_and_docs.py::test_spec_workfile_matrix_is_consistent` | 跑 `scripts/count_workfiles.py` 得 `rows/unique/新/改/生成`，与 §4.6 末行"规模"里的五个数字**逐字相等** | 工作量清单的数字再次自相矛盾（评审 P2-1：v1 的 75/68/33/32/3 三个口径互相打架） |

### 7.3 M8 测试

| 编号 | 位置 | 断言 |
|---|---|---|
| `T-TOUCH-1` | `e2e/mobile.spec.ts::toolbar stays inside a 390x844 viewport` | 选中第 1–2 行后 `getByRole('toolbar')` 的 `boundingBox()` 四边均在 `[0, vw] × [0, vh]`；三个动作按钮依次 `click()` 成功；**且工具条顶边在选区底边下方 ≤ 120px**（评审 P1-6：只断言"在视口内"会放过当前这个"贴在面板左上角"的实现） |
| `T-TOUCH-2` | `::no horizontal scroll on any layer` | 5 条路由 × 3 视口：`documentElement.scrollWidth <= clientWidth + 1` |
| `T-TOUCH-3` | `::deep dive uses pane switcher below xl` | 390px 下出现「代码/执行/提问」三个 tab；点「提问」后 textarea 获得焦点；1024px 下**不出现**该 tablist |
| `T-TOUCH-4` | `::tap targets are at least 44px` | 390×844 与 768×1024 两个视口下，遍历 **`[data-rl-tap]:visible`** 的元素，`height ≥ 43.5` 且 `width ≥ 43.5`（留 0.5 子像素容差）。**评审 P1-7：范围必须收窄**——遍历"所有 `button`/`a`"会命中 Monaco 注入的 16–22px 控件与大量 `height=0` 的隐藏元素，门禁在第一天就红，随后必然被删；桌面视口不参与本断言（桌面下限是 28px，见 §3.3.1） |
| `T-A11Y-1` | `e2e/a11y.spec.ts` | 6 路由 axe `serious\|critical === 0`；未登记 moderate 也判失败。**评审 P1-8：deep-dive 一律经 `?code=plain` 打开，且 `exclude('.monaco-editor')`**（第三方编辑器内部控件不可控；排除项在 baseline 里带 `reason`）；断言前先校验"当前确实是 plain 视图"（`[data-code-view="plain"]` 存在），否则说明深链没生效、用例在测另一条路径 |
| `T-A11Y-2` | `e2e/keyboard.spec.ts` | 6 步键盘链路全通；`Escape` 后焦点回到触发元素；无焦点落 `body` |
| `T-A11Y-3` | `apps/web/src/lib/ide/toolbar-position.test.ts` | 8 个边界（含 `anchor.left` 超出视口、`size.width > viewport.width` 的极端值不返回负数） |
| `T-A11Y-4` | `e2e/a11y.spec.ts::monaco when available` | 当 `?code=monaco` 且编辑器**确实就绪**（`aria-busy="false"`）时，只对"工具条 / 大纲 / 播放器 / 提问面板"四个我们自己控制的子树跑 axe，`serious\|critical === 0`；Monaco 子树排除。编辑器 4.5s 内没就绪则本用例 `test.skip` 并打印原因——这是唯一允许的 skip，因为它测的是"我们有没有把可访问性做在**自己的**控件上"，而不是 Monaco 好不好 |
| `T-RM-1` | `apps/web/src/styles/tokens.test.ts` | `tokens.css` 含 `@media (prefers-reduced-motion: reduce)` 且含 `animation-duration`/`transition-duration` 两条 `!important`；含 `--tap-target: 44px` |

### 7.4 M9 测试

| 编号 | 断言 | 为什么需要它 |
|---|---|---|
| `T-SEARCH-1` | 迁移后 `course_search` 存在且行数 = `course_versions` 行数（含软删）；`reindex-search` 后复跑结果不变 | 回填漏行是"搜索结果少了"的最常见原因 |
| `T-SEARCH-2` | 3 门课（标题含"缓存"/"异步"/无关）插入后 `q=缓存&mode=fts` 命中 1 门，`bm25` 升序，`created_at` 并列稳定 | 中文子串可用性 |
| `T-SEARCH-3` | `q=缓存`（2 字）在 `mode=fts` 下 `mode=="scan"`、`fallback_reason=="query_too_short"`、且**命中数 > 0** | 防止 F15 的静默空结果 |
| `T-SEARCH-4` | `q='NEAR("a" "b")'`、`q='a*'`、`q='a -b'`、`q='"'` 均 200 且按字面量匹配（不 500、不语法错） | FTS `MATCH` 是表达式语言，直接拼接必爆 |
| `T-SEARCH-5` | `REPOLEARN_SEARCH=scan` 时同一查询返回的 `items` **id 序列**与旧实现一致（固定夹具 + 固定 `created_at`，只比 id 与顺序键）。**评审 P2-5：不要逐字段快照**——本轮 `CourseListItem` 新增 `highlights`，逐字段快照会在实现当天就过期，然后被人用"更新快照"糊过去，这条断言就永久失效了 | 回落路径不能"顺手改语义" |
| `T-SEARCH-6` | 触发器一致性：直接 `UPDATE course_versions SET title=...` 后搜索立刻命中新词、旧词不再命中；`reindex-search` 后仍一致 | 有触发器没被触发是最隐蔽的一类 |
| `T-SEARCH-7` | `UPDATE repositories SET full_name=...` 后按新 `full_name` 可搜到 | 覆盖第 4 个触发器 |
| `T-SEARCH-8` | 离线 E2E：输入 ≥3 字命中并高亮 `<mark>`；输入 2 字出现"已按时间列出（查询短于 3 字）"提示且**不空**；`/` 聚焦输入框 | 用户可见的行为闭环 |
| `T-SEARCH-9` | **触发器存活**（评审 P0-1）：`alembic upgrade head` 后 `SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='course_versions'` **恰好 4**；`downgrade 0003 → upgrade 0003` 往返后仍恰好 4；`reindex-search` 后仍恰好 4。再加一条行为断言：直接 `UPDATE course_versions SET title='新标题'` 后**立刻**能搜到"新标"，且搜不到被替换掉的旧词 | "迁移绿、搜索悄悄不再更新"是这套方案最可能出现的静默失效；只数表存在是查不出来的 |
| `T-SEARCH-10` | **能力缺失时的降级**（评审 P0-2）：monkeypatch 让探测返回"不支持 trigram" → `alembic upgrade head` **成功**、`course_search` 不存在、`GET /v1/courses?q=缓存&mode=fts` 返回 `mode="scan"` + `fallback_reason="sqlite_too_old"` 且 `items` 非空、Doctor 的搜索项为 `degraded`、`reindex-search` 退出码 0 | 老机器上"功能少一半"可以接受，"整仓 pytest 起不来"不可以 |
| `T-CONTR-1` | `mode`/`next_offset`/`highlights` 出现在 `openapi.json`，且 `contracts:check` 绿。**评审 P0-4 追加**：`VALIDATION_FAILED` 必须出现在 `openapi.json` 的 error 枚举与前端 `errors.ts` 的映射里，且 `GET /v1/courses?mode=scan&offset=5` 返回 **422 + code=VALIDATION_FAILED + retryable=false**（不是 500） | 契约漂移；以及"未知码静默变 500"这条逃生通道 |

### 7.5 M10 测试

| 编号 | 断言 |
|---|---|
| `T-UPG-1` | `plan_upgrade` 6 个场景：无变化→`none`；1 文件命中 2 课时→`partial`；受影响 70%→`full`；新增 4 文件→`full`；`old_mirror_ok=False`→`full`；空 delta→`none` |
| `T-UPG-2` | `diff_snapshots` 对 tiny_v1→tiny_v2 给出 1 modified + 1 added + 1 removed（确定性，与 `gen_fixtures.py` 二次运行字节一致） |
| `T-UPG-3` | `dry_run=True` 后数据库行数（`course_versions`/`jobs`）不变 |
| `T-UPG-4` | 真跑 `run_upgrade_job`（template runtime）：新版本 `lesson_count == 旧 + 0`；受影响课时 `title` 变化，未受影响课时的 `steps.segments` **逐字节相同**（`copied_from` 存在）；新版本 `status=="ready"`、`upgraded_from_id==旧版本 id` |
| `T-UPG-5` | 锚点来自旧 commit 的课时，`quality_report.upgrade.anchor_origin=="mixed"`，且发布不因 `ANCHOR_STALE` 失败 |
| `T-UPG-6` | 进度迁移：旧版本学到第 3 课时 → 新版本 `current_lesson_key` 存在则保留、`percent` **等于 §3.5.3 公式的计算值**（不是"不为 0"）；若该 key 被删除则落到最近存活 key，且同时满足两条不变式：`percent_new ≤ old_percent` 与 `percent_new ≤ floor(100*kept/new_lessons)` |
| `T-UPG-7` | 幂等：同 to_sha 连续调两次 → 第二次 200 `mode in {"none","reused"}`，`course_versions` 只多 1 行 |

### 7.6 全局门禁（本地一条命令，CI 六个 job 共用同一批命令）

```powershell
# 后端
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m repolearn.cli export-openapi --check
.\.venv\Scripts\python.exe -m repolearn.cli reindex-search --batch 500   # 幂等自检

# 前端
pnpm contracts:check
cd apps/web ; npx tsc --noEmit ; npx vitest run ; npx next build ; npx playwright test

# 内核
cd services/agent-kernel ; npm test ; npm run typecheck

# 真链路（新增，需要本机有 .venv 与 chromium；CI 用同一脚本）
node scripts/e2e-real.mjs

# 文档与清单自证（新增，评审 P2-1 / P1-11）
python scripts/count_workfiles.py docs/plans/repo-learn-hardening/spec.md   # 数字必须与 §4.6 末行一致
node scripts/probe_gates.mjs --print                                      # 三态结论；与 /healthz.gates 同源
```

### 7.7 验收矩阵（Definition of Done）

| # | 条件 | 判定方式（必须实跑） |
|---|---|---|
| A1 | T-GH-1..**6**、T-FGX-1/2 全绿（含不可信端点的三条攻击面：XSS / 跨域重定向 / 超限体积） | `pytest -q apps/api/tests/test_github_endpoints.py apps/api/tests/test_fake_github.py` |
| A2 | T-CI-1..**6**、T-DOC-1/**2** 全绿 | `pytest -q apps/api/tests/test_ci_and_docs.py` |
| A3 | T-E2E-R1..R4 全绿 | `node scripts/e2e-real.mjs`（退出码 0；`var/e2e/last-run.json` 显示 4 passed） |
| A4 | T-TOUCH-1..4、T-A11Y-1..**4**、T-RM-1 全绿 | `npx playwright test e2e/mobile.spec.ts e2e/a11y.spec.ts e2e/keyboard.spec.ts` + `npx vitest run` |
| A5 | T-SEARCH-1..**10**、T-CONTR-1 全绿 | `pytest -q apps/api/tests/test_search.py` + `pnpm contracts:check` |
| A6 | T-UPG-1..7 全绿 | `pytest -q apps/api/tests/test_upgrade.py apps/api/tests/test_upgrade_pipeline.py` |
| A7 | 既有 197 pytest / 37 kernel / 62 vitest / 14 playwright **一条不红** | 对应命令全跑 |
| A8 | `migrate` → `downgrade base` → `migrate` 三步在空库上可跑通，且 `downgrade` 顺序正确（§6.5） | `python -m repolearn.cli migrate ; ... --downgrade --target base ; migrate` |
| A9 | `.\start.ps1` / `.\stop.ps1` 行为不变（三端口 200、`/` → 307 `/setup`、停后可断） | 实跑一次并记录输出 |
| A10 | 文档四份（README / runbook / architecture / 本文件）与代码一致，README 数字与实测一致 | T-DOC-1 + 人工对照 |
| A11 | **迁移不会静默降级**：`upgrade head` → 触发器恰好 4 个 → `downgrade 0003` → 触发器仍恰好 4 个 → `downgrade 0002` → 表与触发器都没了且无报错 → `upgrade head` 复原 | `pytest -q apps/api/tests/test_search.py -k trigger`；再加 `python -m repolearn.cli reindex-search` 复跑一次 |
| A12 | **不可信端点不越权**：注入型 `html_url` 被清洗、跨域重定向被拒、超限 tarball 被拒且未落盘 | `pytest -q apps/api/tests/test_github_endpoints.py -k "evil or redirect or oversize"` |
| A13 | **真链路层不依赖开发机状态**：删除 `.run/preflight.json` 后跑 `node scripts/e2e-real.mjs`，`book-and-degrade` 仍能拿到非 `unknown` 的 `g2` | 手动删文件 + 实跑；`var/e2e/<runId>/run/preflight.json` 必须存在且 `gates.g2 != "unknown"` |

---

## 8. 风险与缓解（Risks & mitigations）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **Windows CI 上的 PowerShell 5.1 断言**在 `windows-latest` 上可能因 runner 默认 `pwsh` 而误判 | `test_scripts_and_seed.py` 假红，团队开始忽略门禁 | 测试里显式调 `powershell.exe`（不是 `pwsh`），并断言 `$PSVersionTable.PSVersion.Major -eq 5`；`ubuntu` 上 skip 该文件而不是让它红 |
| R2 | e2e-real 在 CI 上偶发超时（`next dev` 首次编译 + 首次 tarball 解包） | 门禁噪声 → 被 `continue-on-error` 掩盖 | 串行 + `retries: 1` + 120s 用例超时；日志用 `testInfo.attach` 落盘；**不允许** `continue-on-error` |
| R3 | 假 GitHub 与真实 GitHub 行为漂移（例如 302 到 codeload） | 真链路绿但真机导入失败 | `download_tarball` 已用 `follow_redirects`（httpx 默认）；假端点同时实现 `/tarball/<sha>` 直出与 `302` 两种模式（`--redirect-tarball`），用例各跑一次 |
| R4 | FTS trigram 索引体积膨胀（中文 trigram ≈ 原文 3 倍） | 2000 门课的 `title+summary` 索引可能到数百 MB | `summary` 只索引前 512 字符（迁移里 `substr`），并在 runbook 记体积基线；`reindex-search` 可随时重建 |
| R5 | 触发器维护成本（4 个触发器 + 2 张表的写入路径） | 漏一条 → 搜索结果与实际不符 | `T-SEARCH-6/7` + `reindex-search` 一致性断言；`reindex-search` 进 CI 的一次性自检 |
| R6 | `plan_upgrade` 的 60% / 10% 阈值是经验值 | 边界课程反复 `full`，成本超预期 | 阈值集中成模块常量并写进 `reasons`（用户可见）；先用 `dry_run` 展示，不静默扣成本 |
| R7 | 复制课时的锚点指向旧 commit | 深链跳到新 commit 的错误行号 | UI 标注"来自上一版"；`anchor_origin:"mixed"` 进质量报告；**注意：`publish_partial` 目前只校验本次重讲的课时，复制来的那些没有机检（复审 P0-6 收紧了门禁口径，但这条缺口保留，见 R18）** |
| R8 | 窄屏改造破坏既有离线 E2E（`getByRole('tab')` 歧义、焦点顺序变化） | A7 不达标 | pane-switcher 只在 `<xl` 渲染；既有 14 条用例先在 1280×720 视口下跑并有断言约束；改动后**先跑旧用例再跑新用例** |
| R9 | 深拷贝课时导致 `steps`/`lessons` 行数翻倍 | 库体积与查询变慢 | 只复制 `keep_keys`；旧版本超过 3 个时提示 `prune`（本轮只记录，不自动删） |
| R10 | 本文件与平台件的差异被忽略（读者只看平台件） | 实现走错口径 | 本文件 §0 明确"平台件继续有效 + 本文为准的四条"；`architecture.md` §9–§11 同步摘要；plan blackboard 指向本文件 |
| R11 | **Monaco 由 CDN 加载**（评审 E5）：离线时 4.5s 后回落纯文本视图，同一份用例在两种 DOM 下行为不同 | 新增的 a11y/mobile/keyboard 门禁"时红时绿"，最坏情况被改成 `continue-on-error` | 本轮先用 `?code=plain` 把门禁钉在一条路径上（§3.3.3），并把"把 `monaco-editor` 装成本地包、`loader.config({ monaco })`"登记为独立技术债；在那之前**不要**把 deep-dive 的两态差异写进任何无人值守门禁 |
| R12 | **`render_as_batch` 与触发器的组合**（评审 E1/E2）：任何一次对 `course_versions` 的 batch 重建都会删掉 FTS 触发器 | 迁移绿、健康检查绿、搜索悄悄不更新 | `0003` 的 upgrade 走原生 `add_column`；downgrade 后重放触发器；`T-SEARCH-9` 常驻；`reindex-search` 是后悔药。**下一次给 `course_versions` 加列/改类型时必须回看这条** |
| R13 | **`preflight.json` 的跨 run 复用**（评审 E6）：`run_dir` 原本固定在 `REPO_ROOT/.run`，e2e-real 会读到开发机的旧结论 | 真链路层"降级断言"用旧事实解释新行为 | `REPOLEARN_RUN_DIR` + 每轮 `probe_gates.mjs` 写入 + `T-E2E-R3` 先断言 `g2 != "unknown"`；A13 专门验证"删掉 `.run` 也能跑" |
| R14 | **FTS5 能力随运行时变化**（评审 P0-2）：开发者机器 3.49、CI 3.45、某台老机器 3.31 | 同一份代码在三处表现不同 | 迁移里探测 + 查询期 `fts_capability()` + Doctor 显示**实际生效模式**；`T-SEARCH-10` 把"缺失时如何降级"变成可执行的断言，而不是文档里的一句话 |
| R18 | **升级链路的锚点机检缺口**（复审新登记）：复制过来的课时只保留旧 `commit_sha`，没有按旧镜像复核行号 | 旧镜像被 LRU 清掉后，旧行号可能已经指向不同代码，而没有任何门禁会红 | 本轮**不修**：旧镜像缺失时校验只会失败得没有信息量；正确做法是在 `copy_lessons` 里对**仍然可见的**旧镜像做一次抽样校验并降级告警（独立一轮）。已把 `publish_partial` 的 docstring 改成如实描述，先消灭"注释说校验过、其实没有" |

---

## 9. 实施顺序（S1–S12，每步独立可验收）

| 步 | 内容 | 完成判据 |
|---|---|---|
| **S0** | **前置（v2 新增，约半天）**：新增第 20 个错误码 + `errors.ts` 映射 + `AppError` 未知码断言；`REPOLEARN_RUN_DIR` / `REPOLEARN_NEXT_DIST_DIR` 两个配置项；`scripts/probe_gates.mjs`；`next.config.ts` 的 `distDir`；`scripts/count_workfiles.py` | `pytest -q apps/api/tests/test_models_and_errors.py` 绿；`node scripts/probe_gates.mjs --print` 输出三态；`count_workfiles.py` 能算出 §4.6 末行的数字 | 评审 P0-4 / P1-4 / P1-5 / P2-1 的落点。**这些是"别人都依赖"的地基**，放到后面做会让每条里程碑都要改一遍 |
| **S1** | M7-A：可配置 GitHub 端点（config + ingest + .env.example + 测试）**+ 出站响应校验（html_url / 逐跳重定向 / 体积双检）** | T-GH-1..**6** 绿；既有 `test_analysis_providers_rendering` 等不红 |
| **S2** | M7-B：`gen_fixtures.py` 双版本夹具 + `fake_github.py` + 测试 | T-FGX-1/2 绿；`gen_fixtures.py` 二次运行字节一致 |
| **S3** | M7-C：`e2e-real.mjs` + `playwright.real.config.ts` + fixtures，先只跑 `import-to-lesson`（含 `REPOLEARN_RUN_DIR` / `REPOLEARN_NEXT_DIST_DIR` 隔离与第 5.5 步 gates 探测） | `node scripts/e2e-real.mjs --spec import-to-lesson` 退出码 0；`var/e2e/<runId>/run/preflight.json` 存在 |
| **S4** | M7-D：其余 3 条真链路用例（quiz/recap、book/degrade、search-parity） | T-E2E-R2..R4 绿（search-parity 先按 scan 断言，M9 完成后补 fts 对照） |
| **S5** | M7-E：`.github/workflows/ci.yml` + `test_ci_and_docs.py`（Node 22、pnpm `12.18.0` pin、lockfile 与 devDep 同提交） | T-CI-1..**6** 绿；CI 首跑六个 job 全绿 |
| **S6** | M9-A：迁移 0002（**先探测能力**）+ `search_ddl.py` + `search.py` + `course_service` 分流 + `test_search.py` | T-SEARCH-1..7、**9/10** 绿；`migrate`/`downgrade` 往返通过且触发器恰好 4 个 |
| **S7** | M9-B：契约再生 + 前端搜索组件 + 离线 E2E | T-CONTR-1、T-SEARCH-8 绿；`pnpm contracts:check` 绿 |
| **S8** | M9-C：Doctor 真实能力 + `reindex-search` CLI + search-parity 的 fts 分支 | Doctor 三态可复现；T-E2E-R4 对两种模式都比对 |
| **S9** | M8-A：`toolbar-position` + 工具条改造 + `use-media-query` + pane-switcher + deep-dive | T-A11Y-3、T-TOUCH-1/3 绿 |
| **S10** | M8-B：书籍/设置/播放器窄屏 + tokens + `tokens.test.ts` | T-TOUCH-2/4、T-RM-1 绿；旧 14 条 E2E 不红 |
| **S11** | M8-C：a11y.spec + keyboard.spec + baseline | T-A11Y-1/2 绿；基线文件每条有 `reason` |
| **S12** | M10：diff + upgrade_service + upgrade_jobs + 部分发布 + 进度迁移 + UI + 文档四份 | T-UPG-1..7 绿；A8/A9/A10 通过 |

**时间盒纪律**：若本轮配额不足，按 S1→S12 顺序交付，**停在任何一个整步之后都是可交付状态**；不允许"每条都做了一半"。若必须裁剪，裁 S12（M10）并保留文档说明，绝不裁 S5（CI）与 S4（真链路）——那两条是本轮的存在理由。

---

## 10. 不采纳 / 有意偏离（附理由）

1. **不做函数级 diff（tree-sitter 双版本符号比对）**：收益是少重建 1–2 个课时，风险是漏判导致"讲解与代码不一致"——而一致性是本产品的核心承诺。文件级 diff 的误判方向是"多重建"，代价可接受。
2. **不做 FTS 的 keyset 游标**：`bm25` 是浮点分数，游标编码浮点 + 索引变更会导致幽灵重复/漏行。用 `offset ≤ 200` + 显式 `next_offset`，把限制暴露给前端而不是藏在后端。
3. **不把 `LIKE` 分支也改成 FTS**：2 字以下中文查询是高频形态，`LIKE` 是唯一正确解；"统一走 FTS"听起来更干净，但会让用户搜不到。
4. **不引入 YAML 解析依赖**（CI 断言）：`pyyaml` 会为一个测试引入新依赖，且只能验证"文件里写了什么"，不能验证"GitHub 真的会跑"。用文本断言 + 首次真跑作为双保险；若将来要严格校验，改用 `actionlint`（独立工具，不进 Python 依赖）。
5. **不做 Playwright 计算样式断言（reduced-motion）**：`0.01ms` 的取整在不同引擎不一致，会变成噪声门禁；改为 CSS 静态断言。
6. **不在本轮做多用户认证 / S3 / 豆包 WS 流式 / PG 支持**：与"可证明"无关，且都是独立演进（平台件 §11 已登记）。本轮只保证这些接缝不被新代码堵死。
7. **不把 `pdf_service.py` 补回来**：平台件 §实施记录已裁定由 `book_service` / `book_jobs` / `rendering.pdf` 三层承担，本轮维持该裁定，并在 `architecture.md` 里补一句"有意偏差"，避免后续读者再把它当遗漏。
8. **（v2 新增）偏离"19 个错误码是定稿"：加第 20 个 `VALIDATION_FAILED`。** 理由见 P0-4：v1 引用了这个码却不存在，而 `AppError` 对未知码静默降级为 `INTERNAL(500, retryable)`——把一个确定性参数错误说成可恢复故障，比多一个码难查得多。代价是 `ERROR_CODE_COUNT` 与前端映射表要同步升级，这与 v2 的"新增错误码必须同时加断言"纪律一致，因此是可接受的；**但到此为止：本轮之后新增错误码仍必须走同一条评审**。
9. **（v2 新增）Gate 0 探测从 PowerShell 复制一份到 Node，而不是把 `check_env.ps1` 改成跨平台。** 理由：`start.ps1` 依赖 PowerShell 5.1 的既有行为（`scripts/parse_check.ps1` 门禁、BOM 处理、`$PSVersionTable` 断言），改动它的风险远大于收益；而 CI 的 `e2e-real` 跑在 Linux 上。因此两份实现、**同一 JSON 形状、同一组判据**，并由一条后续的一致性测试比对两者对同一台机器的输出（本轮不引入该编号，等两份探针都稳定后再补，避免出现"文档里有编号、仓库里没测试"）。这不算"两份真源"：真源是"三个探针命令"，两份实现只是包装。
10. **（v2 新增）a11y 门禁排除第三方 DOM，并用 `?code=plain` 钉定代码视图。** 不这样做的话，"serious = 0"在构造上不可达（Monaco 自带控件），门禁会先被 `continue-on-error` 软化、再被删除——那才是真正的质量损失。真正该被守的是**我们自己的**控件，`T-A11Y-4` 覆盖它。
11. **（v2 新增）旧版本不自动 prune。** R9 只提示不删：自动删除用户的历史课程版本，风险（误删、进度迁移后想回看）远大于收益（磁盘）。等出现真实的存储压力再做，并配"可恢复"设计。
12. **（v2 新增）不给 FTS 做 keyset 游标的结论不变**（原第 2 条），但补一条：**`offset` 的非 0 校验放在路由层而非服务层**——服务层被 CLI/worker 复用时不该重复实现参数校验，而错误码语义只有一层能定义。

---

## 11. 自评（提交评审前，我知道哪几处最可能被驳回）

| 可能的质疑 | 我的回答（或承认） |
|---|---|
| "四条都做，是不是一个迭代装不下？" | 装不下就按 §9 停：S5 与 S4 是不可裁的底线，S12 可裁。**规模上限已按 81 个文件给死**（v2 重算，见 §4.6），避免出现"再加一个里程碑"的滑坡。 |
| "评审加了 4 条 P0，是不是把方案改大了？" | 反过来：这 4 条**没有一条是新功能**，全是"不改就会静默失效"的洞——迁移删触发器、老 SQLite 上迁移炸、不可信端点当可信、不存在的错误码变 500。它们的工作量加起来不到半天的 S0 + 三处局部改动，却决定了 M7–M10 里最贵的那部分（"可证明"）能不能成立。 |
| "`?code=plain` 是不是为了绕开 Monaco 而作弊？" | 不是。它是把"用例测什么"从"运气"变成"前提"：a11y/mobile 要测的是**我们的布局与控件**，不是第三方编辑器。Monaco 分支另有 `T-A11Y-4` 覆盖，且明确只断言我们自己的子树。真正作弊的做法是 `continue-on-error`——本方案在 R2 里已明文禁止。 |
| "新增第 20 个错误码，怎么不遵守 平台件 的'19 个定稿'？" | 已在 §10 第 8 条登记为有意偏离，并给出代价与边界（同步门禁、同步前端、之后新增仍须评审）。与之相比，让 `AppError` 把未知码静默变成 500 才是不可接受的——那是本产品要消灭的同一类缺陷。 |
| "为什么把 `run_dir` 改成可配置？这不是给生产环境加开关吗？" | `run_dir` 里放的是 `preflight.json` / `ports.json` / pid 文件，全是**运行时状态**，本来就该跟运行实例走。固定的 `REPO_ROOT/.run` 让 e2e-real 读到开发机的旧结论（R13），也让并行跑两份工作区时互相覆盖。这是一处修正，不是新增能力。 |
| "e2e-real 用 `runtime=template`，是不是测了个假链路？" | 测的是**链路**（导入→队列→图执行→发布→SSE→播放器→书籍），不是模型质量。真模型链路按 平台件 仍是"人工 + Gate 0 探测"，且本轮不引入任何对真实 Key 的依赖——否则这条门禁在 CI 上永远 skip。 |
| "toolbar 用 `useLayoutEffect` 会不会 SSR 报警？" | 组件是 `'use client'` 且仅在选中后渲染；`useLayoutEffect` 在服务端不执行。已在 §3.3.2 写明，并要求 vitest 里覆盖"viewport 未知时用第一帧兜底"。 |
| "60% / 10% 两个阈值凭什么？" | 经验值，承认。缓解：阈值集中成常量、进 `reasons`、dry_run 先给用户看；不做静默成本扣减。 |
| "FTS 索引体积？" | R4 已列：`summary` 只索引前 512 字符，runbook 记基线，可随时 `reindex-search`。 |
| "为什么搜索的 `mode` 要回显给前端？" | 因为 G3 的本质是"系统说了谎"。回显实际生效模式是让撒谎变得不可能的唯一办法。 |
| "文档里 `T-*` 编号是不是太多了？" | 每条都对应一个能红的断言，没有口号条目。若实现时无法写出红断言，说明那条设计不成立，应回来改设计而不是删测试（平台件 纪律第 3 条）。 |

---

---

## 实施过程发现的方案缺陷（实现节点如实登记）

> 纪律：不静默偏离。凡是与本文 §3/§4/§7 说法不一致的地方，都记在这里并写清"为什么按仓库为准"。
> 下面每一条都是**实跑**撞出来的，不是预判。

| # | 本文的说法 | 实际撞到的事 | 处理 |
|---|---|---|---|
| **D1** | §6.5 / `T-SEARCH-9` 用 `SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='course_versions'` 断言"触发器恰好 4 个" | 4 个触发器里 `trg_repo_search_au` 建在 **`repositories`** 上（仓库改名要同步索引），所以那条 SQL 永远只能数出 **3**。照抄会让 `alembic upgrade` 在第一次跑就红 | `search_ddl.COUNT_TRIGGERS_SQL` 改为**按名字**计数（4 个名字集中成 `TRIGGER_NAMES`）。判据形状可改，"恰好 4 个"这个事实不能改 |
| **D2** | §6.5 说 `0003` 的 downgrade "走 batch，末尾重放触发器" | 只重放**不够**：batch 重建的过程是"建临时表 → 拷数据 → DROP 原表 → 改名"，中间那一瞬 `course_versions` 不存在，任何引用它的触发器都会让 `ALTER TABLE ... RENAME` 直接失败：`error in trigger trg_repo_search_au: no such table: main.course_versions`（实测）。降级因此是一条**抛异常的单程票** | downgrade **先删 4 个触发器**，再 batch 删列，最后重放 + 自检。`0003` 的注释里写明了这个窗口 |
| **D3** | §6.1 的迁移表让 `0003` 加列（带 ORM 上的 `ForeignKey`） | SQLite 无法在**不重建表**的前提下新增外键约束，而重建表正是要避开的动作（D2）。带 FK 的 `op.add_column` 会退化成 batch | 迁移里只加**裸列 + 索引**（原生 `ADD COLUMN`），FK 声明留在 ORM 供 PG 与文档使用；语义由"只有 `upgrade_service` 写这一列"保证 |
| **D4** | §7.3 `T-TOUCH-3` 写"1024px 下不出现该 tablist" | 与 §3.3.1/§3.3.2 的 `xl = 1280` 冲突 | 以 `xl` 为准：`<1280` 出现三段切换、`≥1280` 消失（`mobile.spec.ts` 按此断言） |
| **D5** | §3.2.3 第 6 步 `REPOLEARN_NEXT_DIST_DIR=<repo>/.next-e2e`（绝对路径） | Next 的 `distDir` 按**项目目录**解析，绝对路径会得到 `apps/web/E:\...` 这种非法目录（实测失败） | 编排器传**相对名** `.next-e2e`（落在 `apps/web/.next-e2e`，与 `.next` 仍隔离） |
| **D6** | §3.2.3 第 6 步让 e2e 在 UI 里粘贴 `http://127.0.0.1:<fake>/microsoft/autogen` | 前端 `lib/repo/parseRepoUrl.ts` 把 host 硬编码成 `github.com`，当场拒掉——**UI 那条路走不通**（后端出站确实全走假端点） | 真链路用例粘贴 `https://github.com/microsoft/autogen`（出站仍指向假端点），并额外断言 `repo.html_url === <fake>/...` 作为"真的打了假端点"的证据；被前端挡住的那条留成 `test.fixme` + TODO。**这是产品侧的真实缺口**：见下方 R15 |
| **D7** | §3.2.3 表格写 `POST /api/books` | 仓库实际是 `POST /api/courses/{id}/books`（`/api/books/*` 只覆盖 `/v1/books/*`） | 用例按仓库为准 |
| **D8** | §3.2.3 `T-E2E-R3` 假设"有 Chromium → 可下载 PDF" | `probe_gates.mjs` 的 `g2` 看的是 **Node** playwright 缓存，而产品降级用 `rendering/pdf.py::chromium_available()` 走 **Python** playwright。本机 `.venv` 没装该包 → `g2=ok` 但产品走 `browser-print`，断言红 | 用例保留原断言（它正确地暴露了"两个判据不同源"）；修法是 `pip install -e ".[pdf]"` 或让两处判据同源。**登记为待办 R16**，不弱化断言 |
| **D9** | §3.3.3 断言 deep-dive 的 a11y | 修完 `--text-dim` 对比度之后又冒出一条 `label-content-name-mismatch`：页头 Logo 链接的 `aria-label="回首页"` 与其可见文本 `RepoLearn` 不匹配（axe 规则要求可见文本包含在可访问名里） | 去掉那两个 Logo 链接的 `aria-label`，让可访问名等于可见文本（`site-header.tsx` / `course-shell.tsx` 各一行） |
| **D10** | §7.4 `T-SEARCH-4` 用 `a -b` 验证"表达式不泄漏" | 该查询被切成两个 token（`a`、`-b`），**每个都短于 3 字符**；`AND` 连接后必然 0 行。只判整串长度（4 字符）会让它走上一条永远空结果的 fts 路径 | `plan_search` 改为"整串 ≥3 **且每个 token 都 ≥3**"才走 fts；纯标点 token 直接丢弃（否则表达式被拼成 四个双引号，实测 `unterminated string`）。`T-SEARCH-4` 改用 `a*b` 做字面量断言 |
| **D11** | §4 文件清单没有 `apps/api/repolearn/routers/health.py`、`apps/api/repolearn/jobs/runner.py`、`apps/web/src/components/shell/site-header.tsx`、`apps/web/src/components/shell/course-shell.tsx`、`apps/api/tests/test_courses_api.py` | 实现时不得不动它们：`settings.run_dir` 变成字段后物理路径改叫 `run_path`（health/setup_service 各一行）；"upgrade" 与 "upgrade-plan" 两种 kind 必须在**派发处**注册（本仓库没有 `handlers.py` 的注册表，派发逻辑在 `runner._dispatch`）；D9 的两个 `aria-label`；`test_courses_api` 的"响应体完全等于两个字段"被新增字段打破 | 五处都是一行级改动，理由如上。**如实登记而不是静默改**（§4 的规模数字因此比 86 多 5 行，`count_workfiles.py` 仍按表格算 86——表格未改，规模不变） |
| **D12** | 仓库基线声称 `ruff check .` 是绿的 | 实测 **77 条**报错（含 `E741`、`I001`、`F401`、`UP0xx`、`B010` 等），跨 30+ 个文件 | 跑 `ruff check --fix`（110 处自动修）+ 12 处手工修；现在 `All checks passed!`。这属于"实现节点替上一轮还债"，不是本轮新增缺陷 |

### 由此新登记的风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| **R15** | 前端 `parseRepoUrl.ts` 把 host 硬编码成 `github.com`，而服务端已支持自建 GHE | 用户在浏览器里粘 GHE 地址会被前端当场拒掉（后端其实能处理）——"支持 GHE"只在 API/CLI 层成立 | 前端应改为"接受任意 http(s)、由服务端做 host 白名单"（SSRF 防线本来就在服务端）。本轮由一个 `test.fixme` 标出，未改前端解析器（不在 §4 清单内） |
| **R16** ✅**已关闭** | `probe_gates.mjs` 的 `g2` 与 `rendering/pdf.py::chromium_available()` **不同源**（Node playwright vs Python playwright） | `gates.g2=ok` 但 PDF 仍降级，`book-and-degrade` 红 | **复审实测发现真病因不是"不同源"**：`chromium_available()` 是 sync playwright API，被 async 处理器调用时必抛、又被 `except Exception` 吞掉，于是恒为 False。已修：① `probe_gates.mjs` 的 g2 直接调用产品判据；② 新增 `chromium_available_async()`，`create_pdf` 与 Doctor 改用它；③ CI `e2e-real` 补 `python -m playwright install chromium`。实测 `e2e-real` 4 passed / 0 failed |
| **R17** | `PlayerProvider` 在 `<audio>` 没有 `src` 时 `play().catch()` 把状态立刻改回 `paused`，时间轴永远进不了 `ended` | "无音频走字幕推进"这条主路径在**播放到底**这一环实际不成立（`K` 键切末步可绕过） | 已用 `K` 键路径覆盖了 `T-E2E-R2`；修复方式是不给空 `src` 的 audio 调用 `play()`，改用 `estimated` 计时器驱动（下轮修） |

---

## 变更记录

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| v1 | 2026-11-06 | 首版：M7 交付门禁闭环 / M8 窄屏与无障碍 / M9 搜索生效 / M10 增量升级；68 个唯一文件；**实际 38 条**新测试编号（原记 28，评审 P2-1 更正） | 方案架构节点 |
| **v3** | 2026-11-06 | **交付前复审版**：新增 §交付前复审记录（6 P0 + 8 P1 + 1 P2 逐条说明、新增用例表、仍存缺口）与 §4.7；修 P0-5（`/upgrade` 路由调用不存在的函数）· P0-6（升级永远 `partial` 且 `T-UPG-4` 被放宽）· P0-7（`Query` 校验失败没有错误信封）· P0-8（`<lg` 书籍无换章入口）· P0-9（`g2` 判据同源）· P0-10（sync playwright 在事件循环里恒失败 → PDF 从未用过 Chromium，**关闭 R16**）· P1-12..19 · P2-13；工作量清单 86 → **95 行 / 90 个唯一文件**（新建 39 / 修改 52 / 生成 4）；风险新增 **R18**；实测 250 pytest / 37 kernel / 78 vitest / 44 playwright / **4 真链路 e2e 全绿** | 资深评审节点 |

---

## 评审结论

> **结论：有条件通过（Approved with conditions）。** 本文件（v2）可以作为 M7–M10 的实现依据；下列条件**必须在开工前落实或作为首个提交**，其余按 §9 的 S0→S12 推进即可。

### 一、通过的理由（不是客套）

1. **四条缺口是真的，且证据可复现。** 每一条都落在实读（`ingest/github.py` 的硬编码常量、`list_courses` 只有 `LIKE` 分支、`selection-toolbar` 的 clamp 缺失）或实测（FTS trigram 的 2 字静默空结果、197/37/62/14 的绿）之上。没有一条是"我觉得应该更好"。
2. **方案的每一条主张都自带"会失败的断言"。** 这是最难做到的部分：`T-SEARCH-3` 要的是"2 字查询**命中数 > 0**"（不是"返回了响应"），`T-E2E-R3` 要的是"PDF 按钮与 `g2` 一致且 `g2 != unknown`"（不是"有就下载、无就跳过"），`T-TOUCH-1` 要的是"工具条跟着选区走"。这类断言一旦实现就会立刻暴露问题，而不是等到用户投诉。
3. **规模是克制的。** 四个里程碑、81 个唯一文件、47 条编号，且给出了"停在哪一步都可交付"的裁剪纪律（S5/S4 不可裁，S12 可裁）。没有借机扩张到多用户/S3/PG。
4. **它引用前序 平台件 的方式是对的**：不推倒、不重复，只登记差异，并明确"冲突处以本文为准"。

### 二、通过的条件（C1–C6，逐条可验收）

| # | 条件 | 验收方式 |
|---|---|---|
| **C1** | **S0 前置必须先做**：第 20 个错误码（含前端映射与未知码断言）、`REPOLEARN_RUN_DIR`、`REPOLEARN_NEXT_DIST_DIR`、`probe_gates.mjs`、`count_workfiles.py`。这些是后面每条里程碑都依赖的地基 | §9 S0 的"完成判据"三项全绿；`T-CONTR-1` 里 422 的断言通过 |
| **C2** | **迁移必须同时通过 A11**：`upgrade head` / `downgrade 0003` / `downgrade 0002` / 再 `upgrade head` 四步往返，全程触发器数量可解释（4 或 0），且不出现 `no such trigger` / `no such table` | A11 实跑记录贴进 PR |
| **C3** | **不可信端点三条攻击面必须在 S1 就实现**，不能推到"以后加固"：因为一旦上线了可配置端点却没有 `html_url` 清洗，等于把 XSS 直接发给用户 | A12 实跑；`T-GH-4/5/6` 绿 |
| **C4** | **真链路层不得依赖开发机状态**：`book-and-degrade` 的 `g2` 必须来自**本轮**写入的 `preflight.json`，读到 `unknown` 即判失败 | A13 实跑（先删 `.run/preflight.json`） |
| **C5** | **CI 首跑必须真绿，不接受 `continue-on-error`**。Node 22、pnpm 12.18.0、lockfile 同提交这三条任一没做，首跑必红——这正是它们进 `T-CI-5/6` 的原因 | 首个 CI 运行的六个 job 全绿截图；`T-CI-1..6` 绿 |
| **C6** | **文档与实现同源**：README / runbook / architecture 与本文件的数字一律由脚本或实测得出（`T-DOC-1`/`T-DOC-2`）；`docs/architecture.md` 必须补 §9–§11 与"`pdf_service.py` 有意偏差"一句 | `pytest -q apps/api/tests/test_ci_and_docs.py` 绿 + 人工对照一遍目录 |

### 三、实现阶段必须自己守的三条红线（评审无法替你做）

1. **任何"降级"都必须能被用户看见。** 本轮新增了三处降级路径（FTS 不可用、Monaco 不可用、Chromium 不可用），每一处都要在 UI 上有字、在 Doctor 上有行、在响应里有字段。**只要有一处是静默换路，这条方案的存在理由就没了。**
2. **断言只能"会失败"，不能"必然通过"。** 实现时若发现某条 `T-*` 写不出会红的断言，正确动作是**回来改设计并在此处登记**，而不是把测试删掉或放宽到恒真（v1 自己的 §11 也这么写，评审在此重申）。
3. **不许为了绿而改口径。** 典型诱饵：把 `T-TOUCH-4` 的遍历范围改回"所有 button"再顺手删掉 Monaco 页；把 `dry_run` 的超时从 20s 改成无限；把 `copy_lessons` 的锚点校验从"旧镜像"改成"跳过校验"。这三处都能让门禁变绿而产品变差。

### 四、复审触发条件（出现任一，本文需重新评审）

* 复用 `course_versions` 做**第三次**结构变更（每次 batch 重建都要重放触发器，第三次就该把 FTS 换成独立的物化表）；
* 引入 **PostgreSQL**（`render_as_batch` 与 trigram 的取舍全部失效，§6 需重写）；
* 把 Monaco 从 CDN 换成本地包（`?code=plain` 的钉定策略可撤，`T-A11Y-4` 应升级为全量门禁）；
* 真链路层出现**第二条**依赖"机器能力探测"的断言（说明 `probe_gates.mjs` 需要变成正式能力，而不是 e2e 辅助脚本）。

### 五、一句话总结

**v1 的方向是对的，错在把几处"会静默失效的地基"当成了实现细节：迁移会删掉自己的索引触发器、老运行时上迁移会直接炸、自定义端点的返回值被当成可信数据、以及一个从未存在过的错误码。v2 把这些补成了会红的断言，方案才可以开工。**

---

## 交付前复审记录（第二轮评审 · 实现 → 可交付）

> **对象**：v2 的实现（工作区改动，95 行 / 90 个唯一文件）。
> **方法**：与上一轮同一条纪律——每条结论都落在**一次实读（文件:行号）**或**一次实跑**之上；"文档说的"与"仓库是的"不一致时以仓库为准。
> **结论**：**6 条 P0 + 8 条 P1 全部就地修正**，每条都补了"会失败"的用例或门禁；**1 条明确不修**（R18"复制课时的锚点未按旧镜像复核"——理由见 §D）。
> **实测（本机，2026-11-06）**：`250 pytest` / `37 kernel` / `78 vitest` / `44 playwright` / `4 真链路 e2e` 全绿；`ruff` / `tsc` / `contracts:check` 0 错。

### A. 分级总表

| ID | 维度 | 严重度 | 一句话 | 处置 |
|---|---|---|---|---|
| P0-5 | 可行性 | **P0** | `POST /v1/courses/{id}/upgrade` 调的是 `course_service.start_upgrade`——该函数不存在，唯一对外入口 100% `AttributeError`(500)，而所有 service 级用例全绿 | 已修（改调 `upgrade_service`；`T-UPG-8/9` 经 TestClient 打真路由） |
| P0-6 | 完备性 | **P0** | `publish_partial` 用**空的** `curriculum` 算章节门禁 → `enough_sections` 恒 False → 每一次升级都判 `partial`；`T-UPG-4` 因此被写成 `in {ready, partial}`，缺陷隐形 | 已修（章节回落到新版本行继承的旧大纲；断言收紧为 `== "ready"` 且 `reasons` 不含「章节不齐」） |
| P0-7 | 一致性 | **P0** | `VALIDATION_FAILED` 只在路由自己 `raise` 时生效；`Query(ge/le/max_length/pattern)` 失败走 FastAPI 默认 `{"detail": [...]}` → 前端读不到 `code` 回落 `INTERNAL`，P0-4 的修法只覆盖了一半 | 已修（`main.py` 注册 `RequestValidationError` handler；`T-CONTR-1` 加 `offset=999` / `q=121 字` / `mode=bogus` / `limit=abc`） |
| P0-8 | 可用性 | **P0** | 书籍页没把 `book/activeKey/onSelectChapter` 交给 `BookReader` → `<lg` 时目录栏被隐藏且**没有**等价入口，768px 以下完全无法换章 | 已修（`book-view` 传参；左侧目录 `md:block`→`lg:block`，与 §3.3.1 的 `lg` 双栏断点对齐） |
| P0-9 | 完备性 | **P0** | 真链路 `g2` 与产品 PDF 判据不同源（Node 浏览器缓存 vs Python `chromium_available()`）→ `book-and-degrade` 结构性红，只能靠 `unknown` 蒙过去（R16） | 已修（`probe_gates.mjs` 的 g2 直接调用产品判据；CI `e2e-real` 补 `python -m playwright install chromium`） |
| P0-10 | 可行性 | **P0** | **R16 的真病因**：`chromium_available()` 是 sync playwright API，在事件循环里必抛、又被 `except Exception: return False` 吞掉 → `create_pdf` 与 Doctor 里**恒为 False**，"装了 Chromium 也永远是打印视图" | 已修（新增 `chromium_available_async`，`create_pdf` 与 Doctor 改用它；新增用例钉住"事件循环里拿到真实结果"） |
| P1-12 | 一致性 | P1 | `offset` 只在 `mode=="fts"` 时放行，而前端恒发 `mode=auto` → fts 分页在默认路径上永远 422，同时服务端还在签发自己拒收的 `next_offset` | 已修（判定下移到 `list_courses`，看**生效**的 `plan.mode`） |
| P1-13 | 一致性 | P1 | `request_with_retry` 抛的是 `LlmError`（不是 `AppError`）：`fetch_repo_meta` 把 404 报成"端点不可达"，`resolve_commit` 的异常穿透 `/v1/repos/resolve` 变 500 | 已修（`_raise_mapped` 统一映射；两个站点补逐跳重定向校验） |
| P1-14 | 一致性 | P1 | `total_files` 取的是**新** commit 的 `files` 长度（含 .md/二进制、上限 300、GHE 常缺）→ P1-9 定死的口径失效，缺失时静默退化成 1 | 已修（`_old_total_files`：旧 `Commit.file_count` → 旧镜像条数 → 0 并写进 `stats`） |
| P1-15 | 可用性 | P1 | 20s 超时返回 `503 PROVIDER_UNAVAILABLE`，且 `queue.enqueue` 只 `flush` 不 `commit` → job 随请求回滚，`details.job_id` 指向不存在的任务 | 已修（超时先 `commit`，再回 `202 {job_id, mode:"planning"}`） |
| P1-16 | 可用性 | P1 | `T-TOUCH-3` 根本不存在；且 `PaneSwitcher` 条件渲染会卸载 `CodePane` → 选区在 store、锚点在局部 state → 切回「代码」时工具条退回"面板左上角 + 固定偏移"（D29 复活） | 已修（三段挂载 + 切可见性；新增 `T-TOUCH-3`：tablist 出现 / 提问后 textarea 获焦 / 切回代码仍有代码视图） |
| P1-17 | 完备性 | P1 | `data-rl-tap` 只登记了 6 个文件：抽屉触发器（大纲 / Momo）、角色保存、选区工具条的 ✕ 都没进 44px 门禁，而 ✕ 正是 §3.3.1 逐字点名的那一个 | 已修（补登记 + `max-lg:min-h-[var(--tap-target)]`；✕ 用 `::after` 扩命中区，视觉密度不变） |
| P1-18 | 可行性 | P1 | `e2e-real` 在 `finally` 里无条件删本轮目录 → CI 的 `if: failure()` 上传的 artifact 永远为空（最需要日志时日志没了） | 已修（`keepRunDir = opts.keep \|\| exitCode !== 0`；artifact 补 `apps/web/test-results`） |
| P1-19 | 一致性 | P1 | `apps/web/tsconfig.json` 被工具重排且残留实验目录 `.next-m8a`；`.next-e2e` 没进 `.gitignore` → 构建产物会污染工作区 | 已修（恢复最小 diff、只留 `.next-e2e` 的 include；`.gitignore` 补一行） |
| P2-13 | 一致性 | P2 | `scan` 对完整 `summary_md` 做 LIKE，而 FTS 只索引前 512 字 → 关键词在 512 字之后的课程"scan 命中、fts 零结果"，与 `T-E2E-R4` 的 parity 直接冲突 | 已修（scan 改用 `substr(..., 1, SUMMARY_INDEX_CHARS)`） |

### B. 三条最值得记住的

1. **P0-5 是"服务层全绿、路由层死"的典型。** 所有 unit/integration 用例都直接调 service，路由层一行都没被打过；一个不存在的属性名足以让 M10 的唯一入口 500，而门禁全绿。**修法不是加断言，是让断言走真实入口**（`T-UPG-8/9` 用 TestClient）。
2. **P0-6 关掉的是"永远 partial"。** 更糟的不是 bug，而是它让 `T-UPG-4` 写下 `in {ready, partial}` —— 一条永不失败的断言就是一份免责声明。收紧到 `== "ready"` 之后，任何一处门禁口径漂移都会立刻红。
3. **P0-10 说明"同源判据"本身不够。** 即使 `probe_gates` 与产品调用同一个函数，**调用上下文**不同（有没有事件循环）仍会给出相反答案；R16 被误记成"两个判据不同源"，实际是"同一个函数在两类上下文里行为不同"。修法是把 sync 判据包成 async 版本，而不是再写一个判据。

### C. 本轮新增 / 强化的用例

| 编号 | 位置 | 钉住什么 |
|---|---|---|
| `T-UPG-8` | `apps/api/tests/test_upgrade.py` | 路由真的进到 service（出站失败被映射成 `REPO_NOT_FOUND`，不是 500） |
| `T-UPG-9` | 同上 | `dry_run` 响应形状（少一个字段 = 空抽屉） |
| `T-UPG-4`（收紧） | `apps/api/tests/test_upgrade_pipeline.py` | 升级结果 `status == "ready"`，且 `reasons` 不含「章节不齐」 |
| `T-CONTR-1`（补三条） | `apps/api/tests/test_search.py` | `Query` 校验失败也走 `VALIDATION_FAILED` 信封；`mode=auto` 落在 fts 时 `offset` 可用 |
| `T-SEARCH-5`（去 flake） | 同上 | 排序断言钉死 `created_at`（原先"全量跑红、单跑绿"） |
| 事件循环里的 G2 | `apps/api/tests/test_books_api.py` | `chromium_available_async` 在事件循环里拿到真实结果（P0-10 的回归钉） |
| `T-TOUCH-3` | `apps/web/e2e/mobile.spec.ts` | `<xl` 三段切换：tablist 出现 / 提问后 textarea 获焦 / 切回代码仍有代码视图 |

### D. 仍然存在的缺口（登记，不假装修掉）

* **R18（新登记）**：升级时**复制**过来的课时，锚点没有按旧镜像再校验一遍（`publish_partial` 只校验本次重讲的课时）。影响面是"旧镜像已被 LRU 清掉时，旧行号可能已经指向不同代码"，UI 已经标注"来自上一版"，但没有机检。**本轮不修的理由**：旧镜像缺失时校验只会失败得没有信息量，正确做法是在 `copy_lessons` 里对**可见的**旧镜像做一次抽样校验并降级告警——那是独立一轮的工作量。**已把 `publish_partial` 的 docstring 改成如实描述**，先消灭"注释说校验过、其实没有"这类更坏的缺陷。
* **P1-4 的 `distDir` 并存**仍未在 CI 验证（本地 `start.ps1` 与 `e2e-real` 并跑一次才能验），本轮只补了 `.next-e2e` 的忽略与 `tsconfig` include。
* **GHE 真实端点**仍未实跑（本机只有假 GitHub）。§7.2 的 `T-GH-*` 全在 `respx`/假端点上，`safe_html_url` 的白名单逻辑对"GHE 的 web base 与 api base 不同域"这一常见配置有覆盖，但没有一次真实 GHE 握手。

---

**（文档结束 · v3 · 复审通过：P0/P1 全部落地，R18 明确登记）**