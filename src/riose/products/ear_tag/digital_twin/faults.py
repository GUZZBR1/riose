"""Fault contracts for deterministic software-only adversarial runs."""

from __future__ import annotations

from typing import Any


# These contracts describe what the host C integration suite actually exercises.
# Unsupported electrical coupling remains an explicit blocker. An injected
# LIS2DW12 read failure is the required IMU fault; sample-quality policy is not
# a separate requirement in issue #7.
FAULT_SCENARIOS: tuple[dict[str, Any], ...] = (
    {"fault": "spi_timeout", "injection": "Fail one modeled SX1262 SPI transaction", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "integration:spi_timeout"},
    {"fault": "i2c_timeout", "injection": "Fail one modeled LIS2DW12 I2C read", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "integration:i2c_timeout"},
    {"fault": "sx1262_busy_stuck", "injection": "Hold SX1262 BUSY for bounded wait, release before retry", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "integration:sx1262_busy_stuck"},
    {"fault": "irq_missing", "injection": "Suppress TX/RX radio IRQ until software deadlines", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "RECOVERY", "host_argument": "integration:irq_missing"},
    {"fault": "crc_invalid", "injection": "Corrupt transmitted frame CRC; validate reject then valid next frame", "recovery_expected": True,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "PACKET_CREATED", "host_argument": "integration:crc_corruption"},
    {"fault": "voltage_drop", "injection": "Drop simulated rail below brownout threshold", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BROWNOUT", "host_argument": None,
     "blocker": "Electrical model has no firmware feedback interface"},
    {"fault": "high_esr", "injection": "Raise source ESR during an RF pulse", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BROWNOUT", "host_argument": None,
     "blocker": "No coupled ESR waveform injection"},
    {"fault": "regulator_instability", "injection": "Perturb regulator output under load", "recovery_expected": False,
     "attempts": 0, "terminal_state": "BLOCKED", "trace_event": "BROWNOUT", "host_argument": None,
     "blocker": "Electrical model has no firmware feedback interface"},
    {"fault": "synthetic_watchdog_classification_probe", "injection": "Advance synthetic host time, inject watchdog classification flag, call firmware init", "recovery_expected": False,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "BOOT", "host_argument": "host:synthetic_watchdog_classification_probe"},
    {"fault": "synthetic_reset_classification_probe", "injection": "Advance synthetic host time, inject CPU-lockup classification flag, call firmware init", "recovery_expected": False,
     "attempts": 1, "terminal_state": "SLEEP", "trace_event": "BOOT", "host_argument": "host:synthetic_reset_classification_probe"},
)
