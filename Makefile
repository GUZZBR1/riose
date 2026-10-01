.PHONY: setup demo test benchmark hardware-test hardware-demo hardware-native-sim
setup:
	./setup.sh

demo:
	./run_demo.sh

test:
	uv run pytest -q

benchmark:
	uv run cattle-rf benchmark --profile full --output results

hardware-test:
	cmake -S hardware/tests -B /tmp/cattle-rf-hardware-tests
	cmake --build /tmp/cattle-rf-hardware-tests
	ctest --test-dir /tmp/cattle-rf-hardware-tests --output-on-failure

hardware-demo: hardware-test
	/tmp/cattle-rf-hardware-tests/hardware_integration

hardware-native-sim:
	west build -b native_sim/native/64 -d /tmp/cattle-rf-native-sim hardware/firmware/zephyr
	west build -d /tmp/cattle-rf-native-sim -t run
