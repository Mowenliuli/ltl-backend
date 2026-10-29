"""用户接口：搜索用户（用于发起新会话）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import User
from schemas import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/search", response_model=list[UserOut])
def search_users(
    q: str = Query(min_length=1, max_length=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(User)
        .where(User.username.contains(q) | User.nickname.contains(q))
        .where(User.id != user.id)
        .limit(20)
    )
    return db.scalars(stmt).all()
