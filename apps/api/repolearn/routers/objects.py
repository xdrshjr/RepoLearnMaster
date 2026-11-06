"""二进制对象代理（spec §5.2 / §5.3 "Range/ETag 契约"）。

**浏览器不直接访问这个端点**：契约里永远是 `/api/objects/<kind>/<name>`，
由 BFF 转到这里。这三个层级的写法区别是刻意的（P1-4）：
* 契约（前端可见）：`/api/objects/...`
* BFF（Next.js）：`/v1/objects/...`
* 磁盘：`var/objects/...`

四个头缺一不可，否则播放器 seek 会退化成"从头重新加载"：
`Accept-Ranges: bytes` 恒返回；`Range` → `206` + `Content-Range`；区间非法 → `416`
+ `Content-Range: bytes */total`；`If-None-Match` 命中 → `304`。
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse

from repolearn.core.errors import AppError
from repolearn.routers.deps import require_internal_token
from repolearn.services import object_store

router = APIRouter(prefix="/v1/objects", tags=["objects"], dependencies=[Depends(require_internal_token)])

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")

MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".json": "application/json",
}


def _mime(key: str) -> str:
    for suffix, mime in MIME.items():
        if key.endswith(suffix):
            return mime
    return "application/octet-stream"


@router.get("/{kind}/{name:path}")
async def get_object(
    kind: str,
    name: str,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    try:
        etag = object_store.etag_for(kind, name)
    except object_store.ObjectMissing as exc:
        raise AppError("OBJECT_MISSING", f"对象不存在：{name}", status=404) from exc
    except ValueError as exc:
        raise AppError("OBJECT_MISSING", f"非法的对象路径：{exc}", status=404) from exc

    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Cache-Control": "private, max-age=3600",
    }
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers=headers)

    if not range_header:
        try:
            total = object_store.size(kind, name)
        except ValueError as exc:
            raise AppError("OBJECT_MISSING", str(exc), status=404) from exc
        data = object_store.get(kind, name)
        return Response(
            content=data,
            media_type=_mime(name),
            headers={**headers, "Content-Length": str(total)},
        )

    match = _RANGE_RE.match(range_header.strip())
    if not match:
        total = object_store.size(kind, name)
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{total}"},
        )
    start_raw, end_raw = match.group(1), match.group(2)
    total = object_store.size(kind, name)
    try:
        if not start_raw:
            # `bytes=-N` 是"最后 N 字节"，这里不支持——返回 416 比猜错更安全
            raise ValueError("suffix ranges are not supported")
        start = int(start_raw)
        end = int(end_raw) if end_raw else total - 1
        result = object_store.read_range(kind, name, start, end)
    except (ValueError, object_store.ObjectMissing):
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{total}"},
        )
    headers["Content-Range"] = f"bytes {result.start}-{result.end}/{result.total}"
    headers["Content-Length"] = str(len(result.data))
    return StreamingResponse(
        iter([result.data]),
        status_code=206,
        media_type=_mime(name),
        headers=headers,
    )
