"""Pydantic 请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# bcrypt 只取密码前 72 字节，超长部分被静默截断；注册时限制字节长度避免误解
MAX_PASSWORD_BYTES = 72


def _check_password_bytes(v: str) -> str:
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"密码过长（utf-8 编码后不能超过 {MAX_PASSWORD_BYTES} 字节）")
    return v


# ---- 认证 ----
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    nickname: str = Field(min_length=1, max_length=50)

    _password_bytes = field_validator("password")(_check_password_bytes)


class LoginIn(BaseModel):
    username: str
    password: str

    _password_bytes = field_validator("password")(_check_password_bytes)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str
    avatar: str

    model_config = {"from_attributes": True}


# ---- 聊天 ----
class MessageOut(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    type: str
    content: str
    extra: str
    created_at: datetime
    # 群聊场景附带发送者信息，前端展示昵称/头像
    sender: UserOut | None = None

    model_config = {"from_attributes": True}


class GroupMemberOut(BaseModel):
    user: UserOut
    role: str  # owner / member
    joined_at: datetime


class ConversationOut(BaseModel):
    id: int
    kind: str  # direct / group
    # 私聊
    peer: UserOut | None = None
    # 群聊
    name: str = ""
    owner_id: int = 0
    member_count: int = 0
    members: list[GroupMemberOut] | None = None  # 仅详情接口返回
    # 公共
    last_message: MessageOut | None = None
    created_at: datetime


# ---- 群聊管理 ----
class GroupCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_ids: list[int] = Field(default_factory=list, max_length=200)


class GroupRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupMembersIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=200)
