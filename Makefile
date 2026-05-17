SRC := src/

.PHONY: format format-check lint

VENV := ../../.venv/bin

format:
	$(VENV)/black $(SRC)

format-check:
	$(VENV)/black --check $(SRC)

lint:
	$(VENV)/ruff check $(SRC)
