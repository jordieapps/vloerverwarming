from __future__ import annotations

import math

from shapely.geometry import MultiPolygon, Polygon


UNIT_TO_M = {"mm": 0.001, "cm": 0.01, "m": 1.0}

INSUNITS_TO_UNIT = {
    1: "in",
    2: "ft",
    4: "mm",
    5: "cm",
    6: "m",
    8: "um",
}


def shoelace_area(points: list[tuple[float, float]]) -> float:
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_area_m2(poly: Polygon, unit: str) -> float:
    return abs(poly.area) * UNIT_TO_M[unit] ** 2


def largest_polygon(geom) -> Polygon | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        polys = [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
        if not polys:
            return None
        return max(polys, key=lambda g: g.area)
    return None


def inset_polygon(poly: Polygon, dist: float) -> Polygon | None:
    if dist <= 0:
        return poly
    shrunk = poly.buffer(-dist, join_style=2)
    return largest_polygon(shrunk)


def format_m2(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")
