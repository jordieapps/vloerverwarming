from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, Polygon, box
from shapely.ops import polygonize, unary_union

OBSTACLE_BLOCK_WORDS = ("trap",)
OBSTACLE_LAYER_WORDS = ("trap",)

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


def _insert_footprint(doc, insert, depth: int = 0) -> Polygon | None:
    if depth > 4:
        return None
    try:
        block = doc.blocks.get(insert.dxf.name)
    except Exception:
        return None
    m = insert.matrix44()
    pts = []
    for e in block:
        t = e.dxftype()
        try:
            if t == "LINE":
                raw = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif t == "LWPOLYLINE":
                raw = [(p[0], p[1]) for p in e.get_points("xy")]
            elif t in ("ARC", "CIRCLE"):
                raw = [(e.dxf.center.x, e.dxf.center.y)]
            elif t == "INSERT":
                sub = _insert_footprint(doc, e, depth + 1)
                raw = list(sub.exterior.coords) if sub is not None else []
            else:
                continue
        except Exception:
            continue
        for v in raw:
            w = m.transform((v[0], v[1], 0.0))
            pts.append((w[0], w[1]))
    if len(pts) < 3:
        return None
    poly = MultiPoint(pts).envelope
    if poly.is_empty or poly.geom_type != "Polygon" or poly.area <= 0:
        return None
    return poly


def obstacle_footprints(
    doc,
    region=None,
    block_words=OBSTACLE_BLOCK_WORDS,
    layer_words=OBSTACLE_LAYER_WORDS,
) -> list[Polygon]:
    out: list[Polygon] = []
    msp = doc.modelspace()
    for ins in msp.query("INSERT"):
        naam = ins.dxf.name.lower()
        if not any(w in naam for w in block_words):
            continue
        poly = _insert_footprint(doc, ins)
        if poly is None or poly.area <= 0:
            continue
        if region is not None and not poly.intersects(region):
            continue
        out.append(poly)
    wanted = {w.lower() for w in layer_words}
    for e in msp:
        if e.dxftype() != "LWPOLYLINE":
            continue
        laag = e.dxf.layer.lower()
        if not any(w in laag for w in wanted):
            continue
        if not getattr(e, "closed", False):
            continue
        try:
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
        except Exception:
            continue
        poly = Polygon(pts)
        if not poly.is_valid or poly.is_empty or poly.area <= 0:
            continue
        if region is not None and not poly.intersects(region):
            continue
        out.append(poly)
    return out


def hatch_fill_solids(
    doc,
    region=None,
    layers=("arcering",),
    max_thickness: float = 320.0,
    min_length: float = 400.0,
) -> list[Polygon]:
    wanted = {l.lower() for l in layers}
    out: list[Polygon] = []
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE":
            continue
        if not getattr(e, "closed", False):
            continue
        if not any(w in e.dxf.layer.lower() for w in wanted):
            continue
        try:
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
        except Exception:
            continue
        if len(pts) < 3:
            continue
        poly = Polygon(pts)
        if not poly.is_valid or poly.is_empty or poly.area <= 0:
            continue
        if poly.buffer(0).geom_type != "Polygon":
            continue
        w = poly.bounds[2] - poly.bounds[0]
        h = poly.bounds[3] - poly.bounds[1]
        if min(w, h) > max_thickness or max(w, h) < min_length:
            continue
        if region is not None and not poly.intersects(region):
            continue
        out.append(poly)
    return out


def wall_solids(walls: list[LineString], thickness: float = 120.0) -> Polygon | None:
    if not walls:
        return None
    return unary_union([w.buffer(thickness / 2.0, cap_style=2, join_style=2) for w in walls])


def free_space(
    rooms: list[Polygon],
    obstacles: list[Polygon] | None = None,
    walls: list[LineString] | None = None,
    bridge: float = 700.0,
    wall_thickness: float = 120.0,
    hatch_fills: list[Polygon] | None = None,
) -> Polygon | None:
    if not rooms:
        return None
    merged = unary_union([r for r in rooms if not r.is_empty])
    if bridge > 0:
        merged = merged.buffer(bridge / 2.0, join_style=2).buffer(-bridge / 2.0, join_style=2)
    parts = [g for g in (merged.geoms if merged.geom_type in ("MultiPolygon", "GeometryCollection") else [merged])
             if g.geom_type == "Polygon" and not g.is_empty]
    if not parts:
        return None
    merged = unary_union(parts)
    if obstacles:
        merged = merged.difference(unary_union([o for o in obstacles if not o.is_empty]))
    if walls:
        solids = wall_solids(walls, wall_thickness)
        if solids is not None and not solids.is_empty:
            merged = merged.difference(solids)
    if hatch_fills:
        fills = unary_union([f for f in hatch_fills if not f.is_empty])
        if not fills.is_empty:
            merged = merged.difference(fills)
    parts = [g for g in (merged.geoms if merged.geom_type in ("MultiPolygon", "GeometryCollection") else [merged])
             if g.geom_type == "Polygon" and not g.is_empty]
    if not parts:
        return None
    return unary_union(parts)


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
