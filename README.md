# Vloerverwarming — ruimtes, m², kringen en verdelers

Programma om DXF/DWG-tekeningen in te lezen, ruimtes te detecteren of zelf in te tekenen,
de oppervlakte (m²) te berekenen en complete vloerverwarmingsinstallaties te genereren:
slangen met instelbare hart-op-hart afstand (bv. **h.o.h. 10 cm** of **h.o.h. 15 cm**),
automatisch opgesplitst in **kringen** die aansluiten op je **verdeler**.

## Functies

- **DXF inlezen** rechtstreeks; **DWG inlezen** via de gratis ODA File Converter (zie onder)
- Ruimtes **automatisch detecteren** (gesloten polylines) of **zelf intekenen** door te klikken
- **m² per ruimte** en totaal, automatisch berekend
- Slangenpatronen: **serpentine** (heen-en-weer) en **spiraal**, met randafstand tot de muur
- **Verdeler plaatsen**: klik in de tekening waar de verdeler komt (meerdere verdelers mogelijk,
  elk met eigen max. kringlengte en aantal uitgangen)
- **Automatische kringen**: slangen worden opgesplitst in kringen van max. de ingestelde
  kringlengte (incl. aanvoer/retour), doorgenummerd per verdeler (KRING 1, 2, …)
- **Aanvoer- en retourlijnen** (gestippeld) van de verdeler naar elke kring
- Ruimtes worden **automatisch toegewezen** aan de dichtstbijzijnde verdeler (handmatig te wijzigen)
- **Materiaallijst** als legende in de DXF: per ruimte m², aantal kringen en slanglengte + totaal
- **CSV-rapport**: per kring de lengte, klaar voor je leverancier of offerteaanvraag
- Waarschuwingen: kring te lang, meer kringen nodig dan uitgangen op de verdeler
- Export naar DXF met de lagen:
  - `VV_LANG` — slangen in het veld
  - `VV_AANVOER` — aanvoer/retourlijnen verdeler ↔ kring
  - `VV_VERDELER` — verdelersymbool + naam
  - `VV_RUIMTE` — bewerkte zone (randafstand)
  - `VV_TEKST` — kringlabels, ruimtelabels en materiaallijst

## Installatie

```bash
pip install -r requirements.txt
```

Vereist Python 3.10+ met tkinter (zit standaard bij Python van python.org; op Homebrew:
`brew install python python-tk`).

### DWG-ondersteuning

DWG is een gesloten Autodesk-formaat. Om `.dwg` in te lezen:

1. Installeer de gratis **[ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)** (Open Design Alliance).
2. `ezdxf` vindt het programma automatisch (Windows: standaardlocatie; macOS/Linux: `odafc` in PATH).

Alternatief: sla de tekening in je CAD-programma (AutoCAD, BricsCAD, NanoCAD…) op als **DXF** — dat werkt altijd.

## Gebruik — GUI (aanbevolen)

```bash
python main.py
```

1. **Tekening openen…** → kies `.dxf` of `.dwg`
2. **Ruimtes detecteren** (gesloten polylines; kies eventueel eerst een laag) of **Ruimte intekenen**:
   klik de hoekpunten, dubbelklik of Enter om te sluiten, Esc om te annuleren
3. **Verdeler plaatsen** → klik in de tekening waar de verdeler komt; geef naam,
   max. kringlengte en aantal uitgangen in (herhaal voor meerdere verdelers)
4. Instellingen kiezen: eenheid (mm/cm/m), **h.o.h. (cm)**, randafstand, patroon, hoek,
   max. kringlengte, kringen per verdeler
5. **🔥 Vloerverwarming tekenen** → kringen, aanvoer/retour en berekeningen per ruimte
6. Eventueel: ruimte selecteren in de lijst, verdeler kiezen en **OK** om handmatig toe te wijzen
7. **DXF opslaan als…** en/of **Rapport opslaan (CSV)…**

Bediening canvas: scrollen = in-/uitzoomen, middelste/rechtermuisknop slepen = pannen.

## Gebruik — CLI (batch)

```bash
# h.o.h. 15 cm, serpentine, randafstand 10 cm, verdeler op (2500, 2000), max 60 m per kring
python cli.py plattegrond.dxf --uit plattegrond_vv.dxf --hoh 15 --rand 10 \
    --verdeler 2500,2000 --max-kring 60 --rapport rapport.csv

# twee verdelers, spiraal, alleen laag RUIMTES, slangen onder 45°
python cli.py plattegrond.dxf --uit plattegrond_vv.dxf --hoh 10 --patroon spiraal \
    --laag RUIMTES --hoek 45 --verdeler 3000,1500 --verdeler 12000,1500
```

Opties: `--hoh` (cm), `--rand` (cm), `--patroon serpentine|spiraal`, `--hoek` (°),
`--laag`, `--eenheid mm|cm|m`, `--max-kring` (m), `--max-kringen` (per verdeler),
`--verdeler X,Y` (herhaalbaar), `--rapport` (CSV), `--geen-legende`.
De eenheid wordt automatisch uit `$INSUNITS` gelezen; Belgische tekeningen zijn meestal in mm.
Verdelers in de CLI krijgen max. kringlengte/uitgangen uit de algemene opties; ruimtes gaan
automatisch naar de dichtstbijzijnde verdeler.

## Testen

```bash
python -m pytest tests -q
```

## Richtwaarden slang per m²

| h.o.h. | m slang per m² |
|-------:|---------------:|
| 10 cm  | ± 9–10 m/m²    |
| 15 cm  | ± 6–6,7 m/m²   |

## Beperkingen (v2)

- Slangen volgen de ingestelde hoek; obstakels (bv. trapgat) worden omzeild via de
  randafstand, niet met individuele omleidingen
- Bij spiraal in sterk niet-convexe ruimtes wordt de grootste deelzone genomen
- Aanvoer/retour lopen als rechte lijn van de verdeler naar het begin/einde van de kring
- De materiaallijst is een indicatieve opgave: tel de verliesmeters van je verdeler er zelf bij op
