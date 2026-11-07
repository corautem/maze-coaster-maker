#!/usr/bin/env python3
# Maze Coaster Maker: circular-maze coasters for 3D printing.
# Copyright (C) 2026 corautem
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file for details.
"""Circular-maze coaster generator: 3MF for printing, DXF and SVG drawings.

Each coaster can be written as:
  <name>.3mf  the finished 3D model (solid base, maze walls on top), ready for a slicer
  <name>.dxf  2D drawing in mm with two layers, OUTLINE (the coaster's edge) and
              CHANNELS (closed loops around the gaps between the walls)
  <name>.svg  a picture of the design; output/index.html shows them all
Everything inside OUTLINE that is not a channel is wall or rim, so in a CAD program
you extrude the outline to full height and cut the channels down to the floor.

    python coaster_gen.py --examples
    python coaster_gen.py --shape hexagon --pattern theta --seed 42
    python coaster_gen.py --shape flower --petals 5 --pattern classical
"""
from __future__ import annotations

import argparse
import bisect
import html
import math
import random
import struct
import zipfile
from collections import Counter
from datetime import datetime
from dataclasses import dataclass, field, replace
from pathlib import Path

import ezdxf
from ezdxf import path as ezpath
from shapely import constrained_delaunay_triangles, union_all
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, polylabel, unary_union
from shapely.prepared import prep

ARC_STEP = math.radians(0.25)  # circle discretisation: chord error ~1e-4 mm at r = 50 mm
EPS = 0.01                     # overlap so neighbouring channel pieces fuse cleanly
GRID = 1e-6                    # snap unions so edges that should coincide (e.g. at 0 / 2*pi) do
MIN_SAGITTA = 1e-3             # flatter arcs than this (mm) are exported as lines
BIG = 1000.0
CENTER = "center"
SHAPES = ("circle", "hexagon", "octagon", "rounded-square", "flower")


class CoasterError(ValueError):
    """A design that can't be built with the chosen settings; the message says why."""


@dataclass
class Design:
    shape: str = "circle"
    pattern: str = "theta"         # theta | classical
    size: float = 100.0            # overall width (across flats for polygons)
    rim: float = 3.0               # solid border between outline and maze
    wall: float = 1.0
    gap: float = 1.0
    corner_r: float | None = None  # polygon corner rounding (default per shape)
    petals: int = 6
    outline_file: str | None = None
    seed: int | None = None
    algo: str = "dfs"              # dfs | prim
    bias: str = "none"             # none | ring | radial
    center_d: float | None = None  # smallest centre (goal) diameter in mm; default_center() if None
    cell_length: float | None = None  # theta min cell length (default 1.5 * pitch)
    name: str | None = None
    base: float = 2.0              # 3MF: solid floor thickness in mm
    height: float = 2.0            # 3MF: wall height above the floor in mm

    @property
    def pitch(self) -> float:
        return self.wall + self.gap

    def default_center(self) -> float:
        return (3 if self.pattern == "theta" else 8) * self.pitch

    def center_radius(self) -> float:
        return (self.center_d if self.center_d is not None else self.default_center()) / 2

    def default_name(self) -> str:
        shape = Path(self.outline_file).stem if self.outline_file else self.shape
        if self.shape == "flower" and not self.outline_file:
            shape += str(self.petals)
        parts = [shape, self.pattern]
        if self.pattern == "theta":
            if self.algo != "dfs":
                parts.append(self.algo)
            if self.bias != "none":
                parts.append(self.bias)
            parts.append(f"s{self.seed}")
        # non-default sizes go in the name too, so different designs never share a file
        if self.size != 100:
            parts.insert(1, f"{self.size:g}mm")
        if (self.wall, self.gap, self.rim) != (1.0, 1.0, 3.0):
            parts.append(f"w{self.wall:g}-g{self.gap:g}-r{self.rim:g}")
        if self.center_d is not None and self.center_d != self.default_center():
            parts.append(f"c{self.center_d:g}")
        if (self.base, self.height) != (2.0, 2.0):
            parts.append(f"b{self.base:g}-h{self.height:g}")
        return "_".join(parts)


# ---------------------------------------------------------------- geometry helpers

def arc_coords(r, t0, t1):
    n = max(1, math.ceil(abs(t1 - t0) / ARC_STEP))
    return [(r * math.cos(t0 + (t1 - t0) * i / n), r * math.sin(t0 + (t1 - t0) * i / n))
            for i in range(n + 1)]


def disk(r):
    return Polygon(arc_coords(r, 0, 2 * math.pi)[:-1])


def annulus(r0, r1):
    return Polygon(arc_coords(r1, 0, 2 * math.pi)[:-1], [arc_coords(r0, 0, 2 * math.pi)[:-1]])


def sector(r0, r1, t0, t1):
    return Polygon(arc_coords(r1, t0, t1) + arc_coords(r0, t1, t0))


def ray_strip(theta, half_w, d0, d1):
    """Rectangle of width 2*half_w centred on the ray at angle theta, from distance d0 to d1."""
    ux, uy = math.cos(theta), math.sin(theta)
    nx, ny = -uy * half_w, ux * half_w
    return Polygon([(d0 * ux + nx, d0 * uy + ny), (d1 * ux + nx, d1 * uy + ny),
                    (d1 * ux - nx, d1 * uy - ny), (d0 * ux - nx, d0 * uy - ny)])


def bulge_arc(p0, p1, b):
    """Centre, radius, start angle and signed sweep of the arc p0 -> p1 with DXF bulge b."""
    sweep = 4 * math.atan(b)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    chord = math.hypot(dx, dy)
    r = chord / (2 * math.sin(sweep / 2))
    h = r * math.cos(sweep / 2)
    cx = (p0[0] + p1[0]) / 2 - dy / chord * h
    cy = (p0[1] + p1[1]) / 2 + dx / chord * h
    return (cx, cy), abs(r), math.atan2(p0[1] - cy, p0[0] - cx), sweep


def flatten_loop(loop, step=ARC_STEP):
    """Points of a closed (x, y, bulge) polyline with arcs sampled every step radians."""
    pts = []
    for i, (x0, y0, b) in enumerate(loop):
        pts.append((x0, y0))
        if b:
            x1, y1, _ = loop[(i + 1) % len(loop)]
            (cx, cy), r, a0, sweep = bulge_arc((x0, y0), (x1, y1), b)
            n = max(2, math.ceil(abs(sweep) / step))
            pts += [(cx + r * math.cos(a0 + sweep * k / n), cy + r * math.sin(a0 + sweep * k / n))
                    for k in range(1, n)]
    return pts


def parts(geom):
    if geom.is_empty:
        return []
    return list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]


# ---------------------------------------------------------------- outlines

@dataclass
class Outline:
    loop: list                      # closed polyline [(x, y, bulge), ...]
    circle_r: float | None = None   # set when the outline is a plain circle

    def polygon(self) -> Polygon:
        return Polygon(flatten_loop(self.loop))


