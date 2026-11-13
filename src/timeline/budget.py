"""Conservative character-based input estimate and whole-turn planning."""

import re
import unicodedata


_WORD = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")


def estimate_tokens(text):
    total, index = 0, 0
    while index < len(text):
        word = _WORD.match(text, index)
        if word:
            total += 2
            index = word.end()
            continue
        char = text[index]
        code = ord(char)
        cjk = (0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or
               0x20000 <= code <= 0x323AF or 0x3000 <= code <= 0x30FF or
               0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F or
               0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F or
               0xA960 <= code <= 0xA97F or 0xAC00 <= code <= 0xD7FF)
        total += 1 if (char.isspace() or char.isdigit() or
                       unicodedata.category(char).startswith('P') or not cjk) else 2
        index += 1
    return total


def plan_groups(segments, context_size, input_text):
    """Greedily plan contiguous segments; input_text(group) is the exact request input."""
    if not segments:
        return []
    if not context_size:
        return [list(segments)]
    limit = context_size // 2
    groups, current = [], []
    for segment in segments:
        proposed = current + [segment]
        if current and estimate_tokens(input_text(proposed)) > limit:
            groups.append(current)
            current = [segment]
        else:
            current = proposed
    if current:
        groups.append(current)
    return groups
