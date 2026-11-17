from __future__ import annotations

import argparse
import csv
import sys

from shapely.geometry import Point

from vloerverwarming.dxf_io import (
    add_legend,
    add_manifold,
    add_room_result,
    detect_rooms,
    open_drawing,
    save_drawing,
    unit_to_m,
)
from vloerverwarming.geometry import polygon_area_m2
from vloerverwarming.heating import generate_room


def parse_verdeler(spec: str):
    try:
        x_s, y_s = spec.split(",")
        return (float(x_s), float(y_s))
    except ValueError:
        print(f"Ongeldige verdeler-positie '{spec}' (gebruik: x,y in tekeningseenheden).")
        sys.exit(2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Vloerverwarming: ruimtes uit DXF/DWG, m² berekenen, kringen en verdelers intekenen."
    )
    parser.add_argument("input", help="DXF- of DWG-bestand")
    parser.add_argument("--uit", "-o", required=True, help="Uitvoerbestand (aanbevolen: .dxf)")
    parser.add_argument("--laag", default=None, help="Laagnaam met gesloten polylines (standaard: alle lagen)")
    parser.add_argument("--hoh", type=float, default=10.0, help="Hart-op-hart afstand in cm (standaard 10)")
    parser.add_argument("--rand", type=float, default=10.0, help="Randafstand tot muur in cm (standaard 10)")
    parser.add_argument("--patroon", choices=["serpentine", "spiraal"], default="serpentine")
    parser.add_argument("--hoek", type=float, default=0.0, help="Hoek slangen in graden (serpentine)")
    parser.add_argument("--eenheid", choices=["mm", "cm", "m"], default=None, help="Eenheid tekening (standaard: uit $INSUNITS)")
    parser.add_argument("--max-kring", type=float, default=120.0, help="Maximale kringlengte in m incl. aanvoer/retour (standaard 120)")
    parser.add_argument("--max-kringen", type=int, default=8, help="Maximale kringen per verdeler (standaard 8)")
    parser.add_argument(
        "--verdeler",
        action="append",
        default=[],
        metavar="X,Y",
        help="Positie verdeler in tekeningseenheden (herhaalbaar voor meerdere verdelers)",
    )
    parser.add_argument("--geen-legende", action="store_true", help="Geen materiaallijst in de DXF zetten")
    parser.add_argument("--rapport", default=None, help="CSV-rapport opslaan (pad naar .csv)")
    args = parser.parse_args(argv)

    doc, unit = open_drawing(args.input, args.eenheid)
    u = unit_to_m(unit)
    rooms = detect_rooms(doc, layer=args.laag, unit=unit)
    if not rooms:
        print("Geen gesloten polylines gevonden. Teken ruimtes als gesloten polyline of gebruik --laag.")
        return 1

    verdelers = []
    for i, spec in enumerate(args.verdeler, start=1):
        verdelers.append({"name": f"Verdeler {i}", "pos": parse_verdeler(spec), "max_kringen": args.max_kringen})
    for v in verdelers:
        add_manifold(doc, v["pos"], v["name"], unit)

    print(f"{'Ruimte':<22} {'m²':>7} {'Verdeler':<12} {'Kringen':>7} {'Slang':>9} {'m/m²':>6}  Opmerking")
    print("-" * 95)
    results = []
    circuit_counters: dict[str, int] = {}
    for index, (layer, poly, _entity) in enumerate(rooms, start=1):
        manifold = None
        if verdelers:
            centroid = (poly.centroid.x, poly.centroid.y)
            manifold = min(verdelers, key=lambda v: Point(centroid).distance(Point(v["pos"])))
        mname = manifold["name"] if manifold else None
        mpos = manifold["pos"] if manifold else None
        first_nr = circuit_counters.get(mname, 0) + 1 if mname else 1
        result = generate_room(
            name=f"Ruimte {index}",
            poly=poly,
            unit_to_m=u,
            hoh_m=args.hoh / 100.0,
            edge_m=args.rand / 100.0,
            pattern=args.patroon,
            angle_deg=args.hoek,
            max_circuit_m=args.max_kring,
            manifold_name=mname,
            manifold_pos=mpos,
            first_circuit_number=first_nr,
            max_circuits=manifold["max_kringen"] if manifold else None,
        )
        if result is None:
            print(f"{'?':<22} {polygon_area_m2(poly, unit):>7.2f} {'-':<12} {'-':>7} {'-':>9} {'-':>6}  overgeslagen")
            continue
        if mname:
            circuit_counters[mname] = first_nr + len(result.circuits) - 1
        add_room_result(doc, result, unit)
        results.append(result)
        note = "; ".join(result.warnings) if result.warnings else ""
        print(
            f"{result.name:<22} {result.area_m2:>7.2f} {mname or '-':<12} "
            f"{len(result.circuits):>7} {result.pipe_length_m:>8.1f}m {result.m_per_m2:>6.2f}  {note}"
        )

    if not args.geen_legende and results:
        add_legend(doc, results, unit)

    save_drawing(doc, args.uit)
    print(f"\nOpgeslagen: {args.uit} (lagen VV_LANG, VV_AANVOER, VV_VERDELER, VV_RUIMTE, VV_TEKST)")

    if args.rapport:
        with open(args.rapport, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Ruimte", "m²", "Verdeler", "Kring", "Lengte (m)"])
            for r in results:
                for c in r.circuits:
                    writer.writerow([
                        r.name,
                        f"{r.area_m2:.2f}".replace(".", ","),
                        r.manifold or "",
                        c.number,
                        f"{c.length_m:.1f}".replace(".", ","),
                    ])
                if not r.circuits:
                    writer.writerow([r.name, f"{r.area_m2:.2f}".replace(".", ","), r.manifold or "", "", ""])
            writer.writerow([])
            writer.writerow([
                "TOTAAL",
                f"{sum(r.area_m2 for r in results):.2f}".replace(".", ","),
                "",
                sum(len(r.circuits) for r in results),
                f"{sum(r.pipe_length_m for r in results):.1f}".replace(".", ","),
            ])
        print(f"Rapport: {args.rapport}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
