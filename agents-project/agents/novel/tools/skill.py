"""技能包的使用：读技能里的文件、跑技能自带的脚本。路径校验在 utils/skills.py。"""
import asyncio
import sys
from pathlib import Path

from langchain_core.tools import tool

from ..utils.skills import SkillError, describe, skill_path

# 单个参考文件读出来最多给这么多字符（最大的 review-dimensions.md 才 17KB）。
MAX_CHARS = 200_000
# 脚本最长跑这么久，超了杀掉。
SCRIPT_TIMEOUT = 60
# 脚本的输出上限，别让一个报错把上下文灌满。
MAX_OUTPUT_CHARS = 8_000


@tool
async def read_skill_file(skill: str, path: str = "") -> str:
    """读技能包里的文件。要按技能做某件事之前，先读它的 SKILL.md。

    Args:
        skill: 技能名，如 setupSkill（开书前设定补充）、writerSkill（章节编写）
        path: 技能目录内的相对路径，如 SKILL.md、references/hook-techniques.md。
              留空则先列出这个技能里有哪些文件，方便挑一个再读。
    """
    try:
        target = skill_path(skill, path)
    except SkillError as e:
        return str(e)

    if target.is_dir():
        return describe(skill)
    if not target.is_file():
        return f"技能 {skill} 里没有这个文件：{path}。现有文件：\n{describe(skill)}"

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"{path} 不是文本文件，读不了。"

    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n\n（文件太长，只给了前 {MAX_CHARS} 字符）"
    return text


@tool
async def run_skill_script(skill: str, script: str, argv: list[str] | None = None) -> str:
    """跑技能自带脚本，返回它的输出。

    脚本按技能文档里写的方式调用（cwd 就是技能根目录），参数原样传给脚本。

    Args:
        script: scripts/ 下的脚本文件名，如 check_chapter_wordcount.py
        argv: 按顺序传给脚本的参数，如 ["novels/某书/第01章.md"]
    """
    # 只认文件名，目录部分丢掉再拼 scripts/ —— 传什么都出不了这个技能的 scripts/。
    name = Path(script).name
    if not name.endswith(".py"):
        return f"只能跑技能 scripts/ 下的 .py 脚本：{script}"

    try:
        root = skill_path(skill, "")
        target = skill_path(skill, f"scripts/{name}")
    except SkillError as e:
        return str(e)

    if not target.is_file():
        return f"技能 {skill} 的 scripts/ 里没有这个脚本：{name}。现有文件：\n{describe(skill)}"

    # -X utf8：Windows 上父子进程之间不会因为控制台编码对不上话。
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-X",
        "utf8",
        str(target),
        *(argv or []),
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"脚本超过 {SCRIPT_TIMEOUT} 秒没跑完，已终止：{script}"

    parts = [f"exit code {proc.returncode}"]
    for label, raw in (("stdout", out), ("stderr", err)):
        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            parts.append(f"[{label}]\n{text[:MAX_OUTPUT_CHARS]}")
    return "\n".join(parts)
