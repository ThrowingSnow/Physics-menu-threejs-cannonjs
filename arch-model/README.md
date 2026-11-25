# Haus — grobes parametrisches Arbeitsmodell

Ein **parametrisches** Architektur-Grobmodell. Alle Masse stehen in **einer** Datei
(`house.json`); ein Generator baut daraus `house.glb` — das gleiche File läuft in
**Blender** *und* im **WebGL-Viewer**.

```
 house.json  ──►  build_house.py  ──►  house.glb ──┬─►  Blender  (File ▸ Import ▸ glTF 2.0)
 (Masse)          (numpy/pygltflib)                └─►  WebGL    (viewer/, Three.js GLTFLoader)
```

**Der Update-Loop (darum geht's):** Du schickst neue Masse → ich (oder du) änderst
nur `house.json` → `python3 build_house.py` → Blender **und** Viewer bekommen
automatisch dasselbe aktualisierte Modell. Kein Nachmodellieren von Hand.

---

## Dateien

| Datei | Zweck |
|---|---|
| `house.json` | **Einzige Quelle der Wahrheit.** Alle Masse, Räume, Öffnungen. |
| `build_house.py` | Generator: JSON → `house.glb` (+ optionale Vorschau-PNG). |
| `house.glb` | Das fertige Modell. Für Blender und WebGL. Wird neu generiert. |
| `viewer/index.html` | Standalone WebGL-Viewer (Vogelperspektive, Three.js). |
| `preview.png` | Offline-Vorschau aus dem letzten Build. |

---

## Neu generieren

```bash
cd arch-model
python3 build_house.py                       # schreibt house.glb
python3 build_house.py --preview preview.png  # zusätzlich eine Vorschau-PNG
```

Einmalig die zwei kleinen Abhängigkeiten:
```bash
pip install pygltflib numpy          # für den Build
pip install matplotlib               # nur für --preview (optional)
```

Der Build gibt einen Report aus (Geschossfläche, Fensterfläche, Höhe) — praktisch,
um gegen bekannte Werte zu kalibrieren (z. B. Plan sagt `B.: 47.0 m²`).

---

## In Blender öffnen

1. `File ▸ Import ▸ glTF 2.0 (.glb/.gltf)`
2. `house.glb` wählen.

Masse sind in **Metern**, das Modell steht aufrecht (glTF Y-up wird automatisch zu
Blenders Z-up). Bauteile sind nach Gruppen benannt (`Shell`, `Slabs`, `Roof`,
`Interior`, `RoomPads`, `Stairs`) und im Outliner einzeln wählbar.

> Neue Masse? `build_house.py` laufen lassen, in Blender `house.glb` erneut
> importieren (altes Objekt vorher löschen) — oder *File ▸ Import* ersetzt es.

---

## WebGL-Viewer starten

Ein lokaler Server ist nötig (ein `.glb` lädt nicht über `file://`):

```bash
cd arch-model
python3 -m http.server 8000
# dann im Browser:  http://localhost:8000/viewer/
```

**Steuerung:** Ziehen = drehen · Scroll = zoomen · Rechts-Ziehen = schieben
`R` Dach · `G` Hülle · `F` neu einpassen · `T` Draufsicht.
Bauteile rechts einzeln ein-/ausblenden.

Der Viewer lädt Three.js (0.160.0) per CDN.

### Teilbarer Viewer (GLB eingebettet, ein File)

Für einen Viewer, der ohne Server/Dateien überall läuft (z. B. als Link):

```bash
python3 build_house.py --artifact viewer_standalone.html
```

Erzeugt aus `viewer/standalone.template.html` + `house.glb` eine self-contained
HTML-Seite (GLB als data-URI eingebettet). Diese Variante hat zusätzlich feste
**Ansichten** (`1`–`6`: Front / Hinten / Links / Rechts / Oben / ISO) und einen
**`U` = UI aus**-Modus für saubere Markup-Screenshots.

Jedes **Stockwerk** (Dach, OG3 … UG, Umgebung) lässt sich einzeln ein- und
ausblenden. Mit **„Einzeln“** zeigt ein Tipp nur dieses Stockwerk, **„Alle zeigen“**
holt alles zurück. Die Fenster sind aufklappbar; am Handy starten sie zugeklappt.

Im GLB ist das Modell als Baum **Stockwerk → Bauteil** aufgebaut (z. B. `EG/Shell`),
in Blender erscheinen die Etagen also als eigene Gruppen im Outliner.

---

## Konventionen

- **Einheiten:** Meter. **Achsen:** Y = oben; Grundriss in X (Breite) / Z (Tiefe).
- **Nullpunkt:** Südwest-Ecke des Hauses, Boden EG bei `Y = 0`.
- **Geschosse** werden von unten aufsummiert (`EG`, `OG1`, `OG2`, `OG3`).
- **`detail_floor.level_index`** bestimmt, welches Geschoss den detaillierten
  Grundriss bekommt (aktuell `1` = OG1 — das Wohngeschoss aus dem Plan).

### Öffnungen (Türen/Fenster)
Werden ohne CSG erzeugt: eine Wand wird in Pfosten / Brüstung / Sturz zerlegt.
Jede Öffnung: `{ from, to, y0, y1 }` entlang der Wand (`from/to` = Lauflänge,
`y0/y1` = Höhe über Geschossboden).

---

## Stand & was als Nächstes hilft

Rev 1 ist **grob** und bewusst voller markierter Schätzungen
(`"_conf": "estimate"` in `house.json`). Am meisten bringen als Nächstes:

1. **Aussenmasse** des Fussabdrucks (Breite × Tiefe) — aktuell geschätzt, damit
   die Netto-Geschossfläche ~47 m² trifft.
2. **Geschosshöhe** (Boden-zu-Boden) und **Anzahl Geschosse** bestätigen.
3. **Innenwände** des Wohngeschosses: Lage/Länge, Tür­breiten.
4. **Fenster/Türen:** Breite, Brüstungshöhe, Position pro Wand.
5. **Dach:** Firsthöhe, Neigung bzw. Dachform, Überstand.

Schick die Zahlen so grob oder präzise wie du sie hast — jede ersetzt eine
Schätzung, und das Modell wird Schritt für Schritt genauer.