def rounded_polygon(n, apothem, corner_r):
    """Regular n-gon with a flat edge at the bottom and filleted corners."""
    circ = apothem / math.cos(math.pi / n)
    start = -math.pi / 2 - math.pi / n
    verts = [(circ * math.cos(start + 2 * math.pi * i / n), circ * math.sin(start + 2 * math.pi * i / n))
             for i in range(n)]
    turn = 2 * math.pi / n
    t = corner_r * math.tan(turn / 2)
    if t > apothem * math.tan(math.pi / n):
        raise CoasterError(f"A corner radius of {corner_r:g} mm is too large for this shape and size.")
    loop = []
    for i, (vx, vy) in enumerate(verts):
        if corner_r <= 0:
            loop.append((vx, vy, 0.0))
            continue
        px, py = verts[i - 1]
        qx, qy = verts[(i + 1) % n]
        lin, lout = math.hypot(vx - px, vy - py), math.hypot(qx - vx, qy - vy)
        loop.append((vx - (vx - px) / lin * t, vy - (vy - py) / lin * t, math.tan(turn / 4)))
        loop.append((vx + (qx - vx) / lout * t, vy + (qy - vy) / lout * t, 0.0))
    return Outline(loop)


def flower(n, R):
    """n round petals with concave fillets between them; petal tips touch radius R."""
    s = math.sin(math.pi / n)
    rp = 2 * R * s / (1.3 + 2 * s)
    dist = R - rp
    f = max(2.0, 0.06 * R)
    angles = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
    centers = [(dist * math.cos(a), dist * math.sin(a)) for a in angles]
    D = dist * math.cos(math.pi / n) + math.sqrt((rp + f) ** 2 - (dist * s) ** 2)
    fillets = [(D * math.cos(a + math.pi / n), D * math.sin(a + math.pi / n)) for a in angles]

    def touch(c, fc):
        return (c[0] + rp * (fc[0] - c[0]) / (rp + f), c[1] + rp * (fc[1] - c[1]) / (rp + f))

    def ang(p, c):
        return math.atan2(p[1] - c[1], p[0] - c[0])

    loop = []
    for i in range(n):
        c, fc = centers[i], fillets[i]
        start, end = touch(c, fillets[i - 1]), touch(c, fc)
        nxt = touch(centers[(i + 1) % n], fc)
        petal = (ang(end, c) - ang(start, c)) % (2 * math.pi)
        dip = -((ang(end, fc) - ang(nxt, fc)) % (2 * math.pi))
        loop.append((*start, math.tan(petal / 4)))
        loop.append((*end, math.tan(dip / 4)))
    return Outline(loop)


def outline_from_dxf(path, rim):
    """Largest closed outline in a DXF (mm), re-centred on the roomiest point inside the rim."""
    doc = ezdxf.readfile(path)
    lines = []
    for e in doc.modelspace():
        try:
            pth = ezpath.make_path(e)
        except (TypeError, ValueError):
            continue
        pts = [(round(v.x, 4), round(v.y, 4)) for v in pth.flattening(0.01)]  # snap so chained ends meet
        if len(pts) >= 2:
            lines.append(LineString(pts))
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        raise CoasterError(f"No closed outline found in {path}.")
    poly = Polygon(max(polys, key=lambda p: p.area).exterior)
    cx, cy = polylabel(poly.buffer(-rim), 0.01).coords[0]
    return Outline([(x - cx, y - cy, 0.0) for x, y in poly.exterior.coords[:-1]])


def make_outline(d: Design) -> Outline:
    R = d.size / 2
    if d.outline_file:
        return outline_from_dxf(d.outline_file, d.rim)
    if d.shape == "circle":
        return Outline([(R, 0.0, 1.0), (-R, 0.0, 1.0)], circle_r=R)
    if d.shape == "flower":
        if d.petals < 3:
            raise CoasterError("A flower needs at least 3 petals.")
        return flower(d.petals, R)
    n = {"hexagon": 6, "octagon": 8, "rounded-square": 4}[d.shape]
    corner = d.corner_r if d.corner_r is not None else (12.0 if n == 4 else 4.0)
    return rounded_polygon(n, R, corner)


# ---------------------------------------------------------------- centre size

