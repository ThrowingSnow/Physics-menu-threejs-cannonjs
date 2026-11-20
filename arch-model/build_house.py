#!/usr/bin/env python3
"""
build_house.py  -  parametrischer Haus-Generator

  house.json  --(dieses Script)-->  house.glb   (Blender: File > Import > glTF 2.0)
                                                 (WebGL:  viewer/index.html, GLTFLoader)

Eine Quelle der Wahrheit: ALLE Masse stehen in house.json. Neue Masse -> JSON
anpassen -> dieses Script laufen lassen -> fertig. Nichts von Hand nachmodellieren.

Benutzung:
    python3 build_house.py                      # schreibt house.glb
    python3 build_house.py --preview preview.png # zusaetzlich eine Vorschau-PNG
    python3 build_house.py --in house.json --out house.glb

Koordinaten: Meter, Y = oben (glTF-Standard). Grundriss liegt in X (Breite) / Z (Tiefe).
Nullpunkt = Suedwest-Ecke des Hauses, Boden EG bei Y = 0.
"""

import argparse, json, struct, os, math
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Material-Palette.  rgba + alphaMode.  Fuer die Vogelperspektive ist die
# Huelle (Aussenwaende/Decken/Dach) transparent, damit man ins Detailgeschoss
# schaut; das Detailgeschoss ist farbig-solide.
# ---------------------------------------------------------------------------
MATS = {
    "shell":   {"rgba": (0.80, 0.82, 0.85, 0.16), "blend": True,  "double": True},
    "slab":    {"rgba": (0.74, 0.75, 0.78, 0.13), "blend": True,  "double": True},
    "roof":    {"rgba": (0.58, 0.44, 0.40, 0.17), "blend": True,  "double": True},
    "part":    {"rgba": (0.93, 0.93, 0.96, 1.00), "blend": False, "double": True},
    "stair":   {"rgba": (0.62, 0.64, 0.68, 0.90), "blend": True,  "double": False},
    # Raum-Pads bekommen ihre Farbe dynamisch (siehe unten): "room:<id>"
}

def room_material(color):
    return {"rgba": (color[0], color[1], color[2], 1.0), "blend": False, "double": False}


# ===========================================================================
# Geometrie-Sammler:  Dreiecke, gruppiert nach (gruppe, material)
# ===========================================================================
class MeshBuilder:
    def __init__(self):
        # key = (group, matkey) -> {"pos":[...], "nrm":[...]}
        self.prims = defaultdict(lambda: {"pos": [], "nrm": []})
        self.materials = {}  # matkey -> material dict

    def _mat(self, matkey, mat):
        if matkey not in self.materials:
            self.materials[matkey] = mat

    def tri(self, group, matkey, mat, p0, p1, p2):
        self._mat(matkey, mat)
        a = np.array(p1) - np.array(p0)
        b = np.array(p2) - np.array(p0)
        n = np.cross(a, b)
        ln = np.linalg.norm(n)
        n = (n / ln) if ln > 1e-9 else np.array([0.0, 1.0, 0.0])
        d = self.prims[(group, matkey)]
        for p in (p0, p1, p2):
            d["pos"].extend([float(p[0]), float(p[1]), float(p[2])])
            d["nrm"].extend([float(n[0]), float(n[1]), float(n[2])])

    def quad(self, group, matkey, mat, p0, p1, p2, p3):
        # p0..p3 gegen den Uhrzeigersinn von aussen gesehen
        self.tri(group, matkey, mat, p0, p1, p2)
        self.tri(group, matkey, mat, p0, p2, p3)

    def box(self, group, matkey, mat, cx, cy, cz, sx, sy, sz):
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        x0, x1 = cx - hx, cx + hx
        y0, y1 = cy - hy, cy + hy
        z0, z1 = cz - hz, cz + hz
        # 8 Ecken
        v = {
            "000": (x0, y0, z0), "100": (x1, y0, z0), "110": (x1, y1, z0), "010": (x0, y1, z0),
            "001": (x0, y0, z1), "101": (x1, y0, z1), "111": (x1, y1, z1), "011": (x0, y1, z1),
        }
        q = lambda a, b, c, d: self.quad(group, matkey, mat, v[a], v[b], v[c], v[d])
        q("001", "101", "111", "011")  # +Z
        q("100", "000", "010", "110")  # -Z
        q("101", "100", "110", "111")  # +X
        q("000", "001", "011", "010")  # -X
        q("010", "011", "111", "110")  # +Y (oben)
        q("000", "100", "101", "001")  # -Y (unten)


