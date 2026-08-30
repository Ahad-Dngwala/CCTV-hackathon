"""
Script to seed boundary MultiPolygon geometries for all 33 Gujarat districts in PostGIS.
"""

import sys
from pathlib import Path

# Ensure shared is importable
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from sqlalchemy import text
from shared.db.session import get_db, init_engine

# Gujarat 33 Districts Bounding Box Bounding MultiPolygons (approximate boundary geometries)
DISTRICT_BOUNDARIES = {
    "Kutch": [
        [(68.5, 22.8), (71.3, 22.8), (71.5, 24.5), (68.8, 24.6), (68.5, 22.8)]
    ],
    "Banaskantha": [
        [(71.3, 23.8), (72.8, 23.8), (72.9, 24.6), (71.4, 24.5), (71.3, 23.8)]
    ],
    "Patan": [
        [(71.4, 23.5), (72.3, 23.5), (72.3, 24.1), (71.5, 24.1), (71.4, 23.5)]
    ],
    "Mehsana": [
        [(72.0, 23.3), (72.7, 23.3), (72.7, 23.9), (72.1, 23.9), (72.0, 23.3)]
    ],
    "Sabarkantha": [
        [(72.8, 23.5), (73.4, 23.5), (73.4, 24.2), (72.9, 24.2), (72.8, 23.5)]
    ],
    "Aravalli": [
        [(73.1, 23.4), (73.7, 23.4), (73.7, 24.0), (73.2, 24.0), (73.1, 23.4)]
    ],
    "Gandhinagar": [
        [(72.5, 23.0), (72.9, 23.0), (72.9, 23.5), (72.5, 23.5), (72.5, 23.0)]
    ],
    "Ahmedabad": [
        [(72.2, 22.6), (72.8, 22.6), (72.8, 23.3), (72.2, 23.3), (72.2, 22.6)]
    ],
    "Surendranagar": [
        [(71.1, 22.3), (72.2, 22.3), (72.2, 23.3), (71.1, 23.3), (71.1, 22.3)]
    ],
    "Morbi": [
        [(70.4, 22.5), (71.2, 22.5), (71.2, 23.2), (70.4, 23.2), (70.4, 22.5)]
    ],
    "Jamnagar": [
        [(69.6, 22.1), (70.5, 22.1), (70.5, 22.8), (69.6, 22.8), (69.6, 22.1)]
    ],
    "Devbhoomi Dwarka": [
        [(68.9, 21.8), (69.7, 21.8), (69.7, 22.5), (68.9, 22.5), (68.9, 21.8)]
    ],
    "Porbandar": [
        [(69.4, 21.3), (70.0, 21.3), (70.0, 21.9), (69.4, 21.9), (69.4, 21.3)]
    ],
    "Rajkot": [
        [(70.5, 21.9), (71.3, 21.9), (71.3, 22.7), (70.5, 22.7), (70.5, 21.9)]
    ],
    "Botad": [
        [(71.4, 21.9), (71.9, 21.9), (71.9, 22.4), (71.4, 22.4), (71.4, 21.9)]
    ],
    "Bhavnagar": [
        [(71.5, 21.3), (72.4, 21.3), (72.4, 22.1), (71.5, 22.1), (71.5, 21.3)]
    ],
    "Amreli": [
        [(70.9, 21.0), (71.7, 21.0), (71.7, 21.8), (70.9, 21.8), (70.9, 21.0)]
    ],
    "Junagadh": [
        [(70.1, 21.1), (70.8, 21.1), (70.8, 21.7), (70.1, 21.7), (70.1, 21.1)]
    ],
    "Gir Somnath": [
        [(70.3, 20.6), (71.1, 20.6), (71.1, 21.1), (70.3, 21.1), (70.3, 20.6)]
    ],
    "Anand": [
        [(72.7, 22.2), (73.2, 22.2), (73.2, 22.7), (72.7, 22.7), (72.7, 22.2)]
    ],
    "Kheda": [
        [(72.6, 22.5), (73.2, 22.5), (73.2, 23.1), (72.6, 23.1), (72.6, 22.5)]
    ],
    "Panchmahal": [
        [(73.3, 22.4), (73.9, 22.4), (73.9, 23.0), (73.3, 23.0), (73.3, 22.4)]
    ],
    "Mahisagar": [
        [(73.2, 23.0), (73.8, 23.0), (73.8, 23.5), (73.2, 23.5), (73.2, 23.0)]
    ],
    "Dahod": [
        [(73.8, 22.6), (74.5, 22.6), (74.5, 23.3), (73.8, 23.3), (73.8, 22.6)]
    ],
    "Vadodara": [
        [(73.0, 21.9), (73.6, 21.9), (73.6, 22.5), (73.0, 22.5), (73.0, 21.9)]
    ],
    "Chhota Udepur": [
        [(73.7, 22.0), (74.3, 22.0), (74.3, 22.5), (73.7, 22.5), (73.7, 22.0)]
    ],
    "Bharuch": [
        [(72.5, 21.4), (73.3, 21.4), (73.3, 22.1), (72.5, 22.1), (72.5, 21.4)]
    ],
    "Narmada": [
        [(73.2, 21.4), (73.9, 21.4), (73.9, 21.9), (73.2, 21.9), (73.2, 21.4)]
    ],
    "Surat": [
        [(72.6, 21.0), (73.3, 21.0), (73.3, 21.5), (72.6, 21.5), (72.6, 21.0)]
    ],
    "Tapi": [
        [(73.2, 20.9), (73.9, 20.9), (73.9, 21.5), (73.2, 21.5), (73.2, 20.9)]
    ],
    "Navsari": [
        [(72.8, 20.6), (73.3, 20.6), (73.3, 21.0), (72.8, 21.0), (72.8, 20.6)]
    ],
    "Dang": [
        [(73.5, 20.6), (73.9, 20.6), (73.9, 21.1), (73.5, 21.1), (73.5, 20.6)]
    ],
    "Valsad": [
        [(72.7, 20.1), (73.3, 20.1), (73.3, 20.7), (72.7, 20.7), (72.7, 20.1)]
    ],
}


def populate_boundaries(db_url: str = "postgresql://sentinel:sentinel_dev@127.0.0.1:5432/sentinel"):
    init_engine(db_url)
    db_gen = get_db()
    db = next(db_gen)

    count = 0
    for name, coords in DISTRICT_BOUNDARIES.items():
        polygon_str = ", ".join(f"{lon} {lat}" for lon, lat in coords[0])
        wkt = f"SRID=4326;MULTIPOLYGON((({polygon_str})))"
        
        res = db.execute(
            text("UPDATE districts SET boundary = ST_GeogFromText(:wkt) WHERE name = :name"),
            {"wkt": wkt, "name": name},
        )
        count += res.rowcount

    db.commit()
    print(f"Successfully populated boundary geometries for {count} districts.")


if __name__ == "__main__":
    populate_boundaries()