def fit_centre(d: Design, r_fit: float, floor_r: float):
    """Centre radius, ring count, and the smallest centre radius this outline allows.

    Rings step outward by one pitch and the outermost must end exactly at r_fit
    (the border where the outline is closest), so the centre gets the requested
    radius (at least floor_r) plus whatever is left over, less than one pitch.
    """
    def fit(req):
        n = int((r_fit + EPS - req) // d.pitch)
        return max(r_fit - d.pitch * n, req), n

    c, n = fit(max(d.center_radius(), floor_r))
    return c, n, fit(floor_r)[0]


def centre_notes(d: Design, actual: float, smallest: float) -> list:
    """(level, text) messages for when the centre isn't the size that was asked for."""
    asked = d.center_d
    if asked is None:
        return []
    step = 2 * d.pitch
    if asked < smallest - 0.05:
        why = ("The labyrinth's turns need room around it" if d.pattern == "classical"
               else "The doorway into it needs room")
        return [("warning", f"The centre can't be smaller than {smallest:g} mm on this coaster, so {asked:g} mm "
                            f"gives the same result as {smallest:g} mm. {why}, and the rings come in "
                            f"{step:g} mm steps so they end exactly at the border.")]
    if actual > asked + 0.05:
        return [("note", f"The centre is {actual:g} mm instead of {asked:g} mm: the rings come in {step:g} mm "
                         f"steps, so the centre grows to make them end exactly at the border.")]
    return []


# ---------------------------------------------------------------- theta maze

def carve(adj, start, algo, weight, rng):
    """Spanning tree over adj; returns the opened edges as (u, v, kind, gamma)."""
    visited = {start}
    opened = []
    if algo == "dfs":  # recursive backtracker: long winding corridors
        stack = [start]
        while stack:
            cur = stack[-1]
            nxt = [e for e in adj[cur] if e[0] not in visited]
            if not nxt:
                stack.pop()
                continue
            v, kind, gamma = rng.choices(nxt, [weight(e[1]) for e in nxt])[0]
            visited.add(v)
            opened.append((cur, v, kind, gamma))
            stack.append(v)
    else:  # randomised Prim: bushier, many short dead ends
        frontier = [(start, *e) for e in adj[start]]
        while frontier:
            i = rng.choices(range(len(frontier)), [weight(f[2]) for f in frontier])[0]
            u, v, kind, gamma = frontier[i]
            frontier[i] = frontier[-1]
            frontier.pop()
            if v in visited:
                continue
            visited.add(v)
            opened.append((u, v, kind, gamma))
            frontier += [(v, *e) for e in adj[v] if e[0] not in visited]
    return opened


def theta_channels(play: Polygon, d: Design, rng: random.Random):
    """Random maze on concentric rings, grown from a central goal disk.

    Ring k's channel band is [a_k, a_k + gap]; the rings are split into cells at
    least cell_length long. Walls between cells are constant-width radial strips
    and openings to the next ring are constant-width strips through the ring wall.
    """
    g, w, pitch = d.gap, d.wall, d.pitch
    cell_len = d.cell_length if d.cell_length is not None else 1.5 * pitch
    h = (w + g) / 2 + 0.02  # opening centre line to radial-wall centre line
    r_fit = play.exterior.distance(Point(0, 0))
    c, n, c_small = fit_centre(d, r_fit, g)  # the doorway into the centre is one gap wide
    if n < 1:
        raise CoasterError("The centre is too big for this coaster: there's no room for a ring around it. "
                           "Make the centre smaller or the coaster bigger.")

    r_max = max(math.hypot(x, y) for x, y in play.exterior.coords)
    rings = []  # (inner radius, cell count, angular offset)
    a = c + w
    while a + g <= r_max + EPS:  # tolerance: the play area is a polygon a hair inside the true circle
        n = max(3, int(2 * math.pi * a // cell_len))
        rings.append((a, n, rng.uniform(0, 2 * math.pi / n)))
        a += pitch

    def span(k, j):  # both ends from the same formula so neighbouring sectors share an exact edge
        _, n, off = rings[k]
        return off + 2 * math.pi * j / n, off + 2 * math.pi * (j + 1) / n

    inside = prep(play.buffer(EPS))  # tolerance so a ring that exactly fills the rim still counts
    cells = {(k, j) for k, (a, n, _) in enumerate(rings) for j in range(n)
             if inside.contains(sector(a, a + g, *span(k, j)))}

    adj = {node: [] for node in cells | {CENTER}}

    def link(u, v, kind, gamma=None):
        adj[u].append((v, kind, gamma))
        adj[v].append((u, kind, gamma))

    for k, j in cells:
        n = rings[k][1]
        if (k, (j + 1) % n) in cells:
            link((k, j), (k, (j + 1) % n), "ring")

    # An opening's centre line at angle gamma must stay h away from the radial wall
    # centre lines of both cells, measured at the smallest radius the opening reaches.
    def window(k, j, r):
        t0, t1 = span(k, j)
        dt = math.asin(min(1.0, h / r))
        return t0 + dt, t1 - dt

    for k in range(len(rings) - 1):
        a, n, _ = rings[k]
        a2, n2, off2 = rings[k + 1]
        s0 = math.sqrt((a + g) ** 2 - (g / 2) ** 2) - EPS
        step2 = 2 * math.pi / n2
        for j in range(n):
            if (k, j) not in cells:
                continue
            lo, hi = window(k, j, s0)
            if lo > hi:
                continue
            for jj in range(math.floor((lo - off2) / step2), math.floor((hi - off2) / step2) + 1):
                if (k + 1, jj % n2) not in cells:
                    continue
                dt = math.asin(min(1.0, h / a2))
                l, r = max(lo, off2 + jj * step2 + dt), min(hi, off2 + (jj + 1) * step2 - dt)
                if l <= r:
                    link((k, j), (k + 1, jj % n2), "radial", (l + r) / 2)

    # the goal gets a single doorway into the first ring
    doors = []
    for j in range(rings[0][1]):
        lo, hi = window(0, j, rings[0][0])
        if (0, j) in cells and lo <= hi:
            doors.append(((0, j), (lo + hi) / 2))
    if not doors:
        raise CoasterError("There's no room for a doorway into the maze centre. Try a bigger centre or shorter cells.")
    node, gamma = rng.choice(doors)
    link(CENTER, node, "radial", gamma)

    # cells the maze can't reach (cut off by the outline) stay solid
    keep, todo = {CENTER}, [CENTER]
    while todo:
        for v, _, _ in adj[todo.pop()]:
            if v not in keep:
                keep.add(v)
                todo.append(v)
    adj = {u: [e for e in es if e[0] in keep] for u, es in adj.items() if u in keep}

    ring_w, radial_w = {"none": (1, 1), "ring": (4, 1), "radial": (1, 4)}[d.bias]
    passages = carve(adj, CENTER, d.algo, lambda kind: ring_w if kind == "ring" else radial_w, rng)
    open_ring = {frozenset((u, v)) for u, v, kind, _ in passages if kind == "ring"}

    pieces = [disk(c)]
    for k, (a, n, off) in enumerate(rings):
        js = [j for j in range(n) if (k, j) in keep]
        if not js:
            continue
        band = annulus(a, a + g) if len(js) == n else union_all(
            [sector(a, a + g, *span(k, j)) for j in js], grid_size=GRID)
        cuts = []
        for j in range(n):
            left, right = (k, (j - 1) % n), (k, j)
            if (left in keep or right in keep) and frozenset((left, right)) not in open_ring:
                cuts.append(ray_strip(off + 2 * math.pi * j / n, w / 2, a - pitch, a + g + pitch))
        pieces.append(band.difference(unary_union(cuts)) if cuts else band)

    for u, v, kind, gamma in passages:
        if kind != "radial":
            continue
        if CENTER in (u, v):
            pieces.append(ray_strip(gamma, g / 2, c / 2, rings[0][0] + EPS))
        else:
            k = min(u[0], v[0])
            a, a2 = rings[k][0], rings[k + 1][0]
            s0 = math.sqrt((a + g) ** 2 - (g / 2) ** 2) - EPS
            pieces.append(ray_strip(gamma, g / 2, s0, a2 + EPS))

    stats = {"rings": len(rings), "cells": len(keep) - 1, "centre_d": round(2 * c, 1)}
    return union_all(pieces, grid_size=GRID), stats, round(2 * c_small, 1)


# ---------------------------------------------------------------- classical labyrinth

def classical_channels(play: Polygon, d: Design):
    """Cretan-style single-path labyrinth drawn with concentric circuits.

    Circuits are numbered 1 (outermost) .. n, the centre is n + 1 and the
    outside is 0. The classical core has 4m - 1 circuits and visits
    h, h-1 .. 1, h+1, core, core-1 .. h+2 (h = (core-1)/2). Any 0-3 circuits left
    over are walked in order first (1, 2, 3), so every circuit count works and the
    centre size can change in steps of one ring.
    Every change of circuit happens in a turning zone at the bottom, alternating
    left and right of a vertical axis wall. On each side the transitions nest like
    brackets; a bracket at depth D becomes a vertical strip at |x| in
    [w/2 + D*pitch, w/2 + D*pitch + gap] joining its two circuits.
    """
    g, w, p = d.gap, d.wall, d.pitch
    r_fit = play.exterior.distance(Point(0, 0))
    c, n, c_small = fit_centre(d, r_fit, w / 2 + p + g)  # the turning zone needs room at the inner circuits
    if n < 3:
        raise CoasterError("There's no room for a classical labyrinth. Make the centre smaller or the coaster bigger.")
    core = n - (n + 1) % 4
    k = n - core
    h = (core - 1) // 2
    seq = [0, *range(1, k + 1), *(k + j for j in (*range(h, 0, -1), h + 1, *range(core, h + 1, -1))), n + 1]

    def inner(k):
        return c + w + p * (n - k)

    brackets = [(-1 if i % 2 == 0 else 1, *sorted(seq[i:i + 2])) for i in range(len(seq) - 1)]
    depth = {b: sum(1 for o in brackets if o[0] == b[0] and o[1] < b[1] and o[2] > b[2]) for b in brackets}
    end_x = {}  # (circuit, side) -> |x| where the circuit's channel stops
    for b in brackets:
        for k in b[1:]:
            end_x[k, b[0]] = w / 2 + depth[b] * p

    pieces = [disk(c)]
    for k in range(1, n + 1):
        gap_box = box(-end_x[k, -1], -BIG, end_x[k, 1], 0)
        pieces.append(annulus(inner(k), inner(k) + g).difference(gap_box))
    for b in brackets:
        side, lo, hi = b
        x0 = w / 2 + depth[b] * p
        r_in = c / 2 if hi == n + 1 else inner(hi) + g / 2
        r_out = inner(1) + g if lo == 0 else inner(lo) + g / 2
        strip = box(x0, -BIG, x0 + g, 0) if side > 0 else box(-x0 - g, -BIG, -x0, 0)
        pieces.append(strip.intersection(sector(r_in, r_out, -math.pi, 0)))

    return union_all(pieces, grid_size=GRID), {"circuits": n, "centre_d": round(2 * c, 1)}, round(2 * c_small, 1)


# ---------------------------------------------------------------- export

def ring_to_loop(coords, tol=1e-3):
    """Shapely ring -> closed (x, y, bulge) polyline.

    Every curved channel edge is a circle about the origin, so runs of short
    segments whose ends sit at the same radius are merged back into true arcs.
    """
    pts = []
    for x, y in coords[:-1]:
        if not pts or math.hypot(x - pts[-1][0], y - pts[-1][1]) > 5e-4:
            pts.append((x, y))
    while len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 5e-4:
        pts.pop()
    n = len(pts)
    rad = [math.hypot(x, y) for x, y in pts]
    seg = []
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        dth = math.atan2(x0 * y1 - y0 * x1, x0 * x1 + y0 * y1)
        is_arc = abs(rad[i] - rad[(i + 1) % n]) < tol and rad[i] > 0.1 and abs(dth) <= ARC_STEP * 1.01
        seg.append((round(rad[i], 2), dth > 0) if is_arc else None)

    start = next((i for i in range(n) if seg[i] is None or seg[i] != seg[i - 1]), 0)
    loop = []
    i, done = start, 0
    while done < n:
        if seg[i] is None:
            loop.append((*pts[i], 0.0))
            i, done = (i + 1) % n, done + 1
            continue
        j, total = i, 0.0
        while done < n and seg[j] == seg[i]:
            (x0, y0), (x1, y1) = pts[j], pts[(j + 1) % n]
            total += math.atan2(x0 * y1 - y0 * x1, x0 * x1 + y0 * y1)
            j, done = (j + 1) % n, done + 1
        pieces = max(1, math.ceil(abs(total) / math.pi - 1e-9))  # keep every arc <= 180 deg
        a0 = math.atan2(pts[i][1], pts[i][0])
        for q in range(pieces):
            p = pts[i] if q == 0 else (rad[i] * math.cos(a0 + total * q / pieces),
                                       rad[i] * math.sin(a0 + total * q / pieces))
            loop.append((*p, math.tan(total / pieces / 4)))
        i = j

    # arcs that bow less than 1 um are lines to any printer, and some CAD programs reject them as arcs
    for i, (x0, y0, b) in enumerate(loop):
        x1, y1, _ = loop[(i + 1) % len(loop)]
        if b and abs(b) * math.hypot(x1 - x0, y1 - y0) / 2 < MIN_SAGITTA:
            loop[i] = (x0, y0, 0.0)

    # drop vertices in the middle of straight runs
    out = []
    for v in loop + loop[:1]:
        if len(out) >= 2 and out[-2][2] == 0 and out[-1][2] == 0:
            (ax, ay, _), (bx, by, _) = out[-2], out[-1]
            ux, uy, vx, vy = bx - ax, by - ay, v[0] - bx, v[1] - by
            if abs(ux * vy - uy * vx) < 1e-9 * math.hypot(ux, uy) * math.hypot(vx, vy) + 1e-12 and ux * vx + uy * vy > 0:
                out[-1] = v
                continue
        out.append(v)
    return out[:-1] if len(out) > 1 and out[-1][:2] == out[0][:2] else out


def geometry_loops(geom):
    loops = []
    for poly in parts(geom):
        loops.append(ring_to_loop(list(poly.exterior.coords)))
        loops += [ring_to_loop(list(r.coords)) for r in poly.interiors]
    return loops


def make_dxf(outline: Outline, loops):
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$MEASUREMENT"] = 1
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("CHANNELS", color=1)
    msp = doc.modelspace()
    if outline.circle_r:
        msp.add_circle((0, 0), outline.circle_r, dxfattribs={"layer": "OUTLINE"})
    else:
        msp.add_lwpolyline(outline.loop, format="xyb", close=True, dxfattribs={"layer": "OUTLINE"})
    for loop in loops:
        msp.add_lwpolyline(loop, format="xyb", close=True, dxfattribs={"layer": "CHANNELS"})
    return doc


def svg_path(loops):
    out = []
    for loop in loops:
        d = [f"M{loop[0][0]:.4f},{loop[0][1]:.4f}"]
        for i, (x0, y0, b) in enumerate(loop):
            x1, y1, _ = loop[(i + 1) % len(loop)]
            if b:
                r = math.hypot(x1 - x0, y1 - y0) * (1 + b * b) / (4 * abs(b))
                d.append(f"A{r:.4f},{r:.4f} 0 {int(abs(b) > 1)} {int(b > 0)} {x1:.4f},{y1:.4f}")
            else:
                d.append(f"L{x1:.4f},{y1:.4f}")
        out.append("".join(d) + "Z")
    return "".join(out)


def write_svg(path: Path, outline: Outline, loops, bounds):
    minx, miny, maxx, maxy = bounds
    m = 2.0
    W, H = maxx - minx + 2 * m, maxy - miny + 2 * m
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{H:.1f}mm" '
        f'viewBox="{minx - m:.3f} {-maxy - m:.3f} {W:.3f} {H:.3f}">\n'
        f'<g transform="scale(1,-1)">\n'
        f'<path d="{svg_path([outline.loop])}" fill="#e6d7b9" stroke="#8a7556" stroke-width="0.3"/>\n'
        f'<path d="{svg_path(loops)}" fill="#3a2e27"/>\n'
        f'</g>\n</svg>\n', encoding="utf-8")


# ---------------------------------------------------------------- 3D model (3MF)

MESH_STEP = math.radians(1.5)  # arc sampling for the 3D model: under 0.005 mm off the true curve at r = 50 mm


def mesh_ring(loop, ccw):
    """Flattened closed loop with near-duplicate points dropped, turned to the requested direction."""
    pts = []
    for p in flatten_loop(loop, MESH_STEP):
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 5e-4:
            pts.append(p)
    if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 5e-4:
        pts.pop()
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    return pts if (area2 > 0) == ccw else pts[::-1]


def make_mesh(outline: Outline, loops, base: float, height: float):
    """Closed triangle mesh of the printed coaster: a solid floor with the maze walls on top.

    The bottom is the whole outline at z = 0, the channel floors sit at z = base and
    the tops of the walls and rim at z = base + height. Every face is built from the
    same boundary points, so each edge is shared by exactly two triangles. Returns
    (vertices, triangles), triangles counter-clockwise seen from outside, with the
    model's bounding box starting at (0, 0, 0) so it lands on a slicer's bed.
    """
    top = base + height
    outer = mesh_ring(outline.loop, ccw=True)
    holes = [mesh_ring(loop, ccw=False) for loop in loops]  # channels: material to the left of travel
    index, verts, tris = {}, [], []

    def vertex(x, y, z):
        key = (x, y, z)
        if key not in index:
            index[key] = len(verts)
            verts.append(key)
        return index[key]

    def cap(poly, z, up):
        for t in constrained_delaunay_triangles(poly).geoms:
            (ax, ay), (bx, by), (cx, cy) = t.exterior.coords[:3]
            abc = [vertex(ax, ay, z), vertex(bx, by, z), vertex(cx, cy, z)]
            if ((bx - ax) * (cy - ay) - (by - ay) * (cx - ax) > 0) != up:
                abc.reverse()
            tris.append(tuple(abc))

    def side(ring, z0, z1):  # with material on the left of travel, these quads face outward
        for (px, py), (qx, qy) in zip(ring, ring[1:] + ring[:1]):
            p0, q0, q1, p1 = vertex(px, py, z0), vertex(qx, qy, z0), vertex(qx, qy, z1), vertex(px, py, z1)
            tris.extend([(p0, q0, q1), (p0, q1, p1)])

    cap(Polygon(outer), 0.0, up=False)
    cap(Polygon(outer, holes), top, up=True)
    side(outer, 0.0, top)
    for ring in holes:
        cap(Polygon(ring), base, up=True)
        side(ring, base, top)

    minx, miny = min(x for x, _, _ in verts), min(y for _, y, _ in verts)
    return [(x - minx, y - miny, z) for x, y, z in verts], tris


def mesh_is_closed(tris) -> bool:
    """Every edge is used once in each direction: no holes, no loose flaps, faces all turned the same way."""
    edges = Counter((a, b) for t in tris for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])))
    return all(n == 1 and edges[(b, a)] == 1 for (a, b), n in edges.items())


