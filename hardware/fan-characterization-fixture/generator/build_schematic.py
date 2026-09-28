"""Generate the fixture's KiCad 9 schematic and project file from fixture.py.

    python3 build_schematic.py OUT_DIR

writes OUT_DIR/fan-characterization-fixture.kicad_sch, .kicad_pro, and
intent.json (the per-pin net assignment check_netlist.py compares against).
Output is deterministic: UUIDs derive from content, so an unchanged
fixture.py reproduces the checked-in files byte for byte. Symbols are
embedded from the KiCad 9 libraries in KICAD_SYMBOL_DIR.
"""
import json
import math
import os
import sys
import uuid

import sexp
from sexp import Sym as S, dump, pins
import fixture as F

NS = uuid.UUID('6f1a3c52-7d0e-4c1b-9a51-0d4a2b7e9c11')


def U(*k): return str(uuid.uuid5(NS, '/'.join(map(str, k))))


ROOT = U('root')
STUB = 2.54
C = F.COMPONENTS


def rot(px, py, a):
    r = math.radians(a)
    return (px * math.cos(r) - py * math.sin(r), px * math.sin(r) + py * math.cos(r))


def g(v): return round(round(v / 1.27) * 1.27, 4)


items = []


def wire(x1, y1, x2, y2):
    items.append([S('wire'), [S('pts'), [S('xy'), x1, y1], [S('xy'), x2, y2]],
                  [S('stroke'), [S('width'), 0], [S('type'), S('default')]], [S('uuid'), U('w', x1, y1, x2, y2)]])


def label(name, x, y, ang):
    just = [S('left'), S('bottom')] if ang in (0, 90) else [S('right'), S('bottom')]
    items.append([S('label'), name, [S('at'), x, y, ang], [S('fields_autoplaced')],
                  [S('effects'), [S('font'), [S('size'), 1.27, 1.27]], [S('justify')] + just], [S('uuid'), U('l', name, x, y)]])


def text(t, x, y, size=1.27, bold=False):
    font = [S('font'), [S('size'), size, size]] + ([S('bold')] if bold else [])
    items.append([S('text'), t, [S('at'), x, y, 0], [S('effects'), font, [S('justify'), S('left'), S('top')]],
                  [S('uuid'), U('t', t[:40], x, y)]])


def rect(x1, y1, x2, y2, title):
    items.append([S('rectangle'), [S('start'), x1, y1], [S('end'), x2, y2],
                  [S('stroke'), [S('width'), 0.254], [S('type'), S('dash')]], [S('fill'), [S('type'), S('none')]],
                  [S('uuid'), U('r', title)]])
    text(title, x1 + 1.27, y1 + 1.27, 1.8, True)


def prop(name, val, x, y, hide=False, just=None, ang=0):
    eff = [S('effects'), [S('font'), [S('size'), 1.27, 1.27]]]
    if just: eff.append([S('justify')] + [S(j) for j in just])
    if hide: eff.append(S('hide'))
    return [S('property'), name, val, [S('at'), x, y, ang], eff]


def field_positions(c):
    """Reference/Value placement per symbol kind: (ref xy, value xy, justify)."""
    x, y, r, kind = c['x'], c['y'], c['rot'], c['sym']
    if kind in ('R', 'C', 'C_Polarized', 'Fuse'):
        if r == 90: return (x, y - 2.54), (x, y + 2.54), None
        return (x + 2.54, y - 1.27), (x + 2.54, y + 1.27), ['left']
    if kind.startswith('Jumper'): return (x, y - 5.08), (x, y + 3.81), None
    if kind == 'TestPoint' and r == 180: return (x + 3.175, y + 4.445), (x, y), None
    if kind == 'TestPoint': return (x + 1.27, y - 3.175), (x, y), ['left']
    if kind.startswith('Screw'): return (x - 2.54, y - 6.35), (x - 2.54, y + (11.43 if '04' in kind else 6.35)), ['left']
    if c['ref'].startswith('Q'): return (x + 5.08, y - 1.27), (x + 5.08, y + 1.27), ['left']
    if kind == 'BAT54S': return (x, y - 7.62), (x, y - 5.08), None
    if kind == 'NetTie_2': return (x, y - 2.54), (x, y + 2.54), None
    if kind == 'LED' and r == 90: return (x + 6.35, y - 1.27), (x + 7.62, y + 1.27), None
    raise SystemExit(f"no field placement for {c['ref']} ({kind})")


