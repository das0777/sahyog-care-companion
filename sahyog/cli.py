"""Developer commands: `python -m sahyog.cli seed` and `python -m sahyog.cli token`."""

import argparse
import sys

from sahyog.auth import Role, issue_token
from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.seed.generate import seed


def _seed(_: argparse.Namespace) -> None:
    settings = get_settings()
    with get_sessionmaker()() as session, session.begin():
        result = seed(session, random_seed=settings.seed_random_seed, tz=settings.timezone)
    width = max(len(k) for k in result.counts)
    for table, n in result.counts.items():
        print(f"{table:<{width}}  {n:>7,}")
    print(f"{'fingerprint':<{width}}  {result.fingerprint}")


def _token(args: argparse.Namespace) -> None:
    print(issue_token(Role(args.role), args.id))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sahyog")
    sub = parser.add_subparsers(required=True)

    p_seed = sub.add_parser("seed", help="Load deterministic synthetic data")
    p_seed.set_defaults(fn=_seed)

    p_token = sub.add_parser("token", help="Issue a local dev token")
    p_token.add_argument("--role", required=True, choices=[r.value for r in Role])
    p_token.add_argument("--id", required=True, help="Actor id, e.g. P0001, D0001, DESK01")
    p_token.set_defaults(fn=_token)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