# ===========================================================================
# Bau-Helfer (Waende mit Oeffnungen, Decken mit Loch, Dach)
# ===========================================================================
def wall_axis_aligned(mb, group, matkey, mat, axis, at, s_from, s_to,
                      base_y, height, thickness, openings=None):
    """Gerade, achsparallele Wand. axis='x': laeuft in X, z fix = at.
                                   axis='z': laeuft in Z, x fix = at.
    openings: Liste {from,to,y0,y1} entlang der Lauflaenge -> echte Loecher
    (Wand wird in Pfosten/Sturz/Bruestung zerlegt, kein CSG noetig)."""
    openings = sorted(openings or [], key=lambda o: o["from"])

    def panel(a, b, y_lo, y_hi):
        if b - a <= 1e-6 or y_hi - y_lo <= 1e-6:
            return
        cy = (y_lo + y_hi) / 2
        sy = (y_hi - y_lo)
        if axis == "x":
            cx, cz = (a + b) / 2, at
            sx, sz = (b - a), thickness
        else:
            cx, cz = at, (a + b) / 2
            sx, sz = thickness, (b - a)
        mb.box(group, matkey, mat, cx, base_y + cy, cz, sx, sy, sz)

    cur = s_from
    for o in openings:
        o0 = max(s_from, o["from"]); o1 = min(s_to, o["to"])
        if o1 <= o0:
            continue
        panel(cur, o0, 0, height)                       # volles Stueck davor
        panel(o0, o1, 0, o["y0"])                        # Bruestung unter Oeffnung
        panel(o0, o1, o["y1"], height)                   # Sturz ueber Oeffnung
        cur = o1
    panel(cur, s_to, 0, height)                          # Reststueck


def slab_with_hole(mb, group, matkey, mat, x0, x1, z0, z1, y_top, thick, hole=None):
    """Horizontale Platte (Decke/Boden) Oberkante bei y_top. hole=(hx0,hx1,hz0,hz1)
    erzeugt eine Rahmen-Platte um das Treppenloch."""
    cy = y_top - thick / 2
    if hole is None:
        mb.box(group, matkey, mat, (x0 + x1) / 2, cy, (z0 + z1) / 2, x1 - x0, thick, z1 - z0)
        return
    hx0, hx1, hz0, hz1 = hole
    hx0 = max(x0, hx0); hx1 = min(x1, hx1); hz0 = max(z0, hz0); hz1 = min(z1, hz1)
    # 4 Rahmenstuecke (Sued, Nord, West, Ost) um das Loch
    if hz0 > z0:  # Sued
        mb.box(group, matkey, mat, (x0 + x1) / 2, cy, (z0 + hz0) / 2, x1 - x0, thick, hz0 - z0)
    if hz1 < z1:  # Nord
        mb.box(group, matkey, mat, (x0 + x1) / 2, cy, (hz1 + z1) / 2, x1 - x0, thick, z1 - hz1)
    if hx0 > x0:  # West (nur Loch-Tiefe)
        mb.box(group, matkey, mat, (x0 + hx0) / 2, cy, (hz0 + hz1) / 2, hx0 - x0, thick, hz1 - hz0)
    if hx1 < x1:  # Ost
        mb.box(group, matkey, mat, (hx1 + x1) / 2, cy, (hz0 + hz1) / 2, x1 - hx1, thick, hz1 - hz0)


