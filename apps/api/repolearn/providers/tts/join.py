"""把多段 MP3 拼成一条音轨（spec §3.8「配音降级为字幕」的正面实现）。

为什么需要它：豆包 TTS 是**按句**合成的，一次调用只返回一句话的音频。而播放器
的时间轴是**按步**推进的——一步里有 2~4 个 segment，用户点"暂停/拖动"命中的是
这一步的音轨。若把整课 12 段直接拼起来，`step.audio` 的 duration 与 url 就对不上：
url 只指向第一句，duration 却是全课总和，播放器会以为音轨有 3 分钟、实际 8 秒就静音。

MP3 是帧序列，帧与帧之间没有容器级索引，因此**帧级拼接**是合法且被所有播放器
支持的（这也是 HLS 之前广播领域拼 MP3 的老办法）。唯一要处理的是每段开头的
ID3v2 标签：它描述的是"这一段的元数据"，留在中间会让部分解码器读到脏字节。
"""

from __future__ import annotations

from collections.abc import Iterable

ID3V2 = b"ID3"
ID3V1_SIZE = 128


def strip_id3(data: bytes) -> bytes:
    """去掉 ID3v2（头部）与 ID3v1（尾部 128 字节）标签，只留音频帧。"""
    if not data:
        return b""
    out = data
    if len(out) >= 10 and out[:3] == ID3V2:
        # ID3v2 size 是 4 个 synchsafe 字节（每字节只用低 7 位）
        size = (
            ((out[6] & 0x7F) << 21)
            | ((out[7] & 0x7F) << 14)
            | ((out[8] & 0x7F) << 7)
            | (out[9] & 0x7F)
        )
        footer = 10 if out[5] & 0x10 else 0
        out = out[10 + size + footer :]
    if len(out) > ID3V1_SIZE and out[-ID3V1_SIZE : -ID3V1_SIZE + 3] == b"TAG":
        out = out[:-ID3V1_SIZE]
    return out


def join_mp3(chunks: Iterable[bytes]) -> bytes:
    """按顺序拼接多段 MP3，去掉每段的标签。全空时返回空字节串。"""
    return b"".join(strip_id3(chunk) for chunk in chunks if chunk)


__all__ = ["ID3V1_SIZE", "join_mp3", "strip_id3"]
