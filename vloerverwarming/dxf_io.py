from __future__ import annotations

import ezdxf
from ezdxf.enums import TextEntityAlignment

from . import binary_dxf
from .geometry import INSUNITS_TO_UNIT, shoelace_area
from .heating import RoomResult


LAYER_PIPE = "VV_LANG"
LAYER_ROOM = "VV_RUIMTE"
LAYER_TEXT = "VV_TEKST"
LAYER_SUPPLY = "VV_AANVOER"
LAYER_MANIFOLD = "VV_VERDELER"


class DrawingError(Exception):
    pass


def open_drawing(path: str, unit: str | None = None):
    low = path.lower()
    try:
        if low.endswith(".dwg"):
            from ezdxf.addons import odafc

            doc = odafc.readfile(path)
        elif low.endswith(".dxf"):
            with open(path, "rb") as fp:
                head = fp.read(22)
            if head.startswith(binary_dxf.SENTINEL):
                with open(path, "rb") as fp:
                    doc = ezdxf.read(binary_dxf.binary_dxf_to_stream(fp.read()))
            else:
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


def detect_rooms(doc, layer: str | None = None, min_area_m2: float = 0.5, unit: str = "mm"):
    unit_to_m_val = {"mm": 0.001, "cm": 0.01, "m": 1.0}[unit]
    min_area_units = min_area_m2 / unit_to_m_val**2
    rooms = []
    for entity in doc.modelspace():
        etype = entity.dxftype()
        if etype not in ("LWPOLYLINE", "POLYLINE"):
            continue
        if layer and entity.dxf.layer.lower() != layer.lower():
            continue
        if not bool(getattr(entity, "closed", False)):
            continue
        try:
            points = [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]
        except Exception:
            continue
        if len(points) < 3:
            continue
        if abs(shoelace_area(points)) < min_area_units:
            continue
        rooms.append((entity.dxf.layer, __import__("shapely.geometry", fromlist=["Polygon"]).Polygon(points), entity))
    return rooms


def ensure_layers(doc) -> None:
    layers = {
        LAYER_PIPE: 1,
        LAYER_ROOM: 3,
        LAYER_TEXT: 2,
        LAYER_SUPPLY: 30,
        LAYER_MANIFOLD: 5,
    }
    for name, color in layers.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)


def add_manifold(doc, pos: tuple[float, float], name: str, unit: str = "mm") -> None:
    ensure_layers(doc)
    u = unit_to_m(unit)
    msp = doc.modelspace()
    x, y = pos
    r = 0.25 / u
    msp.add_circle((x, y), r, dxfattribs={"layer": LAYER_MANIFOLD, "lineweight": 35})
    msp.add_line((x - r, y), (x + r, y), dxfattribs={"layer": LAYER_MANIFOLD})
    msp.add_line((x, y - r), (x, y + r), dxfattribs={"layer": LAYER_MANIFOLD})
    msp.add_text(
        name,
        height=0.15 / u,
        dxfattribs={"layer": LAYER_MANIFOLD},
    ).set_placement((x + 1.3 * r, y + 1.3 * r), align=TextEntityAlignment.LEFT)