def write_3mf(path: Path, name: str, verts, tris):
    model = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
        f' <metadata name="Title">{html.escape(name)}</metadata>',
        ' <metadata name="Application">Maze Coaster Maker</metadata>',
        f' <resources><object id="1" name="{html.escape(name)}" type="model"><mesh><vertices>',
        *(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in verts),
        '</vertices><triangles>',
        *(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris),
        '</triangles></mesh></object></resources>',
        ' <build><item objectid="1"/></build>',
        '</model>',
    ]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
                   '</Relationships>')
        z.writestr("3D/3dmodel.model", "\n".join(model))


def write_stl(path: Path, name: str, verts, tris):
    """Binary STL: the same mesh as the 3MF, for programs that only read STL."""
    header = f"Maze Coaster Maker: {name}".encode("ascii", "replace")[:80].ljust(80, b" ")
    with open(path, "wb") as f:
        f.write(header + struct.pack("<I", len(tris)))
        for a, b, c in tris:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = verts[a], verts[b], verts[c]
            ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            f.write(struct.pack("<12fH", nx / length, ny / length, nz / length,
                                ax, ay, az, bx, by, bz, cx, cy, cz, 0))


# ---------------------------------------------------------------- CAD solid (STEP)

STEP_FACE_EDGES = 250  # aim for flat faces with at most about this many boundary edges; CAD
                       # programs take far longer to open faces with thousands of edges


