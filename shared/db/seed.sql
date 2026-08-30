-- ============================================================
-- Sentinel — seed data
-- ============================================================
-- Run after schema.sql (and triggers.sql, though seeding doesn't
-- depend on it). Three sections: departments, districts, cameras.
-- ============================================================

-- ------------------------------------------------------------
-- Departments
-- ------------------------------------------------------------
INSERT INTO departments (name, category) VALUES
    ('Home Department (Police)',            'Home/Police'),
    ('Food & Civil Supplies Department',    'Food & Civil Supplies'),
    ('Regional Transport Office (RTO)',     'RTO'),
    ('Municipal Corporation',               'Municipal Corporation'),
    ('Unassigned / Pending Department List','Placeholder — 22 of 26 departments not yet named in the brief');

-- ------------------------------------------------------------
-- Users (Authentication & RBAC)
-- ------------------------------------------------------------
INSERT INTO users (username, email, hashed_password, role, department_id)
VALUES
    ('admin_home', 'admin.home@sentinel.gujarat.gov.in', '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'dept_admin', (SELECT id FROM departments WHERE name = 'Home Department (Police)')),
    ('admin_rto',  'admin.rto@sentinel.gujarat.gov.in',  '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'dept_admin', (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)')),
    ('operator1',  'operator1@sentinel.gujarat.gov.in',  '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'operator',   NULL),
    ('viewer1',    'viewer1@sentinel.gujarat.gov.in',    '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'viewer',     NULL)
ON CONFLICT (username) DO NOTHING;

-- ------------------------------------------------------------
-- Districts — all 33 Gujarat districts with PostGIS MultiPolygon boundaries
-- ------------------------------------------------------------
INSERT INTO districts (name, boundary) VALUES
    ('Ahmedabad',       ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.2 22.6, 72.8 22.6, 72.8 23.3, 72.2 23.3, 72.2 22.6)))')),
    ('Amreli',          ST_GeogFromText('SRID=4326;MULTIPOLYGON(((70.9 21.0, 71.7 21.0, 71.7 21.8, 70.9 21.8, 70.9 21.0)))')),
    ('Anand',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.7 22.2, 73.2 22.2, 73.2 22.7, 72.7 22.7, 72.7 22.2)))')),
    ('Aravalli',        ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.1 23.4, 73.7 23.4, 73.7 24.0, 73.2 24.0, 73.1 23.4)))')),
    ('Banaskantha',     ST_GeogFromText('SRID=4326;MULTIPOLYGON(((71.3 23.8, 72.8 23.8, 72.9 24.6, 71.4 24.5, 71.3 23.8)))')),
    ('Bharuch',         ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.5 21.4, 73.3 21.4, 73.3 22.1, 72.5 22.1, 72.5 21.4)))')),
    ('Bhavnagar',       ST_GeogFromText('SRID=4326;MULTIPOLYGON(((71.5 21.3, 72.4 21.3, 72.4 22.1, 71.5 22.1, 71.5 21.3)))')),
    ('Botad',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((71.4 21.9, 71.9 21.9, 71.9 22.4, 71.4 22.4, 71.4 21.9)))')),
    ('Chhota Udepur',   ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.7 22.0, 74.3 22.0, 74.3 22.5, 73.7 22.5, 73.7 22.0)))')),
    ('Dahod',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.8 22.6, 74.5 22.6, 74.5 23.3, 73.8 23.3, 73.8 22.6)))')),
    ('Dang',            ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.5 20.6, 73.9 20.6, 73.9 21.1, 73.5 21.1, 73.5 20.6)))')),
    ('Devbhoomi Dwarka',ST_GeogFromText('SRID=4326;MULTIPOLYGON(((68.9 21.8, 69.7 21.8, 69.7 22.5, 68.9 22.5, 68.9 21.8)))')),
    ('Gandhinagar',     ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.5 23.0, 72.9 23.0, 72.9 23.5, 72.5 23.5, 72.5 23.0)))')),
    ('Gir Somnath',     ST_GeogFromText('SRID=4326;MULTIPOLYGON(((70.3 20.6, 71.1 20.6, 71.1 21.1, 70.3 21.1, 70.3 20.6)))')),
    ('Jamnagar',        ST_GeogFromText('SRID=4326;MULTIPOLYGON(((69.6 22.1, 70.5 22.1, 70.5 22.8, 69.6 22.8, 69.6 22.1)))')),
    ('Junagadh',        ST_GeogFromText('SRID=4326;MULTIPOLYGON(((70.1 21.1, 70.8 21.1, 70.8 21.7, 70.1 21.7, 70.1 21.1)))')),
    ('Kheda',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.6 22.5, 73.2 22.5, 73.2 23.1, 72.6 23.1, 72.6 22.5)))')),
    ('Kutch',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((68.5 22.8, 71.3 22.8, 71.5 24.5, 68.8 24.6, 68.5 22.8)))')),
    ('Mahisagar',       ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.2 23.0, 73.8 23.0, 73.8 23.5, 73.2 23.5, 73.2 23.0)))')),
    ('Mehsana',         ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.0 23.3, 72.7 23.3, 72.7 23.9, 72.1 23.9, 72.0 23.3)))')),
    ('Morbi',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((70.4 22.5, 71.2 22.5, 71.2 23.2, 70.4 23.2, 70.4 22.5)))')),
    ('Narmada',         ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.2 21.4, 73.9 21.4, 73.9 21.9, 73.2 21.9, 73.2 21.4)))')),
    ('Navsari',         ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.8 20.6, 73.3 20.6, 73.3 21.0, 72.8 21.0, 72.8 20.6)))')),
    ('Panchmahal',      ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.3 22.4, 73.9 22.4, 73.9 23.0, 73.3 23.0, 73.3 22.4)))')),
    ('Patan',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((71.4 23.5, 72.3 23.5, 72.3 24.1, 71.5 24.1, 71.4 23.5)))')),
    ('Porbandar',       ST_GeogFromText('SRID=4326;MULTIPOLYGON(((69.4 21.3, 70.0 21.3, 70.0 21.9, 69.4 21.9, 69.4 21.3)))')),
    ('Rajkot',          ST_GeogFromText('SRID=4326;MULTIPOLYGON(((70.5 21.9, 71.3 21.9, 71.3 22.7, 70.5 22.7, 70.5 21.9)))')),
    ('Sabarkantha',     ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.8 23.5, 73.4 23.5, 73.4 24.2, 72.9 24.2, 72.8 23.5)))')),
    ('Surat',           ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.6 21.0, 73.3 21.0, 73.3 21.5, 72.6 21.5, 72.6 21.0)))')),
    ('Surendranagar',   ST_GeogFromText('SRID=4326;MULTIPOLYGON(((71.1 22.3, 72.2 22.3, 72.2 23.3, 71.1 23.3, 71.1 22.3)))')),
    ('Tapi',            ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.2 20.9, 73.9 20.9, 73.9 21.5, 73.2 21.5, 73.2 20.9)))')),
    ('Vadodara',        ST_GeogFromText('SRID=4326;MULTIPOLYGON(((73.0 21.9, 73.6 21.9, 73.6 22.5, 73.0 22.5, 73.0 21.9)))')),
    ('Valsad',          ST_GeogFromText('SRID=4326;MULTIPOLYGON(((72.7 20.1, 73.3 20.1, 73.3 20.7, 72.7 20.7, 72.7 20.1)))'));

