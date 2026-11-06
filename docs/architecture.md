# 架构（长期文档）

> 由 `docs/plans/repo-learn-platform/spec.md` §3 精简而来。要改结构，先改这份，再改代码。

## 1. 为什么是三个进程

| 进程 | 语言 | 端口 | 为什么必须独立 |
|---|---|---|---|
| `apps/web` | Node / Next.js | 3000 | RSC 首屏 + Client 岛屿；同时充当 BFF，是浏览器唯一认识的地址 |
| `apps/api` | Python / FastAPI | 8000（回环） | 仓库解析是 CPU+IO 混合长任务；课程生成是分钟级可中断事务 |
| `services/agent-kernel` | Node ESM | 8787（回环） | `@aragon-agent/core` 是 ESM-only 闭源包，无法在 Python 进程内加载 |

三者只通过 HTTP/SSE 与数据库通信。任一进程崩溃，另外两个仍可服务只读页面；
Job 状态机保证重启后**继续跑**而不是从头重来。

## 2. 单一同源通路（最容易返工的一条）

**浏览器只与 `:3000` 通信。** API 与 Kernel 只绑 `127.0.0.1`，并要求 `X-Internal-Token`。

不是架构洁癖：`SameSite=Lax` 的会话 cookie **不会**随跨源 `fetch` 发送。跨源就意味着
CSRF 双提交、SSE 鉴权、音频 `Range` 拖动三件事同时失效；而修复它们需要
`SameSite=None; Secure`，那就要求 HTTPS，与"`.\start.ps1` 一条命令在 localhost 跑起来"直接冲突。

BFF 只做三件事，多一件就变成第二个后端：

1. 转发（附带 `X-Internal-Token` / `X-Request-Id` / `X-CSRF-Token`）；
2. 透传流（SSE 逐 chunk、二进制原样转发 `Range`/`ETag`/`206`/`416`/`304`）；
3. 把上游结构化错误体**原样**交给前端（不吞、不改写成 500）。

## 3. 课程生成工作流（9 节点）

```
N1 normalize_repo → N2 resolve_commit → N3 fetch_repo → N4 analyze_repo
   → N5 plan_curriculum →(Send 扇出 12 课时)→ N6 write_lessons
   → N7 simulate_trace → N8 synthesize_audio → N9 publish_course
```

三条执行模型的硬约束：

1. **checkpointer 必须是异步实现**（`AsyncSqliteSaver`）。同步 `SqliteSaver` + `graph.ainvoke()`
   会在写 checkpoint 时抛"不能在事件循环里调用同步 IO"。
2. **checkpoint 库与业务库物理隔离**（`langgraph.sqlite` vs `repolearn.db`）：
   每个 superstep 一次 checkpoint 提交会与业务写入互相推到 `busy_timeout`。
3. **并行分支必须声明 reducer**（`lessons/traces/narration` 浅合并、
   `failed_lessons` 去重追加、`warnings` 追加、`budget` 逐字段取 max）。
   没有 reducer，LangGraph 直接抛 `InvalidUpdateError`。

**状态体积预算 ≤ 256KB**：state 里只放引用，大体量产物落
`var/objects/artifacts/<job>/<node>/<key>.json`。测试会遍历 checkpoint 断言这一条。

## 4. 降级矩阵（每一条都被测试覆盖）

| 故障 | 行为 | 用户看到 |
|---|---|---|
| Kernel 进程挂了，但 core 包在 | `ExecCliRuntime`（A→B） | 设置页"降级（CLI 直连）" |
| core 包不可获取 | **直接模板降级**，不尝试 exec（C） | "课程为简化版" |
| tree-sitter 缺失 | 正则抽取 | `ANALYSIS_DEGRADED`，锚点置信度 low |
| TTS 不可用 | 字幕自动推进 | 播放器"无配音" |
| Chromium 缺失 | 打印视图 | P10 无"下载 PDF"，有"打开打印视图" |
| 预算超限 | 保留已完成课时，`partial` | 完课页可"继续生成" |
| API 重启留下僵尸版本 | reaper 置 `failed` 并释放锁 | "上次生成中断 · 可重新生成" |

> B 与 C 是两个**不同的**失败域。`aragon` CLI 与 `@aragon-agent/core` 来自同一个包、
> 同一个 registry，所以"包拉不下来"时两条路一起废——B 只能救"进程挂了"，救不了"装不上"。

## 5. 数据模型的三个关键决定

1. **课程聚合根 = `course_versions` 的一行**，没有独立的 `courses` 表。
   `course_id ≡ course_versions.id`。理由：PRD 没有"跨版本的同一门课"这个概念，
   分两级会让 URL/权限/进度/书籍/笔记全部需要重映射。
2. **步骤数据唯一真源 = `steps` 表**；`lessons.playback_meta` 只放非步骤字段。
   `PlaybackBundle` 由二者只读拼装，永不回写——否则第一个修 bug 的人就会让两边分叉，
   表现是"播放到第 3 步又跳回第 1 步"。
3. **幂等键按 `scope` 隔离**（`idempotency_keys(scope, key)`），不在 `jobs` 上。
   `POST /courses` 与 `POST /books` 复用同一个 UUID 时，全局唯一会让两个不同资源互相踩。

## 6. 预算三层

| 层 | 默认 | 闸门位置 | 超限 |
|---|---|---|---|
| Job | 180k tokens / 0.35 USD / 25 分钟 | `budget_guard.JobBudget`（runner 持有） | `failed_budget`，已发布课时保留 |
| 节点 | N5 20k、N6 每课时 9k、N7 每课时 2k，预留 28k 给重试 | 每次 Kernel 调用前下发 | 只让该课时失败 |
| Run | 跟随节点下发（9k–20k），`maxTurns=16` | Kernel `budget.ts` | Kernel 主动 abort 并回 `budget.exceeded` |

**先到的那个生效。** 没有价格的模型记 0 并带 `PRICE_UNKNOWN`——不猜价格，
否则"≤0.35 USD"这条门禁会变成假数据。

## 7. 可追溯性怎么变成代码

- 锚点 = `file + symbol + line_start/line_end + commit_sha`；
- N7 的每一步带 `certainty`（源码事实 / 静态推断 / 教学模拟）；
- `source_fact` 必须带 evidence，且 evidence 必须能在镜像里定位到行——**不能定位就降级**，
  而不是删掉 evidence 蒙混过去；
- 发布前校验：锚点存在性、segments 连续覆盖、每课时至少一题带 evidence；
- `source_fact` 占比 < 40% → `trace_quality="weak"`，前端提示"以推演为主"。

## 8. 观测性

- 结构化 JSON 日志（`req_id` / `job_id` / `node` / `duration_ms`），请求体永不入日志；
- `/v1/metrics` 聚合：成功率、P50/P95、缓存命中率、token/USD、完成率、正确率、导出率；
- Doctor 面板：DB / Kernel / Chromium / tree-sitter / 模型配置 / TTS / GitHub / 搜索模式。
