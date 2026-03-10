#!/usr/bin/env python3
"""Build secid batches for batch training workflows.

Supports:
- full universe from stock-grabber/data/all_stocks.json
- explicit secid list (sh600267,sz001696,...)
- explicit numeric code list (600267,001696,...)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SECID_RE = re.compile(r"^(sh|sz|bj)\d{6}$", re.IGNORECASE)
CODE_RE = re.compile(r"^\d{6}$")


def _load_all_stocks(path: Path) -> tuple[list[str], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    secids: list[str] = []
    code_to_secid: dict[str, str] = {}

    for item in data.get("sh", []):
        code = str(item.get("code", "")).strip()
        if not CODE_RE.fullmatch(code):
            continue
        secid = f"sh{code}"
        secids.append(secid)
        code_to_secid.setdefault(code, secid)

    for item in data.get("sz", []):
        code = str(item.get("code", "")).strip()
        if not CODE_RE.fullmatch(code):
            continue
        secid = f"sz{code}"
        secids.append(secid)
        code_to_secid.setdefault(code, secid)

    # historical convention in this project: BJ repos use secid prefix "sz"
    for item in data.get("bj", []):
        code = str(item.get("code", "")).strip()
        if not CODE_RE.fullmatch(code):
            continue
        secid = f"sz{code}"
        code_to_secid.setdefault(code, secid)

    return sorted(set(secids)), code_to_secid


def _iter_tokens(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[\s,;，；]+", raw.strip())
    return [p for p in parts if p]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build secid batch JSON")
    parser.add_argument("--all-stocks-json", required=True, help="Path to all_stocks.json")
    parser.add_argument("--secids", default="", help="secid/code list, comma or whitespace separated")
    parser.add_argument("--include-bj", action="store_true", help="Include BJ stocks when secids is empty")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size")
    parser.add_argument("--max-batches", type=int, default=0, help="Max batches (0 means all)")
    parser.add_argument("--output", default="", help="Output JSON file path")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")
    if args.max_batches < 0:
        raise SystemExit("--max-batches must be >= 0")

    all_path = Path(args.all_stocks_json).expanduser().resolve()
    if not all_path.exists():
        raise SystemExit(f"all_stocks.json not found: {all_path}")

    all_secids, code_to_secid = _load_all_stocks(all_path)

    if args.secids.strip():
        secids: list[str] = []
        unknown: list[str] = []
        for tok in _iter_tokens(args.secids):
            t = tok.strip().lower()
            if SECID_RE.fullmatch(t):
                if t.startswith("bj"):
                    t = "sz" + t[2:]
                secids.append(t)
                continue
            if CODE_RE.fullmatch(t):
                sid = code_to_secid.get(t)
                if sid:
                    secids.append(sid)
                else:
                    unknown.append(tok)
                continue
            unknown.append(tok)

        if unknown:
            raise SystemExit(f"Unknown secid/code tokens: {', '.join(unknown)}")
        secids = sorted(set(secids))
    else:
        secids = list(all_secids)
        if args.include_bj:
            data = json.loads(all_path.read_text(encoding="utf-8"))
            bj = []
            for item in data.get("bj", []):
                code = str(item.get("code", "")).strip()
                if CODE_RE.fullmatch(code):
                    bj.append(f"sz{code}")
            secids = sorted(set(secids + bj))

    batches = [secids[i : i + args.batch_size] for i in range(0, len(secids), args.batch_size)]
    if args.max_batches > 0:
        batches = batches[: args.max_batches]

    selected_secids = [sid for batch in batches for sid in batch]
    payload = {
        "total_secids": len(selected_secids),
        "batch_size": args.batch_size,
        "batch_count": len(batches),
        "secids": selected_secids,
        "batches": batches,
    }

    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(out)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
