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
    e = sub.add_parser("evaluate", help="Run the backtests: stint forecasts and live win probability")
    e.add_argument("--out", default="results")
    v = sub.add_parser("serve", help="Open the site locally (downloads the latest races first)")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--offline", action="store_true", help="Do not check for new races")
    v.add_argument("--rebuild", action="store_true", help="Rebuild all data from OpenF1 instead of downloading it")
    v.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    api = OpenF1(Path(args.cache))
    if args.cmd == "serve":
        from .build import build_site
        from .serve import serve, sync_from_site

        site = Path(__file__).resolve().parent.parent / "site"
        if args.rebuild:
            build_site(api, site / "data", args.year)
        elif not args.offline:
            try:
                print("Checking for new races…", flush=True)
                n = sync_from_site(site, args.year)
                print(f"{n} race(s) downloaded." if n else "Already up to date.", flush=True)
            except Exception as exc:  # offline or site unreachable: serve what we have
                print(f"Could not reach the published site ({exc}); using local data.", flush=True)
        if not (site / "data" / str(args.year) / "index.json").exists():
            raise SystemExit("No race data yet. Connect to the internet or run `pitwall serve --rebuild`.")
        serve(site, args.port, not args.no_browser)
    elif args.cmd == "build":
        from .build import build_site

        build_site(api, Path(args.out), args.year)
    else:
        from .evaluate import run
        from .winprob_eval import run as run_winprob

        r = run(api, Path(args.out), args.year)
        t = r["test"]["mae"]
        print(f"stint forecast, test MAE: model {t['model']:.3f}s  flat {t['flat']:.3f}s  no_deg {t['no_deg']:.3f}s")
        w = run_winprob(api, Path(args.out), args.year)["test"]
        print(f"win probability, test log-loss: calibrated {w['calibrated_simulator']['log_loss']:.3f}  "
              f"running-order prior {w['running_order_prior']['log_loss']:.3f}")


if __name__ == "__main__":
    main()
