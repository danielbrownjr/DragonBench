"""Minimal S-expression reader/writer for KiCad library and schematic files."""
import os, re

# KiCad 9 symbol libraries; verify.sh runs this inside the pinned kicad/kicad:9.0 image.
SYMBOL_DIR = os.environ.get('KICAD_SYMBOL_DIR', '/usr/share/kicad/symbols')
TOK = re.compile(r'\s*(?:(\()|(\))|("(?:[^"\\]|\\.)*")|([^\s()"]+))')
class Sym(str):
    """A bare atom (keyword, number, flag). dump() writes it unquoted; a plain str is quoted."""
ESC = re.compile(r'\\(.)', re.S)
UNESC = {'\\': '\\', '"': '"', 'n': '\n'}
def unq(s):
    """Decode the body of a quoted string in one pass, reversing exactly what q() escapes.

    \\\\, \\" and \\n become a backslash, a quote and a newline. Any other escape,
    such as \\x, is kept as written, so text parse() cannot interpret survives unchanged.
    """
    return ESC.sub(lambda m: UNESC.get(m.group(1), m.group(0)), s)
def parse(text):
    """Parse KiCad S-expression text into nested lists; returns the list of top-level forms.

    Only the subset KiCad writes: parentheses, double-quoted strings (decoded by unq())
    and bare atoms. Atoms, numbers included, stay Sym strings, so parse -> dump
    reproduces every token, provided strings use only the escapes q() writes (an
    unknown escape such as \\x is kept by parse but dumped as \\\\x). Whitespace
    and line layout are dump()'s own.
    There is no error reporting: the input is trusted KiCad output, and parsing just
    stops at the first text that is not a token.
    """
    pos = 0; stack = [[]]
    while True:
        m = TOK.match(text, pos)
        if not m or m.end() == pos: break
        pos = m.end()
        if m.group(1): stack.append([])
        elif m.group(2):
            l = stack.pop(); stack[-1].append(l)
        elif m.group(3): stack[-1].append(unq(m.group(3)[1:-1]))
        else: stack[-1].append(Sym(m.group(4)))
    return stack[0]
def q(s):
    """Quote a str for KiCad. Escapes only backslash, quote and newline; unq() reverses it."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'
def dump(x, ind=0):
    """Serialise a parse()/build tree: Sym bare, str via q(), int/float via fmt().

    A list goes on one line if that is under 100 characters, otherwise one child
    per line indented two spaces per level, the layout the checked-in schematic uses.
    """
    if isinstance(x, list):
        inner = [dump(e, ind + 1) for e in x]
        one = '(' + ' '.join(inner) + ')'
        if len(one) < 100 and '\n' not in one: return one
        return '(' + inner[0] + ''.join('\n' + '  ' * (ind + 1) + i for i in inner[1:]) + ')'
    if isinstance(x, Sym): return str(x)
    if isinstance(x, (int, float)): return fmt(x)
    return q(x)
def fmt(v):
    """Format a number: floats to at most 4 decimals with trailing zeros and "-0" removed."""
    if isinstance(v, float):
        s = ('%.4f' % v).rstrip('0').rstrip('.')
        return '0' if s in ('-0', '') else s
    return str(v)
def find(lst, head):
    return [e for e in lst if isinstance(e, list) and e and e[0] == head]
_libcache = {}
def libsym(lib, name):
    """Return symbol NAME from LIB.kicad_sym in SYMBOL_DIR, as written in the library.

    Each library file is parsed once and cached. Raises KeyError if the library has no
    such symbol. A derived symbol still carries (extends ...); use flat() to embed it.
    """
    if lib not in _libcache:
        _libcache[lib] = parse(open(os.path.join(SYMBOL_DIR, f'{lib}.kicad_sym')).read())[0]
    for s in find(_libcache[lib], 'symbol'):
        if s[1] == name: return s
    raise KeyError(name)
def pins(sym):
    """List every pin in SYM and its unit sub-symbols, in library coordinates.

    Each is a dict: num, name, x, y, rot (degrees, 0 if omitted) and the electrical
    type. Pass flat()'s result for a derived symbol; libsym() alone has no pins for it.
    """
    out = []
    def walk(n):
        for e in n:
            if isinstance(e, list) and e and e[0] == 'pin':
                at = find(e, 'at')[0]; num = find(e, 'number')[0][1]; nm = find(e, 'name')[0][1]
                out.append(dict(num=num, name=nm, x=float(at[1]), y=float(at[2]), rot=float(at[3]) if len(at) > 3 else 0.0, type=str(e[1])))
            elif isinstance(e, list): walk(e)
    walk(sym); return out
def flat(lib, name):
    """Return LIB:NAME with (extends ...) resolved, as eeschema embeds a derived symbol.

    The result is the parent's body under the child's name: the child's properties
    replace same-named parent ones, child-only properties follow the parent's, and unit
    sub-symbols are renamed from the parent's prefix to NAME. Chains resolve recursively.
    """
    s = libsym(lib, name)
    ext = find(s, 'extends')
    if not ext: return s
    parent = flat(lib, ext[0][1])
    out = [s[0], name]
    child_props = {p[1]: p for p in find(s, 'property')}
    for e in parent[2:]:
        if isinstance(e, list) and e and e[0] == 'property':
            out.append(child_props.pop(e[1], e))
        elif isinstance(e, list) and e and e[0] == 'symbol':
            sub = list(e); sub[1] = name + sub[1][len(parent[1]):]; out.append(sub)
        else:
            out.append(e)
    # Child-only properties go after the parent's, before the unit bodies.
    idx = max(i for i, e in enumerate(out) if isinstance(e, list) and e and e[0] == 'property') + 1
    out[idx:idx] = list(child_props.values())
    return out
