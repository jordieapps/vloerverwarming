from __future__ import annotations

import math

import ezdxf
from shapely.geometry import LineString, Point, Polygon

from .geometry import INSUNITS_TO_UNIT, shoelace_area
from .heating import RoomResult


LAYER_PIPE = "VV_LANG"
LAYER_ROOM = "VV_RUIMTE"
LAYER_TEXT = "VV_TEKST"


class DrawingError(Exception):
    pass


def open_drawing(path: str, unit: str | None = None):
    low = path.lower()
    try:
        if low.endswith(".dwg"):
            from ezdxf.addons import odafc

            doc = odafc.readfile(path)
        elif low.endswith(".dxf"):
            doc = ezdxf.readfile(path)
        else:
            raise DrawingError("Ondersteunde bestanden: .dxf en .dwg")
    except DrawingError:
        raise
    except Exception as exc:
        raise DrawingError(str(exc)) from exc
    if unit is None:
        insunits = doc.header.get("$INSUNITS", 0) or 0
        unit = INSUNITS_TO_UNIT.get(insunits, "mm")
    return doc, unit


def save_drawing(doc, path: str) -> None:
    if str(path).lower().endswith(".dwg"):
        from ezdxf.addons import odafc

        odafc.export_dwg(doc, path)
    else:
        doc.saveas(path)


def _polyline_points(entity) -> list[tuple[float, float]]:
    try:
        return [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]
    except Exception:
        return []


def detect_rooms(doc, layer: str | None = None, min_area_m2: float = 0.5, unit: str = "mm"):
    min_area_units = min_area_m2 / (0.001 if unit == "mm" else 0.01 if unit == "cm" else 1.0) ** 2
    rooms = []
    for entity in doc.modelspace():
        etype = entity.dxftype()
        if etype not in ("LWPOLYLINE", "POLYLINE"):
            continue
        if layer and entity.dxf.layer.lower() != layer.lower():
            continue
        if not bool(getattr(entity, "closed", False)):
            continue
        points = _polyline_points(entity)
        if len(points) < 3:
            continue
        area_units = abs(shoelace_area(points))
        if area_units < min_area_units:
            continue
        name = ""
        rooms.append((entity.dxf.layer, Polygon(points), entity))
    return rooms


def ensure_layers(doc) -> None:
    layers = {LAYER_PIPE: 1, LAYER_ROOM: 3, LAYER_TEXT: 2}
    for name, color in layers.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)


def add_room_result(doc, result: RoomResult) -> None:
    ensure_layers(doc)
    unit = INSUNITS_TO_UNIT.get(doc.header.get("$INSUNITS", 0) or 0, "mm")
    u = unit_to_m(unit)
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(x, y) for x, y in result.inset_polygon.exterior.coords],
        close=True,
        dxfattribs={"layer": LAYER_ROOM, "lineweight": 0},
    )
    msp.add_lwpolyline(
        result.path.as_xyb(),
        format="xyb",
        dxfattribs={"layer": LAYER_PIPE, "lineweight": 25},
    )
    xs = [p[0] for p in result.path.points]
    ys = [p[1] for p in result.path.points]
    text = (
        f"{result.name}: {result.area_m2:.2f} m² | "
        f"{result.pipe_length_m:.1f} m | {result.m_per_m2:.2f} m/m²"
    )
    msp.add_mtext(
        text,
        dxfattribs={"layer": LAYER_TEXT, "char_height": 0.2 / u},
    ).set_location((min(xs), max(ys) + 0.3 / u), attachment_point=1)


def unit_to_m(unit: str) -> float:
    return {"mm": 0.001, "cm": 0.01, "m": 1.0}[unit]
