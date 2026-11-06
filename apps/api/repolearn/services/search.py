"""搜索的纯函数层（hardening spec §3.4.3）。

这个文件刻意**不碰 IO**：分流规则与表达式构造都是纯函数，因此能被单测咬住；
真正执行 SQL 的地方在 `services/course_service.py`。之所以要这样切，是因为搜索
这一轮要修的核心缺陷（G3）是"配置里说了 fts，代码里只有 LIKE，而 Doctor 还报 ok"。
一个"能算清楚自己该走哪条路"的纯函数，是让这种谎言再也编不下去的最小单位。

三条实测事实决定了这里的形状（SQLite 3.49.1 实测，见 spec 评审 E3）：

1. `trigram` 分词器可用，但**匹配单位是 3 字符**：`MATCH '"Ag"'`（2 字符）返回
   0 行**且不报错**。2 字中文查询（"缓存"、"异步"、"入口"）是本产品最高频的
   形态，直接交给 MATCH 就是"库里有、用户搜不到"——比慢严重一个数量级。
   因此必须按长度分流，并且分流结果要能回显（`mode` / `fallback_reason`）。
2. `MATCH` 是**表达式语言**：`-` 是 NOT、`*` 是前缀、`NEAR(...)` 是邻接。把用户
   输入直接拼进去，轻则结果错，重则跑出一个语法错 500。因此每个 token 都用
   双引号包裹并把内部 `"` 双写，让一切退化成语面量。
3. `MATCH` 与 `bm25()` 的参数**必须写表名**，写别名会 `no such column`。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

#: trigram 的最小匹配单位。小于它的查询只能走 `LIKE`。
MIN_TRIGRAM = 3

#: fts 模式下的 `offset` 上限（`limit ≤ 50` 时最多 4 页）。
#: 为什么不做 keyset 游标：`bm25` 是浮点分数，游标里编码浮点 + 索引变更会导致
#: 幽灵重复/漏行。把限制**显式暴露**给前端（`next_offset`），比藏在后端好。
MAX_OFFSET = 200

#: 高亮片段的最大长度。返回整段 512 字的摘要给前端做高亮，等于把"截断"这件事
#: 从服务端甩给浏览器。
HIGHLIGHT_MAX_LEN = 120

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Segment:
    """高亮片段：`marked=True` 的片段由前端渲染成 `<mark>`（**不返回 HTML**）。

    为什么不是返回 `<mark>` 字符串：那会诱导前端用 `dangerouslySetInnerHTML`，
    而 `title` / `summary` 来自 LLM 生成的文本——"LLM 输出不可信"是本仓库的硬
    规则（平台件 §3.12）。返回结构化片段，注入面直接消失。
    """

    text: str
    marked: bool


@dataclass(frozen=True)
class SearchPlan:
    """一次搜索该怎么做（**契约**，实现不得偏离，也不得"优化"成别的）。"""

    mode: Literal["none", "scan", "fts"]
    tokens: tuple[str, ...] = ()
    fts_expression: str | None = None
    like_pattern: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class FtsCapability:
    """FTS 能力探测结论（迁移、查询、Doctor 三处共用同一判据）。"""

    available: bool
    reason: str
    detail: str = ""


def normalize_query(raw: str | None) -> str:
    """归一化查询串：去首尾空白、内部空白压成一个空格。

    不做小写化：中文没有大小写，英文的匹配由 `LIKE`+`lower()` 与 trigram 的
    大小写折叠分别处理，在这里折一次会让"用户输英文大写却搜不到"变成长期缺陷。
    """
    return _WS.sub(" ", (raw or "").strip())


def tokenize(raw: str | None) -> tuple[str, ...]:
    text = normalize_query(raw)
    if not text:
        return ()
    return tuple(token for token in text.split(" ") if token)


def build_fts_expression(tokens: Sequence[str]) -> str:
    """把 tokens 变成 FTS5 的 `MATCH` 表达式：每个 token 加引号，用 AND 连接。

    `NEAR(`、`*`、`-`、`:`、`"` 全部退化为字面量——这正是我们要的：用户输入
    `a -b` 时应该按字面找"a -b"，而不是执行"a 减去 b"。
    """
    quoted = []
    for token in tokens:
        # 只有标点的 token 在 trigram 下不可能命中任何东西，却会把表达式拼成
        # `""""` 这种非法形状（实测：`unterminated string`）。直接丢掉它。
        if not any(ch.isalnum() for ch in token):
            continue
        cleaned = token.replace('"', '""')
        if cleaned:
            quoted.append(f'"{cleaned}"')
    return " AND ".join(quoted)


