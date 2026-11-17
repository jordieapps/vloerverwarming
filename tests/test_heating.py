import math

import pytest
from shapely.geometry import Point, Polygon

from vloerverwarming.heating import generate_room, serpentine, spiral


def rect_mm(x=5000.0, y=4000.0):
    return Polygon([(0, 0), (x, 0), (x, y), (0, y)])


def test_serpentine_length_and_bounds():
    poly = rect_mm()
    spacing = 150.0
    inner = poly.buffer(-100)
    path = serpentine(inner, spacing)
    assert path is not None
    for x, y in path.points:
        assert inner.contains(Point(x, y)) or inner.exterior.distance(Point(x, y)) < 1e-6
    minx, miny, maxx, maxy = inner.bounds
    n_rows = int((maxy - miny) / spacing)
    expected = n_rows * (maxx - minx) + (n_rows - 1) * math.pi * spacing / 2
    assert path.arc_length() == pytest.approx(expected, rel=0.05)


def test_serpentine_angle():
    path = serpentine(rect_mm().buffer(-100), 100.0, angle_deg=45.0)
    assert path is not None
    inner = rect_mm().buffer(-100)
    for x, y in path.points:
        assert inner.contains(Point(x, y)) or inner.exterior.distance(Point(x, y)) < 1e-6


def test_spiral_closes_inward():
    path = spiral(rect_mm().buffer(-100), 100.0)
    assert path is not None
    assert path.arc_length() > 0


def test_unit_conversion_and_m_per_m2():
    result = generate_room("test", rect_mm(), unit_to_m=0.001, hoh_m=0.10, edge_m=0.10)
    assert result is not None
    assert result.area_m2 == pytest.approx(20.0, abs=0.01)
    assert 8.5 < result.m_per_m2 < 10.5


def test_warning_on_long_circuit():
    big = Polygon([(0, 0), (30000, 0), (30000, 20000), (0, 20000)])
    result = generate_room("groot", big, unit_to_m=0.001, hoh_m=0.10, edge_m=0.10, max_circuit_m=120)
    assert result is not None
    assert result.warnings
