def test_login_success_sets_httponly_cookie(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_home", "password": "password123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["user"]["username"] == "admin_home"
    assert body["user"]["role"] == "dept_admin"
    assert body["user"]["department_id"] is not None

    cookie = resp.cookies.get("access_token")
    assert cookie is not None
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header


def test_login_wrong_password_rejected(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_home", "password": "not-the-password"},
    )
    assert resp.status_code == 401


def test_login_unknown_username_rejected(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "someone_who_does_not_exist", "password": "password123"},
    )
    assert resp.status_code == 401


def test_protected_endpoint_requires_auth(anon_client):
    # create_camera requires dept_admin auth
    resp = anon_client.post("/api/v1/cameras", json={"name": "Should Fail"})
    assert resp.status_code == 401


def test_logout_clears_session(admin_home_client):
    # Confirm authenticated first
    assert admin_home_client.get("/api/v1/cameras").status_code == 200

    resp = admin_home_client.post("/api/v1/auth/logout")
    assert resp.status_code in (200, 204)

    # Map page should now redirect to /login since user is anonymous again.
    # (TestClient follows redirects by default; check final URL.)
    page = admin_home_client.get("/", follow_redirects=False)
    assert page.status_code in (302, 303, 307)
    assert "/login" in page.headers.get("location", "")


def test_operator_and_viewer_can_login_but_are_not_dept_admin(operator_client, viewer_client):
    assert operator_client.get("/api/v1/cameras").status_code == 200
    assert viewer_client.get("/api/v1/cameras").status_code == 200

    # Neither role may create a camera (require_role("dept_admin"))
    assert operator_client.post("/api/v1/cameras", json={"name": "X"}).status_code == 403
    assert viewer_client.post("/api/v1/cameras", json={"name": "X"}).status_code == 403
