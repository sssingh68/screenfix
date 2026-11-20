from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

