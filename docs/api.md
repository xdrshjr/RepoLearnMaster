# API 约定（补充说明）

> 权威契约是 `packages/contracts/openapi.json`（由 `python -m repolearn.cli export-openapi` 生成）。
> 这份文档只补 OpenAPI 表达不了的约定：分页、SSE、幂等、错误、Range。

## 1. 入口与鉴权

| 谁 | 访问什么 | 头 |
|---|---|---|
| 浏览器 | `http://localhost:3000/api/*`（**唯一**入口） | cookie + `X-CSRF-Token`（写） |
| BFF | `http://127.0.0.1:8000/v1/*` | `X-Internal-Token` |
| CLI / 测试 | 同上 | `X-Internal-Token` |

`REPOLEARN_INTERNAL_TOKEN` 未配置时 API 放行（本地调试）；配置了就必须带，否则 401。
**CORS 全关**：同源设计下不需要它，留着只会给未来留一个错误开关。

## 2. 分页

```
GET /v1/courses?limit=20&cursor=<opaque>
→ { "items": [...], "next_cursor": "eyJ..." | null }
```

- 游标是不透明的 base64（`created_at|id`），**不是 offset**：并发插入时 offset 会跳行。
- `limit` 上限硬编码 50。搜索态（有 `q`）强制 `≤50` + 服务端 300ms 超时（超时返回已匹配部分）。
- 索引门禁只覆盖**游标分页主查询**；模糊搜索不在门禁内（前缀通配符下任何 B 树索引都不生效）。

## 3. SSE（`GET /v1/jobs/{id}/events`）

帧格式固定：

```
id: <seq>
event: <type>
data: {"schemaVersion":1,"type":"...","seq":12,"ts":1762437600123,"jobId":"job_...","data":{...}}

```

| 规则 | 说明 |
|---|---|
| `seq` 从 1 开始单调递增 | 断线重连靠它精确续传；不用时间戳近似（同毫秒会丢帧） |
| `Last-Event-ID` 落后于保留窗口（500 条） | 服务端**不补发**，改发一帧 `job.snapshot`，前端据此重建 UI |
| 未知 `type` | 客户端必须忽略并继续读流（后端加事件不会让旧前端白屏） |
| 缓冲 | 全链路禁用：`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no` |
| keepalive | 每 15 秒一帧 `: keepalive` |

事件类型：`system.init` / `agent.thinking` / `agent.text.delta` / `tool.start` / `tool.end` /
`step.delta` / `question.delta` / `question.completed` / `job.phase` / `node.completed` /
`job.completed` / `job.failed` / `job.snapshot` / `run.completed` / `budget.exceeded`。

## 4. 幂等

两种幂等是两件事，必须分别理解：

| 类型 | 键 | 存储 | 行为 |
|---|---|---|---|
| 请求级 | `Idempotency-Key` 头 | `idempotency_keys(scope, key)` | 10 分钟内同键同体 → 返回**逐字节相同**的首次响应快照；同键异体 → 422 `IDEMPOTENCY_MISMATCH` |
| 内容级 | `cache_key`（repo+sha+policy+lang / course+preset+template） | `course_versions.cache_key` / `book_versions.cache_key` | 命中 → `200 {reused:true}`，**不建 Job、不花 token** |

`scope` 取路径模板（`courses.create` / `books.create` / `pdf.create`），不是完整 URL——
路径里的 id 会把同一逻辑操作算成不同 scope，幂等随即失效。

## 5. 错误

```json
{ "error": { "code": "COURSE_NOT_READY", "message": "课程还没生成完成",
             "hint": "等生成任务结束后再打开（页面会显示进度）",
             "retryable": false, "details": {"status": "generating"}, "req_id": "req_1a2b" } }
```

19 个错误码的完整表在 `GET /v1/errors`（也是 `core/errors.py` 的镜像）。
`retryable` 是**显式声明**，不从 HTTP 状态推断：`COURSE_NOT_READY`(409) 不该重试，
`JOB_CONFLICT`(409) 该跳转而不是重试。

唯一例外：`POST /v1/setup/llm/probe` 与 `/v1/setup/tts/probe` 是**测量接口**，
失败返回 `200 + ok:false`，但 `error` 字段形状与上表一致（前端错误渲染不需要分叉）。

## 6. 二进制与 Range（`/v1/objects/{kind}/{name}`）

三种写法各有其位，混用必 404：

| 场景 | 写法 |
|---|---|
| 契约里（前端可见） | `/api/objects/audio/<hash>.mp3` |
| BFF 内部 | `/v1/objects/audio/<hash>.mp3` |
| 磁盘 | `var/objects/audio/<hh>/<hash>.mp3` |

| 请求 | 响应 |
|---|---|
| 无 `Range` | `200` + `Accept-Ranges: bytes` + `ETag` |
| `Range: bytes=0-99` | `206` + `Content-Range: bytes 0-99/<total>` |
| 区间越界 | `416` + `Content-Range: bytes */<total>` |
| `If-None-Match: <etag>` | `304` |

`ETag` 取内容 sha256 前缀——内容寻址存储天然满足"内容变则 ETag 变"。
BFF 必须原样转发这四个头，否则播放器 seek 会退化成"从头重新加载"。

## 7. 写接口的 CSRF

所有写方法要求 `Cookie: rl_csrf=...` + `X-CSRF-Token: <同值>`。任一缺失 → 403。
例外：`POST /v1/courses/{id}/progress/beacon` 不校验 CSRF——`navigator.sendBeacon`
无法设置请求头，而该端点只写"进度"这一种幂等覆盖型数据。

## 8. 版本

响应头 `X-API-Version: 1`。破坏性变更必须升 `/v2`，不允许在 `/v1` 上改字段语义。
