"""Unit tests for the MediaMTX external auth hook."""

import asyncio
import os
import unittest
from unittest import mock

from tests.unit._stubs import ensure_auth_service, ensure_litestar

ensure_litestar()
ensure_auth_service()

from litestar.exceptions import HTTPException  # noqa: E402

import controllers.mediamtx_controller as mc  # noqa: E402


def auth(data: dict):
    """Run the async authenticate logic; returns None when allowed.

    Calls the module-level function directly so the test doesn't depend on
    instantiating the Litestar Controller (whose __init__ requires an owner
    and whose @post wraps the method in a route handler)."""
    return asyncio.run(mc.authenticate_request(data=data))


PUBLISH_ENV = {"MEDIAMTX_PUBLISH_USER": "picam",
               "MEDIAMTX_PUBLISH_PASSWORD": "sekrit"}


class TestPublishAuth(unittest.TestCase):
    def test_correct_credentials_allowed(self):
        with mock.patch.dict(os.environ, PUBLISH_ENV):
            self.assertIsNone(auth({"action": "publish", "path": "birdcam",
                                    "protocol": "srt", "user": "picam",
                                    "password": "sekrit"}))

    def test_wrong_password_denied(self):
        with mock.patch.dict(os.environ, PUBLISH_ENV):
            with self.assertRaises(HTTPException) as ctx:
                auth({"action": "publish", "user": "picam", "password": "nope"})
            self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_user_denied(self):
        with mock.patch.dict(os.environ, PUBLISH_ENV):
            with self.assertRaises(HTTPException):
                auth({"action": "publish", "user": "evil", "password": "sekrit"})

    def test_denied_when_password_not_configured(self):
        env = {"MEDIAMTX_PUBLISH_USER": "picam"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("MEDIAMTX_PUBLISH_PASSWORD", None)
            with self.assertRaises(HTTPException):
                auth({"action": "publish", "user": "picam", "password": ""})

    def test_missing_credentials_denied(self):
        with mock.patch.dict(os.environ, PUBLISH_ENV):
            with self.assertRaises(HTTPException):
                auth({"action": "publish"})


class TestReadAuth(unittest.TestCase):
    def setUp(self):
        # Default state: anonymous reads allowed, stream not blocked
        os.environ.pop("MEDIAMTX_REQUIRE_READ_AUTH", None)
        mc.stream_settings.video_enabled = True
        mc.stream_settings.audio_enabled = True

    def test_anonymous_read_allowed_by_default(self):
        self.assertIsNone(auth({"action": "read", "path": "birdcam",
                                "protocol": "webrtc"}))

    def test_internal_rtsp_read_always_allowed(self):
        with mock.patch.dict(os.environ, {"MEDIAMTX_REQUIRE_READ_AUTH": "true"}):
            self.assertIsNone(auth({"action": "read", "protocol": "rtsp"}))

    def test_read_denied_without_jwt_when_auth_required(self):
        with mock.patch.dict(os.environ, {"MEDIAMTX_REQUIRE_READ_AUTH": "true"}):
            with self.assertRaises(HTTPException):
                auth({"action": "read", "protocol": "webrtc", "query": ""})

    def test_read_allowed_with_valid_jwt(self):
        with mock.patch.dict(os.environ, {"MEDIAMTX_REQUIRE_READ_AUTH": "true"}), \
             mock.patch.object(mc.auth_svc, "decode_jwt",
                               side_effect=lambda t: {"sub": "1"} if t == "good" else None):
            self.assertIsNone(auth({"action": "read", "protocol": "webrtc",
                                    "query": "jwt=good"}))
            with self.assertRaises(HTTPException):
                auth({"action": "read", "protocol": "webrtc", "query": "jwt=bad"})

    def test_read_denied_while_stream_fully_blocked(self):
        mc.stream_settings.video_enabled = False
        mc.stream_settings.audio_enabled = False
        if not hasattr(mc.stream_settings, "fully_blocked"):
            self.skipTest("stream_settings has no fully_blocked()")
        with self.assertRaises(HTTPException):
            auth({"action": "read", "protocol": "webrtc"})


class TestOtherActions(unittest.TestCase):
    def test_api_action_allowed(self):
        # backend peer-count polling hits the (unpublished) control API
        self.assertIsNone(auth({"action": "api"}))

    def test_metrics_denied(self):
        with self.assertRaises(HTTPException):
            auth({"action": "metrics"})

    def test_unknown_action_denied(self):
        with self.assertRaises(HTTPException):
            auth({"action": "playback-list"})


if __name__ == "__main__":
    unittest.main()