def build(out_dir):
    libs, pinpos = {}, {}
    wired = {p for _, pts in F.WIRES for p in pts if isinstance(p, str)}
    for c in C:
        key = f"{c['lib']}:{c['sym']}"
        ls = sexp.flat(c['lib'], c['sym'])
        libs[key] = ls
        if sorted(p['num'] for p in pins(ls)) != sorted(c['nets']):
            raise SystemExit(f"{c['ref']}: pin/net mismatch")
        for p in pins(ls):
            rx, ry = rot(p['x'], p['y'], c['rot'])
            px, py = g(c['x'] + rx), g(c['y'] - ry)
            name = f"{c['ref']}.{p['num']}"
            pinpos[name] = (px, py)
            if name in wired: continue
            # Unwired pin: short stub pointing away from the body, ending in a net label.
            ox, oy = rot(1, 0, p['rot'] + 180 + c['rot'])
            dx, dy = round(ox), -round(oy)
            ex, ey = px + dx * STUB, py + dy * STUB
            wire(px, py, ex, ey)
            label(c['nets'][p['num']], ex, ey, {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)])

    junctions = [(g(x), g(y)) for x, y in F.JUNCTIONS]
    for net, pts in F.WIRES:
        for p in pts:
            if isinstance(p, str):
                ref, num = p.split('.')
                want = next(c for c in C if c['ref'] == ref)['nets'][num]
                if want != net: raise SystemExit(f"wire {net} touches {p} ({want})")
        xy = [pinpos[p] if isinstance(p, str) else (g(p[0]), g(p[1])) for p in pts]
        for a, b in zip(xy, xy[1:]):
            if a[0] != b[0] and a[1] != b[1]: raise SystemExit(f"diagonal wire in {net}: {a}->{b}")
            # eeschema does not split a segment at a junction on load: cut it here so every
            # tap is a real segment endpoint.
            cuts = sorted({q for q in junctions if q not in (a, b) and
                           min(a[0], b[0]) <= q[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= q[1] <= max(a[1], b[1])},
                          key=lambda q: abs(q[0] - a[0]) + abs(q[1] - a[1]))
            for u, v in zip([a] + cuts, cuts + [b]):
                wire(u[0], u[1], v[0], v[1])
    for x, y in junctions:
        items.append([S('junction'), [S('at'), x, y], [S('diameter'), 0], [S('color'), 0, 0, 0, 0], [S('uuid'), U('j', x, y)]])
    for net, x, y, a in F.LABELS:
        label(net, g(x), g(y), a)
    for block in F.BLOCKS:
        rect(*block)
    for t, x, y in F.NOTES:
        text(t, x, y)

    syms = []
    for c in C:
        x, y, r, kind = c['x'], c['y'], c['rot'], c['sym']
        rp, vp, j = field_positions(c)
        fang = r if r in (90, 270) else 0
        s = [S('symbol'), [S('lib_id'), f"{c['lib']}:{kind}"], [S('at'), x, y, r], [S('unit'), 1],
             [S('in_bom'), S('no') if kind == 'NetTie_2' else S('yes')], [S('on_board'), S('yes')],
             [S('dnp'), S('yes') if c['dnp'] else S('no')], [S('uuid'), U('s', c['ref'])],
             prop('Reference', c['ref'], *rp, just=j, ang=fang),
             prop('Value', c['value'], *vp, just=j, ang=fang, hide=kind == 'TestPoint'),
             prop('Footprint', c['fp'], x, y, hide=True), prop('Datasheet', '~', x, y, hide=True),
             prop('Status', c['status'], x, y, hide=True), prop('Function', c['function'], x, y, hide=True)]
        if c['default']:
            s.append(prop('Default', c['default'], x, y, hide=True))
        for p in pins(libs[f"{c['lib']}:{kind}"]):
            s.append([S('pin'), p['num'], [S('uuid'), U('p', c['ref'], p['num'])]])
        s.append([S('instances'), [S('project'), F.PROJECT, [S('path'), '/' + ROOT, [S('reference'), c['ref']], [S('unit'), 1]]]])
        syms.append(s)

    tb = F.TITLE_BLOCK
    lib_symbols = [S('lib_symbols')] + [[v[0], k] + list(v[2:]) for k, v in libs.items()]
    doc = [S('kicad_sch'), [S('version'), 20250114], [S('generator'), 'eeschema'], [S('generator_version'), '9.0'],
           [S('uuid'), ROOT], [S('paper'), 'A3'],
           [S('title_block'), [S('title'), tb['title']], [S('date'), tb['date']], [S('rev'), tb['rev']],
            [S('company'), tb['company']]] + [[S('comment'), i + 1, t] for i, t in enumerate(tb['comments'])],
           lib_symbols] + items + syms + [[S('sheet_instances'), [S('path'), '/', [S('page'), '1']]]]

    base = os.path.join(out_dir, F.PROJECT)
    with open(base + '.kicad_sch', 'w') as f:
        f.write(dump(doc) + '\n')
    with open(base + '.kicad_pro', 'w') as f:
        json.dump({'meta': {'filename': F.PROJECT + '.kicad_pro', 'version': 1},
                   'schematic': {'legacy_lib_dir': '', 'legacy_lib_list': []},
                   'sheets': [[ROOT, '']]}, f, indent=2)
        f.write('\n')
    with open(os.path.join(out_dir, 'intent.json'), 'w') as f:
        json.dump([dict(ref=c['ref'], nets=c['nets'], default=c['default']) for c in C], f, indent=1)


if __name__ == '__main__':
    build(sys.argv[1])
