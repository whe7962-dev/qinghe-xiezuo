"""FastAPI 入口：本地网页 + JSON API。

一条命令启动：uvicorn app.main:app --reload
页面：http://127.0.0.1:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.harness import Harness

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="青禾协作 · 根据聊天记录更新任务表")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

harness = Harness()


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/state")
def state():
    return JSONResponse(harness.snapshot())


@app.get("/api/metrics")
def metrics():
    from app.observability import metrics as m
    return JSONResponse(m.snapshot())


@app.post("/api/load")
async def load(task_csv: UploadFile = File(...), chat_csv: UploadFile = File(...)):
    task_text = (await task_csv.read()).decode("utf-8-sig")
    chat_text = (await chat_csv.read()).decode("utf-8-sig")
    result = harness.load(task_text, chat_text)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/analyze")
def analyze():
    result = harness.analyze()
    status = 200 if result.get("ok") else 502
    return JSONResponse(result, status_code=status)


@app.post("/api/decide")
def decide(body: dict):
    result = harness.decide(int(body.get("index", -1)), str(body.get("decision", "")),
                            str(body.get("modified_value", "")))
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/apply")
def apply():
    result = harness.apply()
    status = 200 if result.get("ok") else 403
    return JSONResponse(result, status_code=status)


@app.post("/api/export")
def export():
    result = harness.export()
    status = 200 if result.get("ok") else 403
    return JSONResponse(result, status_code=status)


@app.get("/api/download")
def download(name: str):
    """按文件名下载导出的产物（仅允许 exports/ 内）。"""
    from app.config import EXPORT_DIR
    allowed = {"任务表.csv", "建议清单.json", "变更说明.md"}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="未知文件")
    path = EXPORT_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=name)
