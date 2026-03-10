#!/usr/bin/env python3
"""Trim most recent N trading days from a parquet dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description="Trim latest trading days from dataset")
    parser.add_argument("--input", required=True, help="Input parquet path")
    parser.add_argument("--output", required=True, help="Output parquet path")
    parser.add_argument("--exclude-days", type=int, default=20, help="How many latest trading days to exclude")
    args = parser.parse_args()

    if args.exclude_days < 0:
        raise SystemExit("--exclude-days must be >= 0")

    src = Path(args.input).expanduser().resolve()
    dst = Path(args.output).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"input not found: {src}")

    df = pd.read_parquet(src)
    if "date" not in df.columns:
        raise SystemExit("dataset has no 'date' column")

    date_col = df["date"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(8)
    trading_days = sorted(date_col.unique())
    if not trading_days:
        raise SystemExit("dataset has no trading days")

    if args.exclude_days == 0:
        kept = df.copy()
        dropped_days: list[str] = []
        cutoff = trading_days[-1]
    else:
        if len(trading_days) <= args.exclude_days:
            raise SystemExit(
                f"not enough trading days: total={len(trading_days)}, exclude={args.exclude_days}"
            )
        cutoff = trading_days[-(args.exclude_days + 1)]
        dropped_days = trading_days[-args.exclude_days :]
        kept = df[date_col <= cutoff].copy()

    dst.parent.mkdir(parents=True, exist_ok=True)
    kept.to_parquet(dst, index=False)

    print(f"input_rows={len(df)} output_rows={len(kept)}")
    print(f"total_days={len(trading_days)} cutoff={cutoff}")
    print(f"dropped_days={','.join(dropped_days) if dropped_days else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
