import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import leads
from .config import settings

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
_tz = ZoneInfo(settings.timezone)


def _local_time(value: str | None) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value).astimezone(_tz).strftime("%d.%m.%Y %H:%M")


def _tg_link(lead: dict) -> str | None:
    if lead.get("tg_username"):
        return f"https://t.me/{lead['tg_username']}"
    if lead.get("tg_user_id"):
        return f"tg://user?id={lead['tg_user_id']}"
    return None


templates.env.filters["local_time"] = _local_time
templates.env.globals.update(
    SOURCES=leads.SOURCES, STATUSES=leads.STATUSES, tg_link=_tg_link
)


class LoginRequired(Exception):
    pass


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise LoginRequired
    return user


def _back_to_lead(lead_id: int) -> RedirectResponse:
    return RedirectResponse(f"/leads/{lead_id}", status_code=303)


def _existing_lead(lead_id: int) -> dict:
    lead = leads.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, "Лид не найден")
    return lead


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/")
def index():
    return RedirectResponse("/leads", status_code=303)


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, login: str = Form(...), password: str = Form(...)):
    ok = secrets.compare_digest(login, settings.admin_login) and secrets.compare_digest(
        password, settings.admin_password
    )
    if not ok:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )
    request.session["user"] = login
    return RedirectResponse("/leads", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/tags")
def tags_page(request: Request, error: str | None = None, user: str = Depends(require_user)):
    return templates.TemplateResponse(request, "tags.html", {
        "tags": leads.tag_counts(), "user": user, "error": error,
    })


@router.post("/tags")
def tags_create(name: str = Form(""), user: str = Depends(require_user)):
    if leads.create_tag(name) is None:
        return RedirectResponse("/tags?error=empty", status_code=303)
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/rename")
def tags_rename(old: str = Form(...), name: str = Form(""), user: str = Depends(require_user)):
    if leads.rename_tag(old, name) is None and not leads.normalize_tag(name):
        return RedirectResponse("/tags?error=empty", status_code=303)
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/delete")
def tags_delete(name: str = Form(...), user: str = Depends(require_user)):
    leads.delete_tag(name)
    return RedirectResponse("/tags", status_code=303)


@router.get("/leads")
def leads_list(request: Request, tag: str | None = None, q: str | None = None,
               user: str = Depends(require_user)):
    tag = leads.normalize_tag(tag) if tag else None
    return templates.TemplateResponse(request, "leads.html", {
        "leads": leads.list_leads(tag=tag, q=q),
        "tags": leads.tag_counts(),
        "active_tag": tag,
        "q": q or "",
        "user": user,
    })


@router.get("/leads/new")
def lead_new_form(request: Request, user: str = Depends(require_user)):
    return templates.TemplateResponse(request, "lead_new.html", {
        "tags": leads.tag_counts(), "user": user, "error": None, "form": {},
    })


@router.post("/leads/new")
def lead_create(request: Request, name: str = Form(""), contact: str = Form(""),
                request_text: str = Form("", alias="request"), tags: str = Form(""),
                user: str = Depends(require_user)):
    if not name.strip() and not contact.strip():
        return templates.TemplateResponse(request, "lead_new.html", {
            "tags": leads.tag_counts(), "user": user,
            "error": "Укажите хотя бы имя или контакт",
            "form": {"name": name, "contact": contact, "request": request_text, "tags": tags},
        }, status_code=400)
    lead_id = leads.create_lead(
        name=name, contact=contact, request=request_text, source="manual",
        tags=leads.parse_tags(tags),
    )
    return _back_to_lead(lead_id)


@router.get("/leads/{lead_id}")
def lead_card(request: Request, lead_id: int, user: str = Depends(require_user)):
    return templates.TemplateResponse(request, "lead.html", {
        "lead": _existing_lead(lead_id), "all_tags": leads.tag_counts(), "user": user,
    })


@router.post("/leads/{lead_id}/edit")
def lead_edit(lead_id: int, name: str = Form(""), contact: str = Form(""),
              request_text: str = Form("", alias="request"),
              user: str = Depends(require_user)):
    _existing_lead(lead_id)
    leads.update_lead(lead_id, name=name, contact=contact, request=request_text)
    return _back_to_lead(lead_id)


@router.post("/leads/{lead_id}/status")
def lead_status(lead_id: int, status: str = Form(...), user: str = Depends(require_user)):
    _existing_lead(lead_id)
    if status not in leads.STATUSES:
        raise HTTPException(400, "Неизвестный статус")
    leads.set_status(lead_id, status)
    return _back_to_lead(lead_id)


@router.post("/leads/{lead_id}/tags")
def lead_add_tags(lead_id: int, tags: str = Form(""), user: str = Depends(require_user)):
    _existing_lead(lead_id)
    leads.add_tags(lead_id, leads.parse_tags(tags))
    return _back_to_lead(lead_id)


@router.post("/leads/{lead_id}/tags/remove")
def lead_remove_tag(lead_id: int, tag: str = Form(...), user: str = Depends(require_user)):
    _existing_lead(lead_id)
    leads.remove_tag(lead_id, tag)
    return _back_to_lead(lead_id)
