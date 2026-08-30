"""
Gap-analysis API router — spatial camera coverage hole reporting.
GET /api/v1/gap-analysis

Performs PostGIS spatial operations (ST_Buffer, ST_Union, ST_Difference) to identify
uncovered monitoring regions across Gujarat's 33 districts assuming a 1km (0.009°)
effective camera coverage radius.
"""

import json
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from shared.db.models import User as UserModel
from shared.db.session import get_db

router = APIRouter(prefix="/api/v1/gap-analysis", tags=["gap-analysis"])


class DistrictCoverageResponse(BaseModel):
    district_id: uuid.UUID
    district_name: str
    camera_count: int
    district_area_sq_km: float
    uncovered_area_sq_km: float
    coverage_pct: float
    uncovered_geojson: Optional[dict] = None


@router.get("", response_model=list[DistrictCoverageResponse])
def get_gap_analysis(
    radius_km: float = Query(
        1.0, ge=0.1, le=10.0, description="Effective camera monitoring radius in kilometers"
    ),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    Computes spatial camera coverage percentages and uncovered area MultiPolygons for each district.
    
    Assumes a fixed monitoring radius per active camera (default 1.0 km). Sync query execution
    is optimal for ~30 cameras / 33 districts; revisit asynchronous background jobs at statewide scale (80,000+ cameras).
    """
    # Convert km radius to approximate lat/long degrees (1km approx 0.009 degrees at 23°N)
    buffer_degrees = radius_km * 0.009

    query_str = text("""
        SELECT
            d.id AS district_id,
            d.name AS district_name,
            COUNT(c.id) AS camera_count,
            ST_Area(d.boundary::geometry) AS district_area_deg,
            CASE
                WHEN COUNT(c.id) = 0 OR d.boundary IS NULL THEN ST_Area(d.boundary::geometry)
                ELSE ST_Area(ST_Difference(
                    d.boundary::geometry,
                    COALESCE(ST_Union(ST_Buffer(c.location::geometry, :buf)), ST_GeomFromText('POLYGON EMPTY'))
                ))
            END AS uncovered_area_deg,
            ST_AsGeoJSON(
                CASE
                    WHEN COUNT(c.id) = 0 OR d.boundary IS NULL THEN d.boundary::geometry
                    ELSE ST_Difference(
                        d.boundary::geometry,
                        COALESCE(ST_Union(ST_Buffer(c.location::geometry, :buf)), ST_GeomFromText('POLYGON EMPTY'))
                    )
                END
            ) AS uncovered_geojson
        FROM districts d
        LEFT JOIN cameras c ON c.district_id = d.id AND c.is_active = true AND c.location IS NOT NULL
        GROUP BY d.id, d.name, d.boundary
        ORDER BY camera_count ASC, d.name ASC;
    """)

    rows = db.execute(query_str, {"buf": buffer_degrees}).fetchall()

    results = []
    # 1 square degree at ~23°N is approximately 111km * 102km = 11,322 sq km
    DEG_TO_SQ_KM = 11322.0

    for r in rows:
        dist_area_deg = float(r.district_area_deg or 0.0)
        uncov_area_deg = float(r.uncovered_area_deg or 0.0)

        dist_area_km2 = round(dist_area_deg * DEG_TO_SQ_KM, 2)
        uncov_area_km2 = round(uncov_area_deg * DEG_TO_SQ_KM, 2)

        if dist_area_deg > 0:
            coverage_pct = round(max(0.0, min(100.0, (1.0 - (uncov_area_deg / dist_area_deg)) * 100.0)), 2)
        else:
            coverage_pct = 0.0

        geojson_dict = json.loads(r.uncovered_geojson) if r.uncovered_geojson else None

        results.append(
            DistrictCoverageResponse(
                district_id=r.district_id,
                district_name=r.district_name,
                camera_count=int(r.camera_count),
                district_area_sq_km=dist_area_km2,
                uncovered_area_sq_km=uncov_area_km2,
                coverage_pct=coverage_pct,
                uncovered_geojson=geojson_dict,
            )
        )

    # Sort results by coverage_pct ascending (worst covered district first)
    results.sort(key=lambda x: (x.coverage_pct, x.district_name))
    return results
