"""文件上传 API - 本地存储"""
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from loguru import logger

router = APIRouter(prefix="/upload", tags=["文件上传"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".avi", ".webm"}


@router.post("/work-order-image", summary="上传工单附件图片/视频")
async def upload_work_order_image(file: UploadFile = File(...)):
    """上传图片或视频，返回文件 URL"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    # 确保目录存在
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # 生成唯一文件名: YYYYMMDD_uuid.ext
    date_str = datetime.now().strftime("%Y%m%d")
    unique_name = f"{date_str}_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 返回可访问的 URL（通过静态文件服务）
    url = f"/api/v1/upload/files/{unique_name}"

    logger.info(f"[Upload] 文件上传成功: {unique_name} ({len(content)} bytes)")
    return {
        "url": url,
        "name": file.filename,
        "size": len(content),
        "type": "video" if ext in {".mp4", ".mov", ".avi", ".webm"} else "image",
    }
