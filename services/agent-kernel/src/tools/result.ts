/**
 * 工具结果的小封装。
 *
 * core 的 `ToolExecuteFn` 要求返回 `ToolResult`（`{content:[{type:'text',text}]}`），
 * 而不是任意对象。我们的工具一律返回 **JSON 字符串**：模型读 JSON 比读自然语言
 * 稳定得多，而且 `truncated`/`blocked` 这类标记能被上层（Python）在日志里 grep 到。
 */

import { errorResult, textResult } from '@aragon-agent/core';

export interface ToolResultLike {
  content: Array<{ type: 'text'; text: string } | { type: 'image'; mediaType: string; data: string }>;
  isError?: boolean;
}

export function ok(payload: Record<string, unknown>): ToolResultLike {
  return textResult(JSON.stringify(payload)) as ToolResultLike;
}

export function fail(message: string, extra: Record<string, unknown> = {}): ToolResultLike {
  // `errorResult` 会把消息包成 "Error: ..."，保持与 core 其它工具一致的形状。
  const base = errorResult(message) as ToolResultLike;
  if (Object.keys(extra).length === 0) return base;
  const text = base.content[0];
  const suffix = JSON.stringify(extra);
  return {
    content: [{ type: 'text', text: text && text.type === 'text' ? `${text.text} ${suffix}` : suffix }],
    isError: true,
  };
}

/** 从 ToolResult 里取回 JSON（测试与上层调试用）。 */
export function readPayload(result: ToolResultLike): Record<string, unknown> {
  const first = result.content[0];
  if (!first || first.type !== 'text') return {};
  const raw = first.text.replace(/^Error:\s*/, '');
  const start = raw.indexOf('{');
  if (start < 0) return {};
  try {
    return JSON.parse(raw.slice(start)) as Record<string, unknown>;
  } catch {
    return {};
  }
}