class SplitFailed(Exception):
    """Cutting the flat faces into strips didn't work out; the export falls back to whole faces."""


def oriented_loop(loop, ccw):
    """A closed (x, y, bulge) loop turned to run counter-clockwise (ccw=True) or clockwise."""
    pts = flatten_loop(loop)
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if (area2 > 0) == ccw:
        return list(loop)
    n = len(loop)  # walking backwards, each segment keeps its arc but bends the other way
    return [(loop[-k % n][0], loop[-k % n][1], -loop[(-k - 1) % n][2]) for k in range(n)]


def step_cuts(loops):
    """x positions of upright cutting lines that split the big flat faces into strips.

    Each line stays at least 1 µm clear of every corner and every arc's turning point, so
    it crosses edges cleanly.
    """
    edges = sum(len(loop) for loop in loops)
    strips = edges // STEP_FACE_EDGES
    if not strips:
        return []
    xs = sorted(x for loop in loops for x, _, _ in loop)
    arcs = set()
    for loop in loops:
        for i, (x0, y0, b) in enumerate(loop):
            if b:
                x1, y1, _ = loop[(i + 1) % len(loop)]
                (cx, _), r, _, _ = bulge_arc((x0, y0), (x1, y1), b)
                arcs.add((round(cx, 6), round(r, 6)))

    def clear(c):
        i = bisect.bisect_left(xs, c)
        near = xs[max(0, i - 1):i + 1]
        return all(abs(x - c) > 1e-3 for x in near) and all(abs(abs(c - cx) - r) > 1e-3 for cx, r in arcs)

    cuts = []
    for j in range(1, strips + 1):
        c = xs[0] + (xs[-1] - xs[0]) * j / (strips + 1) + 0.0137
        for _ in range(500):
            if clear(c):
                cuts.append(c)
                break
            c += 0.0173
    return cuts


def arc_mid_angle(a, b, centre, ccw):
    ta = math.atan2(a[1] - centre[1], a[0] - centre[0])
    tb = math.atan2(b[1] - centre[1], b[0] - centre[0])
    sweep = (tb - ta) % (2 * math.pi) if ccw else -((ta - tb) % (2 * math.pi))
    return ta, sweep


def split_loop(loop, cuts):
    """Pieces of a loop's edges between the cutting lines.

    Returns one list per edge of (a, b, arc) pieces, arc = (centre, r, ccw) or None.
    Points where a cutting line crosses an edge get x exactly equal to that line.
    """
    out = []
    n = len(loop)
    for i, (x0, y0, b) in enumerate(loop):
        x1, y1, _ = loop[(i + 1) % n]
        hits = []
        if b:
            (cx, cy), r, a0, sweep = bulge_arc((x0, y0), (x1, y1), b)
            arc = ((cx, cy), r, sweep > 0)
            for c in cuts:
                if abs(c - cx) < r:
                    dy = math.sqrt(r * r - (c - cx) ** 2)
                    for y in (cy - dy, cy + dy):
                        turn = (math.atan2(y - cy, c - cx) - a0) * (1 if sweep > 0 else -1)
                        t = (turn % (2 * math.pi)) / abs(sweep)
                        if 1e-9 < t < 1 - 1e-9:
                            hits.append((t, (c, y)))
        else:
            arc = None
            for c in cuts:
                if (x0 - c) * (x1 - c) < 0:
                    t = (c - x0) / (x1 - x0)
                    hits.append((t, (c, y0 + t * (y1 - y0))))
        pts = [(x0, y0)] + [p for _, p in sorted(hits)] + [(x1, y1)]
        out.append([(pts[j], pts[j + 1], arc) for j in range(len(pts) - 1)])
    return out


def piece_mid_x(piece):
    a, b, arc = piece
    if arc is None:
        return (a[0] + b[0]) / 2
    centre, r, ccw = arc
    ta, sweep = arc_mid_angle(a, b, centre, ccw)
    return centre[0] + r * math.cos(ta + sweep / 2)


def trace_faces(pieces, steps, cuts):
    """Flat faces left over when the cutting lines split a region.

    pieces: all (a, b, arc) pieces; steps: (piece index, forward) pairs that run around the
    region with it on their left. Returns closed walks of ("piece", index, forward) and
    ("cut", from point, to point) steps.
    """
    on_cut = set(cuts)
    leaving, from_left = {}, {}
    for k, forward in steps:
        a, b, _ = pieces[k]
        start, end = (a, b) if forward else (b, a)
        if start in leaving:
            raise SplitFailed
        leaving[start] = (k, forward)
        if end[0] in on_cut:
            from_left[end] = piece_mid_x(pieces[k]) < end[0]

    # Walking up a cutting line, the region starts at a crossing that comes from the left and
    # ends at one that comes from the right; those two points bound one cut segment.
    partner = {}
    lines = {}
    for p, left in from_left.items():
        lines.setdefault(p[0], []).append((p[1], left, p))
    for crossings in lines.values():
        crossings.sort()
        if len(crossings) % 2:
            raise SplitFailed
        for (_, left0, p0), (_, left1, p1) in zip(crossings[0::2], crossings[1::2]):
            if not left0 or left1:
                raise SplitFailed
            partner[p0], partner[p1] = p1, p0

    walks, used = [], set()
    for first in steps:
        if first in used:
            continue
        walk, step = [], first
        while step not in used:
            used.add(step)
            walk.append(("piece",) + step)
            a, b, _ = pieces[step[0]]
            end = b if step[1] else a
            if end in partner:
                walk.append(("cut", end, partner[end]))
                end = partner[end]
            step = leaving.get(end)
            if step is None:
                raise SplitFailed
        if step != first:
            raise SplitFailed
        walks.append(walk)
    return walks


