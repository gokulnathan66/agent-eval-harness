export PYTHONPATH := src

.PHONY: eval test

eval:
	python3 -m eval_harness eval

test:
	python3 -m pytest -q
