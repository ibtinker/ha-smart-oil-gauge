"""Integration tests for gauge-schedule syncing and its entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.smart_oil_gauge.client import (
    CannotConnect,
    SmartOilGaugeException,
    parse_sensor_config,
)
from custom_components.smart_oil_gauge.schedule import GRACE_S, TankSchedule
from tests.conftest import SENSOR_CONFIG_HTML
from tests.test_coordinator_history import CLIENT, LAST, WRITER, _setup, _tank

LAST_READ = datetime.fromtimestamp(LAST["ts"], UTC)


@pytest.fixture(autouse=True)
def frozen_now():
    """Pretend it is one hour after the last upload."""
    now = LAST_READ + timedelta(hours=1)
    with patch(f"{WRITER}.dt_util.utcnow", return_value=now):
        yield now


@pytest.fixture(autouse=True)
def no_writes():
    """No recorder writes in these tests."""
    with (
        patch(f"{WRITER}.async_backfill_states", new=AsyncMock()),
        patch(f"{WRITER}.async_import_hourly_statistics", new=AsyncMock()),
    ):
        yield


async def test_gauge_mode_polls_after_expected_upload(
    hass: HomeAssistant, frozen_now
) -> None:
    """Sync just after the next expected upload, from the portal interval."""
    entry, _, _ = await _setup(hass, [_tank()], schedule_mode="gauge")
    coordinator = entry.runtime_data.coordinator
    expected = LAST_READ + timedelta(hours=12)
    poll_at = expected + timedelta(seconds=GRACE_S)
    # 11 hours away is beyond the 6-hour cap.
    assert coordinator.update_interval == timedelta(hours=6)
    assert coordinator.next_expected_upload("940670") == expected

    sched = coordinator.schedules["940670"]
    assert (sched.configured_h, sched.effective_h, sched.num_tanks) == (12, 12, 2)

    next_upload = hass.states.get("sensor.test_tank_next_gauge_upload")
    assert next_upload.state == expected.isoformat()
    assert next_upload.attributes["overdue"] is False

    select = hass.states.get("select.test_tank_upload_interval")
    assert select.state == "12"
    assert select.attributes["effective_interval_hours"] == 12
    assert select.attributes["pending"] is False
    assert select.attributes["interval_source"] == "portal"
    assert select.attributes["number_of_tanks"] == 2
    assert (
        hass.states.get("binary_sensor.test_tank_upload_interval_change_pending").state
        == "off"
    )
    from custom_components.smart_oil_gauge.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)
    tank = diag["schedule"]["tank_1"]
    assert diag["schedule"]["mode"] == "gauge"
    assert tank["portal_interval_hours"] == 12
    assert tank["pending"] is False
    assert tank["next_expected_upload"] == expected.isoformat()

    # Closer to the upload, the next sync is just after it.
    with patch(f"{WRITER}.dt_util.utcnow", return_value=expected - timedelta(hours=1)):
        coordinator._plan_next_poll(coordinator.data)
    assert coordinator.next_poll_at == poll_at
    await hass.config_entries.async_unload(entry.entry_id)


async def test_fixed_mode_keeps_configured_interval(hass: HomeAssistant) -> None:
    """Fixed mode behaves as before."""
    entry, _, _ = await _setup(
        hass, [_tank()], schedule_mode="fixed", update_interval_hours=3
    )
    coordinator = entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(hours=3)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unreadable_config_falls_back(
    hass: HomeAssistant, mock_sensor_config, caplog
) -> None:
    """If the interval can't be read, syncing continues on the fallback."""
    mock_sensor_config.side_effect = CannotConnect("down")
    entry, _, _ = await _setup(hass, [_tank()], schedule_mode="gauge")
    coordinator = entry.runtime_data.coordinator
    assert coordinator.last_update_success
    assert coordinator.schedules["940670"].config_error == "down"
    assert coordinator.next_expected_upload("940670") is None
    assert "Could not read the upload interval" in caplog.text
    await hass.config_entries.async_unload(entry.entry_id)


