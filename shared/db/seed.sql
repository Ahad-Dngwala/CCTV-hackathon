-- ============================================================
-- Sentinel — seed data
-- ============================================================
-- Run after schema.sql (and triggers.sql, though seeding doesn't
-- depend on it). Three sections: departments, districts, cameras.
-- ============================================================

-- ------------------------------------------------------------
-- Departments
-- ------------------------------------------------------------
-- HackathonPortal.md only names 4 of the stated 26 departments
-- (Home/Police, Food & Civil Supplies, RTO, Municipal Corporations)
-- — that's open question #6 from the schema review, still
-- unresolved. Seeding all 26 with invented names would look more
-- complete than it is; seeding just these 4 plus an explicit
-- placeholder is the honest "good enough for now" version. Replace
-- the placeholder once the real department list is sourced from the
-- portal's resources page.
INSERT INTO departments (name, category) VALUES
    ('Home Department (Police)',            'Home/Police'),
    ('Food & Civil Supplies Department',    'Food & Civil Supplies'),
    ('Regional Transport Office (RTO)',     'RTO'),
    ('Municipal Corporation',               'Municipal Corporation'),
    ('Unassigned / Pending Department List','Placeholder — 22 of 26 departments not yet named in the brief');

-- ------------------------------------------------------------
-- Districts — all 33 Gujarat districts
-- ------------------------------------------------------------
-- `boundary` stays NULL for all of them — no shapefile sourced yet
-- (Project_Context.md §9 open question), so gap-analysis polygon
-- containment queries have nothing to run against until that's
-- loaded. Filtering by district still works fine off the name.
INSERT INTO districts (name) VALUES
    ('Ahmedabad'), ('Amreli'), ('Anand'), ('Aravalli'), ('Banaskantha'),
    ('Bharuch'), ('Bhavnagar'), ('Botad'), ('Chhota Udepur'), ('Dahod'),
    ('Dang'), ('Devbhoomi Dwarka'), ('Gandhinagar'), ('Gir Somnath'),
    ('Jamnagar'), ('Junagadh'), ('Kheda'), ('Kutch'), ('Mahisagar'),
    ('Mehsana'), ('Morbi'), ('Narmada'), ('Navsari'), ('Panchmahal'),
    ('Patan'), ('Porbandar'), ('Rajkot'), ('Sabarkantha'), ('Surat'),
    ('Surendranagar'), ('Tapi'), ('Vadodara'), ('Valsad');

-- ------------------------------------------------------------
-- Cameras — from GET /api/ingest on the government camera grid
-- ------------------------------------------------------------
-- Straight mirror of the 30-camera catalogue: source_grid_id,
-- name, location_label, live status, and stream properties/URLs
-- come directly from the grid response.
--
-- `department_id` is left NULL for all 30 — the grid catalogue
-- has no department field, and it isn't ours to guess; that's a
-- registry-onboarding decision, not something inferable from a
-- location string.
--
-- `district_id` is set ONLY where the location label unambiguously
-- names or clearly implies a real place (e.g. "...-junagadh",
-- "DISTRICT NAVSARI" spelled out, Adalaj → Gandhinagar, Gandhidham
-- → Kutch, Bilimora → Navsari). Ambiguous ones (a bare
-- "Janpath", an unqualified "ONGC Office", "Mohanpura") are left
-- NULL rather than guessed — a wrong district silently poisons
-- gap-analysis and district filtering, a NULL just says "not yet
-- placed," which is the true state. `location` (the actual lat/lng
-- point) is NULL for every row: the grid gives a text label, not
-- coordinates, so geocoding is separate follow-up work, not
-- something this seed can respond to.
--
-- `connectivity_status` is derived from the grid's own `live` flag
-- (online if live, offline otherwise) — it's a reasonable seed
-- default, not the same thing as our registry's health tracking
-- long-term, which will diverge once cameras are actually monitored.

