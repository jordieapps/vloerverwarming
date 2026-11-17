from __future__ import annotations

import math
from dataclasses import dataclass

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


@dataclass
class RoomResult:
    name: str
    area_m2: float
    pipe_length_m: float
    m_per_m2: float
    path: PipePath
    inset_polygon: Polygon
    warnings: list[str]


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


def serpentine(poly: Polygon, spacing: float, angle_deg: float = 0.0) -> PipePath | None:
    work = sh_rotate(poly, angle_deg, origin="centroid") if angle_deg else poly
    minx, miny, maxx, maxy = work.bounds
    passes: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    row = 0
    y = miny + spacing / 2.0
    while y <= maxy + 1e-9:
        line = LineString([(minx - 1.0, y), (maxx + 1.0, y)])
        segs = sorted(_line_segments(line.intersection(work)), key=lambda s: s.coords[0][0])
        forward = row % 2 == 0
        ordered = segs if forward else list(reversed(segs))
        for s in ordered:
            coords = list(s.coords)
            if forward:
                passes.append((coords[0], coords[-1], y))
            else:
                passes.append((coords[-1], coords[0], y))
        row += 1
        y += spacing
    if not passes:
        return None
    points = [passes[0][0]]
    bulges: list[float] = []
    for i, (start, end, row_y) in enumerate(passes):
        points.append(end)
        bulges.append(0.0)
        if i + 1 >= len(passes):
            break
        nstart, _, nrow_y = passes[i + 1]
        if abs(nrow_y - row_y) < 1e-9:
            points.append(nstart)
            bulges.append(0.0)
            continue
        px, py = points[-2]
        tdx, tdy = end[0] - px, end[1] - py
        cdx, cdy = nstart[0] - end[0], nstart[1] - end[1]
        cross = tdx * cdy - tdy * cdx
        points.append(nstart)
        bulges.append(1.0 if cross > 0 else -1.0)
    path = PipePath(points, bulges)
    if angle_deg:
        path = _rotate_path(path, -angle_deg, work.centroid.x, work.centroid.y)
    return path


def _rotate_path(path: PipePath, angle_deg: float, cx: float, cy: float) -> PipePath:
    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    rotated = []
    for x, y in path.points:
        dx, dy = x - cx, y - cy
        rotated.append((cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a))
    return PipePath(rotated, path.bulges)


def spiral(poly: Polygon, spacing: float, max_rings: int = 500) -> PipePath | None:
    rings: list[Polygon] = []
    cur = poly
    while len(rings) < max_rings:
        rings.append(cur)
        nxt = cur.buffer(-spacing, join_style=2)
        nxt = largest_polygon(nxt)
        if nxt is None or nxt.area < spacing * spacing:
            break
        cur = nxt
    if not rings:
        return None
    points: list[tuple[float, float]] = []
    bulges: list[float] = []
    for i, ring in enumerate(rings):
        coords = list(ring.exterior.coords)[:-1]
        if not coords:
            continue
        if points:
            prev = points[-1]
            ring_ls = LineString(ring.exterior.coords)
            ring_coords = list(ring.exterior.coords)
            best_idx, best_d = 0, float("inf")
            for j, c in enumerate(ring_coords):
                d = (c[0] - prev[0]) ** 2 + (c[1] - prev[1]) ** 2
                if d < best_d:
                    best_d, best_idx = d, j
            ordered = ring_coords[best_idx:-1] + ring_coords[: best_idx + 1]
            points.append(ordered[0])
            bulges.append(0.0)
            points.extend(ordered[1:])
            bulges.extend([0.0] * (len(ordered) - 1))
        else:
            points.extend(coords)
            bulges.extend([0.0] * len(coords))
    if len(points) < 2:
        return None
    return PipePath(points, bulges)


def generate_room(
    name: str,
    poly: Polygon,
    unit_to_m: float,
    hoh_m: float,
    edge_m: float,
    pattern: str = "serpentine",
    angle_deg: float = 0.0,
    max_circuit_m: float = 120.0,
) -> RoomResult | None:
    area_m2 = abs(poly.area) * unit_to_m**2
    if area_m2 < 0.5:
        return None
    inset = inset_polygon(poly, edge_m / unit_to_m)
    if inset is None or inset.area < 1e-9:
        return None
    spacing = hoh_m / unit_to_m
    if pattern == "spiraal":
        path = spiral(inset, spacing)
    else:
        path = serpentine(inset, spacing, angle_deg)
    if path is None:
        return None
    length_m = path.arc_length() * unit_to_m
    warnings = []
    if length_m > max_circuit_m:
        warnings.append(
            f"lengte {length_m:.0f} m > max kring {max_circuit_m:.0f} m: splits in meerdere kringen"
        )
    return RoomResult(
        name=name,
        area_m2=area_m2,
        pipe_length_m=length_m,
        m_per_m2=length_m / area_m2 if area_m2 > 0 else 0.0,
        path=path,
        inset_polygon=inset,
        warnings=warnings,
    )