def walk_polygon(pieces, walk):
    pts = []
    for step in walk:
        if step[0] == "cut":
            pts.append(step[1])
            continue
        a, b, arc = pieces[step[1]]
        a, b = (a, b) if step[2] else (b, a)
        pts.append(a)
        if arc:
            centre, r, ccw = arc
            ta, sweep = arc_mid_angle(a, b, centre, ccw == step[2])
            n = max(2, math.ceil(abs(sweep) / ARC_STEP))
            pts += [(centre[0] + r * math.cos(ta + sweep * j / n), centre[1] + r * math.sin(ta + sweep * j / n))
                    for j in range(1, n)]
    return pts


def group_faces(pieces, walks):
    """Pair each hole (a clockwise walk) with the counter-clockwise walk around it."""
    outers, holes = [], []
    for walk in walks:
        pts = walk_polygon(pieces, walk)
        signed = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
        (outers if signed > 0 else holes).append((walk, Polygon(pts)))
    faces = [[walk] for walk, _ in outers]
    for walk, poly in holes:
        inside = [(o.area, i) for i, (_, o) in enumerate(outers) if o.contains(poly.representative_point())]
        if not inside:
            raise SplitFailed
        faces[min(inside)[1]].append(walk)
    return faces


def step_real(x):
    text = f"{x:.9f}".rstrip("0")  # STEP reals need the decimal point: 2. not 2
    return "0." if text in ("0.", "-0.") else text


def step_string(text):
    return "'" + "".join(c if " " <= c <= "~" else "_" for c in text).replace("'", "''") + "'"


class StepWriter:
    """Writes the coaster as a STEP (ISO 10303-21, AP214) solid that CAD programs open as a body.

    Every face is flat (plane) or part of an upright cylinder, and every edge a line or
    circular arc, so the solid is exact: no mesh, nothing approximated.
    """

    def __init__(self):
        self.items = []
        self.cache = {}
        self.uses = Counter()  # (edge, forward) -> times used, for the closed-shell check

    def add(self, entity):
        self.items.append(entity)
        return f"#{len(self.items)}"

    def once(self, key, make):
        if key not in self.cache:
            self.cache[key] = make()
        return self.cache[key]

    def point(self, x, y, z):
        return self.once(("p", x, y, z),
                         lambda: self.add(f"CARTESIAN_POINT('',({step_real(x)},{step_real(y)},{step_real(z)}))"))

    def direction(self, x, y, z):
        return self.once(("d", x, y, z),
                         lambda: self.add(f"DIRECTION('',({step_real(x)},{step_real(y)},{step_real(z)}))"))

    def placement(self, origin, axis, ref):
        return self.add(f"AXIS2_PLACEMENT_3D('',{self.point(*origin)},{self.direction(*axis)},"
                        f"{self.direction(*ref)})")

    def vertex(self, x, y, z):
        return self.once(("v", x, y, z), lambda: self.add(f"VERTEX_POINT('',{self.point(x, y, z)})"))

    def line_edge(self, a, b):
        d = [q - p for p, q in zip(a, b)]
        length = math.sqrt(sum(c * c for c in d))
        vector = self.add(f"VECTOR('',{self.direction(*(c / length for c in d))},{step_real(length)})")
        line = self.add(f"LINE('',{self.point(*a)},{vector})")
        return self.add(f"EDGE_CURVE('',{self.vertex(*a)},{self.vertex(*b)},{line},.T.)")

    def piece_edge(self, pieces, k, z):
        def make():
            (ax, ay), (bx, by), arc = pieces[k]
            if arc is None:
                return self.line_edge((ax, ay, z), (bx, by, z))
            (cx, cy), r, ccw = arc
            # a circle runs counter-clockwise around its axis, so clockwise arcs get the axis pointing down
            circle = self.add(f"CIRCLE('',{self.placement((cx, cy, z), (0, 0, 1 if ccw else -1), (1, 0, 0))},"
                              f"{step_real(r)})")
            return self.add(f"EDGE_CURVE('',{self.vertex(ax, ay, z)},{self.vertex(bx, by, z)},{circle},.T.)")
        return self.once(("e", k, z), make)

    def cut_edge(self, p, q, z):
        lower, upper = sorted((p, q), key=lambda pt: pt[1])
        edge = self.once(("c", lower, upper, z), lambda: self.line_edge((*lower, z), (*upper, z)))
        return edge, p == lower

    def face(self, bounds, surface, same_sense=True):
        """bounds: loops of (edge, forward); the first is the outer boundary."""
        refs = []
        for i, loop in enumerate(bounds):
            oriented = []
            for edge, forward in loop:
                self.uses[edge, forward] += 1
                oriented.append(self.add(f"ORIENTED_EDGE('',*,*,{edge},{'.T.' if forward else '.F.'})"))
            edge_loop = self.add(f"EDGE_LOOP('',({','.join(oriented)}))")
            refs.append(self.add(f"{'FACE_OUTER_BOUND' if i == 0 else 'FACE_BOUND'}('',{edge_loop},.T.)"))
        return self.add(f"ADVANCED_FACE('',({','.join(refs)}),{surface},{'.T.' if same_sense else '.F.'})")

    def plane(self, z, up):
        return self.add(f"PLANE('',{self.placement((0, 0, z), (0, 0, 1 if up else -1), (1, 0, 0))})")

    def flat_faces(self, pieces, faces, z, up):
        out = []
        for walks in faces:
            bounds = [[(self.piece_edge(pieces, s[1], z), s[2]) if s[0] == "piece" else self.cut_edge(s[1], s[2], z)
                       for s in walk] for walk in walks]
            out.append(self.face(bounds, self.plane(z, up)))
        return out

    def walls(self, loop, edge_pieces, pieces, z0, z1):
        """Upright faces along a loop that has material on its left, facing out of the material."""
        n = len(loop)
        upright = [self.line_edge((x, y, z0), (x, y, z1)) for x, y, _ in loop]
        faces = []
        for i, (x0, y0, b) in enumerate(loop):
            x1, y1, _ = loop[(i + 1) % n]
            ks = edge_pieces[i]
            bound = ([(self.piece_edge(pieces, k, z0), True) for k in ks] + [(upright[(i + 1) % n], True)]
                     + [(self.piece_edge(pieces, k, z1), False) for k in reversed(ks)] + [(upright[i], False)])
            if b:
                (cx, cy), r, _, _ = bulge_arc((x0, y0), (x1, y1), b)
                surface = self.add(f"CYLINDRICAL_SURFACE('',{self.placement((cx, cy, z0), (0, 0, 1), (1, 0, 0))},"
                                   f"{step_real(r)})")
                faces.append(self.face([bound], surface, same_sense=b > 0))  # outward = away from the axis
            else:
                length = math.hypot(x1 - x0, y1 - y0)
                dx, dy = (x1 - x0) / length, (y1 - y0) / length
                surface = self.add(f"PLANE('',{self.placement((x0, y0, z0), (dy, -dx, 0), (dx, dy, 0))})")
                faces.append(self.face([bound], surface))
        return faces


