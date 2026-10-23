#!/usr/bin/env bash
# Firewall the three AO input files before any agent reads them.
# Usage: scripts/ao/ao_firewall.sh <dir with ao_*.md> <model folder with brief/>
#  1. A8 question-leakage gate (the deploy gate's own script): each file is wrapped
#     as one YAML description so the gate's 6-gram check reads all of its text.
#  2. Withheld-KB check: every KB name in brief/deleted_ids.txt, grepped (case-
#     insensitive) in each file. Hits are printed; Opus deletes them and logs it.
# Exit 0 only when the gate passes and there are no withheld-KB hits.
set -uo pipefail
export PYENV_VERSION=system
AO_DIR="${1:?ao dir}"; MODEL="${2:?model folder}"
GATE="$HOME/go/src/github.com/diannewood/bird-models-v12/utilities/question_leakage_gate.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
rc=0

echo "=== A8 gate over ao_*.md ==="
for f in "$AO_DIR"/ao_*.md; do
  python3 -c 'import sys,yaml; print(yaml.safe_dump({"description": open(sys.argv[1]).read()}))' "$f" > "$TMP/$(basename "$f" .md).yml"
done
python3 "$GATE" --model-dir "$TMP" --brief "$MODEL/brief/task_brief.json" || rc=1

echo "=== withheld-KB names in ao_*.md ==="
python3 - "$AO_DIR" "$MODEL" <<'PY' || rc=1
import json, re, sys
from pathlib import Path
ao, model = Path(sys.argv[1]), Path(sys.argv[2])
ids = set()
for line in (model / "brief/deleted_ids.txt").read_text().splitlines():
    if line.startswith("#"):
        continue
    ids.update(int(x) for x in line.split()[1:])
names = {}
for line in (model / "brief/kb.jsonl").read_text().splitlines():
    kb = json.loads(line)
    if kb["id"] in ids:
        names[kb["id"]] = kb["knowledge"]
hits = 0
for f in sorted(ao.glob("ao_*.md")):
    text = f.read_text().lower()
    for i, n in sorted(names.items()):
        if n.lower() in text:
            hits += 1
            for ln, row in enumerate(f.read_text().splitlines(), 1):
                if n.lower() in row.lower():
                    print(f"HIT kb {i} '{n}': {f.name}:{ln}: {row[:160]}")
print(f"withheld KB ids: {len(names)}; hits: {hits}")
sys.exit(1 if hits else 0)
PY
echo "firewall rc=$rc"; exit $rc
