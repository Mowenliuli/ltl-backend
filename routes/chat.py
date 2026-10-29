"""会话与历史消息接口（私聊 + 群聊统一列表）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Conversation, GroupMember, Message, User
from schemas import ConversationOut, MessageOut, UserOut
from ws import can_access_conv, get_or_create_direct, message_payload

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _conv_out(db: Session, conv: Conversation, me_id: int) -> ConversationOut:
    last = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id.desc())
        .first()
    )
    last_out = None
    if last:
        payload = message_payload(db, last)
        last_out = MessageOut(**payload)

    if conv.kind == "group":
        member_count = db.query(GroupMember).filter(GroupMember.conversation_id == conv.id).count()
        return ConversationOut(
            id=conv.id,
            kind="group",
            name=conv.name,
            owner_id=conv.owner_id,
            member_count=member_count,
            last_message=last_out,
            created_at=conv.created_at,
        )

    peer_id = conv.user_high_id if conv.user_low_id == me_id else conv.user_low_id
    peer = db.get(User, peer_id)
    return ConversationOut(
        id=conv.id,
        kind="direct",
        peer=UserOut.model_validate(peer),
        last_message=last_out,
        created_at=conv.created_at,
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """我的会话列表（私聊 + 我所在的群），按最后消息时间倒序。"""
    directs = (
        db.query(Conversation)
        .filter(
            Conversation.kind == "direct",
            (Conversation.user_low_id == user.id) | (Conversation.user_high_id == user.id),
        )
        .all()
    )
    group_ids = [
        m.conversation_id
        for m in db.query(GroupMember).filter(GroupMember.user_id == user.id)
    ]
    groups = (
        db.query(Conversation)
        .filter(Conversation.kind == "group", Conversation.id.in_(group_ids))
        .all()
        if group_ids
        else []
    )
    result = [_conv_out(db, c, user.id) for c in (*directs, *groups)]
    result.sort(
        key=lambda c: c.last_message.created_at if c.last_message else c.created_at,
        reverse=True,
    )
    return result


@router.get("/recent-contacts", response_model=list[UserOut])
def recent_contacts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """最近有私聊往来的用户列表（按最后消息时间倒序），用于建群/拉人时快速勾选。"""
    directs = (
        db.query(Conversation)
        .filter(
            Conversation.kind == "direct",
            (Conversation.user_low_id == user.id) | (Conversation.user_high_id == user.id),
        )
        .all()
    )
    peers = []
    for conv in directs:
        peer_id = conv.user_high_id if conv.user_low_id == user.id else conv.user_low_id
        last = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .first()
        )
        peers.append((last.created_at if last else conv.created_at, peer_id))
    peers.sort(key=lambda x: x[0], reverse=True)
    users = [db.get(User, pid) for _, pid in peers]
    return [u for u in users if u]


@router.post("/conversations/{peer_id}", response_model=ConversationOut, status_code=201)
def open_conversation(peer_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """与指定用户发起（或获取已有）私聊会话。"""
    peer = db.get(User, peer_id)
    if not peer:
        raise HTTPException(404, "用户不存在")
    if peer.id == user.id:
        raise HTTPException(400, "不能与自己会话")
    conv = get_or_create_direct(db, user.id, peer_id)
    return _conv_out(db, conv, user.id)


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def list_messages(
    conv_id: int,
    before_id: int | None = Query(default=None, description="分页：拉取此消息 id 之前的历史"),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conv_id)
    if not conv or not can_access_conv(db, conv, user.id):
        raise HTTPException(404, "会话不存在或无权限")
    q = db.query(Message).filter(Message.conversation_id == conv_id)
    if before_id:
        q = q.filter(Message.id < before_id)
    msgs = q.order_by(Message.id.desc()).limit(limit).all()
    msgs.reverse()
    return [MessageOut(**message_payload(db, m)) for m in msgs]
