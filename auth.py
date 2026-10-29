"""认证：注册、登录、JWT 签发与校验。"""
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User
from schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

# ---- 登录限流：同一用户名 60 秒内最多失败 5 次（内存实现，单进程够用）----
_LOGIN_WINDOW = 60
_LOGIN_MAX_FAILS = 5
_login_fails: dict[str, deque] = defaultdict(deque)
_login_lock = threading.Lock()


def _check_login_rate(username: str):
    now = time.monotonic()
    with _login_lock:
        q = _login_fails[username]
        while q and now - q[0] > _LOGIN_WINDOW:
            q.popleft()
        if len(q) >= _LOGIN_MAX_FAILS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "失败次数过多，请 1 分钟后再试",
            )


def _record_login_fail(username: str):
    with _login_lock:
        _login_fails[username].append(time.monotonic())


def _clear_login_fail(username: str):
    with _login_lock:
        _login_fails.pop(username, None)


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _user_from_token(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效或过期的 token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少认证头")
    return _user_from_token(cred.credentials, db)


def get_user_from_ws(websocket: WebSocket, db: Session) -> User:
    """WebSocket 场景：token 通过 query param 传入（浏览器 WS 无法自定义请求头）。

    注意：query param 可能出现在访问日志中，依赖 HTTPS/WSS 传输加密，且日志
    配置不要记录 query string。浏览器原生 WS 不支持自定义头，这是通行做法。
    """
    token = websocket.query_params.get("token", "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 token")
    return _user_from_token(token, db)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    # 用户名与昵称都要求全站唯一，注册时逐项校验
    exists = db.scalar(select(User).where(User.username == body.username))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用")
    if db.scalar(select(User).where(User.nickname == body.nickname)):
        raise HTTPException(status.HTTP_409_CONFLICT, "昵称已被占用")
    user = User(
        username=body.username,
        password_hash=pwd_context.hash(body.password),
        nickname=body.nickname,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_token(user.id))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    _check_login_rate(body.username)
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not pwd_context.verify(body.password, user.password_hash):
        _record_login_fail(body.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    _clear_login_fail(body.username)
    return TokenOut(access_token=create_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