def gable_roof(mb, x0, x1, z0, z1, base_y, height, overhang):
    """Satteldach, First in Z-Richtung, ueber x0..x1 / z0..z1."""
    xo0, xo1 = x0 - overhang, x1 + overhang
    zo0, zo1 = z0 - overhang, z1 + overhang
    xc = (x0 + x1) / 2
    ridge_y = base_y + height
    mat = MATS["roof"]
    # linke und rechte Dachflaeche
    mb.quad("Roof", "roof", mat, (xo0, base_y, zo0), (xo0, base_y, zo1),
            (xc, ridge_y, zo1), (xc, ridge_y, zo0))
    mb.quad("Roof", "roof", mat, (xc, ridge_y, zo0), (xc, ridge_y, zo1),
            (xo1, base_y, zo1), (xo1, base_y, zo0))
    # zwei Giebel-Dreiecke (Stirnseiten)
    mb.tri("Roof", "roof", mat, (x0, base_y, zo0), (x1, base_y, zo0), (xc, ridge_y, zo0))
    mb.tri("Roof", "roof", mat, (x0, base_y, zo1), (x1, base_y, zo1), (xc, ridge_y, zo1))


def straight_stair(mb, x0, x1, z_top, base_y, floor_to_floor, steps=12):
    """Einfache gerade Treppe (Platzhalter) im Schacht, laeuft in -Z nach oben."""
    riser = floor_to_floor / steps
    tread = 0.19
    mat = MATS["stair"]
    for k in range(steps):
        zc = z_top - 0.10 - k * tread - tread / 2
        h = (k + 1) * riser
        mb.box("Stairs", "stair", mat, (x0 + x1) / 2, base_y + h / 2, zc,
               (x1 - x0), h, tread)


# ===========================================================================
# Modell aus house.json aufbauen
# ===========================================================================
def build(spec):
    mb = MeshBuilder()
    b = spec["building"]
    fw = b["footprint"]["width_x"]
    fd = b["footprint"]["depth_z"]
    te = b["wall_exterior_thickness"]
    ti = b["wall_interior_thickness"]
    slab = b["slab_thickness"]
    levels = b["levels"]
    n = len(levels)

    # Geschoss-Unterkanten (Boden-Oberkante) aufsummieren
    base = [0.0]
    for lv in levels:
        base.append(base[-1] + lv["floor_to_floor"])
    roof_base = base[n]  # = Oberkante oberste Decke

    # --- Huelle: Aussenwaende + Decken pro Geschoss ---
    det = spec["detail_floor"]
    di = det["level_index"]
    stair_room = next(r for r in det["rooms"] if r["id"] == "00")
    hole = (stair_room["x"], stair_room["x"] + stair_room["w"],
            stair_room["z"], stair_room["z"] + stair_room["d"])

    for i, lv in enumerate(levels):
        y0 = base[i]
        h = lv["floor_to_floor"]
        mat = MATS["shell"]
        # Detailgeschoss bekommt echte Tuer-/Fensteroeffnungen, sonst nur ein
        # Standardfenster pro Laengsseite, damit es wie ein Haus aussieht.
        if i == di:
            exo = defaultdict(list)
            for o in det["ext_openings"]:
                exo[o["side"]].append(o)
        else:
            exo = {"E": [{"from": fd*0.3, "to": fd*0.7, "y0": 0.9, "y1": 2.1}],
                   "W": [{"from": fd*0.3, "to": fd*0.7, "y0": 0.9, "y1": 2.1}]}
        # 4 Aussenwaende (Mittellinie der Wand liegt te/2 innerhalb der Aussenkante)
        wall_axis_aligned(mb, "Shell", "shell", mat, "x", te/2,        0, fw, y0, h, te, exo.get("S"))  # Sued (z=0)
        wall_axis_aligned(mb, "Shell", "shell", mat, "x", fd - te/2,   0, fw, y0, h, te, exo.get("N"))  # Nord
        wall_axis_aligned(mb, "Shell", "shell", mat, "z", te/2,        0, fd, y0, h, te, exo.get("W"))  # West (x=0)
        wall_axis_aligned(mb, "Shell", "shell", mat, "z", fw - te/2,   0, fd, y0, h, te, exo.get("E"))  # Ost

        # Decke ueber dem Geschoss (bei y0+h). EG-Bodenplatte zusaetzlich bei y=0.
        this_hole = hole if (i + 1) <= n else None
        slab_with_hole(mb, "Slabs", "slab", MATS["slab"], 0, fw, 0, fd, y0 + h, slab,
                       hole=this_hole if i >= 0 else None)
        if i == 0:
            slab_with_hole(mb, "Slabs", "slab", MATS["slab"], 0, fw, 0, fd, 0.0, slab, hole=None)

        # Treppe als Platzhalter in jedem Geschoss
        straight_stair(mb, stair_room["x"]+0.1, stair_room["x"]+1.2,
                       stair_room["z"]+stair_room["d"], y0, h)

    # --- Dach ---
    roof = b["roof"]
    gable_roof(mb, 0, fw, 0, fd, roof_base, roof["height"], roof["overhang"])

    # --- Detailgeschoss: Innenwaende + Raum-Pads ---
    yb = base[di] + slab            # Oberkante Bodenplatte des Detailgeschosses
    clear = levels[di]["floor_to_floor"] - slab
    for p in det["partitions"]:
        wall_axis_aligned(mb, "Interior", "part", MATS["part"],
                          p["axis"], p["at"], p["from"], p["to"],
                          yb, clear, ti, p.get("openings"))
    for r in det["rooms"]:
        mk = "room:" + r["id"]
        mb.box("RoomPads", mk, room_material(r["color"]),
               r["x"] + r["w"]/2, yb + 0.02, r["z"] + r["d"]/2, r["w"], 0.04, r["d"])

    return mb, dict(fw=fw, fd=fd, te=te, n=n, base=base, roof_base=roof_base, di=di)


