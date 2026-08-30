-- Seed Default Users for Model 1 Phase 2 Auth & RBAC
INSERT INTO users (username, email, hashed_password, role, department_id)
VALUES
    ('admin_home', 'admin.home@sentinel.gujarat.gov.in', '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'dept_admin', (SELECT id FROM departments WHERE name = 'Home Department (Police)')),
    ('admin_rto', 'admin.rto@sentinel.gujarat.gov.in', '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'dept_admin', (SELECT id FROM departments WHERE name = 'Regional Transport Office (RTO)')),
    ('operator1', 'operator1@sentinel.gujarat.gov.in', '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'operator', NULL),
    ('viewer1', 'viewer1@sentinel.gujarat.gov.in', '$2b$12$vLHB6Nu1G9aXJoy0O2otYOWD4gEM4sm02d1Gy3wEhGKYjsvUXRUXW', 'viewer', NULL)
ON CONFLICT (username) DO NOTHING;
