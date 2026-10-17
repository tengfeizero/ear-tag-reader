"""
猪耳标编号识别服务
- 手机浏览器拍照 -> 后端调用 LM Studio 视觉大模型识别 -> 返回耳标编号
"""

import base64
import csv
import io
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="猪耳标识别系统")

# ---- CSV 历史记录 ----
HISTORY_CSV = Path(__file__).parent / "ear_tag_records.csv"
HISTORY_CSV_HEADER = ["timestamp", "ear_tag", "cost_ms", "source"]


def append_to_csv(ear_tag: str, cost_ms: int, source: str):
    """追加一条识别记录到 CSV"""
    is_new = not HISTORY_CSV.exists()
    with HISTORY_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(HISTORY_CSV_HEADER)
        writer.writerow([datetime.now().isoformat(), ear_tag, cost_ms, source])

# ---- 视觉大模型配置（LM Studio） ----
LM_STUDIO_URL = "http://127.0.0.1:1234/v1"


def recognize_with_vlm(image_bytes: bytes) -> str | None:
    """调用 LM Studio 视觉大模型识别耳标编号"""
    try:
        client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio", timeout=120)

        # resize 到最大 1024px，减少 token 消耗
        img = Image.open(io.BytesIO(image_bytes))
        max_size = 1024
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize(
                (int(img.size[0] * ratio), int(img.size[1] * ratio)),
                Image.LANCZOS,
            )
        if img.mode == "RGBA":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        response = client.chat.completions.create(
            model="qwen/qwen3-vl-2b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Read the ear tag number in this image. "
                                    "Format: 8 alphanumeric characters, uppercase letters and digits "
                                    "(e.g. BB134C83). Reply ONLY the 8-character number, nothing else.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                },
            ],
            max_tokens=200,
            temperature=0.0,
        )

        msg = response.choices[0].message
        # 优先从 reasoning_content 提取编号（Gemma 4 推理模型会把答案写在这里）
        import re
        text = ""
        rc = getattr(msg, "reasoning_content", None) or ""
        content = (msg.content or "").strip().upper()

        # 从 content 找（必须同时包含字母和数字，排除 THINKING 这类纯字母词）
        if content:
            m = re.search(r'(?=[A-Z]*[0-9])[A-Z0-9]{4,}', content)
            if m:
                text = m.group(0)

        # 从 reasoning_content 找
        if not text and rc:
            logger.info(f"reasoning_content(末200字): ...{rc[-200:]}")
            # 先找 "Result Formulation:" 或 "number is" 等关键词附近
            m = re.search(r'(?:Result\s*Formulation|number\s*(?:is)?)\s*:?\s*["*]*\s*([A-Z0-9]{4,})', rc.upper())
            if not m:
                m = re.search(r'(?=[A-Z]*[0-9])[A-Z0-9]{4,}', rc.upper())
            if m:
                text = m.group(1) if m.lastindex else m.group(0)

        logger.info(f"大模型返回: {text!r}")
        logger.info(f"finish_reason: {response.choices[0].finish_reason}")
        if hasattr(response, "usage"):
            logger.info(f"usage: {response.usage}")
        return text

    except Exception as e:
        logger.error(f"大模型调用失败: {e}")
        return None


# ---- 静态文件 ----
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ---- 路由 ----
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = static_dir / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/recognize")
async def recognize(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        t0 = time.time()

        text = recognize_with_vlm(image_bytes)

        cost_ms = int((time.time() - t0) * 1000)

        # 识别成功则写入 CSV
        source = "camera" if not file.filename else "upload"
        if text:
            append_to_csv(text, cost_ms, source)

        return JSONResponse({
            "code": 0,
            "data": {
                "text": text or "",
                "cost_ms": cost_ms,
                "source": "vlm",
            },
        })

    except Exception as e:
        logger.exception("识别失败")
        return JSONResponse(
            {"code": -1, "message": f"识别失败: {str(e)}"},
            status_code=500,
        )


@app.get("/api/download")
async def download_csv():
    """下载识别记录 CSV"""
    if not HISTORY_CSV.exists():
        return JSONResponse({"code": -1, "message": "暂无记录"}, status_code=404)
    return FileResponse(
        HISTORY_CSV,
        media_type="text/csv",
        filename="ear_tag_records.csv",
        headers={"Content-Disposition": "attachment; filename=ear_tag_records.csv"},
    )
@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---- 启动入口 ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
