# nexa-bidkit

## What this is
A Python library for generating day-ahead and intraday auction bids
for European power markets. EUPHEMIA-compatible output formats.
Part of the Phase Nexa ecosystem.

## Audience
Quants, data scientists, and developers at energy trading companies who build their own trading systems. They are experienced Python users.

## Code style
- Python 3.11+
- Type hints everywhere, strict mypy compliance
- Pydantic v2 for data models
- pytest for testing
- Ruff for linting and formatting
- No classes where a function will do
- Docstrings on all public API (Google style)
- Tabular numerical data uses pandas DataFrames
- Timezone-aware datetimes only (never naive)
- Utilise the Makefile for common developer actions
- Always prefer UK English unless using existing nomenclature popular in energy trading

## Domain context
- MTU = Market Time Unit. EU power markets transitioned to 15-minute
  MTUs on 30 Sept 2025. Library must handle both 15-min and hourly.
- EUPHEMIA = the algorithm used for day-ahead market coupling in Europe.
  Bid formats must be compatible with EUPHEMIA input requirements.
- Bid types: simple hourly bids (price-quantity pairs per MTU),
  block bids (fixed price/volume across consecutive MTUs),
  linked block bids (parent-child relationships),
  exclusive groups (mutually exclusive block bids).
- Bidding zones: e.g. NO1-NO5 (Nordic), DE-LU, FR, etc.

## Testing
- pytest with fixtures for common bid scenarios
- Property-based testing with hypothesis for curve construction
- All monetary values use Decimal, not float
- Aim for high test coverage
- Run `make test` to run unit tests

## Do not
- Do not use float for prices or volumes. Use Decimal.
- Do not create naive datetimes. Always use timezone-aware.
- Do not add unnecessary dependencies.

## Workflow (Trunk-Based Development)
- **NEVER push directly to main**. The main branch is protected.
- **Always work on feature branches**: Create a short-lived feature branch for each task (e.g. `feat/add-curves-module`, `fix/mtu-validation`)
- **Create pull requests**: When work is complete, create a PR to merge into main
- **Branch naming conventions**:
  - `feat/description` for new features
  - `fix/description` for bug fixes
  - `refactor/description` for refactoring
  - `docs/description` for documentation updates
  - `test/description` for test improvements
- **Before creating a PR**:
  - Run `make test` to ensure all tests pass
  - Run type checking: `poetry run mypy src`
  - Run linting: `poetry run ruff check src tests`
  - Ensure Definition of Done criteria are met
  - Write clear, descriptive commit messages
- **PR requirements**:
  - Title should clearly describe the change
  - Description should explain why the change is needed
  - All tests must pass
  - Code coverage should meet or exceed 80%
  - At least 1 approving review required (when branch protection is enabled)
- **Commit workflow**:
  - Make focused, atomic commits
  - Each commit should represent a logical unit of work
  - Run tests before committing
  - Use conventional commit messages when appropriate

## Code layout

```
nexa-bidkit/
  src/nexa_bidkit/
    __init__.py
    bids.py            # bid objects (hourly, block, linked, exclusive)
    curves.py          # merit order curve construction
    epex_spot.py       # Convert your orders to EPEX Spot domain model
    nordpool.py        # Convert your orders to Nord Pool domain model
    orders.py          # order book / portfolio of bids
    validation.py      # bid validation rules
    types.py           # core types/enums (MTU, BiddingZone, etc.)
  tests/
  docs/
  examples/
  pyproject.toml
  CLAUDE.md
  README.md
  ```

  Use pyproject.toml with hatchling or setuptools as the build backend. Don't use setup.py in 2026.

  ## Definition of Done

  - Update tests to include new/changed work, aim for >80% code coverage, but prioritise good tests
  - Run tests and ensure they pass using `make ci`
  - If anything changed that would impact the notebooks, run `make execute-notebooks` to update their output
  - Run the ruff formatter to reformat code
  - Linters (like black or mypy) show no issues
  - Update README and/or docs to document the new behaviour/feature
  - Check if Makefile is missing any common operations (for new functionality added)
  - When adding/changing significant work, add a new notebook to @examples/ documenting the feature
    - If done, execute using `make execute-notebooks` so the output is checked in
  - Add anything needed in @.gitignore to avoid checking in secrets, or temp files/logs