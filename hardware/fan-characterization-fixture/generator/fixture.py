"""Design data for the DragonBench fan-characterization fixture, Rev 0.

This file is the schematic's source. build_schematic.py turns it into
fan-characterization-fixture.kicad_sch; verify.sh checks that the checked-in
schematic is exactly what this file produces. Edit here, never in eeschema.

Coordinates are millimetres on the A3 sheet, snapped to a 1.27 mm grid.
"""

PROJECT = 'fan-characterization-fixture'

TITLE_BLOCK = {
    'title': 'DragonBench fan-characterization fixture (BENCH ONLY)',
    'date': '2026-09-28',
    'rev': '0-draft',
    'company': 'thetechbenders / DragonBench',
    'comments': [
        'BENCH characterization hardware. NOT JumpJet production.',
        'DUT: San Ace 9GA0424P3J001 (24 V, 4-wire), drawing Rev C',
        'Rev 0: JP1-JP4 OPEN, JP5 fitted',
        'Specimen lead ID and configured PPR: UNVERIFIED',
    ],
}

TP_FP = 'TestPoint:TestPoint_Keystone_5000-5004_Miniature'
HDR2 = 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical'
R0805 = 'Resistor_SMD:R_0805_2012Metric'

COMPONENTS, WIRES, JUNCTIONS, LABELS, NOTES = [], [], [], [], []


def comp(ref, lib, sym, x, y, rot, value, fp, nets, status, function, dnp=False, default=None):
    COMPONENTS.append(dict(ref=ref, lib=lib, sym=sym, x=x, y=y, rot=rot, value=value, fp=fp, nets=nets,
                           status=status, function=function, dnp=dnp, default=default))


def W(net, *pts):
    """Wire polyline; points are 'REF.PIN' or (x, y). Every pin named must be on `net`."""
    WIRES.append((net, pts))


def J(x, y): JUNCTIONS.append((x, y))
def L(net, x, y, ang=0): LABELS.append((net, x, y, ang))
def note(x, y, *lines): NOTES.append(('\n'.join(lines), x, y))


def tp(ref, x, y, net):
    """Stand-alone test point with its own net label."""
    comp(ref, 'Connector', 'TestPoint', x, y, 0, net, TP_FP, {'1': net}, 'FINAL', f'Test point {net}')


def tpw(ref, x, y, net, bus_y):
    """Test point above (bus_y > y) or below a horizontal wire, tapped with a junction."""
    comp(ref, 'Connector', 'TestPoint', x, y, 0 if bus_y > y else 180, net, TP_FP, {'1': net}, 'FINAL', f'Test point {net}')
    W(net, f'{ref}.1', (x, bus_y)); J(x, bus_y)


BLOCKS = [
    (15.24, 20.32, 106.68, 124.46, '1. MCU / DragonBench interface'),
    (111.76, 20.32, 266.7, 124.46, '2. PWM open-drain driver'),
    (271.78, 20.32, 406.4, 124.46, '3. Tach input / conditioning'),
    (15.24, 132.08, 213.36, 248.92, '4. 24 V fan supply and ground topology'),
    (218.44, 132.08, 289.56, 248.92, '5. Fan connector'),
    (294.64, 132.08, 406.4, 248.92, '6. Test points / configuration jumpers'),
]

# ================= 1. MCU / DragonBench interface
comp('J1', 'Connector', 'Screw_Terminal_01x04', 45.72, 55.88, 0, 'MCU_IF',
     'TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal',
     {'1': 'MCU_PWM', '2': 'TACH_GPIO', '3': '3V3', '4': 'GND'}, 'PROVISIONAL',
     'Controller link. Pin 1 MCU_PWM (out), 2 TACH_GPIO (in), 3 3V3 from controller, 4 GND')
