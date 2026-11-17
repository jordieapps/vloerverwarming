import math

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from vloerverwarming.heating import (
    _split_strips,
    generate_room,
    l_route,
    route_length,
    serpentine_passes,
    spiral_passes,
)


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


def test_double_spiral_ends_near_supply():
    inner = rect_mm().buffer(-100)
    manifold = (-1000.0, 2000.0)
    from shapely.ops import nearest_points
    from shapely.geometry import Point as P

    _, hint = nearest_points(P(manifold), inner.exterior)
    passes, connectors = spiral_passes(inner, 100.0, (hint.x, hint.y))
    full = [p for p in passes]
    start = full[0].points[0]
    end = full[-1].points[-1]
    assert math.hypot(end[0] - start[0], end[1] - start[1]) < 3 * 100.0
    for p in full:
        for x, y in p.points:
            assert inner.contains(P(x, y)) or inner.exterior.distance(P(x, y)) < 1e-6


def test_l_route():
    assert l_route((0, 0), (10, 5)) == [(0, 0), (0, 5), (10, 5)]
    assert l_route((0, 0), (10, 5), vertical_first=False) == [(0, 0), (10, 0), (10, 5)]
    assert l_route((0, 0), (0, 5)) == [(0, 0), (0, 5)]
    assert route_length([(0, 0), (0, 5), (10, 5)]) == 15.0


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


def _obstacle_room():
    kamer = Polygon([(0, 0), (8000, 0), (8000, 6000), (0, 6000)])
    obstakel = Polygon([(3000, 2000), (5000, 2000), (5000, 4000), (3000, 4000)])
    return kamer, obstakel


def test_obstacle_is_avoided():
    from shapely.geometry import box

    kamer, obstakel = _obstacle_room()
    result = generate_room(
        "test", kamer, 0.001, hoh_m=0.15, edge_m=0.10, pattern="spiraal",
        obstacles=[obstakel],
    )
    assert result is not None
    gebied = obstakel.buffer(-1)
    for c in result.circuits:
        for x, y in c.path.points:
            assert not gebied.contains(Point(x, y))


def test_spiral_with_hole_has_interior_loop():
    kamer, obstakel = _obstacle_room()
    werk = kamer.difference(obstakel)
    passes, connectors = spiral_passes(werk.buffer(-100), 200.0)
    assert passes
    for p in passes:
        for x, y in p.points:
            assert not obstakel.contains(Point(x, y))
    dichtbij = sum(
        1 for p in passes for x, y in p.points
        if obstakel.exterior.distance(Point(x, y)) < 300
    )
    assert dichtbij >= 4


def test_split_strips_creates_groups():
    from shapely.geometry import box

    groot = Polygon([(0, 0), (12000, 0), (12000, 8000), (0, 8000)])
    delen = _split_strips(groot, 3, 0.5 / 0.001**2)
    assert len(delen) >= 3
    totaal = sum(d.area for d in delen)
    assert abs(totaal - groot.area) < groot.area * 0.01


def test_group_splitting_yields_multiple_circuits():
    from shapely.geometry import box

    groot = Polygon([(0, 0), (12000, 0), (12000, 8000), (0, 8000)])
    result = generate_room(
        "groot", groot, 0.001, hoh_m=0.15, edge_m=0.10, pattern="spiraal",
        group_max_m2=25.0,
    )
    assert result is not None
    assert result.area_m2 > 25.0
    assert len(result.circuits) >= 2


def test_grid_router_routes_around_obstacle():
    from shapely.geometry import box
    from shapely.ops import unary_union

    from vloerverwarming.routing import GridRouter

    kamer, obstakel = _obstacle_room()
    vrije = kamer.difference(obstakel)
    router = GridRouter(vrije, 100.0)
    pad = router.route((500, 500), (7500, 5500))
    assert pad is not None
    lijn = LineString(pad)
    assert vrije.buffer(1.0).covers(lijn)
    assert not lijn.crosses(obstakel)
    assert not obstakel.buffer(-1).intersects(lijn)


def test_grid_router_snaps_blocked_endpoints():
    from shapely.geometry import box

    from vloerverwarming.routing import GridRouter

    vrije = box(0, 0, 5000, 5000).buffer(-200)
    router = GridRouter(vrije, 100.0)
    pad = router.route((10, 2500), (4990, 2500))
    assert pad is not None
    assert vrije.buffer(1.0).covers(LineString(pad))


def test_obstacle_footprints_from_blocks():
    ezdxf = pytest.importorskip("ezdxf")
    from vloerverwarming.ruimtes import obstacle_footprints

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    trap = doc.blocks.new(name="trap test")
    trap.add_lwpolyline([(0, 0), (1000, 0), (1000, 300), (0, 300)], close=True)
    msp.add_blockref("trap test", (5000, 5000))
    obstakels = obstacle_footprints(doc)
    assert len(obstakels) == 1
    assert obstakels[0].equals(box(5000, 5000, 6000, 5300))


def test_free_space_subtracts_walls_and_hatch():
    from shapely.geometry import box

    from vloerverwarming.ruimtes import free_space

    kamer = box(0, 0, 8000, 6000)
    wand = LineString([(4000, -60), (4000, 300)])
    obstakel = box(1000, 1000, 2000, 2000)
    hatch = box(3000, 1000, 3100, 1800)
    vr = free_space([kamer], obstacles=[obstakel], walls=[wand], wall_thickness=120,
                    hatch_fills=[hatch])
    assert vr is not None
    assert vr.intersection(obstakel).area == 0
    assert vr.intersection(hatch).area == 0
