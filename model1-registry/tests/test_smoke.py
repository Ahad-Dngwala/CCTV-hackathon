def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_seeded_admin_can_login(admin_home_client):
    resp = admin_home_client.get("/api/v1/cameras")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
