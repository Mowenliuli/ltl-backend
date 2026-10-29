"""数据库迁移：私聊+群聊架构升级。

执行：python migrate_group.py
变更：
  conversations: + kind, + name, + owner_id；user_low_id/user_high_id 改允许 NULL/默认 0
  新建 group_members 表
"""
from sqlalchemy import text

from database import Base, engine
from models import GroupMember  # noqa: F401


def migrate():
    with engine.begin() as conn:
        cols = [c["name"] for c in conn.execute(text(
            "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'conversations'"
        )).mappings()] if engine.dialect.name == "mysql" else []

        if engine.dialect.name == "mysql":
            if "kind" not in cols:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'direct'"))
                conn.execute(text("ALTER TABLE conversations ADD COLUMN name VARCHAR(100) NOT NULL DEFAULT ''"))
                conn.execute(text("ALTER TABLE conversations ADD COLUMN owner_id INT NOT NULL DEFAULT 0"))
                conn.execute(text("ALTER TABLE conversations ADD INDEX ix_conversations_kind (kind)"))
                print("conversations 新增 kind/name/owner_id")
            # user_low_id/user_high_id 允许默认 0（群聊行不用）
            conn.execute(text("ALTER TABLE conversations MODIFY COLUMN user_low_id INT NOT NULL DEFAULT 0"))
            conn.execute(text("ALTER TABLE conversations MODIFY COLUMN user_high_id INT NOT NULL DEFAULT 0"))
            print("conversations user_low/high 默认值调整完成")
        else:
            # SQLite 本地开发：直接重建（数据量小，简单处理）
            print("SQLite 环境，直接 create_all 新表（旧表结构不变，建议删除 dev.db 重建）")

    Base.metadata.create_all(engine)
    print("group_members 表已创建（如不存在）")


if __name__ == "__main__":
    migrate()
