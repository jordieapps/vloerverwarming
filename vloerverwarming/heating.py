from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.affinity import rotate as sh_rotate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points

from .geometry import inset_polygon, largest_polygon


@dataclass
class PipePath:
    points: list[tuple[float, float]]
    bulges: list[float]

    def arc_length(self) -> float:
        total = 0.0
        for i in range(len(self.points) - 1):
            (x1, y1), (x2, y2) = self.points[i], self.points[i + 1]
            chord = math.hypot(x2 - x1, y2 - y1)
            b = self.bulges[i] if i < len(self.bulges) else 0.0
            if abs(b) < 1e-9 or chord < 1e-12:
                total += chord
                continue
            theta = 4.0 * math.atan(b)
            radius = chord / (2.0 * math.sin(abs(theta) / 2.0))
            total += abs(theta) * radius
        return total

    def as_xyb(self) -> list[tuple[float, float, float]]:
        n = len(self.points)
        out = []
        for i, (x, y) in enumerate(self.points):
            b = self.bulges[i] if i < n - 1 and i < len(self.bulges) else 0.0
            out.append((x, y, b))
        return out

    def rotated(self, angle_deg: float, cx: float, cy: float) -> "PipePath":
        a = math.radians(angle_deg)
        cos_a, sin_a = math.cos(a), math.sin(a)
        pts = []
        for x, y in self.points:
            dx, dy = x - cx, y - cy
            pts.append((cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a))
        return PipePath(pts, list(self.bulges))


@dataclass
class Circuit:
    number: int
    path: PipePath
    length_m: float
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass
class RoomResult:
    name: str
    area_m2: float
    manifold: str | None
    manifold_pos: tuple[float, float] | None
    circuits: list[Circuit] = field(default_factory=list)
    pipe_length_m: float = 0.0
    m_per_m2: float = 0.0
    inset_polygon: Polygon | None = None
    warnings: list[str] = field(default_factory=list)


