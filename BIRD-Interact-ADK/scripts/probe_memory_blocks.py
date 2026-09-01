#!/usr/bin/env python3
"""Print the memory blocks the LIVE server appends to list_models.

Why this exists and why grepping a run does not work: every tool result recorded
in a trajectory is truncated to exactly 2014 characters (verified across all 24
tasks of the 2026-09-01 fake_account run — every list_models result is 2014 long,
to the byte). The memory blocks are appended AFTER the model inventory, so they
fall past the cut and are invisible in recorded runs. A census over trajectories
therefore cannot distinguish "the shapes block never served" from "the shapes
block served and the recorder dropped it".

Makes no LLM calls. Reads the store through the server, exactly as the agent
would see it, so it reports what WOULD be served at this instant.

    python scripts/probe_memory_blocks.py --database crypto_exchange [--raw]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import settings                      # noqa: E402
from shared.environment_backends import get_domain_config  # noqa: E402
from shared.mcp_client import MCPClient, MCPEndpoint     # noqa: E402

# Exact headers the renderer emits — feedback.py:949,1018,1087,825 and
# advisories.py:277. A header not listed here is a renderer change, not a miss.
BLOCKS = [
    ("## Previously successful query patterns", "shapes"),
    ("## Corrections from rejected answers", "corrections"),
    ("## Certified query exemplars", "exemplars"),
    ("## Column track record on this model", "columns"),
    ("## Query risk advisories", "advisories"),
    ("## Attempts already rejected for this question", "attempt ledger"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", required=True,
                    help="BIRD database name, e.g. crypto_exchange. Resolved to the "
                         "catalog/schema/table triple the agent passes, which IS the "
                         "server's memory scope — reads fail closed on a blank model.")
    ap.add_argument("--raw", action="store_true", help="dump the whole response")
    args = ap.parse_args()

    cli = MCPClient(MCPEndpoint(url=settings.semantic_layer_mcp_url,
                                bearer_token=settings.semantic_layer_mcp_token))
    # The backend default in .env is "raw"; the semantic model only exists under
    # "atscale", and that is the scope memory is keyed on.
    domain = get_domain_config("atscale", args.database)
    if not domain:
        sys.exit(f"no semantic model configured for {args.database}")
    text = str(cli.call_tool("list_models", domain))

    if args.raw:
        print(text)
        return

    print(f"list_models response: {len(text)} chars "
          f"({'TRUNCATED in a trajectory' if len(text) > 2014 else 'fits in a trajectory'})")
    print(f"scope: {domain['catalog']}.{domain['schema']}.{domain['table']}")
    found = False
    for header, label in BLOCKS:
        if header not in text:
            print(f"  [ ] {label:16} not served")
            continue
        found = True
        body = text.split(header, 1)[1]
        # Stop at the next block header so each is reported on its own.
        for nxt in [h for h, _ in BLOCKS] + ["## Next Steps", "\n---\n"]:
            if nxt in body:
                body = body.split(nxt, 1)[0]
        # Blocks render either as "- " bullets (shapes, corrections, ledger) or
        # as a prose paragraph with an inline comma list (columns). Report both.
        lines = [ln for ln in body.splitlines() if ln.strip().startswith("- ")]
        if not lines:
            lines = [ln for ln in body.splitlines()
                     if ln.strip() and not ln.strip().startswith("**")
                     and not ln.strip().startswith("#")][:4]
        print(f"  [x] {label:16} SERVED, {len(lines)} line(s)")
        for ln in lines:
            print(f"        {ln.strip()[:200]}")
    if not found:
        print("  nothing served — the store has no evidence clearing any bar for this model")


if __name__ == "__main__":
    main()
