async def test_peer_count_sends_count(client):
    with await client.websocket_connect("/peer-count") as ws:
        msg = ws.receive_json()
        assert "count" in msg
        assert isinstance(msg["count"], int)
        assert msg["count"] >= 0


async def test_peer_count_reflects_active_webrtc_peers(client):
    """Count is based on pcs_manager, which starts empty in tests."""
    with await client.websocket_connect("/peer-count") as ws:
        msg = ws.receive_json()
        assert msg["count"] == 0
