"""Command-line interface for StockScribe."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .pipeline import discover, run
from .publishing.site import build_site


def _apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    overrides: dict = {}
    if getattr(args, "num", None) is not None:
        overrides["num_articles"] = args.num
    if getattr(args, "output_dir", None):
        overrides["content_dir"] = args.output_dir
    if getattr(args, "no_trends", False):
        overrides["enable_google_trends"] = False
    if getattr(args, "no_site", False):
        overrides["build_site"] = False
    if getattr(args, "free", False):
        overrides["generator"] = "free"
    return config.merged(overrides) if overrides else config


def _print_candidates(candidates, limit: int) -> None:
    if not candidates:
        print("No trending topics found (no recent headlines / trends reachable).")
        return
    print(f"\nTop {min(limit, len(candidates))} trending topics by virality score:\n")
    for i, c in enumerate(candidates[:limit], 1):
        comp = c.components
        print(f"{i:2}. {c.term}   (score={c.score:.2f})")
        print(
            f"      freq={comp.get('frequency', 0):.2f} "
            f"sources={int(comp.get('sources', 0))} "
            f"diversity={comp.get('diversity', 0):.2f} "
            f"trend={comp.get('trend', 0):.2f}"
        )
        if c.keywords:
            print(f"      keywords: {', '.join(c.keywords)}")
        if c.headlines:
            print(f"      e.g. {c.headlines[0].title} [{c.headlines[0].source}]")
    print()


def cmd_run(args: argparse.Namespace) -> int:
    config = _apply_overrides(Config.load(args.config), args)
    result = run(
        config,
        dry_run=args.dry_run,
        use_trends=not args.no_trends if args.no_trends else None,
    )
    if args.dry_run:
        _print_candidates(result.selected, config.num_articles)
        print(f"Dry run complete: {len(result.selected)} topic(s) would be written.")
        return 0
    print(f"\nGenerated {len(result.articles)} article(s):")
    for path in result.written_paths:
        print(f"  - {path}")
    if result.site_index:
        print(f"\nSite rebuilt: {result.site_index}")
    if not result.articles:
        print("  (nothing new — all top topics were already covered)")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    config = _apply_overrides(Config.load(args.config), args)
    candidates = discover(config, use_trends=not args.no_trends)
    _print_candidates(candidates, args.limit)
    return 0


def cmd_build_site(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    index = build_site(config.content_dir, config.site_dir, config.platform_name)
    print(f"Site built: {index}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockscribe",
        description="Research trending stock-market topics and generate cited articles.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help="Path to a YAML config file")
    common.add_argument("--no-trends", action="store_true", help="Skip Google Trends")

    p_run = sub.add_parser("run", parents=[common], help="Full pipeline: research -> generate -> publish")
    p_run.add_argument("-n", "--num", type=int, help="Number of articles to generate")
    p_run.add_argument("--output-dir", help="Directory for Markdown output")
    p_run.add_argument("--dry-run", action="store_true", help="Research + select only; no API calls")
    p_run.add_argument("--free", action="store_true", help="Generate free no-LLM news roundups (no API key needed)")
    p_run.add_argument("--no-site", action="store_true", help="Do not rebuild the static site")
    p_run.set_defaults(func=cmd_run)

    p_disc = sub.add_parser("discover", parents=[common], help="Print trending topics (no generation)")
    p_disc.add_argument("-l", "--limit", type=int, default=15, help="How many topics to show")
    p_disc.set_defaults(func=cmd_discover)

    p_site = sub.add_parser("build-site", parents=[common], help="Rebuild the static site from content/")
    p_site.set_defaults(func=cmd_build_site)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not getattr(args, "command", None):
        # default to `run` with no extra flags
        args = parser.parse_args(["run", *(argv or [])]) if argv else parser.parse_args(["run"])
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
