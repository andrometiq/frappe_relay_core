"""Paragraph-first chunking by characters, with no tokenizer. A chunk starts with the tail of the one before it."""
import re

SIZE = 1200
OVERLAP = 150
PARAGRAPH = re.compile(r'\n\s*\n')
SENTENCE = re.compile(r'(?<=[.!?।॥])\s+')


def chunk_text(text: str, size: int = SIZE, overlap: int = OVERLAP) -> list[str]:
    """Chunks of at most `size` characters. Whole paragraphs first, then sentences, then words."""
    if size < 1 or not 0 <= overlap < size:
        raise ValueError('Use a chunk size above 0 and an overlap below it')
    chunks, current = [], ''
    for unit, separator in units(text or '', size):
        if not current or len(current) + len(separator) + len(unit) <= size:
            current = current + separator + unit if current else unit
            continue
        chunks.append(current)
        tail = tail_of(current, min(overlap, size - len(unit) - len(separator)))
        current = tail + separator + unit if tail else unit
    return chunks + [current] if current else chunks


def units(text: str, size: int) -> list[tuple[str, str]]:
    """(piece, separator from the piece before) in text order; each piece fits in `size`."""
    found = []
    for paragraph in (part.strip() for part in PARAGRAPH.split(text)):
        sentences = [paragraph] if len(paragraph) <= size else SENTENCE.split(paragraph)
        pieces = [piece for sentence in sentences for piece in split_words(sentence.strip(), size) if piece]
        found += [(piece, ' ' if index else '\n\n') for index, piece in enumerate(pieces)]
    return found


def split_words(text: str, size: int) -> list[str]:
    """Cut text longer than `size` at the last space before the limit, or hard where it has none."""
    pieces = []
    while len(text) > size:
        cut = text.rfind(' ', 0, size + 1)
        cut = cut if cut > 0 else size
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    return pieces + [text]


def tail_of(text: str, length: int) -> str:
    """At most `length` final characters of `text`, starting at a word."""
    if length <= 0:
        return ''
    if len(text) <= length:
        return text
    tail = text[-length:]
    if text[-length - 1].isspace():
        return tail.strip()
    parts = tail.split(None, 1)
    return parts[1].strip() if len(parts) == 2 else ''
