"""The compiled W1 graph and what it depends on, built once and shared across requests."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.graphs.w1 import W1Deps, build_w1
from sahyog.graphs.w2_ask import AskDeps, build_ask
from sahyog.ingest.embedding import Embedder, get_embedder
from sahyog.llm.gateway import ModelGateway, build_gateway
from sahyog.safety.red_flags import RedFlagEngine


@dataclass
class W1Runtime:
    graph: Any
    deps: W1Deps
    checkpointer: Any


def postgres_checkpointer(max_size: int = 10) -> PostgresSaver:
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    pool = ConnectionPool(
        url,
        max_size=max_size,
        open=True,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()  # idempotent; creates the library's own tables
    return saver


def build_runtime(
    *,
    gateway: ModelGateway | None = None,
    checkpointer: Any = None,
    rules_enabled: bool = True,
) -> W1Runtime:
    sessions = get_sessionmaker()
    with sessions() as session:
        engine = RedFlagEngine.from_db(session)
    deps = W1Deps(gateway or build_gateway(), engine, sessions, rules_enabled)
    saver = checkpointer if checkpointer is not None else postgres_checkpointer()
    return W1Runtime(build_w1(deps, saver), deps, saver)


@lru_cache
def get_runtime() -> W1Runtime:
    return build_runtime()


def build_ask_graph(
    *, gateway: ModelGateway | None = None, embedder: Embedder | None = None, guardrails=True
) -> Any:
    sessions = get_sessionmaker()
    with sessions() as session:
        engine = RedFlagEngine.from_db(session)
    deps = AskDeps(gateway or build_gateway(), engine, embedder or get_embedder(), sessions)
    deps.guardrails = guardrails
    return build_ask(deps)


@lru_cache
def get_scribe_runtime() -> W1Runtime:
    from pathlib import Path

    from sahyog.graphs.w3 import ScribeDeps, build_w3
    from sahyog.scribe.stock import CsvStockAdapter

    deps = ScribeDeps(
        build_gateway(), CsvStockAdapter(Path(get_settings().stock_csv)), get_sessionmaker()
    )
    saver = postgres_checkpointer()
    return W1Runtime(build_w3(deps, saver), deps, saver)


@lru_cache
def get_ask_graph() -> Any:
    return build_ask_graph()
