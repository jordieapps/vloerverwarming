from __future__ import annotations

import csv
import math
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from shapely.geometry import Point, Polygon

from .dxf_io import (
    add_manifold,
    add_room_result,
    detect_rooms,
    open_drawing,
    save_drawing,
    unit_to_m,
)
from .geometry import polygon_area_m2
from .heating import generate_room

COLORS = {
    "achtergrond": "#ffffff",
    "tekening": "#333333",
    "ruimte": "#007acc",
    "lang": "#d62728",
    "aanvoer": "#e08214",
    "verdeler": "#2ca02c",
    "selectie": "#ff9900",
}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Vloerverwarming — ruimtes, m², kringen en verdelers")
        self.root.geometry("1360x820")

        self.doc = None
        self.unit = "mm"
        self.rooms: list[dict] = []
        self.verdelers: list[dict] = []
        self.mode: str | None = None
        self.scale = 0.05
        self.offset = (100.0, 100.0)
        self.pan_start = None
        self.trace_points: list[tuple[float, float]] = []
        self.trace_ids: list[int] = []

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._bind_canvas()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Tekening openen…", command=self.open_file).pack(side=tk.LEFT)
        ttk.Label(bar, text="  Laag:").pack(side=tk.LEFT)
        self.layer_var = tk.StringVar(value="(alle lagen)")
        self.layer_combo = ttk.Combobox(bar, textvariable=self.layer_var, width=16, state="readonly")
        self.layer_combo.pack(side=tk.LEFT)
        ttk.Button(bar, text="Ruimtes detecteren", command=self.detect_rooms).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Ruimte intekenen", command=self.start_trace).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Verdeler plaatsen", command=self.start_manifold).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Selectie verwijderen", command=self.delete_selected).pack(side=tk.LEFT, padx=4)

    def _build_body(self) -> None:
        pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pane, padding=6)
        pane.add(left, weight=0)

        settings = ttk.LabelFrame(left, text="Instellingen vloerverwarming", padding=8)
        settings.pack(fill=tk.X)

        ttk.Label(settings, text="Eenheid tekening:").grid(row=0, column=0, sticky="w")
        self.unit_var = tk.StringVar(value="mm")
        ttk.Combobox(
            settings, textvariable=self.unit_var, values=["mm", "cm", "m"], width=6, state="readonly"
        ).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="H.o.h. afstand (cm):").grid(row=1, column=0, sticky="w")
        self.hoh_var = tk.StringVar(value="10")
        ttk.Spinbox(settings, textvariable=self.hoh_var, from_=5, to=40, width=6).grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="Randafstand (cm):").grid(row=2, column=0, sticky="w")
        self.edge_var = tk.StringVar(value="10")
        ttk.Spinbox(settings, textvariable=self.edge_var, from_=0, to=50, width=6).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="Patroon:").grid(row=3, column=0, sticky="w")
        self.pattern_var = tk.StringVar(value="serpentine")
        ttk.Combobox(
            settings, textvariable=self.pattern_var, values=["serpentine", "spiraal"], width=12, state="readonly"
        ).grid(row=3, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="Hoek slangen (°):").grid(row=4, column=0, sticky="w")
        self.angle_var = tk.StringVar(value="0")
        ttk.Spinbox(settings, textvariable=self.angle_var, from_=0, to=90, width=6).grid(row=4, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="Max kringlengte (m):").grid(row=5, column=0, sticky="w")
        self.maxc_var = tk.StringVar(value="120")
        ttk.Spinbox(settings, textvariable=self.maxc_var, from_=40, to=300, width=6).grid(row=5, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="Kringen per verdeler:").grid(row=6, column=0, sticky="w")
        self.maxn_var = tk.StringVar(value="8")
        ttk.Spinbox(settings, textvariable=self.maxn_var, from_=2, to=16, width=6).grid(row=6, column=1, sticky="w", padx=4)

        ttk.Button(settings, text="🔥 Vloerverwarming tekenen", command=self.generate_heating).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(10, 2)
        )
        ttk.Button(settings, text="DXF opslaan als…", command=self.save_file).grid(row=8, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(settings, text="Rapport opslaan (CSV)…", command=self.save_report).grid(row=9, column=0, columnspan=2, sticky="ew", pady=2)

        manifolds = ttk.LabelFrame(left, text="Verdelers", padding=8)
        manifolds.pack(fill=tk.X, pady=(8, 0))
        self.manifold_list = tk.Listbox(manifolds, height=4)
        self.manifold_list.pack(fill=tk.X)
        self.manifold_list.bind("<<ListboxSelect>>", self.on_select_manifold)
        row = ttk.Frame(manifolds)
        row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(row, text="Verwijderen", command=self.delete_manifold).pack(side=tk.LEFT)
        ttk.Label(row, text="  Toewijzen:").pack(side=tk.LEFT)
        self.assign_var = tk.StringVar()
        self.assign_combo = ttk.Combobox(row, textvariable=self.assign_var, width=12, state="readonly")
        self.assign_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="OK", width=4, command=self.assign_room).pack(side=tk.LEFT)

        totals = ttk.LabelFrame(left, text="Ruimtes", padding=8)
        totals.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(
            totals, columns=("naam", "m2", "verdeler", "kringen", "lengte", "mm2"), show="headings", height=12
        )
        for col, text, width, anchor in (
            ("naam", "Ruimte", 110, "w"),
            ("m2", "m²", 50, "e"),
            ("verdeler", "Verdeler", 80, "w"),
            ("kringen", "Kringen", 50, "e"),
            ("lengte", "Slang (m)", 60, "e"),
            ("mm2", "m/m²", 50, "e"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_room)
        self.total_var = tk.StringVar(value="Totaal: —")
        ttk.Label(totals, textvariable=self.total_var).pack(fill=tk.X, pady=(4, 0))

        self.canvas = tk.Canvas(pane, bg=COLORS["achtergrond"], cursor="crosshair")
        pane.add(self.canvas, weight=1)

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="Open een DXF/DWG-tekening om te starten.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w", padding=(6, 2)).pack(
            side=tk.BOTTOM, fill=tk.X
        )

    def _bind_canvas(self) -> None:
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.canvas.bind("<ButtonPress-3>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<B3-Motion>", self.on_pan_move)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Button-4>", self.on_wheel)
        self.canvas.bind("<Button-5>", self.on_wheel)
        self.root.bind("<Return>", self.on_enter)
        self.root.bind("<Escape>", self.on_escape)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Kies tekening",
            filetypes=[("Tekeningen", "*.dxf *.dwg"), ("DXF", "*.dxf"), ("DWG", "*.dwg")],
        )
        if not path:
            return
        try:
            self.doc, self.unit = open_drawing(path)
        except Exception as exc:
            messagebox.showerror(
                "Fout bij openen",
                f"{exc}\n\nDWG-bestanden vereisen de gratis 'ODA File Converter'.\n"
                "Je kan het bestand ook eerst als DXF opslaan in je CAD-programma.",
            )
            return
        self.unit_var.set(self.unit)
        self.rooms = []
        self.verdelers = []
        self.refresh_manifold_widgets()
        self.refresh_tree()
        layers = sorted({e.dxf.layer for e in self.doc.modelspace() if e.dxftype() in ("LWPOLYLINE", "POLYLINE")})
        self.layer_combo["values"] = ["(alle lagen)"] + layers
        self.layer_var.set("(alle lagen)")
        self._fitted = False
        self.redraw()
        self.set_status(f"Geopend: {path} (eenheid: {self.unit}).")

    def _draw_entity(self, entity) -> None:
        etype = entity.dxftype()
        if entity.dxf.layer.startswith("VV_"):
            return
        color = COLORS["tekening"]
        if etype == "LINE":
            p1, p2 = entity.dxf.start, entity.dxf.end
            self.canvas.create_line(*self.to_screen(p1.x, p1.y), *self.to_screen(p2.x, p2.y), fill=color, width=1)
        elif etype in ("LWPOLYLINE", "POLYLINE"):
            try:
                raw = entity.get_points("xy")
            except Exception:
                return
            pts = []
            for p in raw:
                pts.extend(self.to_screen(p[0], p[1]))
            if len(pts) >= 4:
                closed = bool(getattr(entity, "closed", False))
                if closed:
                    pts.extend([pts[0], pts[1]])
                self.canvas.create_line(*pts, fill=color, width=1, smooth=False)
        elif etype == "CIRCLE":
            c, r = entity.dxf.center, entity.dxf.radius
            x1, y1 = self.to_screen(c.x - r, c.y - r)
            x2, y2 = self.to_screen(c.x + r, c.y + r)
            self.canvas.create_oval(x1, y1, x2, y2, outline=color, width=1)
        elif etype == "ARC":
            c = entity.dxf.center
            r = entity.dxf.radius
            pts = []
            for i in range(25):
                a = math.radians(entity.dxf.start_angle + (entity.dxf.end_angle - entity.dxf.start_angle) * i / 24)
                pts.extend(self.to_screen(c.x + r * math.cos(a), c.y + r * math.sin(a)))
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=color, width=1)
        elif etype in ("TEXT", "MTEXT"):
            try:
                pos = entity.dxf.insert
                x, y = self.to_screen(pos.x, pos.y)
                text = entity.dxf.text if etype == "TEXT" else entity.plain_text()
                self.canvas.create_text(x, y, text=text, fill=color, anchor="sw", font=("Arial", 8))
            except Exception:
                pass

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.doc is None:
            return
        for entity in self.doc.modelspace():
            self._draw_entity(entity)
        self._fit_once()

    def _fit_once(self) -> None:
        if getattr(self, "_fitted", False):
            return
        bounds = self._doc_bounds()
        if bounds is None:
            return
        minx, miny, maxx, maxy = bounds
        w = max(maxx - minx, 1e-6)
        h = max(maxy - miny, 1e-6)
        cw = self.canvas.winfo_width() or 1200
        ch = self.canvas.winfo_height() or 700
        self.scale = min(cw / w, ch / h) * 0.9
        self.offset = (40 - minx * self.scale, ch - 40 + miny * self.scale)
        self._fitted = True
        self.redraw_plain()

    def _doc_bounds(self):
        minx = miny = math.inf
        maxx = maxy = -math.inf
        found = False
        for entity in self.doc.modelspace():
            try:
                if entity.dxftype() == "LINE":
                    pts = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
                elif entity.dxftype() in ("LWPOLYLINE", "POLYLINE"):
                    pts = [(p[0], p[1]) for p in entity.get_points("xy")]
                elif entity.dxftype() == "CIRCLE":
                    c, r = entity.dxf.center, entity.dxf.radius
                    pts = [(c.x - r, c.y - r), (c.x + r, c.y + r)]
                else:
                    continue
            except Exception:
                continue
            for x, y in pts:
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
            found = True
        return (minx, miny, maxx, maxy) if found else None

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset[0], -y * self.scale + self.offset[1]

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.offset[0]) / self.scale, -(sy - self.offset[1]) / self.scale

    def on_wheel(self, event) -> None:
        factor = 1.15 if (event.num == 4 or getattr(event, "delta", 0) > 0) else 1 / 1.15
        wx, wy = self.to_world(event.x, event.y)
        self.scale *= factor
        self.offset = (event.x - wx * self.scale, event.y + wy * self.scale)
        if self.doc is not None:
            self.redraw_plain()

    def redraw_plain(self) -> None:
        self.canvas.delete("all")
        if self.doc is None:
            return
        for entity in self.doc.modelspace():
            self._draw_entity(entity)
        for room in self.rooms:
            self._draw_room(room)
        for v in self.verdelers:
            self._draw_manifold(v)

    def on_pan_start(self, event) -> None:
        self.pan_start = (event.x, event.y)

    def on_pan_move(self, event) -> None:
        if self.pan_start:
            dx, dy = event.x - self.pan_start[0], event.y - self.pan_start[1]
            self.offset = (self.offset[0] + dx, self.offset[1] + dy)
            self.pan_start = (event.x, event.y)
            if self.doc is not None:
                self.redraw_plain()

    def start_trace(self) -> None:
        if self.doc is None:
            messagebox.showinfo("Info", "Open eerst een tekening.")
            return
        self.mode = "trace"
        self.trace_points = []
        self.set_status("Ruimte intekenen: klik hoekpunten, dubbelklik of Enter om te sluiten, Esc om te annuleren.")

    def start_manifold(self) -> None:
        if self.doc is None:
            messagebox.showinfo("Info", "Open eerst een tekening.")
            return
        self.mode = "manifold"
        self.set_status("Klik in de tekening waar de verdeler komt.")

    def on_left_click(self, event) -> None:
        if self.mode == "manifold":
            self.place_manifold(event)
            return
        if self.mode == "trace":
            x, y = self.to_world(event.x, event.y)
            self.trace_points.append((x, y))
            if len(self.trace_points) > 1:
                p1 = self.to_screen(*self.trace_points[-2])
                p2 = self.to_screen(*self.trace_points[-1])
                self.trace_ids.append(self.canvas.create_line(*p1, *p2, fill=COLORS["ruimte"], width=2))
            r = 3
            self.trace_ids.append(
                self.canvas.create_oval(event.x - r, event.y - r, event.x + r, event.y + r, fill=COLORS["ruimte"])
            )

    def on_double_click(self, event) -> None:
        if self.mode == "trace":
            self.finish_trace()

    def on_enter(self, event) -> None:
        if self.mode == "trace":
            self.finish_trace()

    def on_escape(self, event) -> None:
        if self.mode == "trace" and self.trace_points:
            self.trace_points = []
            for i in self.trace_ids:
                self.canvas.delete(i)
            self.trace_ids = []
            self.set_status("Intekenen geannuleerd.")
        self.mode = None

    def place_manifold(self, event) -> None:
        x, y = self.to_world(event.x, event.y)
        dialog = ManifoldDialog(self.root, len(self.verdelers) + 1)
        self.root.wait_window(dialog.top)
        if dialog.result is None:
            self.mode = None
            return
        name, max_kring, max_kringen = dialog.result
        v = {"name": name, "pos": (x, y), "max_kring": max_kring, "max_kringen": max_kringen}
        self.verdelers.append(v)
        self.mode = None
        self.refresh_manifold_widgets()
        self.redraw_plain()
        self.set_status(f"{name} geplaatst ({max_kring:.0f} m max, {max_kringen} uitgangen).")

    def delete_manifold(self) -> None:
        selection = self.manifold_list.curselection()
        if not selection:
            return
        index = selection[0]
        name = self.verdelers[index]["name"]
        del self.verdelers[index]
        for room in self.rooms:
            if room.get("manifold") == name:
                room["manifold"] = None
        self.refresh_manifold_widgets()
        self.refresh_tree()
        self.redraw_plain()

    def on_select_manifold(self, _event=None) -> None:
        selection = self.manifold_list.curselection()
        if selection:
            self.assign_var.set(self.verdelers[selection[0]]["name"])

    def assign_room(self) -> None:
        selection = self.tree.selection()
        mname = self.assign_var.get()
        if not selection or not mname:
            messagebox.showinfo("Info", "Selecteer een ruimte (in de lijst) en een verdeler.")
            return
        index = self.tree.index(selection[0])
        self.rooms[index]["manifold"] = mname
        self.refresh_tree()
        self.set_status(f"{self.rooms[index]['name']} toegewezen aan {mname}.")

    def refresh_manifold_widgets(self) -> None:
        self.manifold_list.delete(0, tk.END)
        for v in self.verdelers:
            self.manifold_list.insert(
                tk.END, f"{v['name']} — max {v['max_kring']:.0f} m, {v['max_kringen']} uitgangen"
            )
        self.assign_combo["values"] = [v["name"] for v in self.verdelers]
        if self.verdelers and not self.assign_var.get():
            self.assign_var.set(self.verdelers[0]["name"])

    def start_generation_values(self):
        try:
            hoh = float(str(self.hoh_var.get()).replace(",", "."))
            edge = float(str(self.edge_var.get()).replace(",", "."))
            angle = float(str(self.angle_var.get()).replace(",", "."))
            maxc = float(str(self.maxc_var.get()).replace(",", "."))
            maxn = int(self.maxn_var.get())
        except ValueError:
            messagebox.showerror("Fout", "Ongeldige instellingen (gebruik cijfers).")
            return None
        return hoh, edge, angle, maxc, maxn

    def generate_heating(self) -> None:
        if not self.rooms:
            messagebox.showinfo("Info", "Er zijn geen ruimtes. Detecteer of teken eerst ruimtes.")
            return
        values = self.start_generation_values()
        if values is None:
            return
        hoh, edge, angle, maxc, maxn = values
        if self.doc is not None:
            msp = self.doc.modelspace()
            for entity in list(msp):
                if entity.dxf.layer.startswith("VV_"):
                    msp.delete_entity(entity)
        for v in self.verdelers:
            v["max_kringen"] = maxn
        if self.doc is not None:
            for v in self.verdelers:
                add_manifold(self.doc, v["pos"], v["name"], self.unit_var.get())
        total_m2 = total_m = 0
        warnings = []
        counters: dict[str, int] = {}
        for room in self.rooms:
            manifold = self._manifold_for(room)
            mname = manifold["name"] if manifold else None
            mpos = manifold["pos"] if manifold else None
            first_nr = counters.get(mname, 0) + 1 if mname else 1
            result = generate_room(
                name=room["name"],
                poly=room["poly"],
                unit_to_m=unit_to_m(self.unit_var.get()),
                hoh_m=hoh / 100.0,
                edge_m=edge / 100.0,
                pattern=self.pattern_var.get(),
                angle_deg=angle,
                max_circuit_m=maxc,
                manifold_name=mname,
                manifold_pos=mpos,
                first_circuit_number=first_nr,
                max_circuits=manifold["max_kringen"] if manifold else None,
            )
            room["result"] = result
            if result is None:
                warnings.append(f"{room['name']}: te klein of geen slang mogelijk")
                continue
            if mname:
                counters[mname] = first_nr + len(result.circuits) - 1
            if self.doc is not None:
                add_room_result(self.doc, result, self.unit_var.get())
            total_m2 += result.area_m2
            total_m += result.pipe_length_m
            warnings.extend(f"{result.name}: {w}" for w in result.warnings)
        self.redraw_plain()
        self.refresh_tree()
        if total_m2:
            self.total_var.set(
                f"Totaal: {total_m2:.2f} m² | {total_m:.1f} m | {total_m / total_m2:.2f} m/m²"
            )
        self.set_status("Vloerverwarming getekend. " + (" | ".join(warnings) if warnings else "Geen waarschuwingen."))

    def _manifold_for(self, room: dict) -> dict | None:
        if room.get("manifold"):
            for v in self.verdelers:
                if v["name"] == room["manifold"]:
                    return v
            return None
        if not self.verdelers:
            return None
        poly: Polygon = room["poly"]
        centroid = (poly.centroid.x, poly.centroid.y)
        return min(self.verdelers, key=lambda v: Point(centroid).distance(Point(v["pos"])))

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        total_m2 = total_m = 0.0
        total_circuits = 0
        for room in self.rooms:
            res = room.get("result")
            m2 = polygon_area_m2(room["poly"], self.unit)
            if res:
                total_m2 += res.area_m2
                total_m += res.pipe_length_m
                total_circuits += len(res.circuits)
                self.tree.insert(
                    "", "end",
                    values=(
                        room["name"],
                        f"{res.area_m2:.2f}",
                        res.manifold or "—",
                        len(res.circuits),
                        f"{res.pipe_length_m:.1f}",
                        f"{res.m_per_m2:.2f}",
                    ),
                )
            else:
                self.tree.insert(
                    "", "end",
                    values=(room["name"], f"{m2:.2f}", room.get("manifold") or "—", "—", "—", "—"),
                )
        if self.rooms:
            self.total_var.set(
                f"Totaal: {total_m2:.2f} m² | {total_circuits} kringen | {total_m:.1f} m slang"
            )

    def on_select_room(self, _event=None) -> None:
        for room in self.rooms:
            room["selected"] = False
        for item in self.tree.selection():
            index = self.tree.index(item)
            if 0 <= index < len(self.rooms):
                self.rooms[index]["selected"] = True
        self.redraw_plain()

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        indices = [self.tree.index(item) for item in selection]
        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self.rooms):
                del self.rooms[index]
        self.redraw_plain()
        self.refresh_tree()

    def finish_trace(self) -> None:
        if len(self.trace_points) < 3:
            return
        name = simpledialog.askstring(
            "Ruimtenaam", "Naam van de ruimte:", initialvalue=f"Ruimte {len(self.rooms) + 1}"
        )
        if name is None:
            self.on_escape(None)
            return
        poly = Polygon(self.trace_points)
        room = {"name": name or f"Ruimte {len(self.rooms) + 1}", "poly": poly, "result": None, "manifold": None}
        self.rooms.append(room)
        self.trace_points = []
        for i in self.trace_ids:
            self.canvas.delete(i)
        self.trace_ids = []
        self.mode = None
        self._draw_room(room)
        self.refresh_tree()
        self.set_status(f"Ruimte '{room['name']}' toegevoegd: {polygon_area_m2(poly, self.unit):.2f} m².")

    def _draw_room(self, room: dict) -> None:
        poly: Polygon = room["poly"]
        pts = []
        for x, y in poly.exterior.coords:
            pts.extend(self.to_screen(x, y))
        color = COLORS["selectie"] if room.get("selected") else COLORS["ruimte"]
        self.canvas.create_line(*pts, fill=color, width=2)
        sx, sy = self.to_screen(poly.centroid.x, poly.centroid.y)
        label = f"{room['name']}: {polygon_area_m2(poly, self.unit):.2f} m²"
        res = room.get("result")
        if res:
            label += f" | {len(res.circuits)} kringen | {res.pipe_length_m:.1f} m"
            for c in res.circuits:
                cpts = []
                for x, y in c.path.points:
                    cpts.extend(self.to_screen(x, y))
                if len(cpts) >= 4:
                    self.canvas.create_line(*cpts, fill=COLORS["lang"], width=1)
                lx, ly = self.to_screen(*c.start)
                self.canvas.create_text(
                    lx, ly - 8, text=f"K{c.number}", fill=COLORS["lang"], font=("Arial", 8, "bold")
                )
            if res.manifold_pos:
                for c in res.circuits:
                    for route in (c.supply_route, c.return_route):
                        if len(route) >= 2:
                            pts = []
                            for x, y in route:
                                pts.extend(self.to_screen(x, y))
                            self.canvas.create_line(*pts, fill=COLORS["aanvoer"], width=1, dash=(4, 3))
        self.canvas.create_text(sx, sy, text=label, fill=color, font=("Arial", 9, "bold"))

    def _draw_manifold(self, v: dict) -> None:
        x, y = self.to_screen(*v["pos"])
        r = 6
        self.canvas.create_oval(x - r, y - r, x + r, y + r, outline=COLORS["verdeler"], width=2)
        self.canvas.create_line(x - r, y, x + r, y, fill=COLORS["verdeler"])
        self.canvas.create_line(x, y - r, x, y + r, fill=COLORS["verdeler"])
        self.canvas.create_text(
            x + r + 4, y - r - 4, text=v["name"], fill=COLORS["verdeler"], anchor="sw", font=("Arial", 9, "bold")
        )

    def detect_rooms(self) -> None:
        if self.doc is None:
            messagebox.showinfo("Info", "Open eerst een tekening.")
            return
        layer = self.layer_var.get()
        layer = None if layer == "(alle lagen)" else layer
        found = detect_rooms(self.doc, layer=layer, min_area_m2=0.5, unit=self.unit)
        existing = len(self.rooms)
        for offset, (layer_name, poly, _entity) in enumerate(found, start=1):
            self.rooms.append(
                {"name": f"Ruimte {existing + offset}", "poly": poly, "result": None, "manifold": None}
            )
        self.refresh_tree()
        self.redraw_plain()
        self.set_status(f"{len(found)} ruimte(s) gedetecteerd op gesloten polylines.")

    def save_file(self) -> None:
        if self.doc is None:
            messagebox.showinfo("Info", "Open eerst een tekening.")
            return
        path = filedialog.asksaveasfilename(
            title="DXF opslaan als", defaultextension=".dxf", filetypes=[("DXF", "*.dxf")]
        )
        if not path:
            return
        try:
            save_drawing(self.doc, path)
        except Exception as exc:
            messagebox.showerror("Fout bij opslaan", str(exc))
            return
        self.set_status(f"Opgeslagen: {path}")

    def save_report(self) -> None:
        results = [r["result"] for r in self.rooms if r.get("result")]
        if not results:
            messagebox.showinfo("Info", "Teken eerst de vloerverwarming (dan is er een rapport).")
            return
        path = filedialog.asksaveasfilename(
            title="Rapport opslaan als", defaultextension=".csv", filetypes=[("CSV", "*.csv")]
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Ruimte", "m²", "Verdeler", "Kring", "Lengte (m)"])
            for res in results:
                for c in res.circuits:
                    writer.writerow([
                        res.name,
                        f"{res.area_m2:.2f}".replace(".", ","),
                        res.manifold or "",
                        c.number,
                        f"{c.length_m:.1f}".replace(".", ","),
                    ])
            writer.writerow([
                "TOTAAL",
                f"{sum(r.area_m2 for r in results):.2f}".replace(".", ","),
                "",
                sum(len(r.circuits) for r in results),
                f"{sum(r.pipe_length_m for r in results):.1f}".replace(".", ","),
            ])
        self.set_status(f"Rapport opgeslagen: {path}")


class ManifoldDialog:
    def __init__(self, parent, index: int) -> None:
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("Verdeler")
        self.top.grab_set()
        frm = ttk.Frame(self.top, padding=10)
        frm.pack()
        ttk.Label(frm, text="Naam:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=f"Verdeler {index}")
        ttk.Entry(frm, textvariable=self.name_var, width=20).grid(row=0, column=1, pady=2)
        ttk.Label(frm, text="Max kringlengte (m):").grid(row=1, column=0, sticky="w")
        self.maxc_var = tk.StringVar(value="120")
        ttk.Spinbox(frm, textvariable=self.maxc_var, from_=40, to=300, width=8).grid(row=1, column=1, pady=2)
        ttk.Label(frm, text="Aantal uitgangen:").grid(row=2, column=0, sticky="w")
        self.maxn_var = tk.StringVar(value="8")
        ttk.Spinbox(frm, textvariable=self.maxn_var, from_=2, to=16, width=8).grid(row=2, column=1, pady=2)
        ttk.Button(frm, text="OK", command=self.ok).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.top.bind("<Return>", lambda e: self.ok())
        self.top.bind("<Escape>", lambda e: self.top.destroy())

    def ok(self) -> None:
        try:
            self.result = (
                self.name_var.get() or "Verdeler",
                float(str(self.maxc_var.get()).replace(",", ".")),
                int(self.maxn_var.get()),
            )
        except ValueError:
            return
        self.top.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
