from __future__ import annotations

import argparse
import sys

from vloerverwarming.dxf_io import add_room_result, detect_rooms, open_drawing, save_drawing, unit_to_m
from vloerverwarming.geometry import polygon_area_m2
from vloerverwarming.heating import generate_room


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Vloerverwarming: ruimtes uit DXF/DWG, m² berekenen en slangen intekenen."
    )
    parser.add_argument("input", help="DXF- of DWG-bestand")
    parser.add_argument("--uit", "-o", required=True, help="Uitvoerbestand (aanbevolen: .dxf)")
    parser.add_argument("--laag", default=None, help="Laagnaam met gesloten polylines (standaard: alle lagen)")
    parser.add_argument("--hoh", type=float, default=10.0, help="Hart-op-hart afstand in cm (standaard 10)")
    parser.add_argument("--rand", type=float, default=10.0, help="Randafstand tot muur in cm (standaard 10)")
    parser.add_argument("--patroon", choices=["serpentine", "spiraal"], default="serpentine")
    parser.add_argument("--hoek", type=float, default=0.0, help="Hoek slangen in graden (serpentine)")
    parser.add_argument("--eenheid", choices=["mm", "cm", "m"], default=None, help="Eenheid tekening (standaard: uit $INSUNITS)")
    parser.add_argument("--max-kring", type=float, default=120.0, help="Maximale kringlengte in m (waarschuwing)")
    args = parser.parse_args(argv)

    doc, unit = open_drawing(args.input, args.eenheid)
    u = unit_to_m(unit)
    rooms = detect_rooms(doc, layer=args.laag, unit=unit)
    if not rooms:
        print("Geen gesloten polylines gevonden. Teken ruimtes als gesloten polyline of gebruik --laag.")
        return 1

    print(f"{'Ruimte':<25} {'Laag':<15} {'m²':>8} {'Lengte':>9} {'m/m²':>7}  Opmerking")
    print("-" * 85)
    for index, (layer, poly, _entity) in enumerate(rooms, start=1):
        result = generate_room(
            name=f"Ruimte {index} ({layer})",
            poly=poly,
            unit_to_m=u,
            hoh_m=args.hoh / 100.0,
            edge_m=args.rand / 100.0,
            pattern=args.patroon,
            angle_deg=args.hoek,
            max_circuit_m=args.max_kring,
        )
        if result is None:
            print(f"{'?':<25} {layer:<15} {polygon_area_m2(poly, unit):>8.2f} {'-':>9} {'-':>7}  overgeslagen")
            continue
        add_room_result(doc, result)
        note = "; ".join(result.warnings) if result.warnings else ""
        print(
            f"{result.name:<25} {layer:<15} {result.area_m2:>8.2f} "
            f"{result.pipe_length_m:>8.1f}m {result.m_per_m2:>7.2f}  {note}"
        )

    save_drawing(doc, args.uit)
    print(f"\nOpgeslagen: {args.uit} (lagen VV_LANG, VV_RUIMTE, VV_TEKST)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
