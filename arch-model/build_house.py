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

import argparse, json, os
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

MATS = {
    "shell":  {"rgba": (0.80, 0.82, 0.85, 0.16), "blend": True,  "double": True},
    "slab":   {"rgba": (0.74, 0.75, 0.78, 0.13), "blend": True,  "double": True},
    "roof":   {"rgba": (0.58, 0.44, 0.40, 0.17), "blend": True,  "double": True},
    "part":   {"rgba": (0.93, 0.93, 0.96, 1.00), "blend": False, "double": True},
    "stair":  {"rgba": (0.62, 0.64, 0.68, 0.90), "blend": True,  "double": False},
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
        # Treppe dieses Geschosses
        s = plan.get("stair")
        if s:
            stair_steps(mb, ox+s["x"], ox+s["x"]+s["w"], oz+s["z"], oz+s["z"]+s["d"],
                        yb, h, s.get("dir", "+z"))

    # ---- Boden-/Deckenplatten (eine je Geschoss + oberste Decke) ----
    for sidx in range(n+1):
        lv = levels[sidx] if sidx < n else levels[n-1]
        ox, oz, fw, fd = offset(lv)
        y = base[sidx]
        hole = None
        if sidx >= 1:                       # Loch von der Treppe des Geschosses darunter
            below = levels[sidx-1]
            bs = below.get("plan", {}).get("stair")
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="inp", default=os.path.join(HERE, "house.json"))
    ap.add_argument("--out", dest="out", default=os.path.join(HERE, "house.glb"))
    ap.add_argument("--preview", dest="preview", default=None)
    args = ap.parse_args()
    with open(args.inp, encoding="utf-8") as f: spec = json.load(f)
    mb, dims = build(spec)
    nbytes, nmesh, nprim = write_glb(mb, args.out)
    print("Rev %d  ->  %s" % (spec["meta"]["revision"], args.out))
    print("  GLB: %d kB, %d Meshes, %d Primitives, %d Materialien"
          % (nbytes//1024, nmesh, nprim, len(mb.materials)))
    report(spec, dims)
    if args.preview: preview(mb, args.preview, dims)

if __name__ == "__main__":
    main()
