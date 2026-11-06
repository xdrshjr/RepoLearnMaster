/**
 * 能力探测与健康检查（spec §4.2 `src/health.ts`）。
 *
 * `/healthz` 的价值不在于"返回 200"，而在于**说清楚当前是什么状态**：
 * `coreVersion` 让 `start.ps1` 能校验包版本；`degraded` 让 Python 侧能在
 * A/B/C 三分支里选对路径；`tools` 让 Doctor 面板能显示"内核到底能干什么"（spec §3.5.3）。
 */

export interface CoreStatus {
  available: boolean;
  version: string | null;
  exports: string[];
  error: string | null;
}

export interface CapabilityReport {
  ok: boolean;
  coreVersion: string | null;
  coreAvailable: boolean;
  degraded: boolean;
  degradedReason: string | null;
  providers: string[];
  tools: string[];
  schemaVersion: number;
  maxConcurrentRuns: number;
  uptimeMs: number;
  activeRuns: number;
}

const startedAt = Date.now();

export function uptimeMs(): number {
  return Date.now() - startedAt;
}

export function buildHealth(input: {
  core: CoreStatus;
  providers: string[];
  tools: string[];
  activeRuns: number;
  maxConcurrentRuns: number;
  schemaVersion: number;
}): CapabilityReport {
  const degraded = !input.core.available;
  return {
    ok: true,
    coreVersion: input.core.version,
    coreAvailable: input.core.available,
    degraded,
    degradedReason: degraded ? (input.core.error ?? 'core unavailable') : null,
    providers: input.providers,
    tools: input.tools,
    schemaVersion: input.schemaVersion,
    maxConcurrentRuns: input.maxConcurrentRuns,
    uptimeMs: uptimeMs(),
    activeRuns: input.activeRuns,
  };
}
