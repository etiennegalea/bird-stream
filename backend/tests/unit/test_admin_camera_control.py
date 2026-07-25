from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from litestar.exceptions import HTTPException

import controllers.admin_controller as controller


@pytest.fixture(autouse=True)
def admin_and_mqtt(monkeypatch):
    monkeypatch.setattr(controller, "_require_admin", lambda request, db: 7)
    send = Mock()
    monkeypatch.setattr(controller.mqtt_devices, "send_control", send)
    return send


@pytest.mark.asyncio
async def test_start_one_camera_publishes_scoped_mqtt_command(admin_and_mqtt):
    result = await controller.AdminController.control_stream_camera.fn(
        None,
        request=object(),
        state=SimpleNamespace(db=object()),
        pi_id="pi-01",
        camera_id="cam-2",
        action="start",
    )
    admin_and_mqtt.assert_called_once_with(
        "pi-01", "start", params={"camera_id": "cam-2"})
    assert result["camera_id"] == "cam-2"


@pytest.mark.asyncio
async def test_camera_route_rejects_unsupported_action(admin_and_mqtt):
    with pytest.raises(HTTPException) as exc:
        await controller.AdminController.control_stream_camera.fn(
            None,
            request=object(),
            state=SimpleNamespace(db=object()),
            pi_id="pi-01",
            camera_id="cam-2",
            action="reboot",
        )
    assert exc.value.status_code == 400
    admin_and_mqtt.assert_not_called()


@pytest.mark.asyncio
async def test_disable_camera_publishes_persistent_control(admin_and_mqtt):
    data = controller.CameraEnabledRequest(enabled=False)
    result = await controller.AdminController.set_stream_camera_enabled.fn(
        None,
        request=object(),
        state=SimpleNamespace(db=object()),
        pi_id="pi-01",
        camera_id="cam-2",
        data=data,
    )
    admin_and_mqtt.assert_called_once_with(
        "pi-01",
        "set_camera_enabled",
        params={"camera_id": "cam-2", "enabled": False},
    )
    assert result["enabled"] is False


@pytest.mark.asyncio
async def test_broker_failure_becomes_service_unavailable(
    admin_and_mqtt,
):
    admin_and_mqtt.side_effect = RuntimeError("MQTT broker not connected")
    with pytest.raises(HTTPException) as exc:
        await controller.AdminController.control_stream_camera.fn(
            None,
            request=object(),
            state=SimpleNamespace(db=object()),
            pi_id="pi-01",
            camera_id="cam-2",
            action="stop",
        )
    assert exc.value.status_code == 503
