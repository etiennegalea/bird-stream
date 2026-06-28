async def test_offer_empty_sdp_returns_400(client):
    response = await client.post(
        "/webrtc/offer",
        json={"id": "t1", "offer": {"type": "offer", "sdp": ""}},
    )
    assert response.status_code == 400


async def test_offer_missing_offer_field_returns_400(client):
    response = await client.post("/webrtc/offer", json={"id": "t2"})
    assert response.status_code in (400, 422)


async def test_offer_missing_id_field_returns_400(client):
    response = await client.post(
        "/webrtc/offer",
        json={"offer": {"type": "offer", "sdp": "v=0\r\n"}},
    )
    assert response.status_code in (400, 422)


async def test_offer_invalid_body_returns_400(client):
    response = await client.post(
        "/webrtc/offer",
        content=b"not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)


async def test_get_peers_returns_list(client):
    response = await client.get("/webrtc/getpeers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_get_peers_verbose_returns_dict(client):
    response = await client.get("/webrtc/getpeers?verbose=true")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


async def test_webrtc_config_shape(client):
    response = await client.get("/webrtc/config")
    assert response.status_code == 200
    body = response.json()
    assert {"pool_size", "port_min", "port_max", "port_range"} <= body.keys()
    assert body["port_range"] == body["port_max"] - body["port_min"] + 1
    assert body["port_min"] < body["port_max"]