-- ------------------------------------------------------------
-- Cameras — from GET /api/ingest on the government camera grid
-- ------------------------------------------------------------
-- Mapped with realistic department_id, camera_type, ownership,
-- storage_type, retention_days, and vms_url for full demo functionality.

INSERT INTO cameras (
    source_grid_id, name, location_label, department_id, district_id,
    location, camera_type, ownership, storage_type, retention_days, vms_url,
    connectivity_status, is_live, codec,
    stream_width, stream_height, stream_fps, bitrate_kbps,
    rtsp_url, whep_url, hls_url, grid_synced_at
) VALUES
    ('1',  'Camera 1',  '01 Chiman bhai Bridge', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.587224 23.069362)'), 
     'PTZ', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/1/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/1',  'http://live.corp8.cloud:8889/stream/1/whep',  '/live/stream/1/index.m3u8',  now()),

    ('2',  'Camera 2',  '02 Janpath', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.532222 23.006667)'), 
     'fixed', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/2/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/2',  'http://live.corp8.cloud:8889/stream/2/whep',  '/live/stream/2/index.m3u8',  now()),

    ('3',  'Camera 3',  '03 O.N.G.C. Office', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.597337 23.105555)'), 
     'dome', 'government', 'local', 60, 'http://live.corp8.cloud:8889/stream/3/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/3',  'http://live.corp8.cloud:8889/stream/3/whep',  '/live/stream/3/index.m3u8',  now()),

    ('4',  'Camera 4',  '04 Paldi Circle', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.562515 23.013054)'), 
     'PTZ', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/4/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/4',  'http://live.corp8.cloud:8889/stream/4/whep',  '/live/stream/4/index.m3u8',  now()),

    ('5',  'Camera 5',  '05 Visat teen Rasta', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.592100 23.105800)'),
     'bullet', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/5/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/5',  'http://live.corp8.cloud:8889/stream/5/whep',  '/live/stream/5/index.m3u8',  now()),

    ('6',  'Camera 6',  '06 Timbavadi gate-Junagadh', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.435142 21.502737)'),
     'fixed', 'government', 'cloud', 90, 'http://live.corp8.cloud:8889/stream/6/whep',
     'online', true, 'hevc', 1920, 1080, 25.0, 1923,
     'rtsp://live.corp8.cloud:8554/stream/6',  'http://live.corp8.cloud:8889/stream/6/whep',  '/live/stream/6/index.m3u8',  now()),

    ('7',  'Camera 7',  '07 hero-showroom-gir-somnath', 
     (SELECT id FROM departments WHERE name = 'Food & Civil Supplies Department'),
     (SELECT id FROM districts WHERE name = 'Gir Somnath'),
     ST_GeogFromText('SRID=4326;POINT(70.428300 20.915400)'),
     'dome', 'private', 'local', 30, 'http://live.corp8.cloud:8889/stream/7/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/7',  'http://live.corp8.cloud:8889/stream/7/whep',  '/live/stream/7/index.m3u8',  now()),

    ('8',  'Camera 8',  '08 majewadi-gate-junagadh', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.468210 21.528410)'),
     'PTZ', 'government', 'cloud', 60, 'http://live.corp8.cloud:8889/stream/8/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/8',  'http://live.corp8.cloud:8889/stream/8/whep',  '/live/stream/8/index.m3u8',  now()),

    ('9',  'Camera 9',  '09 new-bypass-near-by-circle-junagadh-2', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.443100 21.531200)'),
     'bullet', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/9/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/9',  'http://live.corp8.cloud:8889/stream/9/whep',  '/live/stream/9/index.m3u8',  now()),

    ('10', 'Camera 10', '10 char-chowk-road-2-junagadh', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.457800 21.516900)'),
     'fixed', 'government', 'local', 30, 'http://live.corp8.cloud:8889/stream/10/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/10', 'http://live.corp8.cloud:8889/stream/10/whep', '/live/stream/10/index.m3u8', now()),

    ('11', 'Camera 11', '11 dolatpara-junagadh', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Junagadh'),
     ST_GeogFromText('SRID=4326;POINT(70.448500 21.547100)'),
     'PTZ', 'government', 'cloud', 60, 'http://live.corp8.cloud:8889/stream/11/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/11', 'http://live.corp8.cloud:8889/stream/11/whep', '/live/stream/11/index.m3u8', now()),

    ('12', 'Camera 12', '12 Tri Mandir Adalaj Tollnaka', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Gandhinagar'),
     ST_GeogFromText('SRID=4326;POINT(72.585500 23.128100)'),
     'fixed', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/12/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/12', 'http://live.corp8.cloud:8889/stream/12/whep', '/live/stream/12/index.m3u8', now()),

    ('13', 'Camera 13', '13 CN Vidhyalaya', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.555900 23.024400)'),
     'dome', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/13/whep',
     'online', true, 'h264', 1920, 1080, 12.5, 902,
     'rtsp://live.corp8.cloud:8554/stream/13', 'http://live.corp8.cloud:8889/stream/13/whep', '/live/stream/13/index.m3u8', now()),

    ('14', 'Camera 14', '14 Delight', 
     (SELECT id FROM departments WHERE name = 'Food & Civil Supplies Department'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.559200 23.033100)'),
     'fixed', 'private', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/14/whep',
     'online', true, 'h264', 1920, 1080, 12.5, 980,
     'rtsp://live.corp8.cloud:8554/stream/14', 'http://live.corp8.cloud:8889/stream/14/whep', '/live/stream/14/index.m3u8', now()),

    ('15', 'Camera 15', '15 Suvidha park', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.541100 23.037800)'),
     'dome', 'government', 'local', 30, 'http://live.corp8.cloud:8889/stream/15/whep',
     'online', true, 'h264', 1920, 1080, 12.5, 690,
     'rtsp://live.corp8.cloud:8554/stream/15', 'http://live.corp8.cloud:8889/stream/15/whep', '/live/stream/15/index.m3u8', now()),

    ('16', 'Camera 16', '16 Visat P2', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Ahmedabad'),
     ST_GeogFromText('SRID=4326;POINT(72.594200 23.109500)'),
     'PTZ', 'government', 'cloud', 60, 'http://live.corp8.cloud:8889/stream/16/whep',
     'online', true, 'h264', 1920, 1080, 12.5, 961,
     'rtsp://live.corp8.cloud:8554/stream/16', 'http://live.corp8.cloud:8889/stream/16/whep', '/live/stream/16/index.m3u8', now()),

    ('17', 'Camera 17', '17 Rajkot Bus Port CCTV', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Rajkot'),
     ST_GeogFromText('SRID=4326;POINT(70.796300 22.291600)'),
     'fixed', 'government', 'cloud', 90, 'http://live.corp8.cloud:8889/stream/17/whep',
     'online', true, 'hevc', 1920, 1080, 24.98, 671,
     'rtsp://live.corp8.cloud:8554/stream/17', 'http://live.corp8.cloud:8889/stream/17/whep', '/live/stream/17/index.m3u8', now()),

    ('18', 'Camera 18', '18 Rajkot CCTV', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Rajkot'),
     ST_GeogFromText('SRID=4326;POINT(70.802200 22.303900)'),
     'PTZ', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/18/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/18', 'http://live.corp8.cloud:8889/stream/18/whep', '/live/stream/18/index.m3u8', now()),

    ('19', 'Camera 19', '19 KHAPARIA GRAM PANCHAYAT , TALUKA GANDEVI, DISTRICT NAVSARI', 
     (SELECT id FROM departments WHERE name = 'Food & Civil Supplies Department'),
     (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(73.011400 20.814200)'),
     'bullet', 'private', 'local', 30, 'http://live.corp8.cloud:8889/stream/19/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/19', 'http://live.corp8.cloud:8889/stream/19/whep', '/live/stream/19/index.m3u8', now()),

    ('20', 'Camera 20', '20 Mohanpura', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Sabarkantha'),
     ST_GeogFromText('SRID=4326;POINT(72.863100 23.541400)'),
     'fixed', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/20/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/20', 'http://live.corp8.cloud:8889/stream/20/whep', '/live/stream/20/index.m3u8', now()),

    ('21', 'Camera 21', '23 Patan Dethali Char Rasta', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Patan'),
     ST_GeogFromText('SRID=4326;POINT(72.115800 23.829100)'),
     'PTZ', 'government', 'cloud', 60, 'http://live.corp8.cloud:8889/stream/21/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/21', 'http://live.corp8.cloud:8889/stream/21/whep', '/live/stream/21/index.m3u8', now()),

    ('22', 'Camera 22', '28 BK Mervada tran Rasta', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Banaskantha'),
     ST_GeogFromText('SRID=4326;POINT(72.411500 24.238400)'),
     'fixed', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/22/whep',
     'online', true, 'hevc', 1920, 1080, 25.0, 2091,
     'rtsp://live.corp8.cloud:8554/stream/22', 'http://live.corp8.cloud:8889/stream/22/whep', '/live/stream/22/index.m3u8', now()),

    ('23', 'Camera 23', '30 kheram', 
     (SELECT id FROM departments WHERE name = 'Food & Civil Supplies Department'),
     (SELECT id FROM districts WHERE name = 'Banaskantha'),
     ST_GeogFromText('SRID=4326;POINT(72.639100 23.955400)'),
     'bullet', 'private', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/23/whep',
     'online', true, 'h264', 1280, 720, 25.0, 4001,
     'rtsp://live.corp8.cloud:8554/stream/23', 'http://live.corp8.cloud:8889/stream/23/whep', '/live/stream/23/index.m3u8', now()),

    ('24', 'Camera 24', '33 dehgam', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Gandhinagar'),
     ST_GeogFromText('SRID=4326;POINT(72.822400 23.167200)'),
     'dome', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/24/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/24', 'http://live.corp8.cloud:8889/stream/24/whep', '/live/stream/24/index.m3u8', now()),

    ('25', 'Camera 25', '34 dhanori', 
     (SELECT id FROM departments WHERE name = 'Municipal Corporation'),
     (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.951200 20.732400)'),
     'fixed', 'government', 'local', 30, 'http://live.corp8.cloud:8889/stream/25/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/25', 'http://live.corp8.cloud:8889/stream/25/whep', '/live/stream/25/index.m3u8', now()),

    ('26', 'Camera 26', '35 TANKAL', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(73.195300 20.684100)'),
     'PTZ', 'government', 'cloud', 60, 'http://live.corp8.cloud:8889/stream/26/whep',
     'online', true, 'hevc', 2560, 1440, 13.35, 2411,
     'rtsp://live.corp8.cloud:8554/stream/26', 'http://live.corp8.cloud:8889/stream/26/whep', '/live/stream/26/index.m3u8', now()),

    ('27', 'Camera 27', '36 bilimora', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.964200 20.764400)'),
     'fixed', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/27/whep',
     'online', true, 'h264', 1280, 960, 24.86, 1112,
     'rtsp://live.corp8.cloud:8554/stream/27', 'http://live.corp8.cloud:8889/stream/27/whep', '/live/stream/27/index.m3u8', now()),

    ('28', 'Camera 28', '37 bilimora', 
     (SELECT id FROM departments WHERE name = 'Home Department (Police)'),
     (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.960100 20.761100)'),
     'dome', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/28/whep',
     'online', true, NULL, NULL, NULL, NULL, NULL,
     'rtsp://live.corp8.cloud:8554/stream/28', 'http://live.corp8.cloud:8889/stream/28/whep', '/live/stream/28/index.m3u8', now()),

    ('29', 'Camera 29', '38 bilimora', 
     (SELECT id FROM departments WHERE name = 'Food & Civil Supplies Department'),
     (SELECT id FROM districts WHERE name = 'Navsari'),
     ST_GeogFromText('SRID=4326;POINT(72.956800 20.758200)'),
     'bullet', 'private', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/29/whep',
     'online', true, 'h264', 1280, 960, 24.78, 907,
     'rtsp://live.corp8.cloud:8554/stream/29', 'http://live.corp8.cloud:8889/stream/29/whep', '/live/stream/29/index.m3u8', now()),

    ('30', 'Camera 30', 'Gandhidham Rambaugh p2', 
     (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)'),
     (SELECT id FROM districts WHERE name = 'Kutch'),
     ST_GeogFromText('SRID=4326;POINT(70.117200 23.076800)'),
     'fixed', 'government', 'cloud', 30, 'http://live.corp8.cloud:8889/stream/30/whep',
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