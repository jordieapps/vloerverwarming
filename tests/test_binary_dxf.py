import io
import struct

import ezdxf

from vloerverwarming.binary_dxf import SENTINEL, binary_dxf_to_stream, is_binary_dxf


def _entry(code: int, value: bytes) -> bytes:
    return struct.pack("<h", code) + value


def test_is_binary_dxf():
    assert is_binary_dxf(SENTINEL + b"whatever")
    assert not is_binary_dxf(b"0\nSECTION\n")


def test_minimal_binary_dxf_roundtrip():
    data = SENTINEL
    data += _entry(0, b"SECTION\x00")
    data += _entry(2, b"HEADER\x00")
    data += _entry(9, b"$ACADVER\x00") + _entry(1, b"AC1032\x00")
    data += _entry(9, b"$INSUNITS\x00") + _entry(70, struct.pack("<h", 4))
    data += _entry(0, b"ENDSEC\x00")
    data += _entry(0, b"EOF\x00")
    stream = binary_dxf_to_stream(data)
    doc = ezdxf.read(stream)
    assert doc.dxfversion == "AC1032"
    assert doc.header.get("$INSUNITS") == 4


def test_binary_with_doubles_and_entities():
    data = SENTINEL
    data += _entry(0, b"SECTION\x00")
    data += _entry(2, b"ENTITIES\x00")
    data += _entry(0, b"LINE\x00")
    data += _entry(8, b"0\x00")
    data += _entry(10, struct.pack("<d", 1500.0))
    data += _entry(20, struct.pack("<d", 2500.5))
    data += _entry(11, struct.pack("<d", 4500.0))
    data += _entry(21, struct.pack("<d", 2500.5))
    data += _entry(0, b"ENDSEC\x00")
    data += _entry(0, b"EOF\x00")
    doc = ezdxf.read(binary_dxf_to_stream(data))
    line = doc.modelspace().query("LINE").first
    assert line.dxf.start.x == 1500.0
    assert line.dxf.start.y == 2500.5
    assert line.dxf.end.x == 4500.0
