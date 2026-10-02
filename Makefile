.PHONY: setup demo test benchmark hardware-test hardware-demo hardware-native-sim hardware-renode-test
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
	west build -d /tmp/riose-ear-tag-native-sim -t run

# Renode is an optional digital platform smoke test. It loads the surrogate
# platform and custom peripheral models; it does not claim STM32L031 fidelity.
hardware-renode-test:
	python3 hardware/renode/scripts/check_tools.py
	@command -v renode >/dev/null 2>&1 && command -v renode-test >/dev/null 2>&1 || { echo "SKIPPED: install renode and renode-test to run the optional platform smoke test"; exit 0; }
	renode-test hardware/renode/tests/platform-smoke.robot
