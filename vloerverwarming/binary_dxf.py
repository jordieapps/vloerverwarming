from __future__ import annotations

import io
import struct

SENTINEL = b"AutoCAD Binary DXF\r\n\x1a\x00"


def is_binary_dxf(data: bytes) -> bool:
    return data.startswith(SENTINEL)


def _string(data: bytes, pos: int) -> tuple[str, int]:
    end = data.index(b"\x00", pos)
    raw = data[pos:end]
    try:
        return raw.decode("utf-8"), end + 1
    except UnicodeDecodeError:
        return raw.decode("cp1252"), end + 1


def _chunk(data: bytes, pos: int) -> tuple[bytes, int]:
    n = data[pos]
    return data[pos + 1 : pos + 1 + n], pos + 1 + n


def _double(data: bytes, pos: int) -> tuple[float, int]:
    (v,) = struct.unpack_from("<d", data, pos)
    return v, pos + 8


def _int16(data: bytes, pos: int) -> tuple[int, int]:
    (v,) = struct.unpack_from("<h", data, pos)
    return v, pos + 2


def _int32(data: bytes, pos: int) -> tuple[int, int]:
    (v,) = struct.unpack_from("<i", data, pos)
    return v, pos + 4


def _int64(data: bytes, pos: int) -> tuple[int, int]:
    (v,) = struct.unpack_from("<q", data, pos)
    return v, pos + 8


def _fmt_double(v: float) -> str:
    if v != v or v in (float("inf"), float("-inf")):
        return "0.0"
    if v == int(v) and abs(v) < 1e15:
        return f"{v:.1f}"
    return repr(v)


def binary_dxf_to_stream(data: bytes) -> io.StringIO:
    if not is_binary_dxf(data):
        raise ValueError("Geen binaire DXF (ontbrekende kenmerk)")
    pos = len(SENTINEL)
    out: list[str] = []
    append = out.append
    n = len(data)
    while pos + 2 <= n:
        (code,) = struct.unpack_from("<h", data, pos)
        pos += 2
        if code <= 9:
            val, pos = _string(data, pos)
        elif code <= 59:
            v, pos = _double(data, pos)
            val = _fmt_double(v)
        elif code <= 79:
            v, pos = _int16(data, pos)
            val = str(v)
        elif code <= 99:
            v, pos = _int32(data, pos)
            val = str(v)
        elif code <= 109:
            val, pos = _string(data, pos)
        elif code <= 149:
            v, pos = _double(data, pos)
            val = _fmt_double(v)
        elif code <= 169:
            v, pos = _int64(data, pos)
            val = str(v)
        elif code <= 179:
            v, pos = _int16(data, pos)
            val = str(v)
        elif code <= 239:
            v, pos = _double(data, pos)
            val = _fmt_double(v)
        elif code <= 289:
            v, pos = _int16(data, pos)
            val = str(v)
        elif code <= 299:
            val = str(data[pos])
            pos += 1
        elif code <= 309:
            val, pos = _string(data, pos)
        elif code <= 319:
            chunk, pos = _chunk(data, pos)
            val = chunk.hex().upper()
        elif code <= 369:
            val, pos = _string(data, pos)
        elif code <= 389:
            v, pos = _int16(data, pos)
            val = str(v)
        elif code <= 399:
            val, pos = _string(data, pos)
        elif code <= 409:
            v, pos = _int16(data, pos)
            val = str(v)
        elif code <= 419:
            val, pos = _string(data, pos)
        elif code <= 429:
            v, pos = _int32(data, pos)
            val = str(v)
        elif code <= 439:
            val, pos = _string(data, pos)
        elif code <= 449:
            v, pos = _int32(data, pos)
            val = str(v)
        elif code <= 459:
            v, pos = _int32(data, pos)
            val = str(v)
        elif code <= 469:
            v, pos = _double(data, pos)
            val = _fmt_double(v)
        elif code <= 481:
            val, pos = _string(data, pos)
        elif code == 999:
            val, pos = _string(data, pos)
        elif code <= 1009:
            val, pos = _string(data, pos)
        elif code <= 1059:
            v, pos = _double(data, pos)
            val = _fmt_double(v)
        elif code <= 1070:
            v, pos = _int16(data, pos)
            val = str(v)
        elif code == 1071:
            v, pos = _int32(data, pos)
            val = str(v)
        else:
            raise ValueError(f"Onbekende groepcode {code} op bytepositie {pos}")
        append(f"{code}\n{val}\n")
    return io.StringIO("".join(out))
