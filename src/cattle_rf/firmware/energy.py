"""Transparent, configurable energy accounting for a virtual livestock tag.

Currents are configuration inputs, not measured claims. The reference profile
uses approximate figures provided in the MVP brief and is explicitly labelled
ASSUMED until verified against a selected part and board implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from cattle_rf.contracts import EvidenceStatus


@dataclass(frozen=True, slots=True)
class EnergyProfile:
    profile_id: str
    sleep_ma: float
    idle_ma: float
    imu_monitoring_ma: float
    rf_tx_ma: float
    rf_rx_ma: float
    ble_active_ma: float
    wifi_active_ma: float
    alert_ma: float
    battery_capacity_mah: float | None = None
    status: EvidenceStatus = EvidenceStatus.ASSUMED
    source: str = (
        "TX/RX and sleep values use approximate figures supplied in the MVP brief; "
        "idle, IMU, BLE, Wi-Fi and alert values are configurable placeholder assumptions. "
        "Verify the complete board profile by measurement."
    )

    def __post_init__(self) -> None:
        currents = (
            self.sleep_ma,
            self.idle_ma,
            self.imu_monitoring_ma,
            self.rf_tx_ma,
            self.rf_rx_ma,
            self.ble_active_ma,
            self.wifi_active_ma,
            self.alert_ma,
        )
        if any(current < 0 for current in currents):
            raise ValueError("currents must be non-negative")
        if self.battery_capacity_mah is not None and self.battery_capacity_mah <= 0:
            raise ValueError("battery capacity must be positive when supplied")

    @classmethod
    def reference_stm32wle5(cls, battery_capacity_mah: float | None = None) -> "EnergyProfile":
        """Approximate demo inputs; all unspecified rails remain explicit assumptions."""
        return cls(
            profile_id="stm32wle5-reference-assumed",
            sleep_ma=0.001,
            idle_ma=0.5,
            imu_monitoring_ma=0.685,
            rf_tx_ma=15.0,
            rf_rx_ma=4.82,
            ble_active_ma=8.0,
            wifi_active_ma=80.0,
            alert_ma=15.0,
            battery_capacity_mah=battery_capacity_mah,
        )


@dataclass(frozen=True, slots=True)
class EnergyReport:
    duration_s: float
    consumed_mah: float
    average_current_ma: float
    energy_per_day_mah: float
    estimated_battery_life_days: float | None
    status: EvidenceStatus
    profile_id: str
    profile_source: str


class EnergyLedger:
    """Accumulates current-time intervals and derives daily use and life."""

    def __init__(self, profile: EnergyProfile) -> None:
        self.profile = profile
        self._charge_mah = 0.0
        self._duration_s = 0.0

    def record(self, current_ma: float, duration_s: float) -> None:
        if current_ma < 0 or duration_s < 0:
            raise ValueError("current and duration must be non-negative")
        self._charge_mah += current_ma * duration_s / 3600.0
        self._duration_s += duration_s

    def report(self) -> EnergyReport:
        avg = self._charge_mah / (self._duration_s / 3600.0) if self._duration_s else 0.0
        daily = avg * 24.0
        life = (
            self.profile.battery_capacity_mah / daily
            if self.profile.battery_capacity_mah is not None and daily > 0
            else None
        )
        return EnergyReport(
            duration_s=self._duration_s,
            consumed_mah=self._charge_mah,
            average_current_ma=avg,
            energy_per_day_mah=daily,
            estimated_battery_life_days=life,
            status=self.profile.status,
            profile_id=self.profile.profile_id,
            profile_source=self.profile.source,
        )
