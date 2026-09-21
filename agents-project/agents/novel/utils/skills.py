"""技能包的定位与边界校验。

模型给的"技能名 + 相对路径"能不能落到 skills/ 里，全在这里收口；tools/skill.py 只管读和跑。
技能是一个目录：SKILL.md 是入口，references/ 参考资料，templates/ 模板，scripts/ 脚本。
"""
from pathlib import Path

# 一起 resolve：技能目录本身是软链时也要能和子目录的 parent 对上。
SKILLS_ROOT = (Path(__file__).resolve().parents[1] / "skills").resolve()


class SkillError(ValueError):
    """技能名不存在，或给的路径跑到技能目录外面去了。"""


def skill_names() -> list[str]:
    """skills/ 下现有的技能名。"""
    if not SKILLS_ROOT.is_dir():
        return []
    return sorted(p.name for p in SKILLS_ROOT.iterdir() if p.is_dir())


def skill_dir(name: str) -> Path:
    """技能名换技能根目录。名字必须是 skills/ 的直接子目录，瞎猜的名字直接报错。"""
    root = (SKILLS_ROOT / name).resolve()
    if root.parent != SKILLS_ROOT or not root.is_dir():
        raise SkillError(
            f"没有这个技能：{name}。现有技能：{'、'.join(skill_names()) or '（无）'}"
        )
    return root


def skill_path(name: str, rel: str) -> Path:
    """技能内的相对路径换绝对路径，越界报错。

    resolve() 会展开符号链接，所以指向外面的软链、"." ".." 这类写法一起都拦得住。
    """
    root = skill_dir(name)
    target = (root / rel).resolve() if rel else root
    if target != root and root not in target.parents:
        raise SkillError(f"路径超出技能目录：{rel}")
    return target


def describe(name: str) -> str:
    """把技能里的文件列成一棵树，让模型知道有哪些能读。"""
    root = skill_dir(name)
    lines = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        lines.append(str(path.relative_to(root)).replace("\\", "/"))
    return f"{name}/\n" + "\n".join(f"  {line}" for line in lines)
