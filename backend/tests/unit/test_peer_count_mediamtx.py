"""Unit tests for the MediaMTX-backed viewer count."""

import asyncio
import unittest

from tests.unit._stubs import ensure_aiohttp, ensure_litestar

ensure_litestar()
ensure_aiohttp()

from controllers.peer_count_controller import get_viewer_count  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, body=None, raise_on_json=False):
        self.status = status
        self._body = body or {}
        self._raise = raise_on_json

    async def json(self):
        if self._raise:
            raise ValueError("bad json")
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.last_url = None

    def get(self, url, **kwargs):
        self.last_url = url
        if self._exc:
            raise self._exc
        return self._response


def count(session):
    return asyncio.run(get_viewer_count(session))


class TestGetViewerCount(unittest.TestCase):
    def test_counts_readers(self):
        session = FakeSession(FakeResponse(200, {"readers": [
            {"type": "webRTCSession", "id": "a"},
            {"type": "hlsMuxer", "id": "b"},
        ]}))
        self.assertEqual(count(session), 2)

    def test_polls_the_configured_path(self):
        session = FakeSession(FakeResponse(200, {"readers": []}))
        count(session)
        self.assertIn("/v3/paths/get/", session.last_url)

    def test_zero_when_no_readers_key(self):
        self.assertEqual(count(FakeSession(FakeResponse(200, {}))), 0)

    def test_zero_when_path_inactive(self):
        # 404 = path not active (Pi offline) — not an error condition
        self.assertEqual(count(FakeSession(FakeResponse(404))), 0)

    def test_zero_on_api_error_status(self):
        self.assertEqual(count(FakeSession(FakeResponse(500))), 0)

    def test_zero_on_network_error(self):
        self.assertEqual(count(FakeSession(exc=ConnectionError("down"))), 0)

    def test_zero_on_malformed_body(self):
        self.assertEqual(
            count(FakeSession(FakeResponse(200, raise_on_json=True))), 0)


if __name__ == "__main__":
    unittest.main()
