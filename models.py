"""数据模型：用户、会话（私聊/群聊）、群成员、消息。

Conversation.kind:
  direct - 一对一私聊（user_low_id/user_high_id 保证唯一）
  group  - 群聊（owner_id 为群主，成员见 GroupMember）

Message.type: text / image / voice / file
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nickname: Mapped[str] = mapped_column(String(50), unique=True, default="")
    avatar: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_low_id", "user_high_id", name="uq_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10), default="direct", index=True)  # direct / group
    # 私聊字段（group 时为 0）
    user_low_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    user_high_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 群聊字段
    name: Mapped[str] = mapped_column(String(100), default="")
    owner_id: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")
    members: Mapped[list["GroupMember"]] = relationship(back_populates="conversation")


class GroupMember(Base):
    """群成员。role: owner / member（预留 admin）。"""

    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_group_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="members")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(10))  # text / image / voice / file
    content: Mapped[str] = mapped_column(Text)     # 文本内容或文件 URL
    extra: Mapped[str] = mapped_column(String(500), default="")  # JSON 元信息
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