tp('TP1', 78.74, 50.8, '3V3')
tp('TP2', 93.98, 50.8, 'GND')
note(19.05, 78.74,
     'Controller-agnostic link. Board wiring is a LOCAL overlay.',
     'N8R8 bench overlay (provisional, NOT product GPIOs):',
     '  J1.1 MCU_PWM   <- GPIO6',
     '  J1.2 TACH_GPIO -> GPIO7',
     '  J1.3 3V3       <- board 3V3 (never 5V)',
     '  J1.4 GND       <- board GND',
     'sdkconfig.fan-characterization.local:',
     '  CONFIG_DB_FAN_PWM_GATE_GPIO=6',
     '  CONFIG_DB_FAN_GATE_SINK_LEVEL=1',
     '  CONFIG_DB_FAN_TACH_GPIO=7',
     'TinyS3[D]: same J1 functions, own overlay.',
     'Breakout is passive: no protection assumed.')

# ================= 2. PWM open-drain driver   (main line y = 50.8)
Y = 50.8
comp('JP1', 'Jumper', 'Jumper_2_Open', 129.54, Y, 0, 'GATE_EN', HDR2,
     {'1': 'MCU_PWM', '2': 'PWM_IN'}, 'FINAL', 'Open: controller disconnected from gate; PWM_IN free for a signal generator',
     default='OPEN')
comp('R1', 'Device', 'R', 152.4, Y, 90, '220R', R0805,
     {'1': 'PWM_IN', '2': 'PWM_GATE'}, 'PROVISIONAL', 'Gate series resistor')
comp('R2', 'Device', 'R', 167.64, 60.96, 0, '10k', R0805,
     {'1': 'PWM_GATE', '2': 'GND'}, 'PROVISIONAL', 'Gate pulldown: Q1 OFF whenever the gate is not actively driven high')
comp('Q1', 'Transistor_FET', 'Q_NMOS_GSD', 182.88, Y, 0, 'NTR4003NT1G', 'Package_TO_SOT_SMD:SOT-23',
     {'1': 'PWM_GATE', '2': 'GND', '3': 'PWM_DRAIN'}, 'PROVISIONAL',
     'Signal-interface open-drain sink for the fan control input; VDS <= 5.25 V, ID <= 2 mA in normal use')
comp('JP2', 'Jumper', 'Jumper_2_Open', 220.98, 38.1, 0, 'PWM_LINE_EN', HDR2,
     {'1': 'PWM_DRAIN', '2': 'FAN_PWM_RAW'}, 'FINAL', 'Open: fan PWM line carries no fixture load at all',
     default='OPEN')
W('PWM_IN', 'JP1.2', 'R1.1'); L('PWM_IN', 135.89, Y)
tpw('TP3', 144.78, 43.18, 'PWM_IN', Y)
W('PWM_GATE', 'R1.2', 'Q1.1'); L('PWM_GATE', 157.48, Y)
W('PWM_GATE', 'R2.1', (167.64, Y)); J(167.64, Y)
tpw('TP4', 172.72, 43.18, 'PWM_GATE', Y)
W('PWM_DRAIN', 'Q1.3', (185.42, 38.1), 'JP2.1'); L('PWM_DRAIN', 186.69, 38.1)
tpw('TP5', 208.28, 30.48, 'PWM_DRAIN', 38.1)
W('FAN_PWM_RAW', 'JP2.2', (243.84, 38.1)); L('FAN_PWM_RAW', 243.84, 38.1)
tpw('TP6', 233.68, 30.48, 'FAN_PWM_RAW', 38.1)
tp('TP7', 254.0, 60.96, 'GND')
note(116.84, 86.36,
     'Q1 non-inverting: gate HIGH = sink => CONFIG_DB_FAN_GATE_SINK_LEVEL=1. sink_duty_pct = Q1 on-time.',
     'Fan control input, 9GA0424P3J001 drawing Rev C: 25 kHz specified; open-collector/open-drain drive OK;',
     '   control open = same speed as 100 %; 0 % = stopped; open voltage <= 5.25 V; source <= 2 mA at 0 V; VIL <= 0.4 V.',
     'Q1 NTR4003NT1G is a signal-interface FET here: normal stress VDS <= 5.25 V, ID <= 2 mA.',
     '   Low level at 2 mA: 2 mA x 2.0 ohm (RDS(on) max, VGS 2.5 V) = 4 mV, << 0.4 V.',
     'R1 220R: gate charge current <= 3.3/220 = 15 mA peak; RC < 25 ns even at 100 pF, vs 20 us half-period.',
     '   Driven gate = VOH x 10k/10.22k = 3.23 V at 3.3 V (2.94 V at a 3.0 V rail): above the 2.5 V RDS(on) row.',
     'R2 10k: GPIO Hi-Z/reset/unpowered -> gate = IGSS x 10k (<= 0.1 V at 10 uA, assumed). GPIO6: no pull at reset.',
     'NOT rated for FAN_PWM_RAW landed on FAN_24V: verify lead identity before landing (BRINGUP step 2).',
     'No RC filter and no fixture pull-up on FAN_PWM_RAW. JP2 open = line fully released for open-line tests.')