def build_like_pattern(raw: str | None) -> str | None:
    """`LIKE` 模式（小写）。用于 scan 分支与 fts 的短查询回落。"""
    text = normalize_query(raw).lower()
    if not text:
        return None
    return f"%{text}%"


def parse_sqlite_version(value: str | tuple[int, ...] | None) -> tuple[int, int, int]:
    """把 `sqlite_version` 归一成三元组。支持 `"3.49.1"` 与 `sqlite_version_info`。"""
    if isinstance(value, tuple) and value:
        parts = list(value)
    elif isinstance(value, str) and value.strip():
        parts = []
        for chunk in value.split("."):
            match = re.match(r"\d+", chunk.strip())
            parts.append(int(match.group(0)) if match else 0)
    else:
        parts = []
    while len(parts) < 3:
        parts.append(0)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def plan_search(raw: str | None, *, configured: str, sqlite_version: str) -> SearchPlan:
    """分流规则（spec §3.4.3 的规则表，逐行实现，顺序即语义）。

    | q | configured | 生效模式 | fallback_reason |
    |---|---|---|---|
    | 空/纯空白 | 任意 | none | — |
    | 1–2 字符 | fts | scan | query_too_short |
    | 1–2 字符 | scan | scan | — |
    | ≥3 字符 | fts | fts | — |
    | ≥3 字符 | scan | scan | — |
    | 任意 | fts 但 SQLite < 3.34 | scan | sqlite_too_old |
    """
    tokens = tokenize(raw)
    if not tokens:
        return SearchPlan(mode="none")

    like_pattern = build_like_pattern(raw)
    wants_fts = (configured or "scan") == "fts"
    if not wants_fts:
        return SearchPlan(mode="scan", tokens=tokens, like_pattern=like_pattern)

    version = parse_sqlite_version(sqlite_version)
    if version < (3, 34):
        # 版本不够时**连表都没建**（迁移里的能力探测会跳过建表），所以查询期
        # 必须回落，否则每个请求都会 `no such table: course_search`。
        return SearchPlan(
            mode="scan",
            tokens=tokens,
            like_pattern=like_pattern,
            fallback_reason="sqlite_too_old",
        )

    joined = " ".join(tokens)
    # 两个条件都必须满足才走 fts：
    #   ① 整串够长（`"缓存策略"` 这类 ≥3 字的中文查询）；
    #   ② **每个 token** 都够长——因为 `AND` 连接意味着任意一个短 token 都会让
    #      整个查询返回 0 行（trigram 的最小单位是 3 字符）。只判整串长度会让
    #      `a -b`（4 字符、两个 token）走上一条永远空结果的路径。
    if len(joined) < MIN_TRIGRAM or any(len(token) < MIN_TRIGRAM for token in tokens):
        # 2 字查询是最高频的中文形态，而 trigram 在这个长度上静默返回 0 行。
        return SearchPlan(
            mode="scan",
            tokens=tokens,
            like_pattern=like_pattern,
            fallback_reason="query_too_short",
        )

    expression = build_fts_expression(tokens)
    if not expression:
        return SearchPlan(
            mode="scan",
            tokens=tokens,
            like_pattern=like_pattern,
            fallback_reason="query_too_short",
        )

    return SearchPlan(
        mode="fts",
        tokens=tokens,
        fts_expression=expression,
        like_pattern=like_pattern,
    )


