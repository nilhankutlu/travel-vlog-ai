import os
import asyncio
import logging
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.core.processor import VideoPipelineProcessor
from backend.models.schema import ProcessedVideoItem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Travel Vlog AI Video Maker & Indexer")

# Global State
PROCESSOR: Optional[VideoPipelineProcessor] = None
PROGRESS_QUEUE = asyncio.Queue()
PROCESSED_ITEMS: List[ProcessedVideoItem] = []
CURRENT_OUTPUT_DIR = os.path.abspath("./output")

os.makedirs(CURRENT_OUTPUT_DIR, exist_ok=True)

class ProcessFolderRequest(BaseModel):
    folder_path: str
    gemini_api_key: Optional[str] = None
    whisper_model: str = "base"

@app.on_event("startup")
async def startup_event():
    global PROCESSOR
    PROCESSOR = VideoPipelineProcessor()

@app.get("/api/status_stream")
async def status_stream():
    """Server-Sent Events endpoint for live progress update streaming."""
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
                    "status_message": "Tüm videolar başarıyla işlendi ve Vlog Senaryosu oluşturuldu!"
                }),
                asyncio.get_event_loop()
            )
        except Exception as e:
            logger.error(f"Batch processing error: {e}")

    background_tasks.add_task(run_batch)
    return {"message": "Batch video işleme başlatıldı", "folder": req.folder_path}

@app.post("/api/upload_video")
async def upload_video(file: UploadFile = File(...), gemini_api_key: Optional[str] = Form(None)):
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

    # Update storyboard
    storyboard = PROCESSOR.vlog_generator.generate_storyboard(PROCESSED_ITEMS)

    return {
        "item": item.model_dump(),
        "total_processed": len(PROCESSED_ITEMS),
        "storyboard": storyboard.model_dump()
    }

@app.get("/api/results")
async def get_results():
    global PROCESSED_ITEMS, PROCESSOR
    if not PROCESSOR:
        PROCESSOR = VideoPipelineProcessor()

    storyboard = PROCESSOR.vlog_generator.generate_storyboard(PROCESSED_ITEMS)
    return {
        "total": len(PROCESSED_ITEMS),
        "videos": [item.model_dump() for item in PROCESSED_ITEMS],
        "storyboard": storyboard.model_dump()
    }

@app.get("/api/export_prompt")
async def export_prompt():
    global PROCESSED_ITEMS, PROCESSOR
    if not PROCESSOR:
        PROCESSOR = VideoPipelineProcessor()
    storyboard = PROCESSOR.vlog_generator.generate_storyboard(PROCESSED_ITEMS)
    return JSONResponse({"prompt": storyboard.chat_ai_prompt})

# Static Files & Frontend Routing
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def read_root():
    index_path = os.path.join(frontend_dir, "index.html")
    return FileResponse(index_path)
