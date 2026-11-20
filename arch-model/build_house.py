#!/usr/bin/env python3
"""
build_house.py  -  parametrischer Haus-Generator (pro Geschoss)

  house.json  --(dieses Script)-->  house.glb   (Blender: File > Import > glTF 2.0)
                                                 (WebGL:  viewer/index.html, GLTFLoader)

Eine Quelle der Wahrheit: ALLE Masse stehen in house.json. Jedes Geschoss ist ein
eigenes "level" mit eigenem Fussabdruck und optionalem Grundriss (plan). Neue Masse
-> JSON anpassen -> dieses Script laufen lassen. Nichts von Hand nachmodellieren.

    python3 build_house.py                       # schreibt house.glb
    python3 build_house.py --preview preview.png  # zusaetzlich eine Vorschau-PNG

Koordinaten: Meter, Y = oben (glTF). Grundriss in X (Breite) / Z (Tiefe).
Geschosse werden zentriert uebereinander gestapelt (building.align = "center").
Plan-Koordinaten sind LOKAL pro Geschoss: 0..width / 0..depth.
"""

import argparse, json, os, math
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

MATS = {
    "shell":  {"rgba": (0.80, 0.82, 0.85, 0.16), "blend": True,  "double": True},
    "slab":   {"rgba": (0.74, 0.75, 0.78, 0.13), "blend": True,  "double": True},
    "roof":   {"rgba": (0.58, 0.44, 0.40, 0.17), "blend": True,  "double": True},
    "part":   {"rgba": (0.93, 0.93, 0.96, 1.00), "blend": False, "double": True},
    "stair":  {"rgba": (0.62, 0.64, 0.68, 0.95), "blend": True,  "double": True},
    "column": {"rgba": (0.50, 0.50, 0.56, 1.00), "blend": False, "double": False},
    "appli":  {"rgba": (0.86, 0.88, 0.92, 1.00), "blend": False, "double": False},
}
def room_material(c): return {"rgba": (c[0], c[1], c[2], 1.0), "blend": False, "double": False}


# ===========================================================================
# Geometrie-Sammler: Dreiecke, gruppiert nach (gruppe, material)
# ===========================================================================
class MeshBuilder:
    def __init__(self):
        self.prims = defaultdict(lambda: {"pos": [], "nrm": []})
        self.materials = {}

    def tri(self, group, matkey, mat, p0, p1, p2):
        self.materials.setdefault(matkey, mat)
        a = np.array(p1) - np.array(p0); b = np.array(p2) - np.array(p0)
        n = np.cross(a, b); ln = np.linalg.norm(n)
        n = (n / ln) if ln > 1e-9 else np.array([0.0, 1.0, 0.0])
        d = self.prims[(group, matkey)]
        for p in (p0, p1, p2):
            d["pos"].extend([float(p[0]), float(p[1]), float(p[2])])
            d["nrm"].extend([float(n[0]), float(n[1]), float(n[2])])

    def quad(self, group, matkey, mat, p0, p1, p2, p3):
        self.tri(group, matkey, mat, p0, p1, p2)
        self.tri(group, matkey, mat, p0, p2, p3)

    def box(self, group, matkey, mat, cx, cy, cz, sx, sy, sz):
        hx, hy, hz = sx/2, sy/2, sz/2
        x0, x1 = cx-hx, cx+hx; y0, y1 = cy-hy, cy+hy; z0, z1 = cz-hz, cz+hz
        v = {"000":(x0,y0,z0),"100":(x1,y0,z0),"110":(x1,y1,z0),"010":(x0,y1,z0),
             "001":(x0,y0,z1),"101":(x1,y0,z1),"111":(x1,y1,z1),"011":(x0,y1,z1)}
        q = lambda a,b,c,d: self.quad(group, matkey, mat, v[a], v[b], v[c], v[d])
        q("001","101","111","011"); q("100","000","010","110")
        q("101","100","110","111"); q("000","001","011","010")
        q("010","011","111","110"); q("000","100","101","001")


