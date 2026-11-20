from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from live import handle_live_session
from tools import decide_approval, get_pending_approvals

app = FastAPI(title="ScreenFix Backend")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def get_root():
    """Serve the employee portal as the landing page."""
    return FileResponse("static/employee.html")


@app.get("/console")
def get_console():
    """Serve the L1 engineer console."""
    return FileResponse("static/console.html")


@app.get("/health")
def health_check():
    """Health check endpoint to verify service uptime."""
    return {"status": "ok"}


@app.get("/api/approvals")
def list_approvals():
    """Returns list of pending approvals for tenant demo-msp."""
    return {"approvals": get_pending_approvals(tenant_id="demo-msp")}


@app.post("/api/approvals/{approval_id}/approve")
def approve_request(approval_id: str):
    """Approve a pending runbook action."""
    success = decide_approval(approval_id, "approved", approver="l1-engineer-demo", tenant_id="demo-msp")
    if not success:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"status": "approved", "approval_id": approval_id}


@app.post("/api/approvals/{approval_id}/reject")
def reject_request(approval_id: str):
    """Reject a pending runbook action."""
    success = decide_approval(approval_id, "rejected", approver="l1-engineer-demo", tenant_id="demo-msp")
    if not success:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"status": "rejected", "approval_id": approval_id}


@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """Bridge employee browser WebSocket to Gemini Live."""
    await handle_live_session(websocket)



