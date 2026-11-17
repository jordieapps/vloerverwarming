from __future__ import annotations

import heapq
import math

from shapely.geometry import Point
from shapely.ops import nearest_points

WALL_HUG_COST = 0.85
STEP_COST = 1.0


def _simplify(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in points:
        if out and abs(out[-1][0] - p[0]) < 1e-9 and abs(out[-1][1] - p[1]) < 1e-9:
            continue
        out.append(p)
    keep: list[tuple[float, float]] = []
    for i, p in enumerate(out):
        if i == 0 or i >= len(out) - 1:
            keep.append(p)
            continue
        a, b = out[i - 1], out[i + 1]
        if not ((abs(a[0] - b[0]) < 1e-9 and abs(a[0] - p[0]) < 1e-9)
                or (abs(a[1] - b[1]) < 1e-9 and abs(a[1] - p[1]) < 1e-9)):
            keep.append(p)
    return keep


class GridRouter:
    def __init__(self, free_space: Polygon, cell: float, extra_points=()):
        self.free = free_space
        bounds = free_space.bounds
        xs = [bounds[0], bounds[2]] + [p[0] for p in extra_points]
        ys = [bounds[1], bounds[3]] + [p[1] for p in extra_points]
        lo_x, lo_y = min(xs) - cell, min(ys) - cell
        hi_x, hi_y = max(xs) + cell, max(ys) + cell
        target_nx = int(math.ceil((hi_x - lo_x) / cell)) + 1
        target_ny = int(math.ceil((hi_y - lo_y) / cell)) + 1
        scale = max(1.0, target_nx / 900.0, target_ny / 900.0)
        self.cell = cell * scale
        self.lo_x, self.lo_y = lo_x, lo_y
        self.nx = int(math.ceil((hi_x - lo_x) / self.cell)) + 1
        self.ny = int(math.ceil((hi_y - lo_y) / self.cell)) + 1
        self.blocked = [[True] * self.ny for _ in range(self.nx)]
        for ix in range(self.nx):
            x = lo_x + ix * self.cell
            col = self.blocked[ix]
            for iy in range(self.ny):
                if free_space.covers(Point(x, lo_y + iy * self.cell)):
                    col[iy] = False
        self.wall_adj = [[False] * self.ny for _ in range(self.nx)]
        for ix in range(self.nx):
            for iy in range(self.ny):
                if self.blocked[ix][iy]:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    cx, cy = ix + dx, iy + dy
                    if 0 <= cx < self.nx and 0 <= cy < self.ny and self.blocked[cx][cy]:
                        self.wall_adj[ix][iy] = True
                        break

    def _to_grid(self, pt: tuple[float, float]):
        gx = int(round((pt[0] - self.lo_x) / self.cell))
        gy = int(round((pt[1] - self.lo_y) / self.cell))
        if not (0 <= gx < self.nx and 0 <= gy < self.ny):
            return None
        return gx, gy

    def _free_cell(self, g):
        gx, gy = g
        if not self.blocked[gx][gy]:
            return g
        for r in range(1, 9):
            best, best_d = None, None
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    cx, cy = gx + dx, gy + dy
                    if 0 <= cx < self.nx and 0 <= cy < self.ny and not self.blocked[cx][cy]:
                        d = dx * dx + dy * dy
                        if best_d is None or d < best_d:
                            best, best_d = (cx, cy), d
            if best is not None:
                return best
        return None

    def _snap(self, pt: tuple[float, float]) -> tuple[float, float]:
        p = Point(pt)
        if self.free.covers(p):
            return pt
        try:
            q = nearest_points(self.free, p)[0]
        except Exception:
            return pt
        return (q.x, q.y)

    def route(self, start: tuple[float, float], goal: tuple[float, float]):
        start = self._snap(start)
        goal = self._snap(goal)
        gs = self._free_cell(self._to_grid(start)) if self._to_grid(start) else None
        gg = self._free_cell(self._to_grid(goal)) if self._to_grid(goal) else None
        if gs is None or gg is None:
            return None
        nx, ny = self.nx, self.ny
        blocked, wall_adj = self.blocked, self.wall_adj

        def h(g):
            return abs(g[0] - gg[0]) + abs(g[1] - gg[1])

        open_set = [(h(gs), 0.0, gs)]
        came = {}
        cost = {gs: 0.0}
        found = gs == gg
        while open_set:
            _, gcur, cur = heapq.heappop(open_set)
            if cur == gg:
                found = True
                break
            if gcur > cost.get(cur, float("inf")):
                continue
            cx, cy = cur
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (cx + dx, cy + dy)
                if not (0 <= nxt[0] < nx and 0 <= nxt[1] < ny) or blocked[nxt[0]][nxt[1]]:
                    continue
                nc = gcur + (WALL_HUG_COST if wall_adj[nxt[0]][nxt[1]] else STEP_COST)
                if nc < cost.get(nxt, float("inf")):
                    cost[nxt] = nc
                    came[nxt] = cur
                    heapq.heappush(open_set, (nc + h(nxt), nc, nxt))
        if not found:
            return None
        path = [gg]
        while path[-1] != gs:
            path.append(came[path[-1]])
        path.reverse()
        pts = [(self.lo_x + gx * self.cell, self.lo_y + gy * self.cell) for gx, gy in path]
        pts[0] = start
        pts[-1] = goal
        return _simplify(pts)