# ===========================================================================
# Bau-Helfer
# ===========================================================================
def wall(mb, group, matkey, mat, axis, at, s_from, s_to, base_y, height, thick, openings=None):
    """Achsparallele Wand mit Oeffnungen (Pfosten/Bruestung/Sturz, kein CSG).
    axis='x': laeuft in X, z fix=at.  axis='z': laeuft in Z, x fix=at.
    openings in ABSOLUTEN Laufkoordinaten (gleiche Achse wie s_from/s_to)."""
    openings = sorted(openings or [], key=lambda o: o["from"])
    def panel(a, b, y_lo, y_hi):
        if b-a <= 1e-6 or y_hi-y_lo <= 1e-6: return
        cy, sy = (y_lo+y_hi)/2, (y_hi-y_lo)
        if axis == "x": cx, cz, sx, sz = (a+b)/2, at, (b-a), thick
        else:           cx, cz, sx, sz = at, (a+b)/2, thick, (b-a)
        mb.box(group, matkey, mat, cx, base_y+cy, cz, sx, sy, sz)
    cur = s_from
    for o in openings:
        o0, o1 = max(s_from, o["from"]), min(s_to, o["to"])
        if o1 <= o0: continue
        panel(cur, o0, 0, height); panel(o0, o1, 0, o["y0"]); panel(o0, o1, o["y1"], height)
        cur = o1
    panel(cur, s_to, 0, height)


def slab(mb, group, matkey, mat, x0, x1, z0, z1, y_top, thick, hole=None):
    """Horizontale Platte, Oberkante y_top. hole=(hx0,hx1,hz0,hz1) -> Rahmenplatte."""
    cy = y_top - thick/2
    if hole is None:
        mb.box(group, matkey, mat, (x0+x1)/2, cy, (z0+z1)/2, x1-x0, thick, z1-z0); return
    hx0, hx1, hz0, hz1 = hole
    hx0=max(x0,hx0); hx1=min(x1,hx1); hz0=max(z0,hz0); hz1=min(z1,hz1)
    if hz0 > z0: mb.box(group, matkey, mat, (x0+x1)/2, cy, (z0+hz0)/2, x1-x0, thick, hz0-z0)
    if hz1 < z1: mb.box(group, matkey, mat, (x0+x1)/2, cy, (hz1+z1)/2, x1-x0, thick, z1-hz1)
    if hx0 > x0: mb.box(group, matkey, mat, (x0+hx0)/2, cy, (hz0+hz1)/2, hx0-x0, thick, hz1-hz0)
    if hx1 < x1: mb.box(group, matkey, mat, (hx1+x1)/2, cy, (hz0+hz1)/2, x1-hx1, thick, hz1-hz0)


def gable_roof(mb, x0, x1, z0, z1, base_y, height, overhang):
    xo0, xo1 = x0-overhang, x1+overhang; zo0, zo1 = z0-overhang, z1+overhang
    xc = (x0+x1)/2; ry = base_y+height; mat = MATS["roof"]
    mb.quad("Roof","roof",mat,(xo0,base_y,zo0),(xo0,base_y,zo1),(xc,ry,zo1),(xc,ry,zo0))
    mb.quad("Roof","roof",mat,(xc,ry,zo0),(xc,ry,zo1),(xo1,base_y,zo1),(xo1,base_y,zo0))
    mb.tri("Roof","roof",mat,(x0,base_y,zo0),(x1,base_y,zo0),(xc,ry,zo0))
    mb.tri("Roof","roof",mat,(x0,base_y,zo1),(x1,base_y,zo1),(xc,ry,zo1))


