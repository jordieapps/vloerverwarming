# Vloerverwarming — ruimtes, m² en slangen intekenen

Programma om DXF/DWG-tekeningen in te lezen, ruimtes te detecteren of zelf in te tekenen,
de oppervlakte (m²) te berekenen en vloerverwarmingslangen te genereren met een instelbare
hart-op-hart afstand (bv. **h.o.h. 10 cm** of **h.o.h. 15 cm**).

## Functies

- **DXF inlezen** rechtstreeks; **DWG inlezen** via de gratis ODA File Converter (zie onder)
- Ruimtes **automatisch detecteren** (gesloten polylines) of **zelf intekenen** door te klikken
- **m² per ruimte** en totaal, automatisch berekend
- Slangenpatronen: **serpentine** (heen-en-weer) en **spiraal**, met randafstand tot de muur
- Instelbaar: h.o.h. afstand (cm), randafstand (cm), hoek van de slangen, maximale kringlengte
- Slanglengte per ruimte in meter en **m slang per m²** (bv. h.o.h. 10 cm ≈ 9–10 m/m², h.o.h. 15 cm ≈ 6–6,7 m/m²)
- Waarschuwing als een kring langer wordt dan de max. kringlengte (standaard 120 m)
- Export naar DXF met de lagen `VV_LANG` (slang), `VV_RUIMTE` (bewerkte zone) en `VV_TEKST` (labels)

## Installatie

```bash
pip install -r requirements.txt
```

### DWG-ondersteuning

DWG is een gesloten Autodesk-formaat. Om `.dwg` in te lezen:

1. Installeer de gratis **[ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)** (Open Design Alliance).
2. `ezdxf` vindt het programma automatisch (Windows: staat standaard op de juiste plaats; Linux: `odafc` in PATH).

Alternatief: sla de tekening in je CAD-programma (AutoCAD, BricsCAD, NanoCAD…) op als **DXF** — dat werkt altijd.

## Gebruik — GUI (aanbevolen)

```bash
python main.py
```

1. **Tekening openen…** → kies `.dxf` of `.dwg`
2. **Ruimtes detecteren** (gesloten polylines; kies eventueel eerst een laag) of **Ruimte intekenen**:
   klik de hoekpunten, dubbelklik of Enter om te sluiten, Esc om te annuleren
3. Instellingen kiezen: eenheid (mm/cm/m), **h.o.h. (cm)**, randafstand, patroon, max. kringlengte
4. **🔥 Vloerverwarming tekenen** → slangen + berekeningen per ruimte
5. **DXF opslaan als…** → openbaar in je CAD-programma

Bediening canvas: scrollen = in-/uitzoomen, middelste/rechtermuisknop slepen = pannen.

## Gebruik — CLI (batch)

```bash
# h.o.h. 15 cm, serpentine, randafstand 10 cm
python cli.py plattegrond.dxf --uit plattegrond_vv.dxf --hoh 15 --rand 10

# h.o.h. 10 cm, spiraal, alleen laag RUIMTES, slangen onder 45°
python cli.py plattegrond.dxf --uit plattegrond_vv.dxf --hoh 10 --patroon spiraal --laag RUIMTES --hoek 45
```

Opties: `--hoh` (cm), `--rand` (cm), `--patroon serpentine|spiraal`, `--hoek` (°),
`--laag`, `--eenheid mm|cm|m`, `--max-kring` (m).
De eenheid wordt automatisch uit `$INSUNITS` gelezen; Belgische tekeningen zijn meestal in mm.

## Testen

```bash
python -m pytest tests -q
```

## Beperkingen (v1)

- Slangen volgen de ingestelde hoek; obstacle-outlines (bv. trapgat) worden omzeild door
  de randafstand, niet door individuele obstakels heen
- Bij spiraal in sterk niet-convexe ruimtes wordt de grootste deelzone genomen
- Kringen worden nog niet automatisch gesplitst; bij overschrijding volgt een waarschuwing