async def test_new_upload_applies_pending_interval(
    hass: HomeAssistant, mock_sensor_config
) -> None:
    """A portal change is pending until the gauge's next upload."""
    entry, _, _ = await _setup(hass, [_tank()], schedule_mode="gauge")
    coordinator = entry.runtime_data.coordinator

    one_hour = parse_sensor_config(
        SENSOR_CONFIG_HTML.replace(" selected>12", ">12").replace(
            '<option value="1">', '<option value="1" selected>'
        )
    )
    mock_sensor_config.return_value = one_hour
    with patch(f"{CLIENT}.async_get_tanks", return_value=[_tank()]):
        await coordinator.async_refresh()
    sched = coordinator.schedules["940670"]
    assert sched.pending
    assert coordinator.next_expected_upload("940670") == LAST_READ + timedelta(hours=12)

    later = _tank(last_read=str(LAST["ts"] + 12 * 3600))
    with (
        patch(f"{CLIENT}.async_get_tanks", return_value=[later]),
        patch(f"{CLIENT}.async_get_graph_data", new=AsyncMock(return_value={})),
    ):
        await coordinator.async_refresh()
    assert not sched.pending
    assert sched.effective_h == 1
    await hass.config_entries.async_unload(entry.entry_id)


async def test_sync_now_button_refreshes(hass: HomeAssistant) -> None:
    """Sync now polls the portal immediately."""
    entry, tanks_mock, _ = await _setup(hass, [_tank()])
    with patch(f"{CLIENT}.async_get_tanks", return_value=[_tank()]) as again:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.test_tank_sync_now"}, blocking=True
        )
    again.assert_awaited_once()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_select_changes_interval(hass: HomeAssistant) -> None:
    """Choosing an interval writes it to the portal and shows it as pending."""
    entry, _, _ = await _setup(hass, [_tank()])
    six = parse_sensor_config(
        SENSOR_CONFIG_HTML.replace(" selected>12", ">12").replace(
            '<option value="6">', '<option value="6" selected>'
        )
    )
    with patch(f"{CLIENT}.async_set_upload_interval", return_value=six) as setter:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.test_tank_upload_interval", "option": "6"},
            blocking=True,
        )
    setter.assert_awaited_once_with("71796", 6)
    state = hass.states.get("select.test_tank_upload_interval")
    assert state.state == "6"
    assert state.attributes["pending"] is True
    assert state.attributes["effective_interval_hours"] == 12
    pending = hass.states.get("binary_sensor.test_tank_upload_interval_change_pending")
    assert pending.state == "on"
    assert pending.attributes["portal_interval_hours"] == 6
    assert pending.attributes["gauge_interval_hours"] == 12

    with (
        patch(
            f"{CLIENT}.async_set_upload_interval",
            side_effect=SmartOilGaugeException("description changed"),
        ),
        pytest.raises(HomeAssistantError, match="description changed"),
    ):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.test_tank_upload_interval", "option": "6"},
            blocking=True,
        )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_registration_means_no_select(hass: HomeAssistant) -> None:
    """Tanks without a sensor registration get no interval select."""
    entry, _, _ = await _setup(hass, [_tank(sensors=[])])
    assert hass.states.get("select.test_tank_upload_interval") is None
    coordinator = entry.runtime_data.coordinator
    with pytest.raises(SmartOilGaugeException):
        await coordinator.async_set_upload_interval("940670", 6)
    await hass.config_entries.async_unload(entry.entry_id)


def test_active_registration_prefers_current_sensor() -> None:
    """The current (not ended) registration is used."""
    from custom_components.smart_oil_gauge.coordinator import (
        SmartOilGaugeDataUpdateCoordinator as C,
    )

    tank = {
        "sensors": [
            {"registration_id": "1", "end_date": "2026-01-01"},
            {"registration_id": "2", "end_date": None},
            {"no": "id"},
        ]
    }
    assert C.active_registration_id(tank) == "2"
    assert C.active_registration_id({"sensors": "x"}) is None
    assert (
        C.active_registration_id(
            {"sensors": [{"registration_id": "9", "end_date": "x"}]}
        )
        == "9"
    )
    assert TankSchedule().interval() == (None, "unknown")