def stair_steps(mb, x0, x1, z0, z1, base_y, floor_to_floor, direction="+z", steps=12):
    """Einfache gerade Treppe (Platzhalter). direction = Aufstiegsrichtung."""
    riser = floor_to_floor/steps
    span = (z1-z0); tread = span/steps; mat = MATS["stair"]
    for k in range(steps):
        if direction == "+z": zc = z0 + (k+0.5)*tread
        else:                 zc = z1 - (k+0.5)*tread
        h = (k+1)*riser
        mb.box("Stairs","stair",mat,(x0+x1)/2, base_y+h/2, zc, (x1-x0), h, tread)


def spiral_stair(mb, cx, cz, r_in, r_out, base_y, ff, start=0.0, turn=math.pi*1.6, steps=14):
    """Wendeltreppe: Trittstufen als Keile um einen zentralen Schacht."""
    mat = MATS["stair"]; riser = ff/steps; thick = max(0.05, riser*0.55)
    def P(r, a, y): return (cx + r*math.cos(a), y, cz + r*math.sin(a))
    for k in range(steps):
        a0 = start + k*(turn/steps); a1 = start + (k+1)*(turn/steps)
        yt = base_y + (k+1)*riser; yb2 = yt - thick
        A=P(r_in,a0,yt); B=P(r_out,a0,yt); C=P(r_out,a1,yt); D=P(r_in,a1,yt)
        a=P(r_in,a0,yb2); b=P(r_out,a0,yb2); c=P(r_out,a1,yb2); d=P(r_in,a1,yb2)
        mb.quad("Stairs","stair",mat, A,B,C,D)   # Trittflaeche
        mb.quad("Stairs","stair",mat, d,c,b,a)   # Unterseite
        mb.quad("Stairs","stair",mat, A,D,d,a)   # innen
        mb.quad("Stairs","stair",mat, B,b,c,C)   # aussen
        mb.quad("Stairs","stair",mat, A,a,b,B)   # Setzstufe (Anfang)


def spiral_stair_in_rect(mb, ox, oz, rect, base_y, ff):
    """Wendeltreppe passend in das (lokale) Treppen-Rechteck."""
    cx = ox + rect["x"] + rect["w"]/2; cz = oz + rect["z"] + rect["d"]/2
    r_out = min(rect["w"], rect["d"])/2 * 0.96
    spiral_stair(mb, cx, cz, r_out*0.18, r_out, base_y, ff,
                 start=float(rect.get("start_angle", 0.0)),
                 turn=math.pi*float(rect.get("turns", 0.8))*2)


def wc_in_shaft(mb, ox, oz, shaft, yb, clear, ti):
    """Abgetrenntes WC/Bad im alten Liftschacht: 4 Waende (Tuer Sueden) + Pad.
    shaft in lokalen Geschoss-Koordinaten."""
    x0, z0, w, d = shaft["x"], shaft["z"], shaft["w"], shaft["d"]
    door_w = min(0.80, w*0.6); df = x0 + (w-door_w)/2
    wall(mb,"Interior","part",MATS["part"],"x", oz+z0,   ox+x0, ox+x0+w, yb, clear, ti,
         [{"from": ox+df, "to": ox+df+door_w, "y0": 0.0, "y1": 2.10}])
    wall(mb,"Interior","part",MATS["part"],"x", oz+z0+d, ox+x0, ox+x0+w, yb, clear, ti)
    wall(mb,"Interior","part",MATS["part"],"z", ox+x0,   oz+z0, oz+z0+d, yb, clear, ti)
    wall(mb,"Interior","part",MATS["part"],"z", ox+x0+w, oz+z0, oz+z0+d, yb, clear, ti)
    mb.box("RoomPads","room:wc", room_material(shaft.get("color",[0.40,0.80,0.86])),
           ox+x0+w/2, yb+0.02, oz+z0+d/2, w, 0.04, d)


# ===========================================================================
# Modell aus house.json
# ===========================================================================
def footprint_of(b, lv):
    fp = lv.get("footprint") or b["default_footprint"]
    return fp["width_x"], fp["depth_z"]