def _snippet(text: str, token: str, *, max_len: int) -> list[Segment]:
    """在以 `token` 为中心的窗口里切出高亮片段。"""
    lowered = text.lower()
    haystack = lowered.find(token.lower())
    if haystack < 0:
        return []
    start = max(0, haystack - max_len // 3)
    end = min(len(text), start + max_len)
    start = max(0, end - max_len)
    window = text[start:end]
    if not window:
        return []
    window_lower = window.lower()
    segments: list[Segment] = []
    cursor = 0
    needle = token.lower()
    while True:
        hit = window_lower.find(needle, cursor)
        if hit < 0:
            break
        if hit > cursor:
            segments.append(Segment(text=window[cursor:hit], marked=False))
        segments.append(Segment(text=window[hit : hit + len(token)], marked=True))
        cursor = hit + len(token)
        if len(segments) > 40:  # 防御：单个 token 出现几十次时不要把响应撑大
            break
    if cursor < len(window):
        segments.append(Segment(text=window[cursor:], marked=False))
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    if prefix and segments:
        segments[0] = Segment(text=prefix + segments[0].text, marked=segments[0].marked)
    if suffix and segments:
        segments[-1] = Segment(text=segments[-1].text + suffix, marked=segments[-1].marked)
    return segments


def highlight_segments(text: str, tokens: Sequence[str], *, max_len: int = HIGHLIGHT_MAX_LEN) -> list[Segment]:
    """把命中文本切成 `[{text, marked}]`（**不返回 HTML**，见 `Segment` 的注释）。

    多个 token 时取"第一个能在文本里找到的 token"作为高亮中心：同时高亮多个
    词会让片段被切成碎块，在 120 字的窗口里反而读不懂。没有命中就返回一段
    未标记的普通文本——空列表会让前端把整行渲染成空白。
    """
    plain = (text or "").strip()
    if not plain:
        return []
    for token in tokens:
        if not token:
            continue
        segments = _snippet(plain, token, max_len=max_len)
        if segments:
            return segments
    return [Segment(text=plain[:max_len], marked=False)]


# --------------------------------------------------------------------------- #
# 能力探测                                                                     #
# --------------------------------------------------------------------------- #


def sqlite_supports_trigram() -> bool:
    """版本层面是否可能支持 trigram（≥ 3.34）。

    只看版本不够：编译期没带 FTS5 或没带 trigram 时版本号一样是新的。因此迁移
    里还会真建一张临时表试一次；这里只做"快速否定"。
    """
    return sqlite3.sqlite_version_info >= (3, 34)


async def fts_capability(session) -> FtsCapability:
    """以**库里的实际状态**为准判断 fts 能不能用。

    为什么不信 `settings.search`：那正是那个"说了 fts 却没人实现"的开关。判定
    顺序固定为"表在不在 → 版本够不够 → 配置想要什么"，任何一环不满足都返回
    `available=False` 并带上原因，好让 Doctor 与响应都能把它显示出来。
    """
    from sqlalchemy import text

    from repolearn.services.search_ddl import TABLE_EXISTS_SQL

    if not sqlite_supports_trigram():
        return FtsCapability(
            available=False,
            reason="sqlite_too_old",
            detail=f"SQLite {sqlite3.sqlite_version} < 3.34，没有 FTS5 trigram",
        )
    try:
        exists = (await session.execute(text(TABLE_EXISTS_SQL))).scalar() or 0
    except Exception as exc:  # noqa: BLE001 - 库还没迁移时不该让页面崩
        return FtsCapability(available=False, reason="probe_failed", detail=str(exc)[:160])
    if not int(exists):
        return FtsCapability(
            available=False,
            reason="index_missing",
            detail="`course_search` 不存在（迁移 0002 跳过了建表，或还没跑）",
        )
    return FtsCapability(available=True, reason="ok", detail=f"SQLite {sqlite3.sqlite_version} · FTS5 trigram")


__all__ = [
    "FtsCapability",
    "HIGHLIGHT_MAX_LEN",
    "MAX_OFFSET",
    "MIN_TRIGRAM",
    "SearchPlan",
    "Segment",
    "build_fts_expression",
    "build_like_pattern",
    "fts_capability",
    "highlight_segments",
    "normalize_query",
    "parse_sqlite_version",
    "plan_search",
    "sqlite_supports_trigram",
    "tokenize",
]
