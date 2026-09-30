#!/usr/bin/env bash
# Prove every marked section of the B2 packet is byte-identical to its v12.md lines.
# Usage: scripts/b2_packet_check.sh [packet] [v12.md]
set -euo pipefail
P=${1:-results/b2_arm/packet_b2.md}; F=${2:-docs/create_bird_model_prompt.v12.md}
fail=0
for m in $(grep -oE '^<!-- v12\.md L[0-9]+-L[0-9]+ BEGIN -->' "$P" | grep -oE '[0-9]+-L[0-9]+'); do
  a=${m%-L*}; b=${m#*-L}
  if cmp -s <(sed -n "/^<!-- v12.md L$a-L$b BEGIN -->/,/^<!-- v12.md L$a-L$b END -->/p" "$P" | sed '1d;$d') <(sed -n "${a},${b}p" "$F"); then
    echo "OK   L$a-L$b"; else echo "DIFF L$a-L$b"; fail=1; fi
done
exit $fail
