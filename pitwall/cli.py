"""``pitwall build`` (site data) and ``pitwall evaluate`` (season backtest)."""

from __future__ import annotations

import argparse
from pathlib import Path

from .openf1 import OpenF1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pitwall")
    parser.add_argument("--cache", default="data/cache", help="OpenF1 response cache directory")
    parser.add_argument("--year", type=int, default=2026)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Fetch completed races and write site/data")
    b.add_argument("--out", default="site/data")
    e = sub.add_parser("evaluate", help="Run the stint-forecast backtest (dev/test split)")
    e.add_argument("--out", default="results")
    args = parser.parse_args(argv)
    api = OpenF1(Path(args.cache))
    if args.cmd == "build":
        from .build import build_site

        build_site(api, Path(args.out), args.year)
    else:
        from .evaluate import run

        r = run(api, Path(args.out), args.year)
        t = r["test"]["mae"]
        print(f"test MAE  model {t['model']:.3f}s  flat {t['flat']:.3f}s  no_deg {t['no_deg']:.3f}s")


if __name__ == "__main__":
    main()