def build(spec):
    mb = MeshBuilder()
    b = spec["building"]
    te = b["wall_exterior_thickness"]; ti = b["wall_interior_thickness"]; st = b["slab_thickness"]
    df = b["default_footprint"]; Cx, Cz = df["width_x"]/2, df["depth_z"]/2
    levels = b["levels"]; n = len(levels)
    lift = b.get("lift_shaft"); cols = b.get("columns", []); stair_core = b.get("stair_core")

    def stair_rect_of(lv):
        pl = lv.get("plan", {})
        if pl.get("open_plan") and stair_core: return stair_core
        return pl.get("stair")

    base = [0.0]
    for lv in levels: base.append(base[-1] + lv["floor_to_floor"])
    roof_base = base[n]

    def offset(lv):                      # Welt-Koordinate der lokalen (0,0)-Ecke
        fw, fd = footprint_of(b, lv)
        return (Cx - fw/2, Cz - fd/2, fw, fd)

    # ---- Waende, Innenwaende, Raeume, Features, Treppen pro Geschoss ----
    for i, lv in enumerate(levels):
        ox, oz, fw, fd = offset(lv)
        y0 = base[i]; h = lv["floor_to_floor"]; plan = lv.get("plan", {})

        # Aussenwaende
        if "plan" in lv:
            exo = defaultdict(list)
            for o in plan.get("ext_openings", []):
                exo[o["side"]].append(o)
        else:  # Geschoss ohne Grundriss: Standardfenster auf Laengsseiten
            win = [{"from": fd*0.30, "to": fd*0.70, "y0": 0.9, "y1": 2.1}]
            exo = {"E": win, "W": win}
        def shift(side, lst):
            start = ox if side in ("S", "N") else oz
            return [{**o, "from": start+o["from"], "to": start+o["to"]} for o in (lst or [])]
        mat = MATS["shell"]
        wall(mb,"Shell","shell",mat,"x", oz+te/2,     ox, ox+fw, y0, h, te, shift("S", exo.get("S")))
        wall(mb,"Shell","shell",mat,"x", oz+fd-te/2,  ox, ox+fw, y0, h, te, shift("N", exo.get("N")))
        wall(mb,"Shell","shell",mat,"z", ox+te/2,     oz, oz+fd, y0, h, te, shift("W", exo.get("W")))
        wall(mb,"Shell","shell",mat,"z", ox+fw-te/2,  oz, oz+fd, y0, h, te, shift("E", exo.get("E")))

        yb = y0 + st; clear = h - st
        # Innenwaende
        for p in plan.get("partitions", []):
            if p["axis"] == "x":
                at = oz + p["at"]; fr, to = ox+p["from"], ox+p["to"]
                ops = [{**o, "from": ox+o["from"], "to": ox+o["to"]} for o in p.get("openings", [])]
            else:
                at = ox + p["at"]; fr, to = oz+p["from"], oz+p["to"]
                ops = [{**o, "from": oz+o["from"], "to": oz+o["to"]} for o in p.get("openings", [])]
            wall(mb,"Interior","part",MATS["part"], p["axis"], at, fr, to, yb, clear, ti, ops)
        # Raum-Pads
        for r in plan.get("rooms", []):
            mk = "room:"+r["id"]
            mb.box("RoomPads", mk, room_material(r["color"]),
                   ox+r["x"]+r["w"]/2, yb+0.02, oz+r["z"]+r["d"]/2, r["w"], 0.04, r["d"])
        # Features (Stuetzen, Geraete)
        for f in plan.get("features", []):
            if f.get("type") == "column":
                mb.box("Features","column",MATS["column"],
                       ox+f["x"]+f["w"]/2, yb+clear/2, oz+f["z"]+f["d"]/2, f["w"], clear, f["d"])
            else:  # appliance
                fh = f.get("h", 0.85)
                mb.box("Features","appli",MATS["appli"],
                       ox+f["x"]+f["w"]/2, yb+fh/2, oz+f["z"]+f["d"]/2, f["w"], fh, f["d"])
        # Offener Grundriss: WC/Bad im alten Liftschacht + Deckenstuetzen (Pfeiler)
        if plan.get("open_plan"):
            if lift:
                wc_in_shaft(mb, ox, oz, lift, yb, clear, ti)
            for c in cols:
                cw, cd = c.get("w", 0.30), c.get("d", 0.30)
                mb.box("Features","column",MATS["column"],
                       ox+c["x"]+cw/2, yb+clear/2, oz+c["z"]+cd/2, cw, clear, cd)
        # Wendeltreppe: Kern durch alle Geschosse ausser dem obersten
        sr = stair_rect_of(lv)
        if sr and i < n-1:
            spiral_stair_in_rect(mb, ox, oz, sr, yb, h)

    # ---- Boden-/Deckenplatten (eine je Geschoss + oberste Decke) ----
    for sidx in range(n+1):
        lv = levels[sidx] if sidx < n else levels[n-1]
        ox, oz, fw, fd = offset(lv)
        y = base[sidx]
        hole = None
        if 1 <= sidx <= n-1:                 # Loch von der Treppe des Geschosses darunter
            below = levels[sidx-1]
            bs = stair_rect_of(below)
            if bs:
                bx, bz, _, _ = offset(below)
                hole = (bx+bs["x"], bx+bs["x"]+bs["w"], bz+bs["z"], bz+bs["z"]+bs["d"])
        slab(mb,"Slabs","slab",MATS["slab"], ox, ox+fw, oz, oz+fd, y, st, hole)

    # ---- Dach ----
    top = levels[n-1]; tox, toz, tfw, tfd = offset(top)
    gable_roof(mb, tox, tox+tfw, toz, toz+tfd, roof_base, b["roof"]["height"], b["roof"]["overhang"])

    return mb, dict(b=b, levels=levels, base=base, roof_base=roof_base, Cx=Cx, Cz=Cz, df=df)


