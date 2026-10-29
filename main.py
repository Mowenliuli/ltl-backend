"""应用入口：CORS 全开放（按用户要求）、路由挂载、WebSocket 端点、上传文件下载。"""
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from auth import get_user_from_ws, router as auth_router
from config import settings
from database import SessionLocal, engine, Base
from routes import chat, files, groups, users
from ws import websocket_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="ltl-web IM API", version="0.1.0")

# CORS 全开放（用户明确要求）。token 走 Authorization 头而非 Cookie，无凭证泄露风险。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users.router)
app.include_router(chat.router)
app.include_router(groups.router)
app.include_router(files.router)

# 上传目录仅确保存在；下载走 /api/files/download 鉴权接口，不再匿名静态挂载
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def init_db():
    """启动时自动建表（免费版 Render 无 Shell，用启动钩子代替）。"""
    try:
        Base.metadata.create_all(engine)
        logging.info("数据库表已就绪")
    except Exception as e:
        logging.error(f"数据库表创建失败: {e}")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    with SessionLocal() as db:
        try:
            user = get_user_from_ws(websocket, db)
        except Exception:
            await websocket.close(code=4401)
            return
    await websocket_loop(websocket, user)


@app.get("/api/health")
def health():
    return {"status": "ok"}
