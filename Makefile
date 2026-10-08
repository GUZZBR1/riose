.PHONY: setup demo test benchmark hardware-test hardware-demo hardware-native-sim hardware-renode-test ci-fast ci-scientific ci-main
HARDWARE_TEST_BUILD_DIR ?= /tmp/riose-ear-tag-hardware-tests-v2
setup:
	./setup.sh

demo:
	./run_demo.sh

test:
	uv run pytest -q

benchmark:
	uv run cattle-rf benchmark --profile full --output results

hardware-test:
	cmake -S hardware/tests -B "$(HARDWARE_TEST_BUILD_DIR)"
	cmake --build "$(HARDWARE_TEST_BUILD_DIR)"
	ctest --test-dir "$(HARDWARE_TEST_BUILD_DIR)" --output-on-failure

hardware-demo: hardware-test
	"$(HARDWARE_TEST_BUILD_DIR)/hardware_integration"

hardware-native-sim:
	west build -b native_sim/native/64 -d /tmp/riose-ear-tag-native-sim hardware/firmware/zephyr
	west build -d /tmp/riose-ear-tag-native-sim -t run > /tmp/riose-native-sim.log 2>&1 || { cat /tmp/riose-native-sim.log; exit 1; }
	cat /tmp/riose-native-sim.log
	python3 hardware/firmware/zephyr/trace_export.py /tmp/riose-native-sim.log --output /tmp/riose-native-sim-trace.jsonl
	west build -d /tmp/riose-ear-tag-native-sim -t run > /tmp/riose-native-sim-repeat.log 2>&1 || { cat /tmp/riose-native-sim-repeat.log; exit 1; }
	python3 hardware/firmware/zephyr/trace_export.py /tmp/riose-native-sim-repeat.log --output /tmp/riose-native-sim-repeat-trace.jsonl
	python3 hardware/firmware/zephyr/check_trace_determinism.py /tmp/riose-native-sim-trace.jsonl /tmp/riose-native-sim-repeat-trace.jsonl
	west build -b native_sim/native/64 -d /tmp/riose-ear-tag-native-sim-failure hardware/firmware/zephyr -- -DEXTRA_CONF_FILE=boards/native_sim_imu_failure.conf
	west build -d /tmp/riose-ear-tag-native-sim-failure -t run > /tmp/riose-native-sim-failure.log 2>&1 || { cat /tmp/riose-native-sim-failure.log; exit 1; }
	cat /tmp/riose-native-sim-failure.log
	python3 hardware/firmware/zephyr/trace_export.py /tmp/riose-native-sim-failure.log --output /tmp/riose-native-sim-failure-trace.jsonl
	west build -b native_sim/native/64 -d /tmp/riose-ear-tag-native-sim-trace-disabled hardware/firmware/zephyr -- -DEXTRA_CONF_FILE=boards/native_sim_trace_disabled.conf
	west build -d /tmp/riose-ear-tag-native-sim-trace-disabled -t run > /tmp/riose-native-sim-trace-disabled.log 2>&1 || { cat /tmp/riose-native-sim-trace-disabled.log; exit 1; }
	grep -q 'SIMULATED native_sim cycle PASS' /tmp/riose-native-sim-trace-disabled.log
	! grep -q 'SIMULATED_TRACE,' /tmp/riose-native-sim-trace-disabled.log

# Renode is an optional digital platform smoke test. It loads the surrogate
# platform and custom peripheral models; it does not claim STM32L031 fidelity.
hardware-renode-test:
	python3 hardware/renode/scripts/check_tools.py
	@if command -v renode >/dev/null 2>&1 && command -v renode-test >/dev/null 2>&1; then \
		renode-test hardware/renode/tests/platform-smoke.robot hardware/renode/tests/spi-transfer-timeout.robot; \
	else \
		echo "SKIPPED: install renode and renode-test to run the optional platform smoke test"; \
	fi

# These local entry points invoke the same gate runner used by GitHub Actions.
ci-fast:
	uv run python scripts/ci/run_gate.py fast

ci-scientific:
	uv run python scripts/ci/run_gate.py scientific

ci-main:
	uv run python scripts/ci/run_gate.py main
