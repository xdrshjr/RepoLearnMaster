"""书籍排版（spec §3.9 S5 / T-BOOK-2）。

分章规则刻意保持"确定性"：章节 = 课程的 4 个 section，正文 = 每课时的
narration 段落 + 代码要点 + 架构图。**不让模型重写一遍**——重写等于再花一遍
课程生成的钱，而 PRD 要的是"把课程变书"，不是"再写一本书"。

`source_refs` 必须非空（T-BOOK-2）：一本书如果指不回源码，它就不是"可追溯"的。
"""

from __future__ import annotations

import html
from collections import defaultdict

SECTION_TITLES = {
    "overview": "第一部分 · 宏观架构",
    "walkthrough": "第二部分 · 全局走读",
    "deep_dive": "第三部分 · 深入源码",
    "recap": "第四部分 · 复盘与进阶",
}

PRESET_DEPTH = {"standard": 1, "deep": 3}


def _words(text: str) -> int:
    return len([w for w in str(text).split()]) + len(str(text)) // 2


def build_chapters(
    *,
    course_title: str,
    commit_sha: str,
    repo_full_name: str,
    sections: list[dict],
    lessons: list[dict],
    preset: str = "standard",
) -> list[dict]:
    depth = PRESET_DEPTH.get(preset, 1)
    by_section: dict[str, list[dict]] = defaultdict(list)
    for lesson in lessons:
        by_section[str(lesson.get("section_key", "overview"))].append(lesson)

    chapters: list[dict] = []
    for index, section in enumerate(sections or [], start=1):
        key = str(section.get("key", f"section_{index}"))
        title = SECTION_TITLES.get(key, str(section.get("title", key)))
        blocks: list[dict] = []
        refs: list[dict] = []

        blocks.append(
            {
                "type": "md",
                "text": (
                    f"本部分包含 {len(by_section.get(key, []))} 个课时，"
                    f"预计 {int(section.get('minutes', 0) or 0)} 分钟。"
                ),
            }
        )
        for lesson_order, lesson in enumerate(by_section.get(key, []), start=1):
            blocks.append({"type": "md", "text": f"## {index}.{lesson_order} {lesson.get('title', '')}"})
            if lesson.get("goal"):
                blocks.append({"type": "md", "text": f"> 学习目标：{lesson['goal']}"})
            for step in (lesson.get("steps") or [])[:depth + 1]:
                segments = [s for s in (step.get("segments") or []) if isinstance(s, dict)]
                for seg in segments[: 2 + depth]:
                    text = str(seg.get("text", "")).strip()
                    if text:
                        blocks.append({"type": "md", "text": text})
                    focus = seg.get("focus")
                    if isinstance(focus, dict) and focus.get("file"):
                        refs.append(
                            {
                                "file": focus["file"],
                                "line_start": int(focus.get("line_start", 1) or 1),
                                "line_end": int(focus.get("line_end", focus.get("line_start", 1)) or 1),
                            }
                        )
                for note in (step.get("code_notes") or [])[:depth]:
                    if not isinstance(note, dict) or not note.get("file"):
                        continue
                    blocks.append(
                        {
                            "type": "code",
                            "text": f"{note['file']}:{note.get('line', 1)}  {note.get('text', '')}",
                            "lang": "text",
                            "caption": f"{note['file']} 第 {note.get('line', 1)} 行",
                        }
                    )
                    refs.append(
                        {
                            "file": note["file"],
                            "line_start": int(note.get("line", 1) or 1),
                            "line_end": int(note.get("line", 1) or 1),
                        }
                    )
                board = step.get("board") or {}
                if isinstance(board, dict) and board.get("mermaid") and depth > 1:
                    blocks.append(
                        {
                            "type": "figure",
                            "text": board["mermaid"],
                            "caption": "架构示意（Mermaid 源码）",
                        }
                    )
            files = [f.get("path") for f in (lesson.get("files") or []) if isinstance(f, dict)]
            if files:
                blocks.append({"type": "md", "text": "涉及文件：" + "、".join(f"`{f}`" for f in files[:8])})

        blocks.append(
            {
                "type": "md",
                "text": (
                    f"\n---\n\n*源仓库：{repo_full_name or '—'} · Commit：{commit_sha[:12] or '—'}*\n\n"
                    "本文内容由 RepoLearn 基于源码自动生成；所有结论均标注了来源文件与行号，"
                    "「教学模拟」部分为讲解需要而补的示例值，不代表程序真实运行结果。"
                ),
            }
        )
        chapters.append(
            {
                "key": key,
                "title": title,
                "blocks": blocks,
                "source_refs": refs[:200],
                "word_count": sum(_words(b.get("text", "")) for b in blocks),
            }
        )
    return chapters


def blocks_to_html(blocks: list[dict]) -> str:
    """把结构化块渲染成 HTML。**不插入原始 HTML**：全部 escape 后按需包装。"""
    out: list[str] = []
    for block in blocks:
        kind = str(block.get("type", "md"))
        text = str(block.get("text", ""))
        if kind == "md":
            for paragraph in text.split("\n"):
                p = paragraph.strip()
                if not p:
                    continue
                if p.startswith("### "):
                    out.append(f"<h4>{html.escape(p[4:])}</h4>")
                elif p.startswith("## "):
                    out.append(f"<h3>{html.escape(p[3:])}</h3>")
                elif p.startswith("# "):
                    out.append(f"<h2>{html.escape(p[2:])}</h2>")
                elif p.startswith("> "):
                    out.append(f"<blockquote>{html.escape(p[2:])}</blockquote>")
                elif p == "---":
                    out.append("<hr/>")
                else:
                    out.append(f"<p>{_inline(p)}</p>")
        elif kind == "code":
            caption = html.escape(str(block.get("caption", "")))
            out.append(
                (f"<p class='ref'>{caption}</p>" if caption else "")
                + f"<pre><code>{html.escape(text)}</code></pre>"
            )
        elif kind == "figure":
            out.append(f"<pre class='figure'>{html.escape(text)}</pre>")
        elif kind == "table":
            out.append(f"<pre>{html.escape(text)}</pre>")
    return "".join(out)


def _inline(text: str) -> str:
    """极小号的内联标记：反引号 + 粗体。够用，且不会引入 XSS。"""
    import re

    safe = html.escape(text)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", safe)
    return safe