# ================= 3. Tach input / conditioning
X0 = 294.64
W('FAN_TACH_RAW', (276.86, 55.88), (X0, 55.88)); L('FAN_TACH_RAW', 276.86, 55.88)
W('FAN_TACH_RAW', (X0, 43.18), (X0, 68.58)); J(X0, 55.88)
comp('JP3', 'Jumper', 'Jumper_2_Open', 304.8, 43.18, 0, 'TACH_PU_EN', HDR2,
     {'1': 'FAN_TACH_RAW', '2': 'TACH_PU'}, 'FINAL', 'Closed: R3 pulls raw tach to 3V3', default='OPEN')
comp('R3', 'Device', 'R', 326.39, 43.18, 90, '10k', R0805,
     {'1': 'TACH_PU', '2': '3V3'}, 'PROVISIONAL', 'External tach pull-up to 3V3 (0.33 mA vs 5 mA IC max)')
comp('JP4', 'Jumper', 'Jumper_2_Open', 304.8, 68.58, 0, 'TACH_GPIO_EN', HDR2,
     {'1': 'FAN_TACH_RAW', '2': 'TACH_SER'}, 'FINAL', 'Open: raw tach isolated from R4/D1/R5 and the GPIO', default='OPEN')
comp('R4', 'Device', 'R', 326.39, 68.58, 90, '22k', R0805,
     {'1': 'TACH_SER', '2': 'TACH_GPIO'}, 'PROVISIONAL', 'Series protection: limits clamp/back-power current to ~1.2 mA at 26.4 V')
W('FAN_TACH_RAW', (X0, 43.18), 'JP3.1'); W('FAN_TACH_RAW', (X0, 68.58), 'JP4.1')
tpw('TP8', 287.02, 63.5, 'FAN_TACH_RAW', 55.88)
W('TACH_PU', 'JP3.2', 'R3.1'); L('TACH_PU', 311.15, 43.18)
W('TACH_SER', 'JP4.2', 'R4.1'); L('TACH_SER', 311.15, 68.58)
YT = 68.58
W('TACH_GPIO', 'R4.2', (391.16, YT)); L('TACH_GPIO', 391.16, YT)
comp('R5', 'Device', 'R', 340.36, 78.74, 0, '470k', R0805,
     {'1': 'TACH_GPIO', '2': 'GND'}, 'PROVISIONAL', 'Holds TACH_GPIO low when JP4 is open')
W('TACH_GPIO', 'R5.1', (340.36, YT)); J(340.36, YT)
comp('D1', 'Diode', 'BAT54S', 358.14, 60.96, 0, 'BAT54S', 'Package_TO_SOT_SMD:SOT-23',
     {'1': 'GND', '2': '3V3', '3': 'TACH_GPIO'}, 'PROVISIONAL', 'Schottky clamp of TACH_GPIO to GND and 3V3')
W('TACH_GPIO', 'D1.3', (358.14, YT)); J(358.14, YT)
comp('C2', 'Device', 'C', 375.92, 78.74, 0, 'DNP', 'Capacitor_SMD:C_0805_2012Metric',
     {'1': 'TACH_GPIO', '2': 'GND'}, 'DNP/TBD', 'Footprint only for a later glitch filter; value from scope data', dnp=True)
