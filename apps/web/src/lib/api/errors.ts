/**
 * Error-code → user-facing copy (spec §5.6).
 *
 * The backend `message` is already Chinese and user-facing, but the frontend is
 * the last place that can turn a code into an *action*. Every one of the 19
 * codes below carries a message plus an executable hint, which is what "稳健"
 * means in the UX layer (§5.6 note: “hint 是可执行下一步”).
 */

export type ErrorCode =
  | 'REPO_NOT_FOUND'
  | 'REPO_FORBIDDEN'
  | 'RATE_LIMITED'
  | 'REPO_TOO_LARGE'
  | 'NO_MODEL_FOR_ROLE'
  | 'SETUP_REQUIRED'
  | 'INVALID_KEY'
  | 'PROVIDER_UNAVAILABLE'
  | 'BUDGET_EXCEEDED'
  | 'JOB_NOT_FOUND'
  | 'JOB_CONFLICT'
  | 'COURSE_NOT_READY'
  | 'ANCHOR_STALE'
  | 'OBJECT_MISSING'
  | 'INGEST_BLOCKED_PATH'
  | 'CONTRACT_VIOLATION'
  | 'IDEMPOTENCY_MISMATCH'
  | 'PROFILE_CONFLICT'
  | 'VALIDATION_FAILED'
  | 'API_UNREACHABLE'
  | 'INTERNAL';

export interface ErrorCopy {
  code: ErrorCode;
  http: number;
  title: string;
  message: string;
  hint: string;
  /** Where the user can go next, if there is a page for it. */
  action?: { label: string; href: string };
  retryable: boolean;
}