def step_solid(outer, channels, base, height, cuts):
    """The coaster's faces in a StepWriter; raises SplitFailed if the cutting lines can't be used."""
    top = base + height
    s = StepWriter()
    pieces, per_loop = [], []
    for loop in [outer] + channels:
        per_edge = []
        for edge in split_loop(loop, cuts):
            per_edge.append(list(range(len(pieces), len(pieces) + len(edge))))
            pieces += edge
        per_loop.append(per_edge)

    def steps(loop_index, forward):
        ks = [k for edge in per_loop[loop_index] for k in edge]
        return [(k, True) for k in ks] if forward else [(k, False) for k in reversed(ks)]

    top_steps = steps(0, True) + [st for i in range(1, len(per_loop)) for st in steps(i, True)]
    floor_steps = [st for i in range(1, len(per_loop)) for st in steps(i, False)]
    top_faces = group_faces(pieces, trace_faces(pieces, top_steps, cuts))
    floor_faces = group_faces(pieces, trace_faces(pieces, floor_steps, cuts))

    faces = [s.face([[(s.piece_edge(pieces, k, 0.0), False) for k, _ in steps(0, False)]], s.plane(0.0, up=False))]
    faces += s.walls(outer, per_loop[0], pieces, 0.0, top)
    for i, loop in enumerate(channels, start=1):
        faces += s.walls(loop, per_loop[i], pieces, base, top)
    faces += s.flat_faces(pieces, floor_faces, base, up=True)
    faces += s.flat_faces(pieces, top_faces, top, up=True)

    if any(s.uses[e, True] != 1 or s.uses[e, False] != 1 for e, _ in s.uses):
        raise SplitFailed
    return s, faces


def write_step(path: Path, name: str, outline: Outline, loops, base: float, height: float):
    """The coaster as an exact CAD solid: floor from z = 0 to base, walls up to base + height.

    Coordinates match the DXF (coaster centred on the origin). Raises CoasterError if the
    faces don't close up into one solid.
    """
    outer = oriented_loop(outline.loop, ccw=True)                     # material on its left
    channels = [oriented_loop(loop, ccw=False) for loop in loops]     # material (walls) on their left
    try:
        s, faces = step_solid(outer, channels, base, height, step_cuts([outer] + channels))
    except SplitFailed:
        try:  # whole faces: slower to open in CAD programs, but the same solid
            s, faces = step_solid(outer, channels, base, height, [])
        except SplitFailed:
            raise CoasterError("The STEP solid didn't close up, so it wasn't saved. Try another seed.") from None

    shell = s.add(f"CLOSED_SHELL('',({','.join(faces)}))")
    brep = s.add(f"MANIFOLD_SOLID_BREP({step_string(name)},{shell})")
    mm = s.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    rad = s.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sr = s.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    tol = s.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),{mm},'distance_accuracy_value',"
                "'confusion accuracy')")
    context = s.add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({tol})) "
                    f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{rad},{sr})) "
                    "REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")
    rep = s.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({step_string(name)},"
                f"({s.placement((0, 0, 0), (0, 0, 1), (1, 0, 0))},{brep}),{context})")
    app = s.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    s.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
    product_context = s.add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
    product = s.add(f"PRODUCT({step_string(name)},{step_string(name)},'',({product_context}))")
    s.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,({product}))")
    formation = s.add(f"PRODUCT_DEFINITION_FORMATION('','',{product})")
    definition_context = s.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
    definition = s.add(f"PRODUCT_DEFINITION('design','',{formation},{definition_context})")
    shape = s.add(f"PRODUCT_DEFINITION_SHAPE('','',{definition})")
    s.add(f"SHAPE_DEFINITION_REPRESENTATION({shape},{rep})")

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    lines = ["ISO-10303-21;", "HEADER;",
             f"FILE_DESCRIPTION(({step_string('Maze coaster ' + name)}),'2;1');",
             f"FILE_NAME({step_string(path.name)},'{stamp}',(''),(''),'Maze Coaster Maker','Maze Coaster Maker','');",
             "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));", "ENDSEC;", "DATA;"]
    lines += [f"#{i}={item};" for i, item in enumerate(s.items, start=1)]
    lines += ["ENDSEC;", "END-ISO-10303-21;", ""]
    path.write_text("\n".join(lines), encoding="ascii")


# ---------------------------------------------------------------- checks

def run_checks(outline_poly, play, channels, d: Design):
    polys = parts(channels)
    rg, rw = d.gap / 2 - 0.02, d.wall / 2 - 0.02
    eroded = channels.buffer(-rg)
    grown = channels.buffer(rw)
    walls = outline_poly.difference(channels)

    def worst_residue(geom, r):
        leftovers = parts(geom.difference(geom.buffer(-r).buffer(r)))
        return max((p.area for p in leftovers), default=0.0)

    sliver = max(worst_residue(channels, rg), worst_residue(walls, rw))
    return [
        ("inside rim", channels.difference(play.buffer(2 * EPS)).area < 1e-4),
        ("no holes", all(not p.interiors for p in polys)),
        (f"gaps >= {2 * rg:.2f} mm", len(parts(eroded)) == len(polys)),
        (f"walls >= {2 * rw:.2f} mm", len(parts(grown)) == len(polys) and all(not p.interiors for p in parts(grown))),
        (f"no thin slivers (worst {sliver:.2f} mm2)", sliver < 1.3 * max(rg, rw) ** 2),
    ]


# ---------------------------------------------------------------- driver

@dataclass
class Result:
    name: str
    outline: Outline
    loops: list               # channel loops as (x, y, bulge) polylines
    stats: dict
    checks: list              # (label, passed) pairs; empty when checks were skipped
    bounds: tuple             # outline bounding box, for the SVG view
    design: Design | None = None
    notes: list = field(default_factory=list)  # (level, text) with level "warning" or "note"
    paths: dict = field(default_factory=dict)  # format -> file, set by save()

    @property
    def files(self) -> list:
        return [self.paths[f] for f in FORMATS if f in self.paths]

    @property
    def ok(self) -> bool:
        return all(ok for _, ok in self.checks)

    def summary(self) -> str:
        info = ", ".join(f"{k} {v}" for k, v in self.stats.items())
        return f"{self.name}: {len(self.loops)} channel loop(s), {sum(map(len, self.loops))} curves, {info}"


def build(d: Design, checks=True) -> Result:
    """Make one coaster's geometry and run the checks. Nothing is written; see save()."""
    if d.seed is None:
        d = replace(d, seed=random.randrange(10000))
    if d.rim < d.wall:
        raise CoasterError("The solid border (rim) must be at least as thick as a wall.")
    name = d.name or d.default_name()
    outline = make_outline(d)
    outline_poly = outline.polygon()
    play = outline_poly.buffer(-d.rim)
    if d.pattern == "theta":
        channels, stats, smallest = theta_channels(play, d, random.Random(d.seed))
    else:
        channels, stats, smallest = classical_channels(play, d)

    loops = geometry_loops(channels)
    results = []
    if checks:
        results = run_checks(outline_poly, play, channels, d)
        results.append(("DXF audit", not make_dxf(outline, loops).audit().has_errors))
    return Result(name, outline, loops, stats, results, outline_poly.bounds,
                  design=d, notes=centre_notes(d, stats["centre_d"], smallest))


