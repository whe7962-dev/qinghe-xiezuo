"""FastAPI 入口：本地网页 + JSON API。

- 一条命令启动：uvicorn app.main:app --port 8000
- 页面：http://127.0.0.1:8000（前端先 `npm run build`，产物 frontend/dist 由后端挂载）
- 错误统一返回 {"error": {"code", "message"}}，不泄露堆栈。
"""
from __future__ import annotations

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import BASE_DIR, EXPORT_DIR, ensure_data_dirs
from app.harness import Harness

FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

app = FastAPI(title="青禾协作 · 根据聊天记录更新任务表")
ensure_data_dirs()


class CacheHeadersMiddleware(BaseHTTPMiddleware):
    """index.html 不缓存（改版即时生效）；内容哈希的 /assets/* 长缓存。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path == "/" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.add_middleware(CacheHeadersMiddleware)

harness = Harness()

_ERROR_CODES = {
    "load": "LOAD_FAILED",
    "analyze": "ANALYZE_FAILED",
    "decide": "DECIDE_FAILED",
    "apply": "APPLY_FAILED",
    "export": "EXPORT_FAILED",
    "undo": "UNDO_FAILED",
}


def _respond(result: dict, action: str, ok_status: int = 200, err_status: int = 400) -> JSONResponse:
    """把 harness 的 {ok, ...}/{ok:false, error} 结果转成统一响应。

    成功保留原结构（含 ok:true）；失败统一为 {"error": {"code", "message"}}。
    """
    if result.get("ok"):
        return JSONResponse(result, status_code=ok_status)
    message = result.get("error") or "操作失败"
    if isinstance(message, dict):  # 已经是统一结构则原样返回
        return JSONResponse({"error": message}, status_code=err_status)
    return JSONResponse({"error": {"code": _ERROR_CODES.get(action, "ERROR"), "message": str(message)}},
                        status_code=err_status)


@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
                        status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误，请把操作步骤交给开发者排查"}},
                        status_code=500)


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
    return _respond(harness.load(task_text, chat_text), "load", err_status=400)


@app.post("/api/analyze")
def analyze():
    return _respond(harness.analyze(), "analyze", err_status=502)


@app.post("/api/decide")
def decide(body: dict):
    try:
        index = int(body.get("index", -1))
        decision = str(body.get("decision", ""))
        modified_value = str(body.get("modified_value", ""))
        reject_reason = str(body.get("reject_reason", ""))
    except (TypeError, ValueError):
        return JSONResponse({"error": {"code": "DECIDE_FAILED", "message": "请求体非法：index 必须是整数"}},
                            status_code=400)
    return _respond(harness.decide(index, decision, modified_value, reject_reason), "decide", err_status=400)


@app.post("/api/apply")
def apply():
    return _respond(harness.apply(), "apply", err_status=403)


@app.post("/api/undo")
def undo(body: dict):
    action = str(body.get("action", ""))
    index = -1
    if body.get("index") is not None:
        try:
            index = int(body["index"])
        except (TypeError, ValueError):
            return JSONResponse({"error": {"code": "UNDO_FAILED", "message": "请求体非法：index 必须是整数"}},
                                status_code=400)
    return _respond(harness.undo(action, index), "undo", err_status=400)


@app.post("/api/export")
def export():
    return _respond(harness.export(), "export", err_status=403)


@app.get("/api/download")
def download(name: str):
    """按文件名下载导出的产物（仅允许 data/exports/ 内的三个固定文件）。"""
    allowed = {"任务表.csv", "建议清单.json", "变更说明.md"}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="未知文件")
    path = EXPORT_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=name)


# 前端：构建产物 frontend/dist 由后端挂载；未构建时给提示
if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/")
    def index():
        return JSONResponse({
            "message": "前端未构建。请在 frontend/ 目录运行 npm install && npm run build，然后重启后端。",
            "api": ["/api/load", "/api/analyze", "/api/decide", "/api/apply",
                    "/api/export", "/api/state", "/api/metrics", "/api/download"],
        })
