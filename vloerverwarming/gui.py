from __future__ import annotations

import math
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from shapely.geometry import LineString, Point, Polygon

from .dxf_io import (
    LAYER_PIPE,
    LAYER_ROOM,
    LAYER_TEXT,
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
    "selectie": "#ff9900",
}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Vloerverwarming — ruimtes, m² en slangen intekenen")
        self.root.geometry("1280x800")

        self.doc = None
        self.unit = "mm"
        self.u = 0.001
        self.rooms: list[dict] = []
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
        self.layer_combo = ttk.Combobox(bar, textvariable=self.layer_var, width=18, state="readonly")
        self.layer_combo.pack(side=tk.LEFT)
        ttk.Button(bar, text="Ruimtes detecteren", command=self.detect_rooms).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Ruimte intekenen", command=self.start_trace).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Geselecteerde verwijderen", command=self.delete_selected).pack(side=tk.LEFT, padx=4)

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
        ttk.Spinbox(settings, textvariable=self.hoh_var, from_=5, to=40, width=6).grid(
            row=1, column=1, sticky="w", padx=4
        )

        ttk.Label(settings, text="Randafstand (cm):").grid(row=2, column=0, sticky="w")
        self.edge_var = tk.StringVar(value="10")
        ttk.Spinbox(settings, textvariable=self.edge_var, from_=0, to=50, width=6).grid(
            row=2, column=1, sticky="w", padx=4
        )

        ttk.Label(settings, text="Patroon:").grid(row=3, column=0, sticky="w")
        self.pattern_var = tk.StringVar(value="serpentine")
        ttk.Combobox(
            settings,
            textvariable=self.pattern_var,
            values=["serpentine", "spiraal"],
            width=12,
            state="readonly",
        ).grid(row=3, column=1, sticky="w", padx=4)

        ttk.Label(settings, text="Hoek slangen (°):").grid(row=4, column=0, sticky="w")
        self.angle_var = tk.StringVar(value="0")
        ttk.Spinbox(settings, textvariable=self.angle_var, from_=0, to=90, width=6).grid(
            row=4, column=1, sticky="w", padx=4
        )

        ttk.Label(settings, text="Max kringlengte (m):").grid(row=5, column=0, sticky="w")
        self.maxc_var = tk.StringVar(value="120")
        ttk.Spinbox(settings, textvariable=self.maxc_var, from_=40, to=300, width=6).grid(
            row=5, column=1, sticky="w", padx=4
        )

        ttk.Button(settings, text="🔥 Vloerverwarming tekenen", command=self.generate_heating).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(10, 2)
        )
        ttk.Button(settings, text="DXF opslaan als…", command=self.save_file).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=2
        )

        totals = ttk.LabelFrame(left, text="Ruimtes", padding=8)
        totals.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(
            totals, columns=("naam", "m2", "lengte", "mm2"), show="headings", height=14
        )
        self.tree.heading("naam", text="Ruimte")
        self.tree.heading("m2", text="m²")
        self.tree.heading("lengte", text="Slang (m)")
        self.tree.heading("mm2", text="m/m²")
        self.tree.column("naam", width=130)
        self.tree.column("m2", width=60, anchor="e")
        self.tree.column("lengte", width=70, anchor="e")
        self.tree.column("mm2", width=60, anchor="e")
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
        self.u = unit_to_m(self.unit)
        self.unit_var.set(self.unit)
        self.rooms = []
        self.refresh_tree()
        layers = sorted({e.dxf.layer for e in self.doc.modelspace() if e.dxftype() in ("LWPOLYLINE", "POLYLINE")})
        self.layer_combo["values"] = ["(alle lagen)"] + layers
        self.layer_var.set("(alle lagen)")
        self.scale = 0.05
        self.offset = (100.0, 100.0)
        self.redraw()
        self.set_status(f"Geopend: {path} (eenheid: {self.unit}). Klik 'Ruimtes detecteren' of teken zelf.")

    def _iter_entities(self):
        for entity in self.doc.modelspace():
            yield entity

    def _draw_entity(self, entity) -> None:
        etype = entity.dxftype()
        layer = LAYER_PIPE if entity.dxf.layer == LAYER_PIPE else COLORS["tekening"]
        if etype == "LINE":
            p1, p2 = entity.dxf.start, entity.dxf.end
            self.canvas.create_line(*self.to_screen(p1.x, p1.y), *self.to_screen(p2.x, p2.y), fill=layer, width=1)
        elif etype in ("LWPOLYLINE", "POLYLINE"):
            pts = []
            try:
                raw = entity.get_points("xy")
            except Exception:
                return
            for p in raw:
                pts.extend(self.to_screen(p[0], p[1]))
            if len(pts) >= 4:
                closed = bool(entity.closed) if etype == "LWPOLYLINE" else bool(entity.is_closed)
                if closed:
                    pts.extend([pts[0], pts[1]])
                self.canvas.create_line(*pts, fill=layer, width=1, smooth=False)
        elif etype == "CIRCLE":
            c, r = entity.dxf.center, entity.dxf.radius
            x1, y1 = self.to_screen(c.x - r, c.y - r)
            x2, y2 = self.to_screen(c.x + r, c.y + r)
            self.canvas.create_oval(x1, y1, x2, y2, outline=layer, width=1)
        elif etype == "ARC":
            c = entity.dxf.center
            r = entity.dxf.radius
            steps = 24
            pts = []
            for i in range(steps + 1):
                a = math.radians(entity.dxf.start_angle + (entity.dxf.end_angle - entity.dxf.start_angle) * i / steps)
                pts.extend(self.to_screen(c.x + r * math.cos(a), c.y + r * math.sin(a)))
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=layer, width=1)
        elif etype in ("TEXT", "MTEXT"):
            try:
                pos = entity.dxf.insert if etype == "TEXT" else entity.dxf.insert
                x, y = self.to_screen(pos.x, pos.y)
                text = entity.dxf.text if etype == "TEXT" else entity.plain_text()
                self.canvas.create_text(x, y, text=text, fill=layer, anchor="sw", font=("Arial", 8))
            except Exception:
                pass

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.doc is None:
            return
        visible = []
        for entity in self._iter_entities():
            if entity.dxf.layer in (LAYER_PIPE, LAYER_ROOM, LAYER_TEXT):
                continue
            self._draw_entity(entity)
            visible.append(entity)
        for room in self.rooms:
            self._draw_room(room)
        if visible:
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
        self.offset = (
            40 - minx * self.scale,
            ch - 40 + miny * self.scale,
        )
        self._fitted = True
        self.canvas.delete("all")
        for entity in self._iter_entities():
            if entity.dxf.layer in (LAYER_PIPE, LAYER_ROOM, LAYER_TEXT):
                continue
            self._draw_entity(entity)
        for room in self.rooms:
            self._draw_room(room)

    def _doc_bounds(self):
        minx = miny = math.inf
        maxx = maxy = -math.inf
        found = False
        for entity in self._iter_entities():
            if entity.dxf.layer in (LAYER_PIPE, LAYER_ROOM, LAYER_TEXT):
                continue
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
        sx = x * self.scale + self.offset[0]
        sy = -y * self.scale + self.offset[1]
        return sx, sy

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        x = (sx - self.offset[0]) / self.scale
        y = -(sy - self.offset[1]) / self.scale
        return x, y

    def on_wheel(self, event) -> None:
        factor = 1.15 if (event.num == 4 or event.delta > 0) else 1 / 1.15
        wx, wy = self.to_world(event.x, event.y)
        self.scale *= factor
        self.offset = (event.x - wx * self.scale, event.y + wy * self.scale)
        if self.doc is not None:
            self.redraw_plain()

    def redraw_plain(self) -> None:
        self.canvas.delete("all")
        if self.doc is None:
            return
        for entity in self._iter_entities():
            if entity.dxf.layer in (LAYER_PIPE, LAYER_ROOM, LAYER_TEXT):
                continue
            self._draw_entity(entity)
        for room in self.rooms:
            self._draw_room(room)

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
        self.trace_points = []
        self.set_status("Ruimte intekenen: klik hoekpunten, dubbelklik of Enter om te sluiten, Esc om te annuleren.")

    def on_left_click(self, event) -> None:
        if not self.trace_ids and not self.trace_points:
            return
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
        self.finish_trace()

    def on_enter(self, event) -> None:
        self.finish_trace()

    def on_escape(self, event) -> None:
        if self.trace_points:
            self.trace_points = []
            for i in self.trace_ids:
                self.canvas.delete(i)
            self.trace_ids = []
            self.set_status("Intekenen geannuleerd.")

    def finish_trace(self) -> None:
        if len(self.trace_points) < 3:
            return
        name = self.ask_name(len(self.rooms) + 1)
        poly = Polygon(self.trace_points)
        room = {"name": name, "poly": poly, "result": None}
        self.rooms.append(room)
        self.trace_points = []
        for i in self.trace_ids:
            self.canvas.delete(i)
        self.trace_ids = []
        self._draw_room(room)
        self.refresh_tree()
        self.set_status(f"Ruimte '{name}' toegevoegd: {polygon_area_m2(poly, self.unit):.2f} m².")

    def ask_name(self, index: int) -> str:
        dialog = simpledialog.askstring("Ruimtenaam", "Naam van de ruimte:", initialvalue=f"Ruimte {index}")
        return dialog or f"Ruimte {index}"

    def _draw_room(self, room: dict) -> None:
        poly: Polygon = room["poly"]
        pts = []
        for x, y in poly.exterior.coords:
            pts.extend(self.to_screen(x, y))
        color = COLORS["selectie"] if room.get("selected") else COLORS["ruimte"]
        self.canvas.create_line(*pts, fill=color, width=2)
        cx, cy = poly.centroid.x, poly.centroid.y
        sx, sy = self.to_screen(cx, cy)
        label = f"{room['name']}: {polygon_area_m2(poly, self.unit):.2f} m²"
        if room.get("result"):
            res = room["result"]
            label += f" | {res.pipe_length_m:.1f} m"
        self.canvas.create_text(sx, sy, text=label, fill=color, font=("Arial", 9, "bold"))

    def detect_rooms(self) -> None:
        if self.doc is None:
            messagebox.showinfo("Info", "Open eerst een tekening.")
            return
        layer = self.layer_var.get()
        layer = None if layer == "(alle lagen)" else layer
        found = detect_rooms(self.doc, layer=layer, min_area_m2=0.5, unit=self.unit)
        for layer_name, poly, _entity in found:
            self.rooms.append({"name": f"{layer_name}", "poly": poly, "result": None})
        self.redraw_plain()
        self.refresh_tree()
        self.set_status(f"{len(found)} ruimte(s) gedetecteerd op gesloten polylines.")

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        indices = [self.tree.index(item) for item in selection]
        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self.rooms):
                del self.rooms[index]
        self.redraw_plain()
        self.refresh_tree()

    def on_select_room(self, _event=None) -> None:
        for room in self.rooms:
            room["selected"] = False
        for item in self.tree.selection():
            index = self.tree.index(item)
            if 0 <= index < len(self.rooms):
                self.rooms[index]["selected"] = True
        self.redraw_plain()

    def generate_heating(self) -> None:
        if not self.rooms:
            messagebox.showinfo("Info", "Er zijn geen ruimtes. Detecteer of teken eerst ruimtes.")
            return
        try:
            hoh = float(str(self.hoh_var.get()).replace(",", "."))
            edge = float(str(self.edge_var.get()).replace(",", "."))
            angle = float(str(self.angle_var.get()).replace(",", "."))
            maxc = float(str(self.maxc_var.get()).replace(",", "."))
        except ValueError:
            messagebox.showerror("Fout", "Ongeldige instellingen (gebruik cijfers).")
            return
        if self.doc is not None:
            for entity in list(self.doc.modelspace()):
                if entity.dxf.layer in (LAYER_PIPE, LAYER_ROOM, LAYER_TEXT):
                    self.doc.modelspace().delete_entity(entity)
        total_m2 = 0.0
        total_m = 0.0
        warnings = []
        for room in self.rooms:
            result = generate_room(
                name=room["name"],
                poly=room["poly"],
                unit_to_m=unit_to_m(self.unit_var.get()),
                hoh_m=hoh / 100.0,
                edge_m=edge / 100.0,
                pattern=self.pattern_var.get(),
                angle_deg=angle,
                max_circuit_m=maxc,
            )
            room["result"] = result
            if result is None:
                warnings.append(f"{room['name']}: te klein of geen slang mogelijk")
                continue
            if self.doc is not None:
                add_room_result(self.doc, result)
            total_m2 += result.area_m2
            total_m += result.pipe_length_m
            warnings.extend(f"{result.name}: {w}" for w in result.warnings)
        self.redraw_plain()
        self.refresh_tree()
        self.total_var.set(f"Totaal: {total_m2:.2f} m² | {total_m:.1f} m slang | {total_m / total_m2 if total_m2 else 0:.2f} m/m²")
        self.set_status("Vloerverwarming getekend. " + (" | ".join(warnings) if warnings else "Geen waarschuwingen."))

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        total_m2 = total_m = 0.0
        for room in self.rooms:
            res = room.get("result")
            m2 = polygon_area_m2(room["poly"], self.unit)
            length = f"{res.pipe_length_m:.1f}" if res else "—"
            ratio = f"{res.m_per_m2:.2f}" if res else "—"
            self.tree.insert("", "end", values=(room["name"], f"{m2:.2f}", length, ratio))
            total_m2 += m2
            if res:
                total_m += res.pipe_length_m
        if self.rooms:
            self.total_var.set(f"Totaal: {total_m2:.2f} m² | {total_m:.1f} m slang")

    def save_file(self) -> None:
        if self.doc is None:
            messagebox.showinfo("Info", "Open eerst een tekening.")
            return
        path = filedialog.asksaveasfilename(
            title="DXF opslaan als",
            defaultextension=".dxf",
            filetypes=[("DXF", "*.dxf")],
        )
        if not path:
            return
        try:
            save_drawing(self.doc, path)
        except Exception as exc:
            messagebox.showerror("Fout bij opslaan", str(exc))
            return
        self.set_status(f"Opgeslagen: {path}")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
