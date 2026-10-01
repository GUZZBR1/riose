from __future__ import annotations

import pytest

from cattle_rf.contracts import EvidenceStatus
from cattle_rf.firmware.energy import EnergyLedger, EnergyProfile
from cattle_rf.firmware.tag import Activity, MemoryHAL, TagConfig, TagController, TagState, detect_optional_capabilities


def test_fsm_boots_and_adapts_beacon_cadence() -> None:
    hal = MemoryHAL()
    tag = TagController(TagConfig("tag-1", normal_beacon_period_s=100, active_beacon_period_s=20), hal)
    assert tag.boot() == TagState.IDLE
    tag.step(1, Activity.NORMAL)
    assert hal.transmissions == [("tag-1", False)]
    tag.step(10, Activity.RUNNING)
    assert tag.state == TagState.IMU_MONITORING
    tag.step(10, Activity.RUNNING)
    assert hal.transmissions[-1] == ("tag-1", True)
    assert tag.beacon_period_s == 20


def test_fence_and_stationary_anomaly_trigger_alert_mode() -> None:
    hal = MemoryHAL()
    tag = TagController(TagConfig("tag-1", normal_beacon_period_s=100, alert_beacon_period_s=5, stationary_alert_after_s=30), hal)
    tag.step(1, Activity.FENCE_WARNING)
    assert tag.state == TagState.ALERT_MODE
    assert tag.beacon_period_s == 5

    resting = TagController(TagConfig("tag-2", normal_beacon_period_s=100, stationary_alert_after_s=30), MemoryHAL())
    resting.step(20, Activity.STATIONARY_ANOMALY)
    assert resting.state == TagState.DEEP_SLEEP
    resting.step(10, Activity.STATIONARY_ANOMALY)
    assert resting.state == TagState.ALERT_MODE


def test_ble_wifi_modes_restore_previous_state() -> None:
    tag = TagController(TagConfig("tag-1"), MemoryHAL())
    tag.step(1)
    tag.set_radio_mode(TagState.BLE_ACTIVE)
    tag.step(5)
    assert tag.state == TagState.BLE_ACTIVE
    tag.end_radio_mode()
    assert tag.state == TagState.DEEP_SLEEP
    with pytest.raises(ValueError):
        tag.set_radio_mode(TagState.RF_TX)


def test_energy_is_integrated_and_lifetime_requires_capacity() -> None:
    profile = EnergyProfile("test", 1, 2, 3, 4, 5, 6, 7, 8, battery_capacity_mah=240)
    ledger = EnergyLedger(profile)
    ledger.record(10, 3600)
    ledger.record(20, 3600)
    report = ledger.report()
    assert report.consumed_mah == pytest.approx(30)
    assert report.average_current_ma == pytest.approx(15)
    assert report.energy_per_day_mah == pytest.approx(360)
    assert report.estimated_battery_life_days == pytest.approx(2 / 3)
    assert report.status == EvidenceStatus.ASSUMED

    no_battery = EnergyLedger(EnergyProfile.reference_stm32wle5())
    no_battery.record(10, 3600)
    assert no_battery.report().estimated_battery_life_days is None


def test_energy_rejects_invalid_values_and_optional_tools_are_reported() -> None:
    with pytest.raises(ValueError):
        EnergyProfile("bad", -1, 0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        EnergyLedger(EnergyProfile.reference_stm32wle5()).record(1, -2)
    capabilities = detect_optional_capabilities()
    assert {"zephyr_native_sim", "wokwi", "sionna"} <= capabilities.keys()
    assert all("available" in capability and "status" in capability for capability in capabilities.values())
