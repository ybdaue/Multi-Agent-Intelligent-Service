"""RerankModel 真实连通性测试：直连 SiliconFlow /v1/rerank，验证接口与 key 是否可用。

用法：先确保 .env（或 .env.development）里配好 SILICONFLOW_API_KEY，然后：
    python test/test_rerank_model.py
"""
import os
import sys
from pathlib import Path

# Windows GBK 控制台打印不了 tickflow 的 emoji，先把输出切到 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 项目根目录注入 sys.path，保证能 import agents.*
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试默认走开发 key：APP_ENV 未设或为 development 时优先 .env.development，
# 仅当显式 APP_ENV=production 时才优先 .env。避免误用 .env 里的占位假 key。
from dotenv import load_dotenv  # noqa: E402

_mode = os.getenv("APP_ENV", "").strip().lower()
if _mode in ("production", "prod"):
    _candidates = [".env", ".env.development"]
else:
    _candidates = [".env.development", ".env"]
_env_path = next((PROJECT_ROOT / c for c in _candidates if (PROJECT_ROOT / c).exists()), None)
if _env_path is not None:
    load_dotenv(_env_path, override=True)
    print(f"loaded env: {_env_path.name}")
_k = os.getenv("SILICONFLOW_API_KEY", "")
print(f"key fingerprint: {_k[:6]}...{_k[-4:]} (len={len(_k)})")

from agents.utils.models import RerankModel  # noqa: E402


def test_rerank():
    query = "合同违约后守约方可以主张哪些赔偿"
    documents = [
        "买卖合同一方违约时，守约方可以要求继续履行，也可以主张违约金或赔偿损失。",
        "借款合同到期后借款人未按时还款，出借人可起诉要求偿还本金、利息并承担违约责任。",
        "用人单位违法解除劳动合同的，应当依照经济补偿标准的二倍向劳动者支付赔偿金。",
        "承担违约责任的方式包括继续履行、采取补救措施或者赔偿损失等，守约方有权选择。",
        "知识产权侵权纠纷中，权利人可要求停止侵害、消除影响并赔偿经济损失。",
    ]

    print(f"query: {query}")
    print(f"documents: {len(documents)} 条, top_n=3\n")

    try:
        ranked = RerankModel(query, documents, top_n=3)
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        print("接口不可用：多为 key 无效(401)或网络问题。")
        return False

    print("OK 接口可用，top 结果如下：")
    for idx, score in ranked:
        print(f"  [{idx}] score={score:.4f}  {documents[idx][:20]}...")
    return True


if __name__ == "__main__":
    ok = test_rerank()
    print()
    print("PASS: 接口连通，key 有效" if ok else "FAIL: 接口不通或 key 无效")
    sys.exit(0 if ok else 1)
