from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.affinity import rotate as sh_rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

from .geometry import inset_polygon, largest_polygon
from .routing import GridRouter


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
    supply_route: list = field(default_factory=list)
    return_route: list = field(default_factory=list)


def l_route(a: tuple[float, float], b: tuple[float, float], vertical_first: bool = True) -> list:
    if abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9:
        return [a, b]
    if vertical_first:
        return [a, (a[0], b[1]), b]
    return [a, (b[0], a[1]), b]


def route_length(points: list) -> float:
    return sum(
        math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        for i in range(len(points) - 1)
    )


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


def _ring_loops(ring: Polygon) -> list[list[tuple[float, float]]]:
    loops = [list(ring.exterior.coords)[:-1]]
    for interior in ring.interiors:
        ic = list(interior.coords)[:-1]
        if len(ic) >= 3:
            loops.append(ic)
    return loops


def _order_loop(coords: list[tuple[float, float]], hint: tuple[float, float] | None) -> list[tuple[float, float]]:
    if hint is None:
        return coords
    best_idx, best_d = 0, float("inf")
    for j, c in enumerate(coords):
        d = (c[0] - hint[0]) ** 2 + (c[1] - hint[1]) ** 2
        if d < best_d:
            best_d, best_idx = d, j
    return coords[best_idx:] + coords[:best_idx]


def _connector(prev_end: tuple[float, float], nxt: tuple[float, float]) -> "PipePath":
    nx, ny = nxt
    px, py = prev_end
    if abs(nx - px) > 1e-9 and abs(ny - py) > 1e-9:
        pts = [prev_end, (nx, py), nxt]
    else:
        pts = [prev_end, nxt]
    return PipePath(pts, [0.0] * (len(pts) - 1))


def spiral_passes(poly: Polygon, spacing: float, start_hint: tuple[float, float] | None = None,
                  max_rings: int = 500):
    inward: list[Polygon] = []
    cur = poly
    while len(inward) < max_rings:
        inward.append(cur)
        nxt = largest_polygon(cur.buffer(-2.0 * spacing, join_style=2))
        if nxt is None or nxt.area < spacing * spacing:
            break
        cur = nxt
    midway: dict[int, Polygon] = {}
    for i in range(len(inward)):
        m = largest_polygon(poly.buffer(-(2 * i + 1) * spacing, join_style=2))
        if m is not None and m.area > 1e-9:
            midway[i] = m
    rings: list[Polygon] = list(inward)
    for i in sorted(midway.keys(), reverse=True):
        rings.append(midway[i])
    passes: list[PipePath] = []
    connectors: list[PipePath | None] = []
    prev_end: tuple[float, float] | None = None
    last_idx = len(rings) - 1
    for idx, ring in enumerate(rings):
        loops = _ring_loops(ring)
        for li, coords in enumerate(loops):
            if len(coords) < 3:
                continue
            is_first = idx == 0 and li == 0
            is_last = idx == last_idx and li == len(loops) - 1
            if (is_first or is_last) and start_hint is not None:
                hint = start_hint
            elif prev_end is not None:
                hint = prev_end
            else:
                hint = None
            ordered = _order_loop(coords, hint)
            if prev_end is not None:
                connectors.append(_connector(prev_end, ordered[0]))
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


def _circuit_length_units(passes, connectors, i0, i1, manifold_pos, estimate=None) -> float:
    path = join_circuit(passes, connectors, i0, i1)
    length = path.arc_length()
    if manifold_pos is not None:
        if estimate is not None:
            length += estimate(path.points[0], path.points[-1])
        else:
            supply = l_route(manifold_pos, path.points[0], vertical_first=True)
            retour = l_route(path.points[-1], manifold_pos, vertical_first=False)
            length += route_length(supply) + route_length(retour)
    return length


def _split_oversized(groups, passes, connectors, max_len_units, manifold_pos, estimate=None):
    for _ in range(50):
        changed = False
        new_groups = []
        for i0, i1 in groups:
            length = _circuit_length_units(passes, connectors, i0, i1, manifold_pos, estimate)
            if length > max_len_units and i1 > i0:
                mid = (i0 + i1) // 2
                new_groups.append((i0, mid))
                new_groups.append((mid + 1, i1))
                changed = True
            else:
                new_groups.append((i0, i1))
        groups = new_groups
        if not changed:
            break
    return groups


