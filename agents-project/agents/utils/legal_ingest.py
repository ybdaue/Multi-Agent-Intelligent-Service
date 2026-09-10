"""
法律文件导入脚本
从 agents-project/lows/ 目录读取 .doc / .docx 文件，解析、切片后存入 Chroma 向量库。

用法:
    python agents/utils/legal_ingest.py

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

import subprocess
import sys
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

# 把项目根目录加入 sys.path
# 本脚本在 agents/utils/ 下，向上三级才是 agents-project/
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# RAG.py / parse.py 与本脚本同目录（agents/utils/）
_PKG_DIR = Path(__file__).resolve().parent


def _load_module(mod_name: str, filename: str):
    """按文件路径加载 agents/utils 子模块，避免触发 agents/__init__.py。
    __init__.py 会急切导入 finance / multiAgent（依赖 DEEPSEEK_API_KEY），
    而本脚本只需要 RAG 和 parse，因此绕过包初始化。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(mod_name, _PKG_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


RAG = _load_module("agents.utils.RAG", "RAG.py")
_parse = _load_module("agents.utils.parse", "parse.py")
_bm25 = _load_module("agents.utils.bm25_index", "bm25_index.py")
_parent_store = _load_module("agents.utils.law_parent_store", "law_parent_store.py")
# 法律语料专用：父子文档切分（子存 Chroma/bm25，父存 PG laws 表）
chunk_laws = _parse.chunk_laws


def write_bm25_table(chunks: list[dict], conn=None) -> bool:
    """把法条切片（已写入 Chroma 的同批数据）同步 upsert 到 Postgres bm25 表。

    conn：批量导入时复用同一事务连接（由调用方 commit），传 None 则自开自提交。
    """
    if not chunks:
        return True

    import psycopg
    from psycopg import sql

    # 表名用 sql.Identifier 引用，杜绝字符串拼接注入
    statement = sql.SQL(
        "INSERT INTO {} "
        "(id, chunk_id, content, heading, file_id, chunk_index, parent_index) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (chunk_id) DO UPDATE SET "
        "content = EXCLUDED.content, "
        "heading = EXCLUDED.heading, "
        "parent_index = EXCLUDED.parent_index"
    ).format(sql.Identifier(_bm25.BM25_TABLE))

    def _exec(cur) -> None:
        for c in chunks:
            meta = c["metadata"]
            cur.execute(
                statement,
                (
                    str(uuid.uuid4()),
                    f"{meta['file_id']}_{meta['chunk_index']}",
                    c["content"],
                    meta.get("heading"),
                    meta["file_id"],
                    meta["chunk_index"],
                    meta.get("parent_index"),
                ),
            )

    try:
        if conn is not None:
            with conn.cursor() as cur:
                _exec(cur)
            return True
        with psycopg.connect(getattr(_bm25, "postgreSQL_URL")) as own:
            with own.cursor() as cur:
                _exec(cur)
            own.commit()
        return True
    except Exception as e:
        print(f"write_bm25_table 失败: {e}")
        return False

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


def _chroma_file_coverage() -> Optional[dict[str, set[int]]]:
    """返回 {file_id: {chunk_index, ...}}：laws_docs 当前已存的切片。失败返回 None（不跳过）。"""
    try:
        res = RAG._laws_collection.get(include=["metadatas"])
    except Exception as e:
        print(f"读取 laws_docs 现有切片失败（本次不跳过任何文件）: {e}")
        return None
    idx: dict[str, set[int]] = {}
    for m in res.get("metadatas") or []:
        fid = m.get("file_id")
        ci = m.get("chunk_index")
        if fid is None or ci is None:
            continue
        try:
            ci = int(ci)
        except (TypeError, ValueError):
            continue
        idx.setdefault(fid, set()).add(ci)
    return idx


def _existing_parent_files() -> Optional[set[str]]:
    """返回 PG laws 表中已有的 file_id 集合。失败返回 None（不跳过）。"""
    import psycopg

    try:
        with psycopg.connect(getattr(_bm25, "postgreSQL_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT DISTINCT file_id FROM {_parent_store.LAWS_TABLE}")
                return {r[0] for r in cur.fetchall()}
    except Exception as e:
        print(f"读取 PG laws 父表覆盖失败（本次不跳过任何文件）: {e}")
        return None


# 分批导入默认上限（先到先冲刷一批）：
#   batch_files = 一批最多文件数；batch_child_cap = 一批最多子切片数
#   上限目的是让"切分→向量化→入库"按可见的批次推进，避免全量一把梭时长时间无输出。
def import_legal_files(force: bool = False, batch_files: Optional[int] = None) -> dict[str, Any]:
    """扫描 laws 目录，分批流式导入到 Chroma/PG。

    流程按批推进：每批【切分若干文件 → 一次合并 encode → Chroma + PG 入库】，
    一批完成即输出一行累计进度（flush 实时可见），避免全量一把梭长时间无反馈。

    force=True 无视已有覆盖强制重导；默认幂等：Chroma 子 + PG 父均已完整的文件跳过向量化。
    batch_files 默认：有 GPU 20 / 无 GPU 5；且每批子切片数超 batch_child_cap 也会先冲刷。
    """
    if not LEGAL_DIR.exists():
        return {"status": "error", "message": f"目录不存在: {LEGAL_DIR}"}

    files = [f for f in sorted(LEGAL_DIR.iterdir()) if f.suffix.lower() in SUPPORTED_SUFFIXES]
    if not files:
        return {
            "status": "ok",
            "message": f"{LEGAL_DIR} 中没有 .doc / .docx 文件",
            "total": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
        }

    RAG.init()
    if not RAG.is_ready():
        return {"status": "error", "message": "RAG 未就绪（Chroma / Embedding 模型加载失败）"}

    total = len(files)
    gpu = getattr(RAG, "_DEVICE", "cpu") == "cuda"
    B = max(1, int(batch_files or (20 if gpu else 5)))
    child_cap = 600
    print(f"分批导入：共 {total} 个文件，每批 ≤{B} 文件 / ≤{child_cap} 子（device={getattr(RAG,'_DEVICE','?')}）",
          flush=True)

    imported = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []

    # 覆盖判定一次性读取（Chroma 子 + PG 父）；读取失败则不跳过，全部重导
    chroma_cov: Optional[dict[str, set[int]]] = None
    parent_files: Optional[set[str]] = None
    if not force:
        chroma_cov = _chroma_file_coverage()
        parent_files = _existing_parent_files()
    skip_enabled = chroma_cov is not None and parent_files is not None

    # PG 单连接复用于整批（每文件 commit）
    import psycopg

    try:
        pg_conn = psycopg.connect(getattr(_bm25, "postgreSQL_URL"))
    except Exception as e:
        pg_conn = None
        print(f"警告: 打开 PG 连接失败（bm25 / 父表本次不写）: {e}", flush=True)

    def _write_pg(j: dict[str, Any]) -> None:
        if pg_conn is None:
            return
        write_bm25_table(j["children"], conn=pg_conn)
        _parent_store.upsert_parents(j["parents"], conn=pg_conn)
        pg_conn.commit()

    batch_no = 0

    def _flush(buf: list[dict[str, Any]]) -> None:
        """冲刷一批：一次 encode + 逐文件 Chroma/PG 入库 + 累计进度。"""
        nonlocal imported, failed, batch_no
        if not buf:
            return
        batch_no += 1
        docs: list[str] = []
        slices: list[tuple[int, int]] = []
        for j in buf:
            s = len(docs)
            docs.extend(c["content"] for c in j["children"])
            slices.append((s, len(docs)))

        n_chunks = len(docs)
        print(f"[批 {batch_no}] {len(buf)} 文件 / {n_chunks} 子，向量化中...", flush=True)
        emb: list = []
        try:
            emb = RAG.embed_documents(docs)
            if not emb or len(emb) != n_chunks:
                raise RuntimeError(f"结果长度不符 {len(emb)} != {n_chunks}")
        except Exception as e:
            print(f"  [批 {batch_no}] 向量化失败，本批 {len(buf)} 文件记为失败: {e}", flush=True)
            failed += len(buf)
            for j in buf:
                details.append({"file": j["file"], "status": "fail", "reason": f"向量化失败: {e}"})
            return

        batch_ok = 0
        for idx, j in enumerate(buf):
            s, e = slices[idx]
            children, parents = j["children"], j["parents"]
            metas = [dict(c["metadata"]) for c in children]
            ids = [f"{j['file_id']}_{c['metadata']['chunk_index']}" for c in children]
            ok = RAG.upsert_preembedded(
                documents=[c["content"] for c in children],
                embeddings=emb[s:e],
                metadatas=metas,
                ids=ids,
                target="laws",
            )
            if not ok:
                failed += 1
                details.append({"file": j["file"], "status": "fail", "reason": "Chroma upsert 失败"})
                continue
            _write_pg(j)
            imported += 1
            batch_ok += 1
            details.append({"file": j["file"], "status": "ok",
                            "children": len(children), "parents": len(parents)})
        print(f"[批 {batch_no}] 完成：本批成功 {batch_ok}/{len(buf)}，"
              f"累计导入 {imported}/{total}，失败 {failed}，跳过 {skipped}", flush=True)

    buf: list[dict[str, Any]] = []
    idx = 0
    try:
        for fpath in files:
            idx += 1
            try:
                text = parse_file(fpath)
                parts = chunk_laws(text, file_id=fpath.stem)
                children, parents = parts["children"], parts["parents"]
                if not children:
                    details.append({"file": fpath.name, "status": "skip", "reason": "切片为空"})
                    continue
            except Exception as e:
                failed += 1
                details.append({"file": fpath.name, "status": "fail", "reason": str(e)})
                print(f"[{idx}/{total}] 失败 {fpath.name}: {e}", flush=True)
                continue

            skip = False
            if skip_enabled:
                need = {c["metadata"]["chunk_index"] for c in children}
                have = chroma_cov.get(fpath.stem)
                if have is not None and need <= have and fpath.stem in parent_files:
                    skip = True
            if skip:
                # 向量已存在不重算，但 bm25 / 父表仍幂等补写（便宜，防单独丢行）
                skipped += 1
                details.append({"file": fpath.name, "status": "skip", "reason": "已存在"})
                _write_pg({"file": fpath.name, "file_id": fpath.stem,
                           "children": children, "parents": parents})
                continue

            buf.append({
                "file": fpath.name,
                "file_id": fpath.stem,
                "children": children,
                "parents": parents,
            })
            n_children = sum(len(x["children"]) for x in buf)
            if len(buf) >= B or n_children >= child_cap:
                _flush(buf)
                buf = []
        if buf:
            _flush(buf)
            buf = []
    finally:
        if pg_conn is not None:
            pg_conn.close()

    return {
        "status": "ok",
        "total": total,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }


def sync_bm25_table() -> dict[str, Any]:
    """把 Chroma laws_docs 全量同步到 Postgres bm25 表（幂等 upsert），返回写入条数。"""
    RAG.init()
    if not RAG.is_ready():
        return {"status": "error", "message": "RAG 未就绪（Chroma 不可用）"}

    try:
        result = RAG._laws_collection.get(include=["documents", "metadatas"])
    except Exception as e:
        return {"status": "error", "message": f"读取 Chroma laws_docs 失败: {e}"}

    docs = result.get("documents") or []
    metas = result.get("metadatas") or [{}] * len(docs)
    chunks = [
        {"content": docs[i], "metadata": metas[i] or {}}
        for i in range(len(docs))
    ]
    try:
        write_bm25_table(chunks)
    except Exception as e:
        return {"status": "error", "message": f"写入 bm25 表失败: {e}"}
    return {"status": "ok", "synced": len(chunks)}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        print("同步 Chroma → bm25 表")
        result = sync_bm25_table()
        if result["status"] == "error":
            print(f"\n错误: {result['message']}")
            sys.exit(1)
        print(f"\n同步完成: 共 {result['synced']} 条法条写入 bm25 表")
        return

    args = sys.argv[1:]
    force = "--force" in args
    batch = None
    if "--batch" in args:
        try:
            batch = int(args[args.index("--batch") + 1])
        except (IndexError, ValueError):
            print("--batch 后需跟文件数，例如 --batch 10")
            sys.exit(2)

    print(f"扫描目录: {LEGAL_DIR}" + ("（强制全量重导）" if force else "（幂等：已导入文件自动跳过）"))
    result = import_legal_files(force=force, batch_files=batch)

    if result["status"] == "error":
        print(f"\n错误: {result['message']}")
        sys.exit(1)

    print(f"\n完成: 共 {result['total']} 个文件，成功 {result['imported']}，"
          f"跳过 {result.get('skipped', 0)}，失败 {result['failed']}")
    for d in result.get("details", []):
        status_icon = {"ok": "OK", "skip": "SKIP"}.get(d["status"], "FAIL")
        if d["status"] == "ok":
            detail = f"子 {d.get('children', 0)} / 父 {d.get('parents', 0)}"
        else:
            detail = d.get("reason", "")
        print(f"  [{status_icon}] {d['file']} ({detail})")


if __name__ == "__main__":
    main()