# ===========================================================================
# GLB schreiben
# ===========================================================================
def write_glb(mb, out_path):
    from pygltflib import (GLTF2, Scene, Node, Mesh, Primitive, Attributes,
                           Buffer, BufferView, Accessor, Material, PbrMetallicRoughness)
    ARRAY_BUFFER, FLOAT, VEC3 = 34962, 5126, "VEC3"
    mat_index, materials = {}, []
    for matkey, m in mb.materials.items():
        r, g, bl, a = m["rgba"]
        materials.append(Material(
            pbrMetallicRoughness=PbrMetallicRoughness(baseColorFactor=[r,g,bl,a],
                metallicFactor=0.0, roughnessFactor=0.85),
            alphaMode="BLEND" if m["blend"] else "OPAQUE",
            doubleSided=bool(m["double"]), name=matkey))
        mat_index[matkey] = len(materials)-1

    blob = bytearray(); bufferViews, accessors = [], []
    def add(flat):
        arr = np.asarray(flat, dtype=np.float32); off = len(blob)
        blob.extend(arr.tobytes())
        while len(blob) % 4: blob.append(0)
        bufferViews.append(BufferView(buffer=0, byteOffset=off, byteLength=int(arr.nbytes),
                                      target=ARRAY_BUFFER))
        return len(bufferViews)-1, arr

    groups = defaultdict(list)
    for (group, matkey), d in mb.prims.items(): groups[group].append((matkey, d))
    meshes, nodes, scene_nodes = [], [], []
    for group, prim_list in groups.items():
        prims = []
        for matkey, d in prim_list:
            pos = np.asarray(d["pos"], dtype=np.float32).reshape(-1,3)
            nrm = np.asarray(d["nrm"], dtype=np.float32).reshape(-1,3)
            bv_p,_ = add(pos.reshape(-1)); a_p = len(accessors)
            accessors.append(Accessor(bufferView=bv_p, componentType=FLOAT, count=pos.shape[0],
                             type=VEC3, min=pos.min(axis=0).tolist(), max=pos.max(axis=0).tolist()))
            bv_n,_ = add(nrm.reshape(-1)); a_n = len(accessors)
            accessors.append(Accessor(bufferView=bv_n, componentType=FLOAT, count=nrm.shape[0], type=VEC3))
            prims.append(Primitive(attributes=Attributes(POSITION=a_p, NORMAL=a_n), material=mat_index[matkey]))
        meshes.append(Mesh(primitives=prims, name=group))
        nodes.append(Node(mesh=len(meshes)-1, name=group)); scene_nodes.append(len(nodes)-1)

    g = GLTF2(scene=0, scenes=[Scene(nodes=scene_nodes)], nodes=nodes, meshes=meshes,
              materials=materials, accessors=accessors, bufferViews=bufferViews,
              buffers=[Buffer(byteLength=len(blob))])
    g.set_binary_blob(bytes(blob)); g.save_binary(out_path)
    return len(blob), len(meshes), sum(len(m.primitives) for m in meshes)


