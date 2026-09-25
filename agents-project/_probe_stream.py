import asyncio
import sys
from typing import Any

sys.path.insert(0, ".")

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class Outer(TypedDict, total=False):
    target: dict
    text: str
    intension: str


class Inner(TypedDict, total=False):
    text: str


async def _intension(state):
    return {"intension": "write"}


async def resolve(state):
    return {"target": {"kind": "write_next", "chapterId": "", "order": 2}}


async def writer(state):
    return {"text": "x"}


async def main():
    inner = StateGraph(Inner)
    inner.add_node("model", writer)
    inner.add_edge(START, "model")
    inner.add_edge("model", END)
    sub = inner.compile(name="writer")

    g = StateGraph(Outer)
    g.add_node("intension", _intension)
    g.add_node("resolve", resolve)
    g.add_node("writer", sub)
    g.add_edge(START, "intension")
    g.add_edge("intension", "resolve")
    g.add_edge("resolve", "writer")
    g.add_edge("writer", END)
    app = g.compile()

    async for ns, mode, data in app.astream(
        {}, stream_mode=["messages", "tasks", "updates"], subgraphs=True
    ):
        if mode == "updates":
            print("UPDATES ns=", repr(ns), "payload=", data)


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