W('TACH_GPIO', 'C2.1', (375.92, YT)); J(375.92, YT)
tpw('TP9', 386.08, 60.96, 'TACH_GPIO', YT)
tp('TP10', 386.08, 91.44, '3V3')
tp('TP11', 398.78, 91.44, 'GND')
note(275.59, 86.36,
     'Sensor, Sanyo spec 9D0001H202: open collector,',
     '   VCE <= 27.6 V, IC <= 5 mA, VCE(sat) <= 0.8 V.',
     '   Spec suggests 2 pulses/rev; configured PPR stays 0',
     '   (unknown) until an optical RPM check on the specimen.',
     'Default JP3 OPEN, JP4 OPEN: raw tach sees only TP8.',
     'JP3: R3 10k to 3V3 -> 0.33 mA sink (IC max 5 mA).',
     'JP4: R4 22k, D1 clamp, R5 470k. High ~3.09 V (VIH',
     '   2.475 V); low <= 0.76 V at VCE(sat) 0.8 V (VIL 0.825 V).',
     'Back-power if the tach lead is faulted to 26.4 V:',
     '   R4/D1 <= 1.2 mA, R3 (JP3) <= 2.7 mA into 3V3.',
     'RULE: controller 3V3 ON before JP3/JP4 close and',
     '   before fan power; off only after fan power is off.',
     'C2 DNP (no glitch filter). Internal pull-up stays OFF.')

# ================= 4. 24 V fan supply and ground topology   (main line y = 154.94)
YP = 154.94
comp('J2', 'Connector', 'Screw_Terminal_01x02', 43.18, 157.48, 0, 'BENCH_PSU',
     'TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal',
     {'1': 'BENCH_24V', '2': 'BENCH_GND'}, 'PROVISIONAL', 'Current-limited 24 V bench supply. Pin 1 BENCH_24V, pin 2 BENCH_GND')
W('BENCH_24V', (50.8, YP), 'F1.1'); L('BENCH_24V', 50.8, YP)
comp('F1', 'Device', 'Fuse', 76.2, YP, 90, 'Fuse TBD',
     'Fuse:Fuseholder_Clip-5x20mm_Littelfuse_111_Inline_P20.00x5.00mm_D1.05mm_Horizontal',
     {'1': 'BENCH_24V', '2': '24V_FUSED'}, 'DNP/TBD', '5x20 mm holder; element rating TBD until startup/locked-rotor current is measured')
tpw('TP12', 66.04, 147.32, 'BENCH_24V', YP)
comp('JP5', 'Jumper', 'Jumper_2_Bridged', 111.76, YP, 0, 'I_MEAS', HDR2,
     {'1': '24V_FUSED', '2': 'FAN_24V'}, 'PROVISIONAL', 'Link fitted, or remove and insert a series ammeter', default='FITTED')
W('24V_FUSED', 'F1.2', 'JP5.1'); L('24V_FUSED', 81.28, YP)
comp('R6', 'Device', 'R', 99.06, 165.1, 0, '10k', R0805,
     {'1': '24V_FUSED', '2': 'LED_A'}, 'PROVISIONAL', 'LED current limit')
W('24V_FUSED', 'R6.1', (99.06, YP)); J(99.06, YP)
comp('D2', 'Device', 'LED', 99.06, 180.34, 90, 'LED green', 'LED_SMD:LED_0805_2012Metric',
     {'2': 'LED_A', '1': 'BENCH_GND'}, 'PROVISIONAL', '24 V present (upstream of I_MEAS)')
W('LED_A', 'R6.2', 'D2.2'); L('LED_A', 99.06, 172.72)
W('FAN_24V', 'JP5.2', (152.4, YP)); L('FAN_24V', 152.4, YP)
tpw('TP13', 124.46, 147.32, 'FAN_24V', YP)
comp('C1', 'Device', 'C_Polarized', 137.16, 165.1, 0, 'DNP', 'Capacitor_THT:CP_Radial_D6.3mm_P2.50mm',
     {'1': 'FAN_24V', '2': 'FAN_GND'}, 'DNP/TBD', 'Optional bulk capacitor at the fan terminal; fitted only for a measured need', dnp=True)
