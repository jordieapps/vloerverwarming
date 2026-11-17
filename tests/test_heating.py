import math

import pytest
from shapely.geometry import Point, Polygon

from vloerverwarming.heating import generate_room, serpentine_passes, spiral_passes


def rect_mm(x=5000.0, y=4000.0):
    return Polygon([(0, 0), (x, 0), (x, y), (0, y)])


def test_serpentine_passes_bounds():
    inner = rect_mm().buffer(-100)
    passes, connectors = serpentine_passes(inner, 150.0)
    assert len(passes) > 10
    for p in passes:
        for x, y in p.points:
            assert inner.contains(Point(x, y)) or inner.exterior.distance(Point(x, y)) < 1e-6
    assert connectors[-1] is None


def test_serpentine_angle():
    inner = rect_mm().buffer(-100)
    passes, _ = serpentine_passes(inner, 100.0, angle_deg=45.0)
    for p in passes:
        for x, y in p.points:
            assert inner.contains(Point(x, y)) or inner.exterior.distance(Point(x, y)) < 1e-6


def test_spiral_passes():
    passes, connectors = spiral_passes(rect_mm().buffer(-100), 100.0)
    assert len(passes) > 3
    assert sum(p.arc_length() for p in passes) > 0


def test_unit_conversion_and_m_per_m2():
    result = generate_room("test", rect_mm(), unit_to_m=0.001, hoh_m=0.10, edge_m=0.10, max_circuit_m=200.0)
    assert result is not None
    assert result.area_m2 == pytest.approx(20.0, abs=0.01)
    assert len(result.circuits) == 1
    assert 8.5 < result.m_per_m2 < 10.5


def test_auto_split_without_manifold():
    result = generate_room("test", rect_mm(), unit_to_m=0.001, hoh_m=0.10, edge_m=0.10)
    assert result is not None
    assert len(result.circuits) == 2
    for c in result.circuits:
        assert c.length_m <= 120.0


def test_circuit_splitting_with_manifold():
    big = Polygon([(0, 0), (30000, 0), (30000, 20000), (0, 20000)])
    result = generate_room(
        "groot",
        big,
        unit_to_m=0.001,
        hoh_m=0.10,
        edge_m=0.10,
        max_circuit_m=120.0,
        manifold_name="Verdeler 1",
        manifold_pos=(15000.0, 10000.0),
    )
    assert result is not None
    assert len(result.circuits) > 1
    numbers = [c.number for c in result.circuits]
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))
    assert result.manifold == "Verdeler 1"
    for c in result.circuits:
        assert c.length_m > 0


def test_max_circuits_warning():
    big = Polygon([(0, 0), (30000, 0), (30000, 20000), (0, 20000)])
    result = generate_room(
        "groot",
        big,
        unit_to_m=0.001,
        hoh_m=0.10,
        edge_m=0.10,
        max_circuit_m=60.0,
        manifold_pos=(15000.0, 10000.0),
        max_circuits=2,
    )
    assert result is not None
    assert any("uitgangen" in w for w in result.warnings)


def test_serpentine_length_matches_theory():
    inner = rect_mm().buffer(-100)
    spacing = 150.0
    passes, connectors = serpentine_passes(inner, spacing)
    minx, miny, maxx, maxy = inner.bounds
    n_rows = int((maxy - miny) / spacing)
    expected = n_rows * (maxx - minx) + (n_rows - 1) * math.pi * spacing / 2
    total = sum(p.arc_length() for p in passes) + sum(
        c.arc_length() for c in connectors[:-1] if c is not None
    )
    assert total == pytest.approx(expected, rel=0.05)