FORMATS = ("3mf", "stl", "step", "dxf", "svg")
DEFAULT_FORMATS = ("3mf", "dxf", "svg")
EXTENSIONS = {"step": "step"}  # file extension per format where it differs from the format name


def save(r: Result, out_dir: Path, formats=DEFAULT_FORMATS) -> Result:
    """Write r into out_dir in the given formats:
    3MF (3D print), STL (mesh), STEP (CAD solid), DXF (2D drawing), SVG (picture)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    r.paths = {}  # record only what this call writes
    d = r.design
    path = {f: out_dir / f"{r.name}.{EXTENSIONS.get(f, f)}" for f in FORMATS}
    if "3mf" in formats or "stl" in formats:  # first, so a failed model leaves nothing half-written
        verts, tris = make_mesh(r.outline, r.loops, d.base, d.height)
        if not mesh_is_closed(tris):
            raise CoasterError("The 3D model came out with a hole in it, so nothing was saved. Try another seed.")
        if "3mf" in formats:
            write_3mf(path["3mf"], r.name, verts, tris)
        if "stl" in formats:
            write_stl(path["stl"], r.name, verts, tris)
    if "step" in formats:
        write_step(path["step"], r.name, r.outline, r.loops, d.base, d.height)
    if "dxf" in formats:
        make_dxf(r.outline, r.loops).saveas(path["dxf"])
    if "svg" in formats:
        write_svg(path["svg"], r.outline, r.loops, r.bounds)
    r.paths = {f: path[f] for f in FORMATS if f in formats}
    return r


def generate(d: Design, out_dir: Path, checks=True, formats=DEFAULT_FORMATS) -> bool:
    r = save(build(d, checks), out_dir, formats)
    print(f"{r.summary()} -> {', '.join(p.name for p in r.files)}")
    if r.checks:
        print("   " + " | ".join(f"{'PASS' if ok else 'FAIL'} {label}" for label, ok in r.checks))
    for level, text in r.notes:
        print(f"   {level.upper()}: {text}")
    return r.ok


EXAMPLES = [
    Design(shape="circle", pattern="theta", seed=1),
    Design(shape="circle", pattern="theta", bias="ring", seed=2),
    Design(shape="circle", pattern="theta", algo="prim", seed=3),
    Design(shape="circle", pattern="classical"),
    Design(shape="hexagon", pattern="theta", seed=4),
    Design(shape="hexagon", pattern="classical"),
    Design(shape="octagon", pattern="theta", bias="radial", seed=5),
    Design(shape="rounded-square", pattern="theta", seed=6),
    Design(shape="flower", pattern="theta", seed=7),
    Design(shape="flower", petals=5, pattern="theta", bias="ring", seed=8),
]


def write_gallery(out_dir: Path):
    cards = []
    for svg in sorted(out_dir.glob("*.svg")):
        n = html.escape(svg.stem)
        cards.append(f'<figure><a href="{n}.svg"><img src="{n}.svg" alt="{n}"></a>'
                     f'<figcaption>{n} <a href="{n}.dxf">DXF</a></figcaption></figure>')
    (out_dir / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Maze Coasters</title>
<style>
:root {{ --bg: #faf8f4; --card: #ffffff; --text: #2b2420; --muted: #7a6e64; --line: #e4ddd2; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #1b1816; --card: #262220; --text: #eee7de; --muted: #a79c90; --line: #3a3430; }}
}}
body {{ margin: 0; padding: 24px 16px; background: var(--bg); color: var(--text);
       font: 15px/1.5 system-ui, sans-serif; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }}
p {{ color: var(--muted); margin: 0 0 20px; }}
main {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }}
figure {{ margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px; }}
img {{ width: 100%; height: auto; display: block; }}
figcaption {{ font-size: 13px; margin-top: 8px; word-break: break-all; }}
a {{ color: inherit; }}
</style></head><body>
<h1>Maze coasters</h1>
<p>{len(cards)} designs. Dark = 1 mm channels, light = walls and rim. Click a preview for full size.</p>
<main>
{chr(10).join(cards)}
</main>
</body></html>
""", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate circular-maze coasters for 3D printing and CAD.")
    ap.add_argument("--examples", action="store_true", help="write the starter set of designs")
    ap.add_argument("--shape", choices=SHAPES, default="circle")
    ap.add_argument("--outline", dest="outline_file", help="closed outline DXF in mm (replaces --shape)")
    ap.add_argument("--pattern", choices=("theta", "classical"), default="theta")
    ap.add_argument("--size", type=float, default=100.0, help="overall width in mm (default 100)")
    ap.add_argument("--rim", type=float, default=3.0, help="solid border in mm (default 3)")
    ap.add_argument("--wall", type=float, default=1.0, help="wall thickness in mm (default 1)")
    ap.add_argument("--gap", type=float, default=1.0, help="channel width in mm (default 1)")
    ap.add_argument("--base", type=float, default=2.0, help="solid floor thickness in mm (default 2)")
    ap.add_argument("--wall-height", dest="height", type=float, default=2.0,
                    help="wall height above the floor in mm (default 2)")
    ap.add_argument("--corner-r", type=float, help="corner radius for hexagon/octagon/rounded-square")
    ap.add_argument("--petals", type=int, default=6, help="petal count for flower (default 6)")
    ap.add_argument("--seed", type=int, help="random seed for theta mazes (default: random)")
    ap.add_argument("--algo", choices=("dfs", "prim"), default="dfs", help="dfs = long corridors, prim = bushy")
    ap.add_argument("--bias", choices=("none", "ring", "radial"), default="none",
                    help="prefer moves around the rings (spiral look) or outward (sunburst look)")
    ap.add_argument("--center", dest="center_d", type=float,
                    help="centre diameter in mm (default 6 for theta, 16 for classical); it can grow by up to "
                         "2 x (wall + gap) so the outer ring meets the border")
    ap.add_argument("--cell-length", type=float, help="theta minimum cell length in mm (bigger = coarser)")
    ap.add_argument("--name", help="output file name (without extension)")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--formats", default=",".join(DEFAULT_FORMATS),
                    help=f"files to write, comma-separated, from {','.join(FORMATS)} "
                         f"(default {','.join(DEFAULT_FORMATS)}); step opens as a solid in CAD programs")
    ap.add_argument("--skip-checks", action="store_true", help="skip the wall/gap checks (faster)")
    args = vars(ap.parse_args(argv))

    out_dir = Path(args.pop("out"))
    examples, checks = args.pop("examples"), not args.pop("skip_checks")
    formats = [f.strip().lower() for f in args.pop("formats").split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown or not formats:
        ap.error(f"--formats takes a comma-separated list from: {', '.join(FORMATS)}")
    designs = EXAMPLES if examples else [Design(**args)]
    try:
        ok = all([generate(d, out_dir, checks, formats) for d in designs])
    except CoasterError as e:
        raise SystemExit(str(e))
    if "svg" in formats:
        write_gallery(out_dir)
        print(f"gallery: {out_dir / 'index.html'}")
    if not ok:
        raise SystemExit("some checks FAILED")


if __name__ == "__main__":
    main()
