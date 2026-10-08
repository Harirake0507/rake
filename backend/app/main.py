from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .bms_adapter import state, movies, cinemas, showtimes_for_cinema, check_alert, BMSAdapterError, ADAPTER_VERSION

app = FastAPI(title="BMS Live Alert API", version=ADAPTER_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

class CheckRequest(BaseModel):
    city: str = "chennai"
    movie: str
    cinemas: list[str] = Field(min_length=1, max_length=3)
    date: str | None = None
    available_only: bool = False

@app.get("/health")
def health():
    return {
        "status": "healthy" if state.ok else "degraded",
        "adapter_version": ADAPTER_VERSION,
        "last_success": datetime.fromtimestamp(state.last_success, timezone.utc).isoformat() if state.last_success else None,
        "last_error": state.last_error,
    }

@app.get("/v1/movies")
def get_movies(city: str = "chennai"):
    try:
        return {"city": city, "items": movies(city)}
    except BMSAdapterError as e:
        raise HTTPException(503, str(e))

@app.get("/v1/cinemas")
def get_cinemas(city: str = "chennai"):
    try:
        return {"city": city, "items": cinemas(city)}
    except BMSAdapterError as e:
        raise HTTPException(503, str(e))

@app.get("/v1/showtimes")
def get_showtimes(cinema: str, city: str = "chennai"):
    try:
        items = cinemas(city)
        found = next((c for c in items if c["name"].lower() == cinema.lower()), None)
        if not found:
            raise HTTPException(404, "Cinema not found")
        return showtimes_for_cinema(found, city)
    except BMSAdapterError as e:
        raise HTTPException(503, str(e))

@app.post("/v1/check")
def post_check(req: CheckRequest):
    try:
        return {
            "city": req.city,
            "movie": req.movie,
            "results": check_alert(req.movie, req.cinemas, req.city, req.date, req.available_only),
        }
    except BMSAdapterError as e:
        raise HTTPException(503, str(e))
