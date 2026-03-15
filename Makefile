.PHONY: test lint typecheck test-notebooks execute-notebooks ci bump build publish-check

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

# make bump version=1.0.0b1
bump:
	@if [ -z "$(version)" ]; then echo "Usage: make bump version=X.Y.Z"; exit 1; fi
	poetry version $(version)
	@echo "Bumped to $(version). Commit pyproject.toml then create a GitHub release tagged v$(version)."

build:
	poetry build

# make publish-check tag=v1.0.0
publish-check:
	@if [ -z "$(tag)" ]; then echo "Usage: make publish-check tag=vX.Y.Z"; exit 1; fi
	@TAG="$(tag)"; VERSION=$${TAG#v}; \
	TOML_VERSION=$$(grep -m1 '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	if [ "$$VERSION" != "$$TOML_VERSION" ]; then \
		echo "ERROR: tag $$VERSION != pyproject.toml $$TOML_VERSION"; exit 1; \
	fi; echo "OK: $$VERSION matches pyproject.toml"
