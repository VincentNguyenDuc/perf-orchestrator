SRC := src/

.PHONY: sync format format-check lint test test-unit test-integration

UV := uv

sync:
	$(UV) sync --extra dev

format:
	$(UV) run ruff format $(SRC)

format-check:
	$(UV) run ruff format --check $(SRC)

lint:
	$(UV) run ruff check $(SRC)

test:
	$(UV) run pytest

test-unit:
	$(UV) run pytest tests/unit/

test-integration:
	$(UV) run pytest tests/integration/
