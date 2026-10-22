"""Lossless, bounded text segments for speech and translation.

Supertonic's sentence splitter does not bound a single long sentence. Keep
whitespace-delimited words intact, including Vietnamese combining characters,
and use punctuation/word boundaries before resorting to a hard CJK split.
"""
from __future__ import annotations

import re
import unicodedata


def split_text(text: str, limit: int = 300) -> list[str]:
    if limit < 16:
        raise ValueError("Text segment limit must be at least 16")
    remaining = unicodedata.normalize("NFC", text).strip()
    chunks: list[str] = []
    while len(remaining) > limit:
        window = remaining[:limit + 1]
        # Prefer complete sentences/clauses in the latter half of the window.
        boundaries = [match.end() for match in re.finditer(r"[.!?。！？;；,，:：](?:\s+|(?=[\u3400-\u9fff\u3040-\u30ff]))", window)]
        cut = next((position for position in reversed(boundaries) if limit // 2 <= position <= limit), 0)
        if not cut:
            spaces = [match.start() for match in re.finditer(r"\s+", window)]
            cut = spaces[-1] if spaces else limit
        # Never cut before a combining mark. Normalization covers Vietnamese;
        # this also protects other scripts that keep decomposed diacritics.
        while cut > 0 and cut < len(remaining) and unicodedata.combining(remaining[cut]):
            cut -= 1
        if not cut:
            raise ValueError("Cannot safely split text at a character boundary")
        piece = remaining[:cut].strip()
        if piece:
            chunks.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
