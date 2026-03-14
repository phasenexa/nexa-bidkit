.PHONY: test lint typecheck test-notebooks execute-notebooks ci

test:
	poetry run pytest --cov=nexa_bidkit --cov-report=term-missing --cov-fail-under=80

lint:
	poetry run ruff check src

typecheck:
	poetry run mypy src

test-notebooks:
	poetry run pytest --nbmake examples/

execute-notebooks:
	poetry run jupyter nbconvert --to notebook --execute --inplace examples/*.ipynb

ci: lint typecheck test test-notebooks