export const ERROR_COPY: Record<ErrorCode, ErrorCopy> = {
  REPO_NOT_FOUND: {
    code: 'REPO_NOT_FOUND',
    http: 404,
    title: '仓库不存在',
    message: '找不到这个 GitHub 仓库。',
    hint: '检查 owner/name 拼写是否正确，并确认仓库是公开的（例如 github.com/facebook/react）。',
    retryable: true,
  },
  REPO_FORBIDDEN: {
    code: 'REPO_FORBIDDEN',
    http: 403,
    title: '仓库不可访问',
    message: '这个仓库是私有的或已被封禁。',
    hint: 'MVP 只支持公开仓库；请在设置里配置 GitHub Token 后改用公开仓库，或等私有仓库支持上线。',
    action: { label: '去设置配置 GitHub Token', href: '/settings' },
    retryable: false,
  },
  RATE_LIMITED: {
    code: 'RATE_LIMITED',
    http: 429,
    title: '请求被限流',
    message: 'GitHub 或模型服务返回了限流。',
    hint: '等待提示中的重试时间后再试；长期解决方法是到设置里填入 GitHub Personal Access Token（未配置时只有 60 次/小时）。',
    action: { label: '配置 GitHub Token', href: '/settings' },
    retryable: true,
  },
  REPO_TOO_LARGE: {
    code: 'REPO_TOO_LARGE',
    http: 422,
    title: '仓库体量超限',
    message: '仓库超过了单次分析的体量上限。',
    hint: '换一个更轻量的仓库，或先只导入某个子目录（等增量分析上线后即可支持大仓库）。',
    retryable: false,
  },
  NO_MODEL_FOR_ROLE: {
    code: 'NO_MODEL_FOR_ROLE',
    http: 409,
    title: '角色缺少模型',
    message: '有角色还没有分配模型，生成被拒绝。',
    hint: '去设置的“角色与默认模型”里给每个角色选一个模型，或点“按能力自动分配”。',
    action: { label: '打开角色矩阵', href: '/settings#roles' },
    retryable: false,
  },
  SETUP_REQUIRED: {
    code: 'SETUP_REQUIRED',
    http: 428,
    title: '还没有完成配置',
    message: '需要先完成 AI 服务配置才能生成课程。',
    hint: '打开配置向导，选一个模型服务并填入 API Key（大约 1 分钟）。',
    action: { label: '打开配置向导', href: '/setup' },
    retryable: false,
  },
  INVALID_KEY: {
    code: 'INVALID_KEY',
    http: 401,
    title: '密钥无效',
    message: '模型服务拒绝了这组凭据。',
    hint: '回到向导第 2 步重新填写 API Key（注意不要带引号或换行），然后点“测试连接”。',
    action: { label: '回到向导第 2 步', href: '/setup?step=2' },
    retryable: false,
  },
  PROVIDER_UNAVAILABLE: {
    code: 'PROVIDER_UNAVAILABLE',
    http: 503,
    title: '模型服务不可用',
    message: '模型服务返回 5xx 或超时。',
    hint: '可以直接重试；若持续失败，到设置里把该角色的模型换成另一个服务商。',
    action: { label: '切换模型', href: '/settings#roles' },
    retryable: true,
  },
  BUDGET_EXCEEDED: {
    code: 'BUDGET_EXCEEDED',
    http: 402,
    title: '生成预算已用尽',
    message: '本次生成的 token / 美元预算已经耗尽。',
    hint: '已生成的课时可以正常学习；在 .env 调大 REPOLEARN_JOB_MAX_TOKENS / REPOLEARN_JOB_MAX_USD 后重启 API 再点「重新生成」（会复用缓存），或把 critic 这类角色换成更便宜的模型。',
    retryable: true,
  },
  JOB_NOT_FOUND: {
    code: 'JOB_NOT_FOUND',
    http: 404,
    title: '任务不存在',
    message: '这个生成任务已经不存在（可能被清理）。',
    hint: '回首页重新发起一次生成，命中缓存的课程会立刻返回。',
    action: { label: '回首页', href: '/' },
    retryable: false,
  },
  JOB_CONFLICT: {
    code: 'JOB_CONFLICT',
    http: 409,
    title: '已有相同任务',
    message: '同一个仓库已有正在运行的生成任务。',
    hint: '直接跳到已有任务的进度页即可，不需要重新发起。',
    retryable: false,
  },
  COURSE_NOT_READY: {
    code: 'COURSE_NOT_READY',
    http: 409,
    title: '课程还没准备好',
    message: '课程版本尚未 ready。',
    hint: '停留在准备页观察四段进度；已发布的课时可以先学。',
    retryable: true,
  },
  ANCHOR_STALE: {
    code: 'ANCHOR_STALE',
    http: 409,
    title: '锚点与代码不同步',
    message: '课程的代码锚点和当前 commit 不匹配（仓库已更新）。',
    hint: '在设置或课程页发起重建，重新对齐到新的 commit。',
    retryable: false,
  },
  OBJECT_MISSING: {
    code: 'OBJECT_MISSING',
    http: 404,
    title: '对象文件已丢失',
    message: '音频 / PDF 对象不存在。',
    hint: '重新生成音频或 PDF 即可；文本字幕教学不受影响。',
    retryable: true,
  },
  INGEST_BLOCKED_PATH: {
    code: 'INGEST_BLOCKED_PATH',
    http: 422,
    title: '跳过了可疑路径',
    message: '仓库里存在可疑路径（路径穿越 / 设备名 / 符号链接）。',
    hint: '这些文件已被记录并跳过，不影响其它文件生成课程；在准备页的告警面板可以看到清单。',
    retryable: false,
  },
  CONTRACT_VIOLATION: {
    code: 'CONTRACT_VIOLATION',
    http: 502,
    title: '模型产出不合规范',
    message: 'Kernel 产出的结构不符合 schema，内部重试后仍失败。',
    hint: '重试通常就能通过；连续失败请到设置 → 诊断面板确认 Kernel 状态。',
    action: { label: '打开诊断面板', href: '/settings#doctor' },
    retryable: true,
  },
  IDEMPOTENCY_MISMATCH: {
    code: 'IDEMPOTENCY_MISMATCH',
    http: 422,
    title: '重复请求内容不一致',
    message: '同一个 Idempotency-Key 被用来发送了不同的请求体。',
    hint: '这是客户端问题：刷新页面重新发起即可（会自动生成新的幂等键）。',
    retryable: true,
  },
  PROFILE_CONFLICT: {
    code: 'PROFILE_CONFLICT',
    http: 409,
    title: '并发的配置切换冲突',
    message: '两次激活 profile 撞上了唯一索引。',
    hint: '再点一次即可，第二次会成功。',
    retryable: true,
  },
  // 第 20 个码（hardening spec P0-4）。`retryable: false` 是关键：重试同一个
  // 非法 offset 只会再拿到同一个 422；给用户一个"重试"按钮等于骗他。
  VALIDATION_FAILED: {
    code: 'VALIDATION_FAILED',
    http: 422,
    title: '请求参数不合法',
    message: '地址栏里的参数超出了允许范围。',
    hint: '分页规则：fts 模式用 offset（0–200），scan 模式用 cursor；其它筛选条件请看提示里的范围说明。',
    retryable: false,
  },
  INTERNAL: {
    code: 'INTERNAL',
    http: 500,
    title: '服务内部错误',
    message: '服务端出现未预期的错误。',
    hint: '带着下方错误编号（req_id）到设置 → 诊断面板查看日志位置，或直接重试。',
    retryable: true,
  },
  // BFF 自己合成的**传输**错误（不是上游错误体）：`/setup` 的"后端未就绪"
  // 视图靠它区分"进程没起来"与"后端报错了"。缺这一条会被降级成 INTERNAL，
  // 向导于是显示"服务内部错误"并丢掉重试入口。
  API_UNREACHABLE: {
    code: 'API_UNREACHABLE',
    http: 503,
    title: '后端未就绪',
    message: 'FastAPI 进程没有响应。',
    hint: '运行 .\\start.ps1 启动三进程，确认 http://127.0.0.1:8000/healthz 返回 ok，然后点重试。',
    action: { label: '查看启动手册', href: '/settings' },
    retryable: true,
  },
};

export const ERROR_CODES = Object.keys(ERROR_COPY) as ErrorCode[];

export function isErrorCode(value: unknown): value is ErrorCode {
  return typeof value === 'string' && value in ERROR_COPY;
}

/**
 * Fallback copy for a code we do not know yet — a new backend code must not
 * blank the UI (spec §5.5: unknown events are ignored, unknown codes degrade).
 */
export function errorCopy(code: string | undefined | null): ErrorCopy {
  if (isErrorCode(code)) return ERROR_COPY[code];
  return ERROR_COPY.INTERNAL;
}
