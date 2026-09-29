"""PocketSmart: AI Budget Planner - FastAPI application."""
import asyncio
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import auth
from gemini_utils import (get_home_recommendations, get_jewelry_recommendations,
                          get_party_recommendations)
from models import HomeBudgetInput, JewelryBudgetInput, PartyBudgetInput

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def cleanup_sessions():
    while True:
        await asyncio.sleep(300)
        cutoff = datetime.now() - timedelta(minutes=30)
        for name in [n for n, s in auth.active_sessions.items() if s["last_activity"] < cutoff]:
            auth.active_sessions.pop(name, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.init_db()
    task = asyncio.create_task(cleanup_sessions())
    yield
    task.cancel()


app = FastAPI(title="PocketSmart: AI Budget Planner", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def page(request: Request, name: str, user=None):
    return templates.TemplateResponse(request, name, {"user": user})


def optional_user(request: Request):
    try:
        return auth.get_current_user(request)
    except HTTPException:
        return None


# ---------- public pages ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return page(request, "index.html", optional_user(request))


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if optional_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return page(request, "login.html")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if optional_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return page(request, "register.html")


# ---------- auth ----------
class RegisterUser(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None


@app.post("/register")
def register(u: RegisterUser):
    auth.create_user(u.username, u.email, u.password, u.full_name)
    return {"message": "Account created"}


@app.post("/token")
def token(username: str = Form(...), password: str = Form(...)):
    user = auth.authenticate(username, password)
    if not user:
        raise HTTPException(401, "Incorrect username or password")
    tok = auth.create_token(user)
    auth.start_session(user, tok)
    resp = JSONResponse({"access_token": tok, "token_type": "bearer"})
    resp.set_cookie("access_token", tok, httponly=True, samesite="lax",
                    max_age=auth.TOKEN_MINUTES * 60)
    return resp


@app.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request):
    tok = auth.get_token(request)
    if tok:
        auth.end_session(tok)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


# ---------- protected pages ----------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "dashboard.html", user)


@app.get("/home-planner", response_class=HTMLResponse)
def home_planner(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "home_planner.html", user)


@app.get("/party-planner", response_class=HTMLResponse)
def party_planner(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "party_planner.html", user)


@app.get("/jewelry-planner", response_class=HTMLResponse)
def jewelry_planner(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "jewelry_planner.html", user)


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "history.html", user)


# ---------- planner APIs ----------
def remember(user, key, data):
    auth.touch_session(user["username"])["user_data"][key] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"), **data}


@app.post("/home-budget")
@app.post("/generate-home")
def plan_home(b: HomeBudgetInput, user=Depends(auth.get_current_user)):
    remember(user, "last_home_budget", {"budget": b.total_budget})
    result = get_home_recommendations(b)
    result["history_id"] = auth.save_history(user["username"], "home", b.model_dump(), result)
    return result


@app.post("/party-budget")
@app.post("/generate-party")
def plan_party(b: PartyBudgetInput, user=Depends(auth.get_current_user)):
    remember(user, "last_party_budget", {"budget": b.total_budget, "guests": b.num_guests})
    result = get_party_recommendations(b)
    result["history_id"] = auth.save_history(user["username"], "party", b.model_dump(), result)
    return result


def save_upload(f: UploadFile) -> str:
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(400, "Only PNG, JPG or WEBP images are allowed")
    path = os.path.join(UPLOAD_DIR, f"{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}{ext}")
    with open(path, "wb") as out:
        shutil.copyfileobj(f.file, out)
    try:
        if os.path.getsize(path) > 5 * 1024 * 1024:
            raise ValueError("Image must be smaller than 5 MB")
        Image.open(path).verify()
    except Exception as e:
        os.remove(path)
        raise HTTPException(400, str(e) if isinstance(e, ValueError) else "That file is not a valid image")
    return path


@app.post("/jewelry-budget")
@app.post("/generate-jewelry")
def plan_jewelry(total_budget: float = Form(...), occasion: str = Form(...),
                 preferences: Optional[str] = Form(None), image: Optional[UploadFile] = File(None),
                 user=Depends(auth.get_current_user)):
    try:
        b = JewelryBudgetInput(total_budget=total_budget, occasion=occasion.strip(),
                               preferences=(preferences or "").strip() or None)
    except ValidationError:
        raise HTTPException(422, "Enter a budget above zero and an occasion")
    has_image = bool(image and image.filename)
    image_path = save_upload(image) if has_image else None
    remember(user, "last_jewelry_budget", {"budget": b.total_budget, "has_image": has_image})
    result = get_jewelry_recommendations(b, image_path)
    data = b.model_dump()
    data["image"] = image.filename if has_image else None
    result["history_id"] = auth.save_history(user["username"], "jewelry", data, result)
    return result


# ---------- history and session ----------
@app.get("/recommendation-history")
def recommendation_history(user=Depends(auth.get_current_user)):
    return {"history": auth.list_history(user["username"])}


@app.get("/recommendation-details/{rid}")
def recommendation_details(rid: str, user=Depends(auth.get_current_user)):
    return auth.get_history_item(user["username"], rid)


@app.get("/session-info")
def session_info(user=Depends(auth.get_current_user)):
    s = auth.touch_session(user["username"])
    return {"username": user["username"], "login_time": s["login_time"].isoformat(timespec="seconds"),
            "last_activity": s["last_activity"].isoformat(timespec="seconds"),
            "session_minutes": int((datetime.now() - s["login_time"]).total_seconds() // 60),
            "user_data": s["user_data"]}


@app.post("/session-data")
def session_data(data: Dict[str, Any], user=Depends(auth.get_current_user)):
    s = auth.touch_session(user["username"])
    s["user_data"].update(data)
    return {"message": "Session data updated", "data": s["user_data"]}


if __name__ == "__main__":
    import uvicorn
    print("Starting PocketSmart: AI Budget Planner on http://127.0.0.1:8000")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
