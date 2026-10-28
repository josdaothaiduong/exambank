from fastapi import FastAPI

app = FastAPI(title="ExamBank AI API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "exambank-api", "milestone": "EB-101/EB-102"}
