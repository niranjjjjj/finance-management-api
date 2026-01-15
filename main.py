from fastapi import FastAPI

app = FastAPI(title="Finance Management API")

@app.get("/")
def root():
    return {"message": "Finance Management API is running"}

@app.get("/health")
def health():
    return {"status": "ok"}