def _line_segments(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        out = []
        for g in geom.geoms:
            out.extend(_line_segments(g))
        return out
    return []


def _close(a: tuple[float, float], b: tuple[float, float], eps: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def serpentine_passes(poly: Polygon, spacing: float, angle_deg: float = 0.0):
    work = sh_rotate(poly, angle_deg, origin="centroid") if angle_deg else poly
    minx, miny, maxx, maxy = work.bounds
    raw: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    row = 0
    y = miny + spacing / 2.0
    while y <= maxy + 1e-9:
        line = LineString([(minx - 1.0, y), (maxx + 1.0, y)])
        segs = sorted(_line_segments(line.intersection(work)), key=lambda s: s.coords[0][0])
        forward = row % 2 == 0
        ordered = segs if forward else list(reversed(segs))
        for s in ordered:
            coords = list(s.coords)
            raw.append((coords[0], coords[-1], y) if forward else (coords[-1], coords[0], y))
        row += 1
        y += spacing
    passes: list[PipePath] = []
    connectors: list[PipePath | None] = []
    for i, (start, end, row_y) in enumerate(raw):
        passes.append(PipePath([start, end], [0.0]))
        if i + 1 >= len(raw):
            connectors.append(None)
            continue
        nstart, _, nrow_y = raw[i + 1]
        if abs(nrow_y - row_y) < 1e-9:
            connectors.append(PipePath([end, nstart], [0.0]))
        else:
            tdx, tdy = end[0] - start[0], end[1] - start[1]
            cdx, cdy = nstart[0] - end[0], nstart[1] - end[1]
            cross = tdx * cdy - tdy * cdx
            connectors.append(PipePath([end, nstart], [1.0 if cross > 0 else -1.0]))
    if angle_deg:
        a = math.radians(-angle_deg)
        cx, cy = work.centroid.x, work.centroid.y
        passes = [p.rotated(-angle_deg, cx, cy) for p in passes]
        connectors = [c.rotated(-angle_deg, cx, cy) if c else None for c in connectors]
    return passes, connectors


def spiral_passes(poly: Polygon, spacing: float, max_rings: int = 500):
    rings: list[Polygon] = []
    cur = poly
    while len(rings) < max_rings:
        rings.append(cur)
        nxt = largest_polygon(cur.buffer(-spacing, join_style=2))
        if nxt is None or nxt.area < spacing * spacing:
            break
        cur = nxt
    passes: list[PipePath] = []
    connectors: list[PipePath | None] = []
    prev_end: tuple[float, float] | None = None
    for ring in rings:
        coords = list(ring.exterior.coords)[:-1]
        if len(coords) < 3:
            continue
        if prev_end is not None:
            best_idx, best_d = 0, float("inf")
            for j, c in enumerate(coords):
                d = (c[0] - prev_end[0]) ** 2 + (c[1] - prev_end[1]) ** 2
                if d < best_d:
                    best_d, best_idx = d, j
            ordered = coords[best_idx:] + coords[:best_idx]
            connectors.append(PipePath([prev_end, ordered[0]], [0.0]))
        else:
            ordered = coords
        ring_pts = ordered + [ordered[0]]
        passes.append(PipePath(ring_pts, [0.0] * (len(ring_pts) - 1)))
        prev_end = ordered[0]
    connectors.append(None)
    return passes, connectors


def join_circuit(passes: list[PipePath], connectors: list[PipePath | None], i0: int, i1: int) -> PipePath:
    pts: list[tuple[float, float]] = []
    bulges: list[float] = []
    for i in range(i0, i1 + 1):
        if i > i0 and connectors[i - 1] is not None:
            conn = connectors[i - 1]
            skip = 1 if pts and _close(pts[-1], conn.points[0]) else 0
            pts.extend(conn.points[skip:])
            bulges.extend(conn.bulges[skip:])
        p = passes[i]
        skip = 1 if pts and _close(pts[-1], p.points[0]) else 0
        pts.extend(p.points[skip:])
        bulges.extend(p.bulges[skip:])
    return PipePath(pts, bulges)


def build_circuits(
    passes: list[PipePath],
    connectors: list[PipePath | None],
    max_len_units: float,
    link_units: float,
) -> list[tuple[int, int]]:
    if not passes:
        return []
    groups: list[tuple[int, int]] = []
    i0 = 0
    acc = 0.0
    for i, p in enumerate(passes):
        add = p.arc_length()
        if i > i0 and connectors[i - 1] is not None:
            add += connectors[i - 1].arc_length()
        if groups == [] and i == 0:
            acc = add
            continue
        if i > i0 and acc + add + 2.0 * link_units > max_len_units:
            groups.append((i0, i - 1))
            i0 = i
            acc = add
        else:
            acc += add
    groups.append((i0, len(passes) - 1))
    return groups


def nearest_point_on_path(path: PipePath, pt: tuple[float, float]) -> tuple[float, float]:
    ls = LineString(path.points)
    _, np_ = nearest_points(Point(pt), ls)
    return (np_.x, np_.y)


def generate_room(
    name: str,
    poly: Polygon,
    unit_to_m: float,
    hoh_m: float,
    edge_m: float,
    pattern: str = "serpentine",
    angle_deg: float = 0.0,
    max_circuit_m: float = 120.0,
    manifold_name: str | None = None,
    manifold_pos: tuple[float, float] | None = None,
    first_circuit_number: int = 1,
    max_circuits: int | None = None,
) -> RoomResult | None:
    area_m2 = abs(poly.area) * unit_to_m**2
    if area_m2 < 0.5:
        return None
    inset = inset_polygon(poly, edge_m / unit_to_m)
    if inset is None or inset.area < 1e-9:
        return None
    spacing = hoh_m / unit_to_m
    if pattern == "spiraal":
        passes, connectors = spiral_passes(inset, spacing)
    else:
        passes, connectors = serpentine_passes(inset, spacing, angle_deg)
    if not passes:
        return None
    max_len_units = max_circuit_m / unit_to_m
    if manifold_pos is not None:
        field_ls = LineString([pt for p in passes for pt in p.points])
        link_units = Point(manifold_pos).distance(field_ls)
    else:
        link_units = 0.0
    groups = build_circuits(passes, connectors, max_len_units, link_units)
    result = RoomResult(
        name=name,
        area_m2=area_m2,
        manifold=manifold_name,
        manifold_pos=manifold_pos,
        inset_polygon=inset,
    )
    warnings: list[str] = []
    if max_circuits is not None and len(groups) > max_circuits:
        warnings.append(
            f"{len(groups)} kringen nodig maar verdeler heeft {max_circuits} uitgangen"
        )
    for k, (i0, i1) in enumerate(groups):
        path = join_circuit(passes, connectors, i0, i1)
        length_units = path.arc_length()
        start = path.points[0]
        end = path.points[-1]
        if manifold_pos is not None:
            length_units += 2.0 * Point(manifold_pos).distance(LineString([start, end]))
        length_m = length_units * unit_to_m
        if length_m > max_circuit_m:
            warnings.append(f"kring {first_circuit_number + k} is {length_m:.0f} m > max {max_circuit_m:.0f} m")
        result.circuits.append(
            Circuit(
                number=first_circuit_number + k,
                path=path,
                length_m=length_m,
                start=start,
                end=end,
            )
        )
    result.pipe_length_m = sum(c.length_m for c in result.circuits)
    result.m_per_m2 = result.pipe_length_m / area_m2 if area_m2 > 0 else 0.0
    result.warnings = warnings
    return result
