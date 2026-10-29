"""群聊管理：创建群、详情、改名、加人、踢人、退群。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Conversation, GroupMember, User
from schemas import ConversationOut, GroupCreateIn, GroupMemberOut, GroupMembersIn, GroupRenameIn, UserOut
from ws import create_group, is_member, member_ids_of, notify_group_updated

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _get_group_or_404(db: Session, conv_id: int) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or conv.kind != "group":
        raise HTTPException(404, "群不存在")
    return conv


def _require_member(db: Session, conv_id: int, user_id: int):
    if not is_member(db, conv_id, user_id):
        raise HTTPException(403, "你不在该群中")


def _require_owner(conv: Conversation, user_id: int):
    if conv.owner_id != user_id:
        raise HTTPException(403, "仅群主可操作")


def _member_out(db: Session, m: GroupMember) -> GroupMemberOut:
    return GroupMemberOut(
        user=UserOut.model_validate(db.get(User, m.user_id)),
        role=m.role,
        joined_at=m.joined_at,
    )


def group_detail(db: Session, conv: Conversation, with_members: bool = False) -> ConversationOut:
    members = db.query(GroupMember).filter(GroupMember.conversation_id == conv.id).all()
    return ConversationOut(
        id=conv.id,
        kind="group",
        name=conv.name,
        owner_id=conv.owner_id,
        member_count=len(members),
        members=[_member_out(db, m) for m in members] if with_members else None,
        created_at=conv.created_at,
    )


@router.post("", response_model=ConversationOut, status_code=201)
def create(body: GroupCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 过滤掉不存在的用户和自己
    valid_ids = [uid for uid in set(body.member_ids) if uid != user.id and db.get(User, uid)]
    conv = create_group(db, user.id, body.name, valid_ids)
    return group_detail(db, conv, with_members=True)


@router.get("/{conv_id}", response_model=ConversationOut)
def detail(conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _get_group_or_404(db, conv_id)
    _require_member(db, conv_id, user.id)
    return group_detail(db, conv, with_members=True)


@router.patch("/{conv_id}", response_model=ConversationOut)
async def rename(conv_id: int, body: GroupRenameIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _get_group_or_404(db, conv_id)
    _require_owner(conv, user.id)
    conv.name = body.name
    db.commit()
    await notify_group_updated(db, conv_id, by="rename")
    return group_detail(db, conv, with_members=True)


@router.post("/{conv_id}/members", response_model=ConversationOut)
async def add_members(conv_id: int, body: GroupMembersIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """群主添加成员。"""
    conv = _get_group_or_404(db, conv_id)
    _require_owner(conv, user.id)
    existing = set(member_ids_of(db, conv_id))
    added = 0
    for uid in set(body.user_ids):
        if uid in existing or not db.get(User, uid):
            continue
        db.add(GroupMember(conversation_id=conv_id, user_id=uid, role="member"))
        added += 1
    db.commit()
    if added:
        await notify_group_updated(db, conv_id, by="add_members")
    return group_detail(db, conv, with_members=True)


@router.delete("/{conv_id}/members/{uid}", response_model=ConversationOut)
async def remove_member(conv_id: int, uid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """群主移除成员（不能移除自己/群主）。"""
    conv = _get_group_or_404(db, conv_id)
    _require_owner(conv, user.id)
    if uid == conv.owner_id:
        raise HTTPException(400, "不能移除群主")
    m = (
        db.query(GroupMember)
        .filter(GroupMember.conversation_id == conv_id, GroupMember.user_id == uid)
        .first()
    )
    if not m:
        raise HTTPException(404, "该用户不在群中")
    db.delete(m)
    db.commit()
    await notify_group_updated(db, conv_id, by="remove_member")
    # 通知被移除者：会话列表需要刷新
    from ws import manager
    await manager.send_to(uid, {"event": "group_updated", "data": {"conversation_id": conv_id, "by": "removed"}})
    return group_detail(db, conv, with_members=True)


@router.post("/{conv_id}/leave", status_code=204)
async def leave(conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """退群。群主退群则解散整个群。"""
    conv = _get_group_or_404(db, conv_id)
    _require_member(db, conv_id, user.id)
    if conv.owner_id == user.id:
        # 解散群：先取成员列表，再删消息、成员、会话，最后通知
        from models import Message
        member_ids = member_ids_of(db, conv_id)
        db.query(Message).filter(Message.conversation_id == conv_id).delete()
        db.query(GroupMember).filter(GroupMember.conversation_id == conv_id).delete()
        db.delete(conv)
        db.commit()
        from ws import manager
        await manager.send_to_many(member_ids, {"event": "group_updated", "data": {"conversation_id": conv_id, "by": "dissolve"}})
        return
    db.query(GroupMember).filter(
        GroupMember.conversation_id == conv_id, GroupMember.user_id == user.id
    ).delete()
    db.commit()
    await notify_group_updated(db, conv_id, by="leave")