# ===========================================================================
# GLB schreiben (glTF 2.0 binary) via pygltflib
# ===========================================================================
def write_glb(mb, out_path):
    from pygltflib import (GLTF2, Scene, Node, Mesh, Primitive, Attributes,
                           Buffer, BufferView, Accessor, Material, PbrMetallicRoughness)
    ARRAY_BUFFER = 34962
    FLOAT = 5126
    VEC3 = "VEC3"

    # Material-Index je matkey
    mat_index = {}
    materials = []
    for matkey, m in mb.materials.items():
        r, g, bl, a = m["rgba"]
        mat = Material(
            pbrMetallicRoughness=PbrMetallicRoughness(
                baseColorFactor=[r, g, bl, a], metallicFactor=0.0, roughnessFactor=0.85),
            alphaMode="BLEND" if m["blend"] else "OPAQUE",
            doubleSided=bool(m["double"]),
            name=matkey,
        )
        mat_index[matkey] = len(materials)
        materials.append(mat)

    blob = bytearray()
    bufferViews, accessors = [], []

    def add_floats(flat):
        arr = np.asarray(flat, dtype=np.float32)
        off = len(blob)
        blob.extend(arr.tobytes())
        while len(blob) % 4:       # 4-Byte-Alignment
            blob.append(0)
        bv = len(bufferViews)
        bufferViews.append(BufferView(buffer=0, byteOffset=off,
                                      byteLength=int(arr.nbytes), target=ARRAY_BUFFER))
        return bv, arr

    # Primitive gruppiert nach Gruppe -> ein Mesh pro Gruppe
    groups = defaultdict(list)
    for (group, matkey), d in mb.prims.items():
        groups[group].append((matkey, d))

    meshes, nodes, scene_nodes = [], [], []
    for group, prim_list in groups.items():
        prims = []
        for matkey, d in prim_list:
            pos = np.asarray(d["pos"], dtype=np.float32).reshape(-1, 3)
            nrm = np.asarray(d["nrm"], dtype=np.float32).reshape(-1, 3)
            count = pos.shape[0]
            bv_p, _ = add_floats(pos.reshape(-1))
            a_p = len(accessors)
            accessors.append(Accessor(bufferView=bv_p, componentType=FLOAT, count=count,
                                      type=VEC3,
                                      min=pos.min(axis=0).tolist(),
                                      max=pos.max(axis=0).tolist()))
            bv_n, _ = add_floats(nrm.reshape(-1))
            a_n = len(accessors)
            accessors.append(Accessor(bufferView=bv_n, componentType=FLOAT, count=count, type=VEC3))
            prims.append(Primitive(attributes=Attributes(POSITION=a_p, NORMAL=a_n),
                                   material=mat_index[matkey]))
        meshes.append(Mesh(primitives=prims, name=group))
        nodes.append(Node(mesh=len(meshes) - 1, name=group))
        scene_nodes.append(len(nodes) - 1)

    g = GLTF2(scene=0, scenes=[Scene(nodes=scene_nodes)], nodes=nodes, meshes=meshes,
              materials=materials, accessors=accessors, bufferViews=bufferViews,
              buffers=[Buffer(byteLength=len(blob))])
    g.set_binary_blob(bytes(blob))
    g.save_binary(out_path)
    return len(blob), len(meshes), sum(len(m.primitives) for m in meshes)