def add_room_result(doc, result: RoomResult, unit: str = "mm") -> None:
    ensure_layers(doc)
    u = unit_to_m(unit)
    msp = doc.modelspace()
    if result.inset_polygon is not None:
        msp.add_lwpolyline(
            [(x, y) for x, y in result.inset_polygon.exterior.coords],
            close=True,
            dxfattribs={"layer": LAYER_ROOM, "lineweight": 0},
        )
    for circuit in result.circuits:
        msp.add_lwpolyline(
            circuit.path.as_xyb(),
            format="xyb",
            dxfattribs={"layer": LAYER_PIPE, "lineweight": 25},
        )
        msp.add_text(
            f"KRING {circuit.number} ({circuit.length_m:.0f} m)",
            height=0.12 / u,
            dxfattribs={"layer": LAYER_TEXT},
        ).set_placement((circuit.start[0], circuit.start[1] + 0.15 / u), align=TextEntityAlignment.LEFT)
        if result.manifold_pos is not None:
            mx, my = result.manifold_pos
            msp.add_line(
                (mx, my), circuit.start, dxfattribs={"layer": LAYER_SUPPLY, "linetype": "DASHED"}
            )
            msp.add_line(
                circuit.end, (mx, my), dxfattribs={"layer": LAYER_SUPPLY, "linetype": "DASHED"}
            )
    xs, ys = [], []
    for c in result.circuits:
        xs.extend(p[0] for p in c.path.points)
        ys.extend(p[1] for p in c.path.points)
    if xs:
        text = (
            f"{result.name}: {result.area_m2:.2f} m² | "
            f"{len(result.circuits)} kring(en) | {result.pipe_length_m:.1f} m | "
            f"{result.m_per_m2:.2f} m/m²"
        )
        msp.add_mtext(
            text,
            dxfattribs={"layer": LAYER_TEXT, "char_height": 0.2 / u},
        ).set_location((min(xs), max(ys) + 0.35 / u), attachment_point=1)


def add_legend(doc, results: list[RoomResult], unit: str = "mm", origin: tuple[float, float] | None = None) -> None:
    ensure_layers(doc)
    u = unit_to_m(unit)
    msp = doc.modelspace()
    if origin is None:
        minx, miny, maxx, maxy = _doc_bounds(doc)
        origin = (maxx + 1.0 / u, maxy)
    x, y = origin
    row_h = 0.5 / u
    col_w = [3.5 / u, 2.0 / u, 3.0 / u, 2.5 / u]
    header = ["RUIMTE", "m²", "KRINGEN", "SLANG (m)"]

    def put(col, text, bold=False):
        t = msp.add_text(
            str(text),
            height=0.15 / u,
            dxfattribs={"layer": LAYER_TEXT},
        )
        t.set_placement((x + sum(col_w[:col]), y), align=TextEntityAlignment.LEFT)

    put(0, "MATERIAALLIJST VLOERVERWARMING")
    y -= row_h * 1.5
    yy = y
    for col, h in enumerate(header):
        t = msp.add_text(h, height=0.15 / u, dxfattribs={"layer": LAYER_TEXT})
        t.set_placement((x + sum(col_w[:col]), yy), align=TextEntityAlignment.LEFT)
    y -= row_h
    total_m2 = total_m = total_circuits = 0
    for r in results:
        put(0, r.name)
        put(1, f"{r.area_m2:.2f}")
        put(2, len(r.circuits))
        put(3, f"{r.pipe_length_m:.1f}")
        y -= row_h
        total_m2 += r.area_m2
        total_m += r.pipe_length_m
        total_circuits += len(r.circuits)
    y -= row_h * 0.5
    put(0, "TOTAAL")
    put(1, f"{total_m2:.2f}")
    put(2, total_circuits)
    put(3, f"{total_m:.1f}")


def _doc_bounds(doc):
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for entity in doc.modelspace():
        try:
            if entity.dxftype() == "LINE":
                pts = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
            elif entity.dxftype() in ("LWPOLYLINE", "POLYLINE"):
                pts = [(p[0], p[1]) for p in entity.get_points("xy")]
            elif entity.dxftype() == "CIRCLE":
                c, r = entity.dxf.center, entity.dxf.radius
                pts = [(c.x - r, c.y - r), (c.x + r, c.y + r)]
            else:
                continue
        except Exception:
            continue
        for px, py in pts:
            minx, miny = min(minx, px), min(miny, py)
            maxx, maxy = max(maxx, px), max(maxy, py)
    if minx == float("inf"):
        return (0.0, 0.0, 1000.0, 1000.0)
    return (minx, miny, maxx, maxy)


def unit_to_m(unit: str) -> float:
    return {"mm": 0.001, "cm": 0.01, "m": 1.0}[unit]