# ===========================================================================
# Report + Vorschau
# ===========================================================================
def report(spec, dims):
    b = spec["building"]
    print("  Geschosse (unten -> oben):")
    for i, lv in enumerate(b["levels"]):
        fw, fd = footprint_of(b, lv)
        iw, idp = fw-2*b["wall_exterior_thickness"], fd-2*b["wall_exterior_thickness"]
        tag = " [Grundriss]" if "plan" in lv else ""
        print("    %-4s aussen %.2f x %.2f m  (innen %.2f x %.2f, %.1f m2)  h=%.2f%s"
              % (lv["name"], fw, fd, iw, idp, iw*idp, lv["floor_to_floor"], tag))
    print("  Gesamthoehe bis First:  %.1f m" % (dims["roof_base"] + b["roof"]["height"]))

def preview(mb, out_png, dims):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(9,9), facecolor="#101216")
    ax = fig.add_subplot(111, projection="3d"); ax.set_facecolor("#101216")
    order = {"Slabs":0,"Shell":1,"Roof":2,"Stairs":3,"Interior":4,"Features":5,"RoomPads":6}
    for (group, matkey), d in sorted(mb.prims.items(), key=lambda kv: order.get(kv[0][0], 9)):
        pos = np.asarray(d["pos"], dtype=np.float32).reshape(-1,3,3)
        tris = pos[:, :, [0,2,1]]                       # Y-up -> matplotlib
        r,g,bl,a = mb.materials[matkey]["rgba"]
        ax.add_collection3d(Poly3DCollection(tris, facecolors=(r,g,bl,a),
            edgecolors=(1,1,1, 0.05 if a<0.5 else 0.15), linewidths=0.2))
    W = dims["df"]["width_x"]; D = dims["df"]["depth_z"]; top = dims["roof_base"]+2.4
    ax.set_xlim(-1, W+1); ax.set_ylim(-1, D+1); ax.set_zlim(0, top+1)
    ax.set_box_aspect((W+2, D+2, top+1)); ax.view_init(elev=28, azim=-58); ax.set_axis_off()
    fig.tight_layout(pad=0); fig.savefig(out_png, dpi=110, facecolor="#101216")
    print("  Vorschau:               %s" % out_png)

