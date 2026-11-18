"""Local tools.

    python -m jobfeed sync --out .local/site-data     build board.json and logos into a folder
"""
import argparse
import logging

from .board import build
from .storage import DirStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m jobfeed")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="build data/board.json and logos into a folder")
    sync.add_argument("--out", default=".local/site-data")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = build(DirStore(args.out))
    print(
        f"{result.roles} roles; {result.skipped} outside the UK skipped; "
        f"kept previous roles for: {', '.join(result.kept) or 'none'}; "
        f"new logos: {len(result.new_logos)}; missing logos: {', '.join(result.missing_logos) or 'none'}"
    )


if __name__ == "__main__":
    main()
