"""TTS 适配器包。"""

from __future__ import annotations

from repolearn.providers.tts.doubao import DoubaoTts, TtsConfigIn, split_sentences, text_hash

__all__ = ["DoubaoTts", "TtsConfigIn", "split_sentences", "text_hash"]