W('FAN_24V', 'C1.1', (137.16, YP)); J(137.16, YP)
tp('TP14', 165.1, 165.1, 'FAN_GND')
XS = 43.18
W('BENCH_GND', (30.48, 205.74), (XS, 205.74)); L('BENCH_GND', 30.48, 205.74)
W('BENCH_GND', (XS, 198.12), (XS, 213.36)); J(XS, 205.74)
comp('NT1', 'Device', 'NetTie_2', 53.34, 198.12, 0, 'NetTie', 'NetTie:NetTie-2_SMD_Pad2.0mm',
     {'1': 'BENCH_GND', '2': 'FAN_GND'}, 'FINAL', 'Star point: fan power-return branch')
comp('NT2', 'Device', 'NetTie_2', 53.34, 213.36, 0, 'NetTie', 'NetTie:NetTie-2_SMD_Pad0.5mm',
     {'1': 'BENCH_GND', '2': 'GND'}, 'FINAL', 'Star point: signal/controller reference branch')
W('BENCH_GND', (XS, 198.12), 'NT1.1'); W('BENCH_GND', (XS, 213.36), 'NT2.1')
note(19.05, 226.06,
     'Ground topology: single star point at J2.2 through NT1/NT2.',
     '  FAN_GND: fan supply return only. GND: Q1 source, tach clamp/pulldowns, J1.4, scope ground.',
     '  Fan motor current never flows in GND; the <= 2 mA PWM and tach currents return through the star.',
     '  Controller USB ground meets the PSU negative ONLY here: use a floating PSU output.',
     'F1: 5x20 holder; rating TBD until startup/locked-rotor current is measured. The bench PSU current',
     '  limit is the first protection during characterization (holder may carry a labelled 0R link).',
     'JP5 I_MEAS: remove link to insert an ammeter. D2/R6 (~2.2 mA) sit upstream of JP5.',
     'No reverse-polarity element: confirm polarity at TP12 before landing the fan. C1 DNP.')

# ================= 5. Fan connector
comp('J3', 'Connector', 'Screw_Terminal_01x04', 251.46, 157.48, 0, 'FAN_DUT',
     'TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal',
     {'1': 'FAN_24V', '2': 'FAN_GND', '3': 'FAN_PWM_RAW', '4': 'FAN_TACH_RAW'}, 'PROVISIONAL',
     'Fixture-side terminal, one lead per position by VERIFIED function; the DUT lead order/colours are not assumed')
note(222.25, 187.96,
     'J3 positions are fixture functions,',
     "not the fan's physical wire order.",
     'Land each lead only after it is',
     'identified on the specimen by',
     'photo + continuity + manufacturer',
     'documentation.',
     'Catalog convention / not yet',
     'verified on specimen:',
     '  red +, black -, brown PWM,',
     '  yellow sensor.')

# ================= 6. Test points / configuration jumpers
note(298.45, 140.97,
     'Jumpers (Rev 0 shipping state)',
     'JP1  GATE_EN        OPEN     MCU_PWM -> R1/Q1 gate',
     'JP2  PWM_LINE_EN    OPEN     Q1 drain -> FAN_PWM_RAW',
     'JP3  TACH_PU_EN     OPEN     R3 3V3 pull-up on raw tach',
     'JP4  TACH_GPIO_EN   OPEN     raw tach -> R4/D1/R5 -> GPIO',
     'JP5  I_MEAS         FITTED   24V_FUSED -> FAN_24V',
     '',
     'Test points',
     'TP12 BENCH_24V   TP13 FAN_24V   TP14 FAN_GND',
     'TP1, TP10 3V3    TP2, TP7, TP11 GND',
     'TP3 PWM_IN (signal-generator injection with JP1 open)',
     'TP4 PWM_GATE     TP5 PWM_DRAIN  TP6 FAN_PWM_RAW',
     'TP8 FAN_TACH_RAW TP9 TACH_GPIO',
     '',
     '25 kHz is the manufacturer-specified control frequency',
     'for 9GA0424P3J001; bench characterization still',
     'verifies specimen behaviour. Configured PPR = 0 (unknown).',
     'Not defined here: JumpJet GPIOs, thresholds, startup',
     'duty, stall limits, fan-safety policy.')
