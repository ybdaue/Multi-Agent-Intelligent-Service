"""把父图的 config 裁成只带 novel_id / user_id 的一份，递给手调的带工具子图。

带工具的子图（writer.planner / reader.pacing / chat）手调 agent.ainvoke 时要递 config ——
fetchDB 靠 novel_id 才知道查哪本书。多带的 thread_id / checkpoint_ns 会给这些没有 checkpointer
的子图种出一份自己的 checkpoint，所以这里只挑这两个键（与 chat.py 原来的口径一致）。
"""


def tool_config(config) -> dict:
    cfg = (config or {}).get("configurable") or {}
    return {
        "configurable": {
            "novel_id": str(cfg.get("novel_id") or ""),
            "user_id": str(cfg.get("user_id") or ""),
        }
    }