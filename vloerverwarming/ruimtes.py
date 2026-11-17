from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import polygonize, unary_union

WALL_LAYER_DEFAULTS = (
    "21---BUITENWANDEN",
    "22---BINNENWANDEN",
    "22a--SCHEIDINGSWANDEN",
    "21---BETONWERK",
)

ROOM_WORDS = (
    "kamer",
    "keuken",
    "woon",
    "living",
    "badkamer",
    "douche",
    "toilet",
    "wc",
    "gang",
    "hal",
    "entree",
    "overloop",
    "berging",
    "garage",
    "kantoor",
    "stook",
    "wasruimte",
    "kleed",
    "kast",
    "trap",
)


def _segments_in_region(entity, region) -> list[LineString]:
    try:
        if entity.dxftype() == "LINE":
            p1 = (entity.dxf.start.x, entity.dxf.start.y)
            p2 = (entity.dxf.end.x, entity.dxf.end.y)
            ls = LineString([p1, p2])
        elif entity.dxftype() in ("LWPOLYLINE", "POLYLINE"):
            pts = [(p[0], p[1]) for p in entity.get_points("xy")]
            if len(pts) < 2:
                return []
            if getattr(entity, "closed", False) and pts[0] != pts[-1]:
                pts.append(pts[0])
            if len(pts) < 2:
                return []
            ls = LineString(pts)
        else:
            return []
    except Exception:
        return []
    if region is not None:
        if not ls.intersects(region):
            return []
        clipped = ls.intersection(region)
        if clipped.is_empty:
            return []
        if clipped.geom_type == "LineString":
            return [clipped]
        if clipped.geom_type in ("MultiLineString", "GeometryCollection"):
            return [g for g in clipped.geoms if g.geom_type == "LineString" and g.length > 1e-9]
        return []
    return [ls]


def wall_lines(doc, layers, region=None) -> list[LineString]:
    wanted = {l.lower() for l in layers}
    lines: list[LineString] = []
    for entity in doc.modelspace():
        if entity.dxftype() not in ("LINE", "LWPOLYLINE", "POLYLINE"):
            continue
        if entity.dxf.layer.lower() not in wanted:
            continue
        lines.extend(_segments_in_region(entity, region))
    return lines


def detect_room_faces(lines: list[LineString], min_area_m2: float = 1.0, max_area_m2: float = 200.0,
                      scale_to_m: float = 0.001) -> list[Polygon]:
    if not lines:
        return []
    merged = unary_union(MultiLineString([l for l in lines if l.length > 1e-9]))
    faces = []
    for ring in polygonize(merged):
        poly = ring if isinstance(ring, Polygon) else Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
            if poly.is_empty or poly.geom_type != "Polygon":
                continue
        area_m2 = poly.area * scale_to_m**2
        if min_area_m2 <= area_m2 <= max_area_m2:
            faces.append(poly)
    return faces


def _label_points(doc, region) -> list[tuple[Point, str]]:
    out = []
    for entity in doc.modelspace():
        if entity.dxftype() not in ("MTEXT", "TEXT"):
            continue
        try:
            text = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
        except Exception:
            continue
        text = text.strip()
        if not text:
            continue
        try:
            pos = entity.dxf.insert
        except Exception:
            continue
        pt = Point(pos.x, pos.y)
        if region is not None and not region.contains(pt):
            continue
        out.append((pt, text))
    return out


def _room_name(text: str) -> str | None:
    low = text.lower()
    for word in ROOM_WORDS:
        if word in low:
            return text.strip().splitlines()[0].strip()[:40]
    return None


def detect_rooms_from_walls(
    doc,
    layers=WALL_LAYER_DEFAULTS,
    region=None,
    min_area_m2: float = 1.0,
    max_area_m2: float = 200.0,
    scale_to_m: float = 0.001,
):
    lines = wall_lines(doc, layers, region)
    faces = detect_room_faces(lines, min_area_m2, max_area_m2, scale_to_m)
    labels = _label_points(doc, region)
    rooms = []
    used = set()
    for face in sorted(faces, key=lambda f: -f.area):
        best = None
        best_i = None
        best_d = None
        for i, (pt, text) in enumerate(labels):
            if i in used:
                continue
            if not face.contains(pt):
                continue
            name = _room_name(text)
            if name is None:
                continue
            d = pt.distance(face.centroid)
            if best_d is None or d < best_d:
                best, best_i, best_d = name, i, d
        if best is None:
            continue
        used.add(best_i)
        rooms.append((best, face))
    return rooms
