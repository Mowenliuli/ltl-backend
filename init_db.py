"""建库 + 建表脚本：python init_db.py

- Render / Railway 等平台：DATABASE_URL 指向已存在的 PostgreSQL，跳过建库直接建表
- 本地 MySQL：先 CREATE DATABASE IF NOT EXISTS，再建表
- SQLite：直接建表
"""
import pymysql
from sqlalchemy import text

from config import settings
from database import Base, engine
from models import Conversation, Message, User  # noqa: F401 注册模型


def ensure_database():
    """MySQL 模式下先确保数据库存在（PostgreSQL / SQLite 跳过）。"""
    url = settings.database_url
    # PostgreSQL：Render 等平台已经建好库，直接跳过
    if url.startswith("postgresql"):
        print("检测到 PostgreSQL，跳过建库（平台已创建）")
        return
    # SQLite：无需建库
    if url.startswith("sqlite"):
        return
    # MySQL：手动建库
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        print(f"数据库 `{settings.MYSQL_DB}` 已就绪")
    finally:
        conn.close()


if __name__ == "__main__":
    ensure_database()
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    print("数据库表已创建：users, conversations, messages")