INSERT INTO cameras (
    source_grid_id, name, location_label, district_id,
    location,
    connectivity_status, is_live, codec,
    stream_width, stream_height, stream_fps, bitrate_kbps,
    rtsp_url, whep_url, hls_url, grid_synced_at
) VALUES
    ('1',  'Camera 1',  '01 Chiman bhai Bridge', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.587224 23.069362)'), 
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/1',  'http://live.corp8.cloud:8889/stream/1/whep',  '/live/stream/1/index.m3u8',  now()),

    ('2',  'Camera 2',  '02 Janpath', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.532222 23.006667)'), 
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/2',  'http://live.corp8.cloud:8889/stream/2/whep',  '/live/stream/2/index.m3u8',  now()),

    ('3',  'Camera 3',  '03 O.N.G.C. Office', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.597337 23.105555)'), 
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/3',  'http://live.corp8.cloud:8889/stream/3/whep',  '/live/stream/3/index.m3u8',  now()),

    ('4',  'Camera 4',  '04 Paldi Circle', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.562515 23.013054)'), 
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/4',  'http://live.corp8.cloud:8889/stream/4/whep',  '/live/stream/4/index.m3u8',  now()),

    ('5',  'Camera 5',  '05 Visat teen Rasta', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.592100 23.105800)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/5',  'http://live.corp8.cloud:8889/stream/5/whep',  '/live/stream/5/index.m3u8',  now()),

    ('6',  'Camera 6',  '06 Timbavadi gate-Junagadh', (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.435142 21.502737)'),
     'online', true, 'hevc', 1920, 1080, 25.0, 1923,
     'rtsp://live.corp8.cloud:8554/stream/6',  'http://live.corp8.cloud:8889/stream/6/whep',  '/live/stream/6/index.m3u8',  now()),

    ('7',  'Camera 7',  '07 hero-showroom-gir-somnath', (SELECT id FROM districts WHERE name = 'Gir Somnath'),
     ST_GeogFromText('SRID=4326;POINT(70.428300 20.915400)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/7',  'http://live.corp8.cloud:8889/stream/7/whep',  '/live/stream/7/index.m3u8',  now()),

    ('8',  'Camera 8',  '08 majewadi-gate-junagadh', (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.468210 21.528410)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/8',  'http://live.corp8.cloud:8889/stream/8/whep',  '/live/stream/8/index.m3u8',  now()),

    ('9',  'Camera 9',  '09 new-bypass-near-by-circle-junagadh-2', (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.443100 21.531200)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/9',  'http://live.corp8.cloud:8889/stream/9/whep',  '/live/stream/9/index.m3u8',  now()),

    ('10', 'Camera 10', '10 char-chowk-road-2-junagadh', (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.457800 21.516900)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/10', 'http://live.corp8.cloud:8889/stream/10/whep', '/live/stream/10/index.m3u8', now()),

    ('11', 'Camera 11', '11 dolatpara-junagadh', (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.448500 21.547100)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/11', 'http://live.corp8.cloud:8889/stream/11/whep', '/live/stream/11/index.m3u8', now()),

    ('12', 'Camera 12', '12 Tri Mandir Adalaj Tollnaka', (SELECT id FROM districts WHERE name = 'Gandhinagar'),
     ST_GeogFromText('SRID=4326;POINT(72.585500 23.128100)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/12', 'http://live.corp8.cloud:8889/stream/12/whep', '/live/stream/12/index.m3u8', now()),

    ('13', 'Camera 13', '13 CN Vidhyalaya', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.555900 23.024400)'),
     'online', true, 'h264', 1920, 1080, 12.5, 902,
     'rtsp://live.corp8.cloud:8554/stream/13', 'http://live.corp8.cloud:8889/stream/13/whep', '/live/stream/13/index.m3u8', now()),

    ('14', 'Camera 14', '14 Delight', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.559200 23.033100)'),
     'online', true, 'h264', 1920, 1080, 12.5, 980,
     'rtsp://live.corp8.cloud:8554/stream/14', 'http://live.corp8.cloud:8889/stream/14/whep', '/live/stream/14/index.m3u8', now()),

    ('15', 'Camera 15', '15 Suvidha park', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.541100 23.037800)'),
     'online', true, 'h264', 1920, 1080, 12.5, 690,
     'rtsp://live.corp8.cloud:8554/stream/15', 'http://live.corp8.cloud:8889/stream/15/whep', '/live/stream/15/index.m3u8', now()),

    ('16', 'Camera 16', '16 Visat P2', (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.594200 23.109500)'),
     'online', true, 'h264', 1920, 1080, 12.5, 961,
     'rtsp://live.corp8.cloud:8554/stream/16', 'http://live.corp8.cloud:8889/stream/16/whep', '/live/stream/16/index.m3u8', now()),

    ('17', 'Camera 17', '17 Rajkot Bus Port CCTV', (SELECT id FROM districts WHERE name = 'Rajkot'),
     ST_GeogFromText('SRID=4326;POINT(70.796300 22.291600)'),
     'online', true, 'hevc', 1920, 1080, 24.98, 671,
     'rtsp://live.corp8.cloud:8554/stream/17', 'http://live.corp8.cloud:8889/stream/17/whep', '/live/stream/17/index.m3u8', now()),

    ('18', 'Camera 18', '18 Rajkot CCTV', (SELECT id FROM districts WHERE name = 'Rajkot'),
     ST_GeogFromText('SRID=4326;POINT(70.802200 22.303900)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/18', 'http://live.corp8.cloud:8889/stream/18/whep', '/live/stream/18/index.m3u8', now()),

    ('19', 'Camera 19', '19 KHAPARIA GRAM PANCHAYAT , TALUKA GANDEVI, DISTRICT NAVSARI', (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(73.011400 20.814200)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/19', 'http://live.corp8.cloud:8889/stream/19/whep', '/live/stream/19/index.m3u8', now()),

    ('20', 'Camera 20', '20 Mohanpura', (SELECT id FROM districts WHERE name = 'Sabarkantha'),
     ST_GeogFromText('SRID=4326;POINT(72.863100 23.541400)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/20', 'http://live.corp8.cloud:8889/stream/20/whep', '/live/stream/20/index.m3u8', now()),

    ('21', 'Camera 21', '23 Patan Dethali Char Rasta', (SELECT id FROM districts WHERE name = 'Patan'),
     ST_GeogFromText('SRID=4326;POINT(72.115800 23.829100)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/21', 'http://live.corp8.cloud:8889/stream/21/whep', '/live/stream/21/index.m3u8', now()),

    ('22', 'Camera 22', '28 BK Mervada tran Rasta', (SELECT id FROM districts WHERE name = 'Banaskantha'),
     ST_GeogFromText('SRID=4326;POINT(72.411500 24.238400)'),
     'online', true, 'hevc', 1920, 1080, 25.0, 2091,
     'rtsp://live.corp8.cloud:8554/stream/22', 'http://live.corp8.cloud:8889/stream/22/whep', '/live/stream/22/index.m3u8', now()),

    ('23', 'Camera 23', '30 kheram', (SELECT id FROM districts WHERE name = 'Banaskantha'),
     ST_GeogFromText('SRID=4326;POINT(72.639100 23.955400)'),
     'online', true, 'h264', 1280, 720, 25.0, 4001,
     'rtsp://live.corp8.cloud:8554/stream/23', 'http://live.corp8.cloud:8889/stream/23/whep', '/live/stream/23/index.m3u8', now()),

    ('24', 'Camera 24', '33 dehgam', (SELECT id FROM districts WHERE name = 'Gandhinagar'),
     ST_GeogFromText('SRID=4326;POINT(72.822400 23.167200)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/24', 'http://live.corp8.cloud:8889/stream/24/whep', '/live/stream/24/index.m3u8', now()),

    ('25', 'Camera 25', '34 dhanori', (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.951200 20.732400)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/25', 'http://live.corp8.cloud:8889/stream/25/whep', '/live/stream/25/index.m3u8', now()),

    ('26', 'Camera 26', '35 TANKAL', (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(73.195300 20.684100)'),
     'online', true, 'hevc', 2560, 1440, 13.35, 2411,
     'rtsp://live.corp8.cloud:8554/stream/26', 'http://live.corp8.cloud:8889/stream/26/whep', '/live/stream/26/index.m3u8', now()),

    ('27', 'Camera 27', '36 bilimora', (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.964200 20.764400)'),
     'online', true, 'h264', 1280, 960, 24.86, 1112,
     'rtsp://live.corp8.cloud:8554/stream/27', 'http://live.corp8.cloud:8889/stream/27/whep', '/live/stream/27/index.m3u8', now()),

    ('28', 'Camera 28', '37 bilimora', (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.960100 20.761100)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/28', 'http://live.corp8.cloud:8889/stream/28/whep', '/live/stream/28/index.m3u8', now()),

    ('29', 'Camera 29', '38 bilimora', (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.956800 20.758200)'),
     'online', true, 'h264', 1280, 960, 24.78, 907,
     'rtsp://live.corp8.cloud:8554/stream/29', 'http://live.corp8.cloud:8889/stream/29/whep', '/live/stream/29/index.m3u8', now()),

    ('30', 'Camera 30', 'Gandhidham Rambaugh p2', (SELECT id FROM districts WHERE name = 'Kutch'),
     ST_GeogFromText('SRID=4326;POINT(70.117200 23.076800)'),
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/30', 'http://live.corp8.cloud:8889/stream/30/whep', '/live/stream/30/index.m3u8', now());

-- ------------------------------------------------------------
-- Model 2 Sample / Seed Data — Watchlists, Tracks, Detections, Alerts
-- ------------------------------------------------------------

INSERT INTO vehicles_watchlist (id, plate_number, category, reported_date, description, status)
VALUES
    ('a0000000-0000-0000-0000-000000000001', 'GJ01AB1234', 'stolen', '2026-08-25', 'White Swift stolen in Ahmedabad district', 'active'),
    ('a0000000-0000-0000-0000-000000000002', 'GJ05CD5678', 'wanted', '2026-08-28', 'Black SUV wanted in connection with Home Dept investigation', 'active'),
    ('a0000000-0000-0000-0000-000000000003', 'GJ03EF9012', 'blacklisted', '2026-08-20', 'Repeated traffic violations - RTO watchlist', 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO vehicle_tracks (id, plate_number, vehicle_color, vehicle_type, first_seen, last_seen, is_watchlisted)
VALUES
    ('b0000000-0000-0000-0000-000000000001', 'GJ01AB1234', 'White', 'Hatchback', NOW() - INTERVAL '3 hours', NOW() - INTERVAL '30 minutes', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO detections (id, camera_id, timestamp, detected_plate, confidence, cropped_image_path, vehicle_track_id)
SELECT 
    'c0000000-0000-0000-0000-000000000001',
    c.id,
    NOW() - INTERVAL '3 hours',
    'GJ01AB1234',
    0.95,
    '/storage/crops/c0000000-0000-0000-0000-000000000001.jpg',
    'b0000000-0000-0000-0000-000000000001'
FROM cameras c LIMIT 1
ON CONFLICT (id) DO NOTHING;

INSERT INTO detections (id, camera_id, timestamp, detected_plate, confidence, cropped_image_path, vehicle_track_id)
SELECT 
    'c0000000-0000-0000-0000-000000000002',
    c.id,
    NOW() - INTERVAL '1 hour 30 minutes',
    'GJ01AB1234',
    0.92,
    '/storage/crops/c0000000-0000-0000-0000-000000000002.jpg',
    'b0000000-0000-0000-0000-000000000001'
FROM cameras c OFFSET 1 LIMIT 1
ON CONFLICT (id) DO NOTHING;

INSERT INTO detections (id, camera_id, timestamp, detected_plate, confidence, cropped_image_path, vehicle_track_id)
SELECT 
    'c0000000-0000-0000-0000-000000000003',
    c.id,
    NOW() - INTERVAL '30 minutes',
    'GJ01AB1234',
    0.98,
    '/storage/crops/c0000000-0000-0000-0000-000000000003.jpg',
    'b0000000-0000-0000-0000-000000000001'
FROM cameras c OFFSET 2 LIMIT 1
ON CONFLICT (id) DO NOTHING;

INSERT INTO alerts (id, detection_id, watchlist_id, alert_type, severity, created_at)
VALUES
    ('d0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000001', 'vehicle_match', 'critical', NOW() - INTERVAL '30 minutes')
ON CONFLICT (id) DO NOTHING;