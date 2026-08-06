"""
法律文件导入脚本
从 agents-project/lows/ 目录读取 .doc / .docx 文件，解析、切片后存入 Chroma 向量库。

用法:
    python agents/legal_ingest.py

如果要看切片：
    浏览器 Swagger 页面（零代码）
    1. 浏览器打开：http://localhost:8000/docs
    2. 先展开 GET /api/v1/collections → 点 Try it out → Execute，能看到所有集合列表。你会看到两个集合：
        - laws_docs — 就是 legal_ingest 写入的法律法规（target="laws"）
        - legal_docs — 用户上传的文件
    3. 拿到集合的 id，再展开 POST /api/v1/collections/{collection_id}/get，把 id 填进去，body 填：
    { "limit": 5, "include": ["documents", "metadatas"] }
    3. Execute 后就能看到库里存的切片文本和元数据。
    4. 想看总数：POST /api/v1/collections/{collection_id}/count。
"""

import os
import re
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Any, Optional

# 把项目根目录加入 sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def _load_module(mod_name: str, filename: str):
    """按文件路径加载 agents 子模块，避免触发 agents/__init__.py。

    __init__.py 会急切导入 finance / multiAgent（依赖 DEEPSEEK_API_KEY），
    而本脚本只需要 RAG 和 parse，因此绕过包初始化。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(mod_name, project_root / "agents" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


RAG = _load_module("agents.RAG", "RAG.py")
_parse = _load_module("agents.parse", "parse.py")
chunk_text = _parse.chunk_text

LEGAL_DIR = project_root / "laws"
SUPPORTED_SUFFIXES = {".doc", ".docx"}


def _parse_docx(raw: bytes) -> str:
    import docx
    import io

    doc = docx.Document(io.BytesIO(raw))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _parse_doc_via_antiword(path: Path) -> Optional[str]:
    """使用 antiword 工具提取 .doc 文件文本。"""
    antiword = shutil.which("antiword")
    if not antiword:
        return None
    try:
        result = subprocess.run(
            [antiword, "-w", "0", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def parse_file(path: Path) -> str:
    """解析 .doc / .docx 文件，返回纯文本。"""
    suffix = path.suffix.lower()
    raw = path.read_bytes()

    if suffix == ".docx":
        return _parse_docx(raw)

    # .doc: 先尝试 docx 方式（部分误标为 .doc 的文件实际是 docx 格式）
    try:
        return _parse_docx(raw)
    except Exception:
        pass

    # 再尝试 antiword
    text = _parse_doc_via_antiword(path)
    if text is not None:
        return text

    raise ValueError(
        f"无法解析 {path.name}。请转换为 .docx 格式后重试。"
    )


def import_legal_files() -> dict[str, Any]:
    """扫描 lows 目录，导入所有法律文件到 Chroma。"""
    if not LEGAL_DIR.exists():
        return {"status": "error", "message": f"目录不存在: {LEGAL_DIR}"}

    files = [f for f in sorted(LEGAL_DIR.iterdir()) if f.suffix.lower() in SUPPORTED_SUFFIXES]
    if not files:
        return {
            "status": "ok",
            "message": f"{LEGAL_DIR} 中没有 .doc / .docx 文件",
            "total": 0,
            "imported": 0,
            "failed": 0,
        }

    RAG.init()
    if not RAG.is_ready():
        return {"status": "error", "message": "RAG 未就绪（Chroma / Embedding 模型加载失败）"}

    total = len(files)
    imported = 0
    failed = 0
    details: list[dict[str, Any]] = []

    for fpath in files:
        try:
            print(f"  处理: {fpath.name}")
            text = parse_file(fpath)
            chunks = chunk_text(text, file_id=fpath.stem)
            if not chunks:
                failed += 1
                details.append({"file": fpath.name, "status": "skip", "reason": "切片为空"})
                print(f"    跳过（切片为空）")
                continue

            result = RAG.upsert_chunks(chunks, target="laws")
            if result:
                imported += 1
                details.append({"file": fpath.name, "status": "ok", "chunks": len(chunks)})
                print(f"    OK - {len(chunks)} 个切片")
            else:
                failed += 1
                details.append({"file": fpath.name, "status": "fail", "reason": "upsert 失败"})
                print(f"    失败: upsert 返回 False")

        except Exception as e:
            failed += 1
            details.append({"file": fpath.name, "status": "fail", "reason": str(e)})
            print(f"    失败: {e}")

    return {
        "status": "ok",
        "total": total,
        "imported": imported,
        "failed": failed,
        "details": details,
    }


def main() -> None:
    print(f"扫描目录: {LEGAL_DIR}")
    result = import_legal_files()

    if result["status"] == "error":
        print(f"\n错误: {result['message']}")
        sys.exit(1)

    print(f"\n完成: 共 {result['total']} 个文件，成功 {result['imported']}，失败 {result['failed']}")
    for d in result.get("details", []):
        status_icon = "OK" if d["status"] == "ok" else "FAIL"
        detail = d.get("chunks", d.get("reason", ""))
        print(f"  [{status_icon}] {d['file']} ({detail})")


if __name__ == "__main__":
    main()
