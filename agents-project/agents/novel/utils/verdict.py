"""模型那段 JSON 判词怎么读成"同不同意"。

editor 的 approve（"go"）与 setup 的 confirm（"confirmed"）形状一样，各自传自己的 key。
放在 utils 里是因为两个图都用：setup 是独立编译的图，import 不到 editor 的节点。
"""
from agents.utils.models import parse_json_value


def verdict(text: str, key: str) -> tuple[bool, str]:
    """把模型那段 JSON 判词解析成 (是否同意, 用户的意见)。

    解析不出来一律按**没同意**处理 —— 拿不准时多问一次，比照着一个没听懂的答复动手强。
    """
    try:
        value = parse_json_value(text)
    except (ValueError, TypeError):
        return False, ""
    if not isinstance(value, dict) or value.get(key) is not True:
        return False, ""
    feedback = value.get("feedback")
    return True, feedback if isinstance(feedback, str) else ""
