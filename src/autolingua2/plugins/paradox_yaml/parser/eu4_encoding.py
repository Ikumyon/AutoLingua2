"""EU4 escape encoding, ported from EU4dll's escape_tool.cpp (forUtf8=false).

Source: https://github.com/Celec7/EU4dll/blob/9c1eda2127f616a52bd2dd9fdcca2acf25e1918f/src/plugin/escape_tool.cpp

MIT License

Copyright (c) 2018 ☆ (ゝω・)v

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations


_UNSAFE_BYTES = frozenset({
    0xA4, 0xA3, 0xA7, 0x24, 0x5B, 0x00, 0x5C, 0x20, 0x0D, 0x0A,
    0x22, 0x7B, 0x7D, 0x40, 0x80, 0x7E, 0x2F, 0x5F, 0xBD, 0x3B,
    0x5D, 0x3D, 0x23, 0x3F, 0x3A, 0x3C, 0x3E, 0x2A, 0x7C,
})
_CP1252_MAPPING = {
    ord(bytes([value]).decode("cp1252")): value
    for value in range(0x80, 0xA0) if value not in {0x81, 0x8D, 0x8F, 0x90, 0x9D}
}


def encode_eu4_escape(text: str) -> bytes:
    """Encode BMP characters without silently replacing unsupported text."""
    result = bytearray()
    for character in text:
        code = ord(character)
        if code == 0 or code > 0xFFFF or 0xD800 <= code <= 0xDFFF:
            raise ValueError(f"EU4 CJKエスケープで出力できない文字です: U+{code:04X}")
        mapped = _CP1252_MAPPING.get(code)
        if mapped is not None:
            result.append(mapped)
            continue
        if 0x100 < code < 0xA00:
            code += 0xE000
        high, low = code >> 8, code & 0xFF
        if high == 0:
            result.append(low)
            continue
        marker = 0x10
        if high in _UNSAFE_BYTES:
            marker += 2
            high = (high - 9) & 0xFF
        if low in _UNSAFE_BYTES:
            marker += 1
            low = (low + 14) & 0xFF
        result.extend((marker, low, high))
    return bytes(result)
