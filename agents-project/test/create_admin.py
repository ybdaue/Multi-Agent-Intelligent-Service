"""创建管理员账号：往 User 表写入用户 + Account 表写入 scrypt 密码。

密码格式兼容 better-auth（salt:key，scrypt N=16384 r=16 p=1 dkLen=64）。

用法：
    python tests/create_admin.py
"""
import getpass
import hashlib
import os
import sys
import uuid
from pathlib import Path

# ── 环境加载（同 test_rerank_model.py 模式）──────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

_mode = os.getenv("APP_ENV", "").strip().lower()
_candidates = [".env.development", ".env"] if _mode not in ("production", "prod") else [".env", ".env.development"]
_env_path = next((PROJECT_ROOT / c for c in _candidates if (PROJECT_ROOT / c).exists()), None)
if _env_path is not None:
    load_dotenv(_env_path, override=True)
    print(f"loaded env: {_env_path.name}")


def _hash_password(password: str) -> str:
    """与 better-auth 兼容的 scrypt 密码哈希，格式 salt:key。

    Node.js crypto.scrypt 传 string salt 时会按 UTF-8 编码，
    所以 salt 字节数 = hex 字符串长度（32），而非原始 16 字节。
    """
    import unicodedata
    raw = os.urandom(16)
    salt_hex = raw.hex()               # 32 字符，存进 hash
    salt_utf8 = salt_hex.encode("utf-8")  # 32 字节，传给 scrypt
    key = hashlib.scrypt(
        unicodedata.normalize("NFKC", password).encode("utf-8"),
        salt=salt_utf8,
        n=16384,
        r=16,
        p=1,
        dklen=64,
        maxmem=128 * 16384 * 16 * 2,  # 匹配 Node.js 的 maxmem 设置
    )
    return f"{salt_hex}:{key.hex()}"


def main():
    import psycopg

    # ── 终端输入 ──────────────────────────────────────────
    email = input("邮箱: ").strip()
    if not email:
        print("邮箱不能为空")
        sys.exit(1)

    name = input("昵称（可选，直接回车跳过）: ").strip() or None

    print("角色：1) superAdmin  2) admin")
    role_choice = input("请选择 [1/2]（默认 1）: ").strip() or "1"
    role = "superAdmin" if role_choice == "1" else "admin"

    password = getpass.getpass("密码: ")
    if not password:
        print("密码不能为空")
        sys.exit(1)
    password2 = getpass.getpass("确认密码: ")
    if password != password2:
        print("两次密码不一致")
        sys.exit(1)

    # ── 写库 ──────────────────────────────────────────────
    pg_url = os.getenv("postgreSQL_URL") or os.getenv("DATABASE_URL")
    if not pg_url:
        print("错误：未设置 postgreSQL_URL 或 DATABASE_URL")
        sys.exit(1)

    conn = psycopg.connect(pg_url)
    try:
        with conn.cursor() as cur:
            # 查重
            cur.execute('SELECT id, role FROM "User" WHERE email = %s', (email,))
            existing = cur.fetchone()
            if existing:
                print(f"用户 {email} 已存在（role={existing[1]}），跳过创建")
                sys.exit(0)

            # 创建用户
            user_id = uuid.uuid4().hex
            cur.execute(
                """INSERT INTO "User" (id, email, name, role, "emailVerified", "createdAt", "updatedAt")
                   VALUES (%s, %s, %s, %s, true, now(), now())""",
                (user_id, email, name, role),
            )

            # 创建 Account 记录（scrypt 哈希，兼容 better-auth）
            hashed = _hash_password(password)
            account_id = uuid.uuid4().hex
            cur.execute(
                """INSERT INTO "Account" (id, "accountId", "providerId", "userId", password, "createdAt", "updatedAt")
                   VALUES (%s, %s, 'credential', %s, %s, now(), now())""",
                (account_id, email, user_id, hashed),
            )

            # 创建 BillingAccount（不然登录后计费会报错）
            cur.execute(
                """INSERT INTO "BillingAccount" ("userId", balance, version, "createdAt", "updatedAt")
                   VALUES (%s, 0, 1, now(), now()) ON CONFLICT ("userId") DO NOTHING""",
                (user_id,),
            )

        conn.commit()
        print(f"\n✅ 管理员创建成功")
        print(f"   邮箱: {email}")
        print(f"   角色: {role}")
        print(f"   ID:   {user_id}")
    except Exception as e:
        conn.rollback()
        print(f"创建失败: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()