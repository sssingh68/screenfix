from fastapi import FastAPI

app = FastAPI(title="ScreenFix Backend")


@app.get("/health")
def health_check():
    """Health check endpoint to verify service uptime."""
    return {"status": "ok"}
