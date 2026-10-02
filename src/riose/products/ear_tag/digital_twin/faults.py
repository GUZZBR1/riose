"""Fault contracts for deterministic software-only adversarial runs."""

from __future__ import annotations

from typing import Any


# These contracts describe what the host C integration suite actually exercises.
# Unsupported electrical/reset couplings remain explicit blockers.
FAULT_SCENARIOS: tuple[dict[str, Any], ...] = (
    {"fault": "i2c_timeout", "injection": "Fail one IMU I2C read", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "test_imu_failure_recovery"},
    {"fault": "spi_timeout", "injection": "Fail one SPI transfer", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "test_radio_fault_recovery"},
    {"fault": "late_tx_done_timeout", "injection": "Suppress TX done IRQ until software deadline", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "test_missing_tx_done_timeout"},
    {"fault": "sx1262_busy_stuck", "injection": "Hold SX1262 BUSY, enforce 100 ms bound, then release", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "digital_fault_sx1262_busy_stuck"},
    {"fault": "irq_missing", "injection": "Hide radio IRQ until software deadline", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "digital_fault_irq_missing"},
    {"fault": "crc_invalid", "injection": "Corrupt frame CRC and then send a valid frame", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "CRC_REJECT", "host_argument": "digital_fault_crc_corruption"},
    {"fault": "voltage_drop", "injection": "Drop simulated rail below brownout threshold", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BROWNOUT", "host_argument": None,
     "blocker": "Electrical model has no firmware feedback interface"},
    {"fault": "high_esr", "injection": "Raise source ESR during an RF pulse", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BROWNOUT", "host_argument": None,
     "blocker": "No coupled ESR waveform injection"},
    {"fault": "regulator_instability", "injection": "Perturb regulator output under load", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BROWNOUT", "host_argument": None,
     "blocker": "Electrical model has no firmware feedback interface"},
    {"fault": "watchdog_reset", "injection": "Expire MCU watchdog on target", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "RESET_CAUSE", "host_argument": None,
     "blocker": "Physical MCU reset cannot be executed by the host integration suite"},
    {"fault": "unexpected_reboot", "injection": "Reinitialize outside planned sleep", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BOOT", "host_argument": None,
     "blocker": "No retained reset supervisor/trace contract"},
)