def _polygon_parts(geom, min_area: float) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        parts = [geom]
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        parts = [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    else:
        return []
    return [p for p in parts if p.area >= min_area]


def _split_strips(poly: Polygon, n: int, min_area: float) -> list[Polygon]:
    minx, miny, maxx, maxy = poly.bounds
    w, h = maxx - minx, maxy - miny
    delen: list[Polygon] = []
    if w >= h:
        for i in range(n):
            x0 = minx + w * i / n
            x1 = minx + w * (i + 1) / n
            delen.extend(_polygon_parts(poly.intersection(box(x0, miny, x1, maxy)), min_area))
    else:
        for i in range(n):
            y0 = miny + h * i / n
            y1 = miny + h * (i + 1) / n
            delen.extend(_polygon_parts(poly.intersection(box(minx, y0, maxx, y1)), min_area))
    return delen if len(delen) >= 2 else [poly]


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
    obstacles: list[Polygon] | None = None,
    group_max_m2: float | None = None,
    free_space_poly: Polygon | None = None,
) -> RoomResult | None:
    area_m2 = abs(poly.area) * unit_to_m**2
    if area_m2 < 0.5:
        return None
    spacing = hoh_m / unit_to_m
    min_area_units = 0.5 / unit_to_m**2

    werk = poly
    if obstacles:
        obst = unary_union([o for o in obstacles if o is not None and not o.is_empty])
        if not obst.is_empty:
            werk = werk.difference(obst)
    delen = _polygon_parts(werk, min_area_units)
    if not delen:
        return None
    if (pattern == "spiraal" and group_max_m2 is not None and group_max_m2 > 0
            and area_m2 > group_max_m2 and len(delen) == 1):
        n = max(2, math.ceil(area_m2 / group_max_m2))
        gestripd = _split_strips(delen[0], n, min_area_units)
        if len(gestripd) >= 2:
            delen = gestripd

    route = None
    if free_space_poly is not None and manifold_pos is not None and not free_space_poly.is_empty:
        router = GridRouter(free_space_poly, spacing / 2.0 if spacing > 0 else 50.0,
                            extra_points=[manifold_pos])

        def route(a, b, vertical_first=True):
            pad = router.route(a, b)
            if pad:
                return pad
            return l_route(a, b, vertical_first)

    result = RoomResult(
        name=name,
        area_m2=area_m2,
        manifold=manifold_name,
        manifold_pos=manifold_pos,
    )
    insets: list[Polygon] = []
    warnings: list[str] = []
    nr = first_circuit_number
    max_len_units = max_circuit_m / unit_to_m
    for deel in delen:
        inset = inset_polygon(deel, edge_m / unit_to_m)
        if inset is None or inset.area < 1e-9:
            continue
        insets.append(inset)
        start_hint = None
        if manifold_pos is not None:
            _, hint_pt = nearest_points(Point(manifold_pos), inset.exterior)
            start_hint = (hint_pt.x, hint_pt.y)
        if pattern == "spiraal":
            passes, connectors = spiral_passes(inset, spacing, start_hint)
        else:
            passes, connectors = serpentine_passes(inset, spacing, angle_deg)
        if not passes:
            continue
        if manifold_pos is not None:
            field_ls = LineString([pt for p in passes for pt in p.points])
            if route is not None:
                _, nabij = nearest_points(Point(manifold_pos), field_ls)
                pad = route(manifold_pos, (nabij.x, nabij.y), True)
                link_units = route_length(pad) if pad else Point(manifold_pos).distance(field_ls)
            else:
                link_units = Point(manifold_pos).distance(field_ls)
        else:
            link_units = 0.0
        route_estimate = None
        if route is not None:
            def route_estimate(a, b):
                heen = route(manifold_pos, a, True)
                terug = route(b, manifold_pos, False)
                return route_length(heen) + route_length(terug)

        groups = build_circuits(passes, connectors, max_len_units, link_units)
        groups = _split_oversized(groups, passes, connectors, max_len_units, manifold_pos, route_estimate)
        for i0, i1 in groups:
            path = join_circuit(passes, connectors, i0, i1)
            length_units = path.arc_length()
            start = path.points[0]
            end = path.points[-1]
            supply_route: list = []
            return_route: list = []
            if route is not None:
                supply_route = route(manifold_pos, start, True)
                return_route = route(end, manifold_pos, False)
                length_units += route_length(supply_route) + route_length(return_route)
            length_m = length_units * unit_to_m
            if length_m > max_circuit_m:
                warnings.append(f"kring {nr} is {length_m:.0f} m > max {max_circuit_m:.0f} m")
            result.circuits.append(
                Circuit(
                    number=nr,
                    path=path,
                    length_m=length_m,
                    start=start,
                    end=end,
                    supply_route=supply_route,
                    return_route=return_route,
                )
            )
            nr += 1
    if not result.circuits:
        return None
    if max_circuits is not None and len(result.circuits) > max_circuits:
        warnings.append(
            f"{len(result.circuits)} kringen nodig maar verdeler heeft {max_circuits} uitgangen"
        )
    result.inset_polygon = unary_union(insets) if len(insets) > 1 else insets[0]
    result.pipe_length_m = sum(c.length_m for c in result.circuits)
    result.m_per_m2 = result.pipe_length_m / area_m2 if area_m2 > 0 else 0.0
    result.warnings = warnings
    return result
