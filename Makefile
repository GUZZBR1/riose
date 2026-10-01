.PHONY: setup demo test benchmark
setup:
	./setup.sh

demo:
	./run_demo.sh

test:
	uv run pytest -q

benchmark:
	uv run cattle-rf benchmark --profile full --output results
