.PHONY: test test-sandbox test-full freeze-testset evaluate evaluate-seed evaluate-charts demo db-up db-down install

# --- Targets that run TODAY in this build environment: numpy/scikit-learn
#     ARE available here (confirmed - see Phase 2 report), only
#     ortools/pydantic/fastapi/sqlalchemy/anthropic are not. This runs the
#     full accumulated suite (159 tests as of Phase 7) minus the one
#     documented CP-SAT skip. ---
test-sandbox:
	cd backend/tests && python3 -m unittest discover -p "test_*.py" -v

freeze-testset:
	cd backend && python3 simulation/freeze_test_set.py

# --- Targets that require `pip install -r backend/requirements.txt` to have
#     actually succeeded (real Postgres/OR-Tools/scikit-learn/pydantic) ---
install:
	pip install -r backend/requirements.txt

test-full: install
	cd backend && pytest tests/ -v

test: test-full  # `make test` is the spec's canonical target once deps are installed

evaluate:
	cd backend && python -m evaluation.run --n-items 100 --seeds 20

evaluate-seed:
	cd backend && python -m evaluation.run --n-items 100 --seeds $${SEED:-20}

evaluate-charts:
	cd backend && python evaluation/charts.py

db-up:
	docker compose up -d db

db-down:
	docker compose down

server:
	cd backend && uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

demo: server

