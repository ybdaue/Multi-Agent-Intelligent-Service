import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

env_path = project_root / ".env"
if not env_path.exists():
    env_path = project_root / ".env.example"
load_dotenv(env_path)

from agents.multiAgent import multiAgent


async def main():
    thread_id = "debug_thread_1"
    config = {"configurable": {"thread_id": thread_id, "userId": 12345}}
    input_state = {
        "messages": [HumanMessage("你好")],
        "userId": 12345,
        "user_message": "你好",
        "file_source": None,
    }

    n_token = 0
    n_values = 0
    async for event in multiAgent.astream(
        input_state, config, stream_mode=["messages", "values"]
    ):
        if not isinstance(event, tuple) or len(event) != 2:
            print("EVT? ->", type(event).__name__, repr(event)[:120])
            continue
        mode, data = event
        if mode == "messages":
            n_token += 1
            if n_token <= 5:
                print("MSG:", type(data[0]).__name__, repr(data[0].content)[:120])
        else:
            n_values += 1
            if n_values <= 3:
                msg = data.get("messages", [])
                if msg:
                    last = msg[-1]
                    print(
                        "VALUES last msg:",
                        type(last).__name__,
                        "content=", repr(last.content)[:100] if isinstance(last.content, str) else "NONSTR",
                        "tool_calls=", getattr(last, "tool_calls", None),
                    )
    print("RESULT: total message events =", n_token, ", values events =", n_values)


if __name__ == "__main__":
    asyncio.run(main())
