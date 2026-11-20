import asyncio
import logging
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from live import handle_live_session
from tools import decide_approval, get_pending_approvals, get_audit_log


# ---------------------------------------------------------------------------
# Suppress noisy uvicorn access-log lines for polling endpoints.
# Only GET /api/approvals and GET /api/audit-log are filtered; everything
# else (WebSocket, POST, errors) still appears normally.
# ---------------------------------------------------------------------------
class _PollFilter(logging.Filter):
    """Drop uvicorn access-log entries for the two high-frequency poll routes."""
    _SKIP = {
        'GET /api/approvals HTTP',
        'GET /api/audit-log HTTP',
    }

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(skip in msg for skip in self._SKIP)


logging.getLogger("uvicorn.access").addFilter(_PollFilter())

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


@app.post("/simulated/endpoint/reset_vpn_profile")
async def simulate_reset_vpn():
    """
    Fake VPN reset endpoint used by execute_action.
    Waits 2 seconds to simulate real work, then returns success.
    NOTE: execute_action calls the internal function directly (same process);
    this HTTP route is exposed for manual testing only.
    """
    await asyncio.sleep(2)
    return {"result": "success", "detail": "VPN profile re-created with company settings"}


@app.get("/api/audit-log")
def list_audit_log():
    """Returns the last 10 audit records for tenant demo-msp."""
    records = get_audit_log(tenant_id="demo-msp", limit=10)
    return {"audit_log": records}

