"""会话公共逻辑：私聊/群聊统一处理。

WebSocket 协议（JSON）：
  客户端 → 服务端: {"action": "send", "peer_id": 2, ...}   # 私聊
                   {"action": "send", "conv_id": 5, ...}   # 按会话发（群聊/私聊均可）
                   {"action": "ping"}
  服务端 → 客户端: {"event": "message", "data": {MessageOut}}  # 收到新消息
                   {"event": "sent",    "data": {MessageOut}}  # 发送者回执
                   {"event": "group_updated", "data": {"conversation_id": 5, "by": "..."}}
                   {"event": "pong"} / {"event": "error", "detail": "..."}

连接：ws://host/ws?token=<JWT>
"""
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import Conversation, GroupMember, Message, User
from schemas import MessageOut, UserOut

logger = logging.getLogger(__name__)


class ConnectionManager:
    """user_id -> WebSocket。单进程内存管理，够用且零依赖。"""

    def __init__(self):
        self._conns: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        # 同一账号已有连接（旧标签页/重连残留）：先关掉旧连接，避免映射被旧连接断开时误删
        old = self._conns.get(user_id)
        if old is not None and old is not ws:
            try:
                await old.close(code=4000)
            except Exception:
                pass
        self._conns[user_id] = ws
        logger.info("WS connected: user=%s online=%s", user_id, len(self._conns))

    def disconnect(self, user_id: int, ws: WebSocket | None = None):
        # 仅当当前映射仍是该连接时才移除，防止旧连接的断开事件删掉新连接的映射
        if ws is not None and self._conns.get(user_id) is not ws:
            return
        self._conns.pop(user_id, None)
        logger.info("WS disconnected: user=%s online=%s", user_id, len(self._conns))

    async def send_to(self, user_id: int, payload: dict) -> bool:
        ws = self._conns.get(user_id)
        if not ws:
            return False
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            return True
        except Exception:
            self.disconnect(user_id, ws)
            return False

    async def send_to_many(self, user_ids, payload: dict):
        for uid in user_ids:
            await self.send_to(uid, payload)


manager = ConnectionManager()


# ---- 会话工具 ----

def get_or_create_direct(db, a: int, b: int) -> Conversation:
    """获取或创建一对一会话（user_low_id < user_high_id 保证唯一）。"""
    low, high = sorted((a, b))
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.kind == "direct",
            Conversation.user_low_id == low,
            Conversation.user_high_id == high,
        )
        .first()
    )
    if not conv:
        conv = Conversation(kind="direct", user_low_id=low, user_high_id=high)
        db.add(conv)
        try:
            db.commit()
        except IntegrityError:
            # 并发下另一请求已创建同一会话（uq_pair 冲突），回滚后重查
            db.rollback()
            conv = (
                db.query(Conversation)
                .filter(
                    Conversation.kind == "direct",
                    Conversation.user_low_id == low,
                    Conversation.user_high_id == high,
                )
                .first()
            )
            if conv:
                return conv
            raise
        db.refresh(conv)
    return conv


def create_group(db, owner_id: int, name: str, member_ids: list[int]) -> Conversation:
    conv = Conversation(kind="group", name=name, owner_id=owner_id)
    db.add(conv)
    db.flush()
    all_ids = {owner_id, *member_ids}
    for uid in all_ids:
        db.add(GroupMember(
            conversation_id=conv.id,
            user_id=uid,
            role="owner" if uid == owner_id else "member",
        ))
    db.commit()
    db.refresh(conv)
    return conv


def member_ids_of(db, conv_id: int) -> list[int]:
    return [m.user_id for m in db.query(GroupMember).filter(GroupMember.conversation_id == conv_id)]


def is_member(db, conv_id: int, user_id: int) -> bool:
    return (
        db.query(GroupMember)
        .filter(GroupMember.conversation_id == conv_id, GroupMember.user_id == user_id)
        .first()
        is not None
    )


def participant_ids(db, conv: Conversation) -> list[int]:
    """会话全部参与者 id（私聊 2 人，群聊全部成员）。"""
    if conv.kind == "group":
        return member_ids_of(db, conv.id)
    return [conv.user_low_id, conv.user_high_id]


