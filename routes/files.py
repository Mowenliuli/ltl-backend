"""文件上传/下载。

上传成功后返回 URL。若带 conv_id 或 peer_id，服务端直接生成消息并推送给会话成员。
静态文件由 FastAPI 的 StaticFiles 挂载提供下载。
"""
import json as _json
import logging
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from config import settings
from database import get_db
from models import Conversation, User
from ws import broadcast_new_message, can_access_conv, get_or_create_direct, save_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_KINDS = ("image", "voice", "file")

EXT_WHITELIST = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "voice": {".mp3", ".m4a", ".aac", ".ogg", ".wav", ".webm"},
    "file": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
             ".txt", ".zip", ".rar", ".7z", ".md", ".csv", ".json"},
}


@router.get("/download/{kind}/{filename}")
def download(kind: str, filename: str, user: User = Depends(get_current_user)):
    """上传文件下载：需要登录（防止匿名遍历），并强制安全响应头。

    - X-Content-Type-Options: nosniff 阻止浏览器把文件嗅探为可执行内容
    - file 类型强制 Content-Disposition: attachment 下载而非内联渲染
    """
    if kind not in ALLOWED_KINDS:
        raise HTTPException(404, "文件不存在")
    # filename 是服务端生成的 uuid+扩展名，拒绝路径分隔符防目录穿越
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(404, "文件不存在")
    path = Path(settings.UPLOAD_DIR) / kind / filename
    if not path.is_file():
        raise HTTPException(404, "文件不存在")

    headers = {"X-Content-Type-Options": "nosniff"}
    media_type = mimetypes.guess_type(filename)[0]
    if kind == "file":
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return FileResponse(path, media_type=media_type, headers=headers)


@router.post("/upload", status_code=201)
async def upload(
    file: UploadFile,
    kind: str = "file",
    conv_id: int | None = None,
    peer_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if kind not in ALLOWED_KINDS:
        raise HTTPException(400, f"kind 必须是 {ALLOWED_KINDS} 之一")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in EXT_WHITELIST[kind]:
        raise HTTPException(400, f"{kind} 不允许 {ext or '(无扩展名)'} 格式")

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"文件超过 {settings.MAX_UPLOAD_MB}MB 上限")

    # 目标会话校验（若要求直接发消息）
    conv = None
    if conv_id:
        conv = db.get(Conversation, conv_id)
        if not conv or not can_access_conv(db, conv, user.id):
            raise HTTPException(404, "会话不存在或无权限")
    elif peer_id:
        peer = db.get(User, peer_id)
        if not peer:
            raise HTTPException(404, "对方用户不存在")
        conv = get_or_create_direct(db, user.id, peer_id)

    upload_dir = Path(settings.UPLOAD_DIR) / kind
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (upload_dir / filename).write_bytes(data)

    url = f"/api/files/download/{kind}/{filename}"
    extra = {"name": file.filename, "size": len(data)}
    logger.info("upload: user=%s kind=%s size=%s", user.id, kind, len(data))

    result = {"url": url, "name": file.filename, "size": len(data), "kind": kind}

    if conv:
        msg = save_message(db, user.id, conv.id, kind, url, _json.dumps(extra, ensure_ascii=False))
        await broadcast_new_message(db, msg)
        from ws import message_payload
        result["message"] = message_payload(db, msg)

    return result
