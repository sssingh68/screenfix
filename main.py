from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from live import handle_live_session

app = FastAPI(title="ScreenFix Backend")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def get_root():
    """Serve the employee portal as the landing page."""
    return FileResponse("static/employee.html")


@app.get("/health")
def health_check():
    """Health check endpoint to verify service uptime."""
    return {"status": "ok"}


@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """Bridge employee browser WebSocket to Gemini Live."""
    await handle_live_session(websocket)


