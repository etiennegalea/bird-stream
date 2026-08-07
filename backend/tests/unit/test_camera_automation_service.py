from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.orm import Base
from services.camera_automation_service import CameraAutomationService


def configured_service(settings=None):
    service = CameraAutomationService()
    service._mqtt = Mock()
    service._settings["pi-01"] = settings or {
        "auto_manage_pov": True,
        "bird_triggered_pov": False,
    }
    return service


def device(*, pov_enabled=False, pov_status="idle"):
    return {
        "pi_id": "pi-01",
        "streams": [
            {
                "camera_id": "feeder", "primary": True,
                "role": None, "enabled": True, "status": "streaming",
                "path": "birdcam",
            },
            {
                "camera_id": "side", "primary": False,
                "role": None, "enabled": True, "status": "streaming",
                "path": "birdcam-pi-01-side",
            },
            {
                "camera_id": "close-up", "primary": False,
                "role": "pov", "enabled": pov_enabled, "status": pov_status,
                "path": "birdcam-pi-01-close-up",
            },
        ],
    }


def test_managed_inventory_enables_pov_and_disables_other_secondary_camera():
    service = configured_service()

    service.handle_device_status(device())

    assert service._mqtt.send_control.call_args_list == [
        (("pi-01", "set_camera_enabled"), {
            "params": {"camera_id": "side", "enabled": False},
        }),
        (("pi-01", "set_camera_enabled"), {
            "params": {"camera_id": "close-up", "enabled": True},
        }),
        (("pi-01", "start"), {
            "params": {"camera_id": "close-up"},
        }),
    ]


def test_normal_managed_mode_keeps_idle_pov_camera_running():
    service = configured_service()

    service.handle_device_status(device(pov_enabled=True, pov_status="idle"))

    assert any(
        call.args == ("pi-01", "start")
        and call.kwargs == {"params": {"camera_id": "close-up"}}
        for call in service._mqtt.send_control.call_args_list
    )


def test_normal_managed_mode_respects_device_schedule_rest():
    service = configured_service()
    resting = device(pov_enabled=True, pov_status="idle")
    resting["resting"] = True

    service.handle_device_status(resting)

    assert not any(
        call.args[1] == "start"
        for call in service._mqtt.send_control.call_args_list
    )


def test_primary_is_never_changed_with_legacy_status_shape():
    service = configured_service()
    legacy = device()
    for stream in legacy["streams"]:
        stream.pop("primary")
    legacy["streams"][0]["enabled"] = False

    service.handle_device_status(legacy)

    changed_ids = [
        call.kwargs["params"]["camera_id"]
        for call in service._mqtt.send_control.call_args_list
    ]
    assert "feeder" not in changed_ids


def test_bird_detection_condition_starts_pov_without_waiting_for_email():
    service = configured_service({
        "auto_manage_pov": True,
        "bird_triggered_pov": True,
    })
    service.handle_device_status(device(pov_enabled=True, pov_status="idle"))
    service._mqtt.send_control.reset_mock()

    service.bird_detection_triggered("pi-01")

    service._mqtt.send_control.assert_called_once_with(
        "pi-01", "start", params={"camera_id": "close-up"}
    )
    assert service.active_pov_target() == {
        "pi_id": "pi-01", "path": "birdcam-pi-01-close-up",
    }


def test_detection_trigger_is_ignored_when_device_setting_is_off():
    service = configured_service({
        "auto_manage_pov": True,
        "bird_triggered_pov": False,
    })
    service.handle_device_status(device(pov_enabled=True, pov_status="idle"))
    service._mqtt.send_control.reset_mock()

    service.bird_detection_triggered("pi-01")

    service._mqtt.send_control.assert_not_called()


def test_pov_waits_for_cat_result_after_primary_bird_leaves():
    service = configured_service({
        "auto_manage_pov": True,
        "bird_triggered_pov": True,
    })
    idle = device(pov_enabled=True, pov_status="idle")
    service.handle_device_status(idle)
    service._mqtt.send_control.reset_mock()

    service.bird_detection_triggered("pi-01")
    service._mqtt.send_control.reset_mock()
    service.bird_presence_ended()

    service._mqtt.send_control.assert_not_called()

    service.pov_cat_presence_changed("pi-01", False)
    service._mqtt.send_control.assert_called_once_with(
        "pi-01", "stop", params={"camera_id": "close-up"}
    )


def test_cat_keeps_pov_running_until_both_streams_are_clear():
    service = configured_service({
        "auto_manage_pov": True,
        "bird_triggered_pov": True,
    })
    service.handle_device_status(device(pov_enabled=True, pov_status="idle"))
    service._mqtt.send_control.reset_mock()
    service.bird_detection_triggered("pi-01")
    service._mqtt.send_control.reset_mock()

    service.pov_cat_presence_changed("pi-01", True)
    service.bird_presence_ended()
    service._mqtt.send_control.assert_not_called()

    service.pov_cat_presence_changed("pi-01", False)
    service._mqtt.send_control.assert_called_once_with(
        "pi-01", "stop", params={"camera_id": "close-up"}
    )


def test_primary_bird_keeps_pov_running_when_cat_is_absent():
    service = configured_service({
        "auto_manage_pov": True,
        "bird_triggered_pov": True,
    })
    service.handle_device_status(device(pov_enabled=True, pov_status="idle"))
    service.bird_detection_triggered("pi-01")
    service._mqtt.send_control.reset_mock()

    service.pov_cat_presence_changed("pi-01", False)

    service._mqtt.send_control.assert_not_called()


def test_detection_stream_is_resolved_to_its_owning_device():
    service = configured_service()
    service.handle_device_status(device())

    assert service.device_id_for_stream_url(
        "rtsp://mediamtx:8554/birdcam"
    ) == "pi-01"
    assert service.device_id_for_stream_url(
        "rtsp://mediamtx:8554/unknown"
    ) is None


def test_per_device_settings_are_persisted_and_reloaded():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db_factory = sessionmaker(bind=engine)
    service = CameraAutomationService()

    result = service.update(
        "pi-01",
        auto_manage_pov=True,
        bird_triggered_pov=True,
        db_factory=db_factory,
    )
    reloaded = CameraAutomationService()
    reloaded.load(db_factory)

    assert result == {
        "auto_manage_pov": True,
        "bird_triggered_pov": True,
    }
    assert reloaded.snapshot("pi-01") == result
