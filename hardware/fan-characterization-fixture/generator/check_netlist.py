"""Compare the netlist KiCad extracted from the schematic with the intended design.

    python3 check_netlist.py NETLIST.xml INTENT.json EXPECTED_NETS.txt

Fails unless all three connectivity views agree exactly, and unless every
configuration jumper carries its required Rev 0 default.
"""
import json
import sys
import xml.etree.ElementTree as ET

REQUIRED_DEFAULTS = {'JP1': 'OPEN', 'JP2': 'OPEN', 'JP3': 'OPEN', 'JP4': 'OPEN', 'JP5': 'FITTED'}


def from_kicad(path):
    root = ET.parse(path).getroot()
    nets = {n.get('name').lstrip('/'): {f"{x.get('ref')}.{x.get('pin')}" for x in n} for n in root.find('nets')}
    defaults = {}
    for comp in root.find('components'):
        for f in comp.iter('field'):
            if f.get('name') == 'Default':
                defaults[comp.get('ref')] = f.text
    return nets, defaults


def from_intent(path):
    nets = {}
    for c in json.load(open(path)):
        for pin, net in c['nets'].items():
            nets.setdefault(net, set()).add(f"{c['ref']}.{pin}")
    return nets


def from_expected(path):
    nets = {}
    for line in open(path):
        line = line.split('#', 1)[0].split()
        if line: nets[line[0]] = set(line[1:])
    return nets


def diff(name_a, a, name_b, b):
    bad = []
    for net in sorted(set(a) | set(b)):
        if a.get(net) != b.get(net):
            bad.append(f"  {net}: {name_a}={sorted(a.get(net, []))} {name_b}={sorted(b.get(net, []))}")
    return bad


def main(netlist, intent, expected):
    kicad, defaults = from_kicad(netlist)
    problems = diff('kicad', kicad, 'fixture.py', from_intent(intent)) + \
        diff('kicad', kicad, 'expected-nets.txt', from_expected(expected))
    for ref, want in REQUIRED_DEFAULTS.items():
        if defaults.get(ref) != want:
            problems.append(f"  {ref}: default {defaults.get(ref)!r}, required {want!r}")
    if problems:
        print('NETLIST CHECK FAILED')
        print('\n'.join(problems))
        return 1
    print(f"netlist check: {len(kicad)} nets match fixture.py and expected-nets.txt; "
          f"jumper defaults {', '.join(f'{k}={v}' for k, v in REQUIRED_DEFAULTS.items())}")
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:4]))
