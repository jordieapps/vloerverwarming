# Vloerverwarming — ruimtes, m², kringen en verdelers

Programma om DXF/DWG-tekeningen in te lezen, ruimtes te detecteren of zelf in te tekenen,
de oppervlakte (m²) te berekenen en complete vloerverwarmingsinstallaties te genereren:
slangen met instelbare hart-op-hart afstand (bv. **h.o.h. 10 cm** of **h.o.h. 15 cm**),
automatisch opgesplitst in **kringen** die aansluiten op je **verdeler**.

## Functies

- **DXF inlezen** rechtstreeks, óók **binaire DXF** ("AutoCAD Binary DXF") wordt automatisch herkend en geconverteerd; **DWG inlezen** via de gratis ODA File Converter (zie onder)
- **Ruimtes detecteren uit wandlijnen** (CLI `--wanden`): vlakvorming tussen wandlagen, gekoppeld aan ruimtelabels (werkt wanneer wanden gesloten contouren vormen)
- Ruimtes **automatisch detecteren** (gesloten polylines) of **zelf intekenen** door te klikken
- **m² per ruimte** en totaal, automatisch berekend
- Slangenpatronen: **serpentine** (heen-en-weer) en **dubbele spiraal**, met randafstand tot de muur
- **Spiraal met haakse aansluitingen**: bij het patroon *spiraal* lopen de aanvoer en retour
  **haaks langs de wanden** van de verdeler naar de spiraal — netjes naar de verdeler toe,
  zonder schuine lijnen
- **Routes via deur en openingen**: aanvoer/retour worden gerouteerd door de **vrije ruimte**
  (kamers minus wanden minus obstakels): ze lopen langs de wanden en **door deuren en
  doorgangen** naar de verdeler, nooit door een wand (met `--rechte-routes` zet je dit uit)
- **Obstakels uitsparen**: blokken met “trap” in de naam worden **automatisch gedetecteerd**
  en niet verwarmd (laag `VV_OBSTAKEL`, stippellijn + tekst “niet verwarmen”); extra
  obstakels (bv. kachel) geef je zelf op met `--obstakel X1,Y1,X2,Y2` of door ze in de
  tekening te tekenen. De spiraal loopt dan als gesloten lus **om het obstakel heen**
- **Grote ruimtes in meerdere spiraal-groepen**: is een ruimte groter dan de instelling
  **max. m² per groep** (standaard 25 m²), dan wordt ze langs de langste zijde opgedeeld in
  meerdere stroken, elk met een eigen spiraal en eigen aanvoer/retour naar de verdeler
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
  - `VV_OBSTAKEL` — uitgespaarde obstakels (stippellijn, “niet verwarmen”)
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
   max. kringlengte, kringen per verdeler, **max. m² per spiraal-groep**
   (0 = grote ruimtes niet opdelen)
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
`--verdeler X,Y` (herhaalbaar), `--rapport` (CSV), `--geen-legende`,
`--groep-m2` (max. m² per spiraal-groep, standaard 25, 0 = uit),
`--obstakel X1,Y1,X2,Y2` (herhaalbaar), `--geen-obstakel-detectie`,
`--rechte-routes` (niet via deur/opening routeren), `--geen-arcering-wand`
(geöarcerde wandvullingen niet als wand meenemen).
Automatische ruimtedetectie uit wanden: `--wanden` met optioneel `--wand-lagen L1,L2` en
`--gebied X1,Y1,X2,Y2` (let op: zet bij negatieve coördinaten `--gebied=-105000,...` met =).
De eenheid wordt automatisch uit `$INSUNITS` gelezen; Belgische tekeningen zijn meestal in mm.
Verdelers in de CLI krijgen max. kringlengte/uitgangen uit de algemene opties; ruimtes gaan
automatisch naar de dichtstbijzijnde verdeler.

Voorbeeld met obstakels en groepen:

```bash
# trap wordt automatisch gedetecteerd; kachel handmatig uitsparen;
# woonkamer > 25 m² wordt opgedeeld in meerdere spiraal-groepen
python cli.py plattegrond.dxf --uit plattegrond_vv.dxf --hoh 10 --patroon spiraal \
    --wanden --gebied=-100000,248000,-76000,272000 \
    --verdeler -92800,260400 --obstakel=-88950,258312,-88150,259112
```

## Testen

```bash
python -m pytest tests -q
```

## Richtwaarden slang per m²

| h.o.h. | m slang per m² |
|-------:|---------------:|
| 10 cm  | ± 9–10 m/m²    |
| 15 cm  | ± 6–6,7 m/m²   |

## Beperkingen (v3)

- Ruimtedetectie uit wanden werkt alleen als de wanden gesloten contouren vormen;
  bij deuropeningen blijven ruimtes open — teken die ruimtes dan in de GUI
- Obstakeldetectie herkent blokken en lagen met “trap” in de naam; andere obstakels
  (kachel, keukeneiland…) geef je zelf op met `--obstakel` of door ze in de tekening te zetten
- Routering door deur/openingen gebeurt over een raster van de halve h.o.h.-afstand; in zeer
  grote tekeningen wordt het raster grof (en valt het terug op rechte routes)
- Gearceerde wandvullingen (dunne gesloten polylines op een arceringslaag) worden als wand
  meegenomen bij het routeren; met `--geen-arcering-wand` zet je dat uit
- De spiraal is opgebouwd uit concentrische ringen (dubbele spiraal: heen naar binnen, terug
  naar buiten) met korte haakse verbindingsstukjes tussen de ringen; beide uiteinden komen
  aan de buitenrand bij de verdeler terecht; om obstakels heen lopen gesloten hulplussen
- Aanvoer/retour lopen **haaks en langs de wanden** door de vrije ruimte naar de verdeler;
  ligt een kring-aansluitpunt in een wandzone, dan wordt het punt iets verschoven naar de
  vrije ruimte
- De materiaallijst is een indicatieve opgave: tel de verliesmeters van je verdeler er zelf bij op