def can_access_conv(db, conv: Conversation, user_id: int) -> bool:
    if conv.kind == "group":
        return is_member(db, conv.id, user_id)
    return user_id in (conv.user_low_id, conv.user_high_id)


def message_payload(db, msg: Message) -> dict:
    out = MessageOut.model_validate(msg).model_dump(mode="json")
    sender = db.get(User, msg.sender_id)
    out["sender"] = UserOut.model_validate(sender).model_dump(mode="json") if sender else None
    return out


def save_message(db, sender_id: int, conv_id: int, type_: str, content: str, extra: str = "") -> Message:
    msg = Message(
        conversation_id=conv_id,
        sender_id=sender_id,
        type=type_,
        content=content,
        extra=extra or "",
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


async def broadcast_new_message(db, msg: Message, exclude: set[int] | None = None):
    """把新消息推给会话内所有在线成员。"""
    conv = db.get(Conversation, msg.conversation_id)
    payload = message_payload(db, msg)
    for uid in participant_ids(db, conv):
        if exclude and uid in exclude:
            continue
        event = "sent" if uid == msg.sender_id else "message"
        await manager.send_to(uid, {"event": event, "data": payload})


async def notify_group_updated(db, conv_id: int, by: str):
    """群信息变更（改名/加人/踢人/退群）时通知全体成员刷新。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        return
    await manager.send_to_many(
        participant_ids(db, conv),
        {"event": "group_updated", "data": {"conversation_id": conv_id, "by": by}},
    )


# ---- WebSocket 主循环 ----

async def websocket_loop(websocket: WebSocket, user: User):
    await manager.connect(user.id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_to(user.id, {"event": "error", "detail": "非法 JSON"})
                continue

            action = data.get("action")
            if action == "ping":
                await manager.send_to(user.id, {"event": "pong"})
                continue
            if action != "send":
                await manager.send_to(user.id, {"event": "error", "detail": f"未知 action: {action}"})
                continue

            msg_type = data.get("type", "text")
            content = str(data.get("content", "")).strip()
            extra = str(data.get("extra", ""))

            if msg_type not in ("text", "image", "voice", "file"):
                await manager.send_to(user.id, {"event": "error", "detail": "非法消息类型"})
                continue
            if not content:
                await manager.send_to(user.id, {"event": "error", "detail": "内容为空"})
                continue
            if msg_type == "text" and len(content) > 5000:
                await manager.send_to(user.id, {"event": "error", "detail": "文本过长"})
                continue
            # 非文本消息的内容只能来自本服务文件下载接口路径，
            # 防止伪造 javascript:/外链 URL 造成存储型 XSS
            if msg_type != "text" and not content.startswith("/api/files/download/"):
                await manager.send_to(user.id, {"event": "error", "detail": "非文本消息必须通过上传接口发送"})
                continue

            with SessionLocal() as db:
                conv = None
                conv_id = data.get("conv_id")
                peer_id = data.get("peer_id")
                try:
                    conv_id = int(conv_id) if conv_id else None
                    peer_id = int(peer_id) if peer_id else None
                except (TypeError, ValueError):
                    await manager.send_to(user.id, {"event": "error", "detail": "conv_id/peer_id 必须是数字"})
                    continue
                if conv_id:
                    conv = db.get(Conversation, conv_id)
                    if not conv or not can_access_conv(db, conv, user.id):
                        await manager.send_to(user.id, {"event": "error", "detail": "会话不存在或无权限"})
                        continue
                elif peer_id:
                    peer = db.get(User, peer_id)
                    if not peer:
                        await manager.send_to(user.id, {"event": "error", "detail": "对方用户不存在"})
                        continue
                    conv = get_or_create_direct(db, user.id, peer.id)
                else:
                    await manager.send_to(user.id, {"event": "error", "detail": "缺少 conv_id 或 peer_id"})
                    continue

                msg = save_message(db, user.id, conv.id, msg_type, content, extra)
                await broadcast_new_message(db, msg)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user.id, websocket)