# ===========================================================================
# Report + optionale Vorschau
# ===========================================================================
def report(spec, dims):
    d = spec["detail_floor"]
    fw, fd, te = dims["fw"], dims["fd"], dims["te"]
    net = (fw - 2*te) * (fd - 2*te)
    print("  Fussabdruck (aussen):   %.2f x %.2f m" % (fw, fd))
    print("  Netto-Geschossflaeche:  %.1f m2   (Plan B.: 47.0 m2)" % net)
    # Fensterflaeche Detailgeschoss
    wa = 0.0
    for o in d["ext_openings"]:
        if o.get("kind") == "window":
            wa += (o["to"] - o["from"]) * (o["y1"] - o["y0"])
    print("  Fensterflaeche Detail:  %.1f m2   (Plan F.:  5.0 m2)" % wa)
    print("  Geschosse:              %d   Gesamthoehe bis First: %.1f m"
          % (dims["n"], dims["roof_base"] + spec["building"]["roof"]["height"]))


def preview(mb, out_png, dims):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    fig = plt.figure(figsize=(9, 9), facecolor="#101216")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#101216")

    # transparente Gruppen zuerst, solide zuletzt (bessere Tiefenwirkung)
    order = {"Slabs": 0, "Shell": 1, "Roof": 2, "Stairs": 3, "Interior": 4, "RoomPads": 5}
    for (group, matkey), d in sorted(mb.prims.items(), key=lambda kv: order.get(kv[0][0], 9)):
        pos = np.asarray(d["pos"], dtype=np.float32).reshape(-1, 3, 3)
        # glTF Y-up -> matplotlib (X, Z, Y) damit Y nach oben zeigt
        tris = pos[:, :, [0, 2, 1]]
        m = mb.materials[matkey]
        r, g, bl, a = m["rgba"]
        pc = Poly3DCollection(tris, facecolors=(r, g, bl, a),
                              edgecolors=(1, 1, 1, 0.06 if a < 0.5 else 0.15), linewidths=0.2)
        ax.add_collection3d(pc)

    fw, fd = dims["fw"], dims["fd"]
    top = dims["roof_base"] + 2.4
    ax.set_xlim(-1, fw + 1); ax.set_ylim(-1, fd + 1); ax.set_zlim(0, top + 1)
    ax.set_box_aspect((fw + 2, fd + 2, top + 1))
    ax.view_init(elev=32, azim=-58)   # Vogelperspektive, schraeg von oben
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    fig.savefig(out_png, dpi=110, facecolor="#101216")
    print("  Vorschau:               %s" % out_png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(HERE, "house.json"))
    ap.add_argument("--out", dest="out", default=os.path.join(HERE, "house.glb"))
    ap.add_argument("--preview", dest="preview", default=None)
    args = ap.parse_args()

    with open(args.inp, "r", encoding="utf-8") as f:
        spec = json.load(f)

    mb, dims = build(spec)
    nbytes, nmesh, nprim = write_glb(mb, args.out)
    print("Rev %d  ->  %s" % (spec["meta"]["revision"], args.out))
    print("  GLB:                    %d kB, %d Meshes, %d Primitives, %d Materialien"
          % (nbytes // 1024, nmesh, nprim, len(mb.materials)))
    report(spec, dims)
    if args.preview:
        preview(mb, args.preview, dims)


if __name__ == "__main__":
    main()
