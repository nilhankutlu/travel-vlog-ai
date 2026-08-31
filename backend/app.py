import os
import subprocess
import asyncio
import logging
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.core.processor import VideoPipelineProcessor
from backend.models.schema import ProcessedVideoItem, RenderVideoRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Travel Vlog AI Video Maker & Indexer")

PROCESSOR: Optional[VideoPipelineProcessor] = None
PROGRESS_QUEUE = asyncio.Queue()
PROCESSED_ITEMS: List[ProcessedVideoItem] = []
CURRENT_OUTPUT_DIR = os.path.abspath("./output")

os.makedirs(CURRENT_OUTPUT_DIR, exist_ok=True)

class ProcessFolderRequest(BaseModel):
    folder_path: str
    gemini_api_key: Optional[str] = None
    whisper_model: str = "base"
    short_mode: int = 1

@app.on_event("startup")
async def startup_event():
    global PROCESSOR
    PROCESSOR = VideoPipelineProcessor()

@app.get("/api/status_stream")
async def status_stream():
    async def event_generator():
        while True:
            try:
                data = await asyncio.wait_for(PROGRESS_QUEUE.get(), timeout=15.0)
                yield {
                    "event": "progress",
                    "data": data
                }
            except asyncio.TimeoutError:
                yield {
                    "event": "ping",
                    "data": "keep-alive"
                }

    return EventSourceResponse(event_generator())

def progress_callback(filename: str, current: int, total: int, overall_ratio: float, status_msg: str):
    asyncio.run_coroutine_threadsafe(
        PROGRESS_QUEUE.put({
            "filename": filename,
            "current": current,
            "total": total,
            "overall_progress": round(overall_ratio * 100, 1),
            "status_message": status_msg
        }),
        asyncio.get_event_loop()
    )

@app.post("/api/process_folder")
async def process_folder(req: ProcessFolderRequest, background_tasks: BackgroundTasks):
    global PROCESSOR, PROCESSED_ITEMS
    if not os.path.exists(req.folder_path):
        raise HTTPException(status_code=404, detail=f"Dizin bulunamadı: {req.folder_path}")

    PROCESSOR = VideoPipelineProcessor(
        whisper_model=req.whisper_model,
        gemini_api_key=req.gemini_api_key
    )

    def run_batch():
        global PROCESSED_ITEMS
        try:
            PROCESSED_ITEMS = PROCESSOR.process_directory(
                directory_path=req.folder_path,
                output_dir=CURRENT_OUTPUT_DIR,
                progress_cb=progress_callback
            )
            asyncio.run_coroutine_threadsafe(
                PROGRESS_QUEUE.put({
                    "filename": "ALL",
                    "current": len(PROCESSED_ITEMS),
                    "total": len(PROCESSED_ITEMS),
                    "overall_progress": 100.0,
                    "status_message": "Tüm videolar ve seçilen Shorts/Reels Modu senaryoları başarıyla oluşturuldu!"
                }),
                asyncio.get_event_loop()
            )
        except Exception as e:
            logger.error(f"Batch processing error: {e}")

    background_tasks.add_task(run_batch)
    return {"message": "Batch video işleme başlatıldı", "folder": req.folder_path}

@app.post("/api/upload_video")
async def upload_video(file: UploadFile = File(...), gemini_api_key: Optional[str] = Form(None), short_mode: int = Form(1)):
    global PROCESSOR, PROCESSED_ITEMS
    temp_dir = os.path.join(CURRENT_OUTPUT_DIR, "uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    file_path = os.path.join(temp_dir, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    if gemini_api_key:
        PROCESSOR.vision_analyzer.api_key = gemini_api_key

    item = PROCESSOR.process_single_video(file_path)
    PROCESSED_ITEMS.append(item)

    storyboard = PROCESSOR.vlog_generator.generate_storyboard(PROCESSED_ITEMS, short_mode=short_mode)

    return {
        "item": item.model_dump(),
        "total_processed": len(PROCESSED_ITEMS),
        "storyboard": storyboard.model_dump()
    }

@app.post("/api/render_video")
async def render_video(req: RenderVideoRequest, background_tasks: BackgroundTasks):
    py_bin = os.path.abspath("./venv/bin/python3")
    if not os.path.exists(py_bin):
        py_bin = "python3"

    def run_render():
        try:
            fmt = req.video_format.lower()
            scripts_to_run = []

            if fmt in ["long", "both"]:
                scripts_to_run.append((os.path.join(CURRENT_OUTPUT_DIR, "render_long_vlog.py"), "🎬 Yatay 16:9 Long-Form Vlog"))
            if fmt in ["short", "both"]:
                scripts_to_run.append((os.path.join(CURRENT_OUTPUT_DIR, "render_short_vlog.py"), "📱 Dik 9:16 Short-Form Reels/TikTok"))

            for script_p, label in scripts_to_run:
                if os.path.exists(script_p):
                    asyncio.run_coroutine_threadsafe(
                        PROGRESS_QUEUE.put({
                            "filename": label,
                            "current": 1,
                            "total": 1,
                            "overall_progress": 50.0,
                            "status_message": f"{label} kurgulanıyor ve oluşturuluyor..."
                        }),
                        asyncio.get_event_loop()
                    )
                    res = subprocess.run([py_bin, script_p], capture_output=True, text=True)
                    logger.info(f"{label} stdout: {res.stdout}")

            asyncio.run_coroutine_threadsafe(
                PROGRESS_QUEUE.put({
                    "filename": "ALL_RENDER",
                    "current": 1,
                    "total": 1,
                    "overall_progress": 100.0,
                    "status_message": "🎉 Tüm seçilen video formatları (Long / Short) başarıyla oluşturuldu!"
                }),
                asyncio.get_event_loop()
            )
        except Exception as e:
            logger.error(f"Render failure: {e}")

    background_tasks.add_task(run_render)
    return {"message": f"{req.video_format} video kurgusu başlatıldı"}

@app.get("/api/results")
async def get_results(short_mode: int = 1):
    global PROCESSED_ITEMS, PROCESSOR
    if not PROCESSOR:
        PROCESSOR = VideoPipelineProcessor()

    storyboard = PROCESSOR.vlog_generator.generate_storyboard(PROCESSED_ITEMS, short_mode=short_mode)
    
    long_exists = os.path.exists(os.path.join(CURRENT_OUTPUT_DIR, "final_travel_vlog_long.mp4"))
    short_exists = os.path.exists(os.path.join(CURRENT_OUTPUT_DIR, "final_travel_vlog_short.mp4"))

    return {
        "total": len(PROCESSED_ITEMS),
        "videos": [item.model_dump() for item in PROCESSED_ITEMS],
        "storyboard": storyboard.model_dump(),
        "rendered_long_video_url": "/media/final_travel_vlog_long.mp4" if long_exists else None,
        "rendered_short_video_url": "/media/final_travel_vlog_short.mp4" if short_exists else None
    }

# Static Mounts
app.mount("/media", StaticFiles(directory=CURRENT_OUTPUT_DIR), name="media")
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def read_root():
    index_path = os.path.join(frontend_dir, "index.html")
    return FileResponse(index_path)