def plan_png(spec, level_name, out_png):
    """2D-Grundriss eines Geschosses von oben (zum Abgleich mit der Handskizze)."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    b = spec["building"]; te = b["wall_exterior_thickness"]; ti = b["wall_interior_thickness"]
    lv = next((l for l in b["levels"] if l["name"].lower() == level_name.lower()), None)
    if lv is None:
        print("  Kein Geschoss '%s'." % level_name); return
    fw, fd = footprint_of(b, lv); plan = lv.get("plan", {})
    fig, ax = plt.subplots(figsize=(6, 6*fd/fw if fw else 6), facecolor="white")
    # Aussenwand (Ring) + Innenraum
    ax.add_patch(Rectangle((0,0), fw, fd, facecolor="#cfd3da", edgecolor="#333", lw=1.5))
    ax.add_patch(Rectangle((te,te), fw-2*te, fd-2*te, facecolor="white", edgecolor="none"))
    # Raeume
    for r in plan.get("rooms", []):
        ax.add_patch(Rectangle((r["x"], r["z"]), r["w"], r["d"],
                     facecolor=(r["color"][0], r["color"][1], r["color"][2], 0.35), edgecolor="none"))
        ax.text(r["x"]+r["w"]/2, r["z"]+r["d"]/2, r["label"], ha="center", va="center",
                fontsize=8, color="#222")
    # Innenwaende (mit Oeffnungen als Luecken)
    for p in plan.get("partitions", []):
        ops = sorted(p.get("openings", []), key=lambda o: o["from"])
        cur = p["from"]; segs = []
        for o in ops:
            if o["from"] > cur: segs.append((cur, o["from"]))
            cur = o["to"]
        segs.append((cur, p["to"]))
        for a, c in segs:
            if p["axis"] == "z": ax.add_patch(Rectangle((p["at"]-ti/2, a), ti, c-a, facecolor="#444"))
            else:                ax.add_patch(Rectangle((a, p["at"]-ti/2), c-a, ti, facecolor="#444"))
    # Features
    for f in plan.get("features", []):
        col = "#555" if f.get("type") == "column" else "#9aa0ab"
        ax.add_patch(Rectangle((f["x"], f["z"]), f["w"], f["d"], facecolor=col, edgecolor="#222", lw=0.6))
        ax.text(f["x"]+f["w"]/2, f["z"]+f["d"]+0.08, f["label"], ha="center", va="bottom", fontsize=6, color="#444")
    # Offener Grundriss: Liftschacht (WC/Bad) + Deckenstuetzen
    if plan.get("open_plan"):
        sh = b.get("lift_shaft")
        if sh:
            sc = sh.get("color", [0.40, 0.80, 0.86])
            ax.add_patch(Rectangle((sh["x"], sh["z"]), sh["w"], sh["d"],
                         facecolor=(sc[0], sc[1], sc[2], 0.55), edgecolor="#333", lw=1.2))
            ax.text(sh["x"]+sh["w"]/2, sh["z"]+sh["d"]/2, "WC/Bad\n(Liftschacht)",
                    ha="center", va="center", fontsize=6, color="#133")
        for c in b.get("columns", []):
            cw, cd = c.get("w", 0.30), c.get("d", 0.30)
            ax.add_patch(Rectangle((c["x"], c["z"]), cw, cd, facecolor="#555", edgecolor="#222", lw=0.6))
    # Treppe (Wendeltreppe als Kreis + Spindel, sonst Rechteck)
    s = b.get("stair_core") if (plan.get("open_plan") and b.get("stair_core")) else plan.get("stair")
    if s:
        if s.get("type") == "spiral":
            from matplotlib.patches import Circle
            cx, cz = s["x"]+s["w"]/2, s["z"]+s["d"]/2; rr = min(s["w"], s["d"])/2
            ax.add_patch(Circle((cx, cz), rr, facecolor="none", edgecolor="#333", lw=1.0))
            ax.add_patch(Circle((cx, cz), rr*0.18, facecolor="#333", edgecolor="none"))
            for a in [i*math.pi/6 for i in range(12)]:
                ax.plot([cx+rr*0.18*math.cos(a), cx+rr*math.cos(a)],
                        [cz+rr*0.18*math.sin(a), cz+rr*math.sin(a)], color="#333", lw=0.4)
            ax.text(cx, cz-rr-0.12, "Wendeltreppe", ha="center", va="top", fontsize=6, color="#333")
        else:
            ax.add_patch(Rectangle((s["x"], s["z"]), s["w"], s["d"], facecolor="none",
                         edgecolor="#333", lw=1.0, hatch="///"))
            ax.text(s["x"]+s["w"]/2, s["z"]+s["d"]/2, s.get("label","Treppe"), ha="center", va="center",
                    fontsize=6, color="#333", rotation=90)
    # Masslinien (innen)
    iw, idp = fw-2*te, fd-2*te
    ax.annotate("", (te, -0.25), (fw-te, -0.25), arrowprops=dict(arrowstyle="<->", color="#c00"))
    ax.text(fw/2, -0.45, "%.0f" % (iw*100), ha="center", color="#c00", fontsize=9)
    ax.annotate("", (-0.25, te), (-0.25, fd-te), arrowprops=dict(arrowstyle="<->", color="#c00"))
    ax.text(-0.5, fd/2, "%.0f" % (idp*100), va="center", ha="center", color="#c00", fontsize=9, rotation=90)
    ax.set_xlim(-0.8, fw+0.3); ax.set_ylim(-0.8, fd+0.3); ax.set_aspect("equal")
    ax.set_title("%s  %s  (innen %.2f x %.2f m)" % (lv["name"], lv.get("role",""), iw, idp), fontsize=10)
    ax.axis("off"); fig.tight_layout(); fig.savefig(out_png, dpi=120, facecolor="white")
    print("  Grundriss %-4s ->      %s" % (lv["name"], out_png))


def build_artifact(spec, glb_path, template_path, out_path):
    """Self-contained Viewer-HTML (GLB eingebettet) aus dem Template erzeugen."""
    import base64
    tpl = open(template_path, encoding="utf-8").read()
    b64 = base64.b64encode(open(glb_path, "rb").read()).decode()
    leg = []
    for lv in spec["building"]["levels"]:
        rooms = (lv.get("plan") or {}).get("rooms") or []
        if rooms:
            leg.append({"name": lv["name"], "role": lv.get("role", ""),
                        "rooms": [{"label": r["label"], "color": r["color"]} for r in rooms]})
    out = (tpl.replace("__REV__", str(spec["meta"]["revision"]))
              .replace("__DATE__", spec["meta"]["date"])
              .replace("/*__LEGEND__*/ []", json.dumps(leg, ensure_ascii=False))
              .replace("__GLB_B64__", b64))
    open(out_path, "w", encoding="utf-8").write(out)
    print("  Artifact-HTML ->        %s (%d kB)" % (out_path, len(out)//1024))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="inp", default=os.path.join(HERE, "house.json"))
    ap.add_argument("--out", dest="out", default=os.path.join(HERE, "house.glb"))
    ap.add_argument("--preview", dest="preview", default=None)
    ap.add_argument("--plan", dest="plan", default=None, help="Geschossname, z.B. UG")
    ap.add_argument("--planout", dest="planout", default=None)
    ap.add_argument("--artifact", dest="artifact", default=None, help="Pfad fuer self-contained Viewer-HTML")
    ap.add_argument("--template", dest="template",
                    default=os.path.join(HERE, "viewer", "standalone.template.html"))
    args = ap.parse_args()
    with open(args.inp, encoding="utf-8") as f: spec = json.load(f)
    mb, dims = build(spec)
    nbytes, nmesh, nprim = write_glb(mb, args.out)
    print("Rev %d  ->  %s" % (spec["meta"]["revision"], args.out))
    print("  GLB: %d kB, %d Meshes, %d Primitives, %d Materialien"
          % (nbytes//1024, nmesh, nprim, len(mb.materials)))
    report(spec, dims)
    if args.preview: preview(mb, args.preview, dims)
    if args.plan:
        plan_png(spec, args.plan, args.planout or os.path.join(HERE, "plan_%s.png" % args.plan))
    if args.artifact:
        build_artifact(spec, args.out, args.template, args.artifact)

if __name__ == "__main__":
    main()
