PYTHON = /Users/sqliang/.local/bin/python3.11

.PHONY: install run dev test lint clean

install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r server/requirements.txt

run:
	cd server && ../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

dev:
	cd server && ../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

test:
	cd server && ../.venv/bin/pytest -v

lint:
	cd server && ../.venv/bin/ruff check app/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -f *.db *.sqlite3
