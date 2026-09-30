#!/usr/bin/env bash
# Regenerate and verify the fan-characterization fixture schematic.
#
#   ./verify.sh            check: the checked-in .kicad_sch/.kicad_pro are exactly what
#                          generator/ produces, ERC is clean, and the extracted netlist
#                          matches generator/fixture.py and generator/expected-nets.txt
#   ./verify.sh --update   regenerate .kicad_sch, .kicad_pro, .pdf and .svg in place,
#                          then run the same checks
#
# Everything runs inside one pinned KiCad 9 image, so the generator reads the same
# symbol libraries that ERC checks against. ERC report and netlist go to a temporary
# directory (printed at the end); they are validation output, not source.
set -euo pipefail

IMAGE="kicad/kicad:9.0@sha256:e638b79b0321f29395a5b783e94bb9f3c73303e8da15da27b8f5cb4b67a37729"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME=fan-characterization-fixture
MODE=check
case "${1:-}" in
  "") ;;
  --update) MODE=update ;;
  *) echo "usage: $0 [--update]" >&2; exit 2 ;;
esac
# Private to this user (mktemp's 0700); the container runs as the same uid, so it can write here.
OUT="$(mktemp -d "${TMPDIR:-/tmp}/fixture-verify.XXXXXX")"
# Check mode only reads the fixture; --update copies regenerated files back into it.
FIXTURE_MOUNT="$HERE:/fixture:ro"
[ "$MODE" = update ] && FIXTURE_MOUNT="$HERE:/fixture"

docker run --rm --network none -u "$(id -u):$(id -g)" \
  -v "$FIXTURE_MOUNT" -v "$OUT:/out" -e MODE="$MODE" -e NAME="$NAME" \
  "$IMAGE" bash -euo pipefail -c '
    # kicad-cli needs the image'\''s global library tables; give any uid a writable HOME with them.
    export HOME=/tmp/home && mkdir -p $HOME/.config/kicad/9.0
    cp /home/kicad/.config/kicad/9.0/*-lib-table $HOME/.config/kicad/9.0/
    kicad-cli version | sed "s/^/kicad-cli /"
    mkdir -p /out/gen
    cd /fixture/generator && PYTHONDONTWRITEBYTECODE=1 python3 build_schematic.py /out/gen
    if [ "$MODE" = update ]; then
      cp /out/gen/$NAME.kicad_sch /out/gen/$NAME.kicad_pro /fixture/
    else
      for f in $NAME.kicad_sch $NAME.kicad_pro; do
        cmp -s /out/gen/$f /fixture/$f || { echo "STALE: $f differs from generator output (run ./verify.sh --update)"; exit 1; }
      done
      echo "generator: checked-in $NAME.kicad_sch and $NAME.kicad_pro reproduce byte for byte"
    fi
    cd /fixture
    kicad-cli sch erc --severity-all --format report -o /out/erc.rpt $NAME.kicad_sch >/dev/null
    grep "ERC messages" /out/erc.rpt | sed "s/^ *\*\* /ERC: /"
    grep -q "ERC messages: 0  Errors 0  Warnings 0" /out/erc.rpt || { cat /out/erc.rpt; exit 1; }
    kicad-cli sch export netlist --format kicadxml -o /out/netlist.xml $NAME.kicad_sch >/dev/null
    python3 /fixture/generator/check_netlist.py /out/netlist.xml /out/gen/intent.json /fixture/generator/expected-nets.txt
    kicad-cli sch export pdf -o /out/$NAME.pdf $NAME.kicad_sch >/dev/null
    kicad-cli sch export svg -o /out $NAME.kicad_sch >/dev/null
    if [ "$MODE" = update ]; then cp /out/$NAME.pdf /out/$NAME.svg /fixture/; echo "updated: .kicad_sch .kicad_pro .pdf .svg"; fi
  '
echo "validation output: $OUT (erc.rpt, netlist.xml, $NAME.pdf, $NAME.svg)"
