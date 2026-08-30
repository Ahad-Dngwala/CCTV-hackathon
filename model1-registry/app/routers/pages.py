"""
Page routes — HTML views served via Jinja2 templates.

These are the user-facing pages, separate from the /api/v1 JSON routers.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from shared.db.models import Camera as CameraModel
from shared.db.models import Department as DeptModel
from shared.db.models import District as DistModel
from shared.db.session import get_db

router = APIRouter(tags=["pages"])


# ── Map (home page) ────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def map_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "map.html", {"request": request}
    )


# ── Camera list ─────────────────────────────────────────────────


@router.get("/cameras", response_class=HTMLResponse)
def cameras_list_page(
    request: Request,
    department_id: Optional[str] = Query(None),
    district_id: Optional[str] = Query(None),
    connectivity_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    departments = db.query(DeptModel).order_by(DeptModel.name).all()
    districts = db.query(DistModel).order_by(DistModel.name).all()

    return request.app.state.templates.TemplateResponse(
        "cameras_list.html",
        {
            "request": request,
            "departments": departments,
            "districts": districts,
            "selected_department": department_id or "",
            "selected_district": district_id or "",
            "selected_status": connectivity_status or "",
        },
    )


# ── Camera list partial (HTMX tbody swap) ──────────────────────


@router.get("/cameras/table", response_class=HTMLResponse)
def cameras_table_partial(
    request: Request,
    department_id: Optional[str] = Query(None),
    district_id: Optional[str] = Query(None),
    connectivity_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    from geoalchemy2.shape import to_shape

    q = (
        db.query(CameraModel)
        .options(
            joinedload(CameraModel.department),
            joinedload(CameraModel.district),
        )
        .filter(CameraModel.is_active == True)  # noqa: E712
    )
    if department_id:
        q = q.filter(CameraModel.department_id == department_id)
    if district_id:
        q = q.filter(CameraModel.district_id == district_id)
    if connectivity_status:
        q = q.filter(CameraModel.connectivity_status == connectivity_status)

    cameras = q.order_by(CameraModel.name).all()

    # Pre-process locations for template
    camera_rows = []
    for cam in cameras:
        loc_str = None
        if cam.location is not None:
            try:
                point = to_shape(cam.location)
                loc_str = f"{point.y:.4f}, {point.x:.4f}"
            except Exception:
                pass
        camera_rows.append({"cam": cam, "location_str": loc_str})

    return request.app.state.templates.TemplateResponse(
        "cameras_table_partial.html",
        {"request": request, "camera_rows": camera_rows},
    )


# ── Camera form (create / edit) ────────────────────────────────


@router.get("/cameras/new", response_class=HTMLResponse)
def camera_new_form(request: Request, db: Session = Depends(get_db)):
    departments = db.query(DeptModel).order_by(DeptModel.name).all()
    districts = db.query(DistModel).order_by(DistModel.name).all()
    return request.app.state.templates.TemplateResponse(
        "camera_form.html",
        {
            "request": request,
            "camera": None,
            "departments": departments,
            "districts": districts,
            "errors": {},
        },
    )


@router.get("/cameras/{camera_id}/edit", response_class=HTMLResponse)
def camera_edit_form(
    camera_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
):
    cam = (
        db.query(CameraModel)
        .options(
            joinedload(CameraModel.department),
            joinedload(CameraModel.district),
        )
        .filter(CameraModel.id == camera_id)
        .first()
    )
    if not cam:
        return HTMLResponse(status_code=404, content="Camera not found")

    departments = db.query(DeptModel).order_by(DeptModel.name).all()
    districts = db.query(DistModel).order_by(DistModel.name).all()

    # Extract lat/lon from PostGIS geography
    lat, lon = None, None
    if cam.location is not None:
        try:
            from geoalchemy2.shape import to_shape
            point = to_shape(cam.location)
            lat, lon = point.y, point.x
        except Exception:
            pass

    return request.app.state.templates.TemplateResponse(
        "camera_form.html",
        {
            "request": request,
            "camera": cam,
            "camera_lat": lat,
            "camera_lon": lon,
            "departments": departments,
            "districts": districts,
            "errors": {},
        },
    )


# ── Departments page ────────────────────────────────────────────


@router.get("/departments", response_class=HTMLResponse)
def departments_page(request: Request, db: Session = Depends(get_db)):
    return request.app.state.templates.TemplateResponse(
        "departments_list.html", {"request": request}
    )


# ── Districts page ──────────────────────────────────────────────


@router.get("/districts", response_class=HTMLResponse)
def districts_page(request: Request, db: Session = Depends(get_db)):
    return request.app.state.templates.TemplateResponse(
        "districts_list.html", {"request": request}
    )


# ── Phase 9 — Model 2 placeholders ─────────────────────────────


@router.get("/detections", response_class=HTMLResponse)
def detections_placeholder(request: Request):
    return request.app.state.templates.TemplateResponse(
        "placeholder.html",
        {
            "request": request,
            "page_title": "Detections",
            "description": "Model 2 — not built yet, see docs/API_Contract.md §2",
        },
    )


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist_placeholder(request: Request):
    return request.app.state.templates.TemplateResponse(
        "placeholder.html",
        {
            "request": request,
            "page_title": "Watchlist",
            "description": "Model 2 — not built yet, see docs/API_Contract.md §2",
        },
    )


@router.get("/alerts", response_class=HTMLResponse)
def alerts_placeholder(request: Request):
    return request.app.state.templates.TemplateResponse(
        "placeholder.html",
        {
            "request": request,
            "page_title": "Alerts",
            "description": "Model 2 — not built yet, see docs/API_Contract.md §2",
        },
    )
