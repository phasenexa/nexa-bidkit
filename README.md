# nexa-bidkit

A Python library for generating day-ahead and intraday auction bids for European power markets. EUPHEMIA-compatible output formats.

Part of the Phase Nexa ecosystem.

## Features

- **Type-safe bid construction**: Pydantic v2 models with strict validation
- **DataFrame-first API**: Build curves from pandas DataFrames
- **15-minute MTU support**: Handle both hourly and quarter-hourly market time units
- **EUPHEMIA compatibility**: Output formats compatible with European power market coupling
- **Comprehensive validation**: EUPHEMIA compliance checks, data quality validation, and temporal constraints

## Installation

```bash
pip install nexa-bidkit
```

## Quick Start

### Constructing curves from DataFrames

```python
import pandas as pd
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from nexa_bidkit import (
    CurveType,
    MTUDuration,
    MTUInterval,
    from_dataframe,
)

# Your bid data as a DataFrame
df = pd.DataFrame({
    "price": [10.5, 25.0, 45.0, 80.0],
    "volume": [50, 100, 75, 25],
})

# Define the MTU this curve applies to
mtu = MTUInterval.from_start(
    datetime(2026, 4, 1, 13, 0, tzinfo=ZoneInfo("Europe/Oslo")),
    MTUDuration.QUARTER_HOURLY
)

# Convert to a validated supply curve
curve = from_dataframe(df, curve_type=CurveType.SUPPLY, mtu=mtu)

print(f"Total volume: {curve.total_volume} MW")
print(f"Price range: {curve.min_price} - {curve.max_price} EUR/MWh")
```

### Combining multiple bids

```python
from nexa_bidkit import merge_curves

# Combine bids from multiple plants
plant_curves = [
    from_dataframe(plant1_df, curve_type=CurveType.SUPPLY, mtu=mtu),
    from_dataframe(plant2_df, curve_type=CurveType.SUPPLY, mtu=mtu),
]
portfolio = merge_curves(plant_curves, aggregation="sum")
```

### Applying constraints

```python
from nexa_bidkit import clip_curve, filter_zero_volume, aggregate_by_price

# Clean and constrain curve
curve = from_dataframe(df, curve_type=CurveType.SUPPLY, mtu=mtu)
curve = filter_zero_volume(curve)  # Remove empty steps
curve = clip_curve(
    curve,
    min_price=Decimal("0"),  # No negative prices
    max_volume=Decimal("500")  # Capacity constraint
)
curve = aggregate_by_price(curve)  # Consolidate for smaller message size
```

### Creating bids

```python
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from nexa_bidkit import (
    BiddingZone,
    Direction,
    DeliveryPeriod,
    MTUDuration,
    block_bid,
    indivisible_block_bid,
    linked_block_bid,
    exclusive_group,
)

# Define a delivery period (4 hours of quarter-hourly MTUs)
delivery = DeliveryPeriod(
    start=datetime(2026, 4, 1, 10, 0, tzinfo=ZoneInfo("Europe/Oslo")),
    end=datetime(2026, 4, 1, 14, 0, tzinfo=ZoneInfo("Europe/Oslo")),
    duration=MTUDuration.QUARTER_HOURLY,
)

# Create a block bid (partially fillable)
peak_bid = block_bid(
    bidding_zone=BiddingZone.NO1,
    direction=Direction.SELL,
    delivery_period=delivery,
    price=Decimal("55.0"),
    volume=Decimal("100"),
    min_acceptance_ratio=Decimal("0.5"),  # Accept 50%+ fill
)

# Create an indivisible block bid (all-or-nothing)
must_run = indivisible_block_bid(
    bidding_zone=BiddingZone.NO1,
    direction=Direction.SELL,
    delivery_period=delivery,
    price=Decimal("25.0"),
    volume=Decimal("50"),
)

# Create a linked block bid (only accepted if parent accepted)
ramp_up = linked_block_bid(
    parent_bid_id=must_run.bid_id,
    bidding_zone=BiddingZone.NO1,
    direction=Direction.SELL,
    delivery_period=delivery,
    price=Decimal("35.0"),
    volume=Decimal("25"),
)

# Create an exclusive group (at most one accepted)
option_a = block_bid(
    bidding_zone=BiddingZone.NO1,
    direction=Direction.SELL,
    delivery_period=delivery,
    price=Decimal("40.0"),
    volume=Decimal("150"),
)
option_b = block_bid(
    bidding_zone=BiddingZone.NO1,
    direction=Direction.SELL,
    delivery_period=delivery,
    price=Decimal("45.0"),
    volume=Decimal("120"),
)
options = exclusive_group([option_a, option_b])

print(f"Peak bid total volume: {peak_bid.total_volume} MW")
print(f"Must-run is indivisible: {must_run.is_indivisible}")
print(f"Exclusive group has {options.member_count} options")
```

### Managing portfolios with OrderBook

```python
from nexa_bidkit import (
    create_order_book,
    add_bid,
    add_bids,
    get_bids_by_zone,
    get_bids_by_status,
    count_bids,
    total_volume_by_zone,
    update_all_statuses,
    orders_to_dataframe,
    BidStatus,
)

# Create an order book
book = create_order_book()

# Add individual bids
book = add_bid(book, must_run)
book = add_bid(book, peak_bid)

# Add multiple bids at once
book = add_bids(book, [ramp_up, options])

# Query bids
no1_bids = get_bids_by_zone(book, BiddingZone.NO1)
draft_bids = get_bids_by_status(book, BidStatus.DRAFT)

# Aggregate statistics
bid_counts = count_bids(book)
volumes = total_volume_by_zone(book)

print(f"Total bids: {sum(bid_counts.values())}")
print(f"NO1 volume: {volumes[BiddingZone.NO1]} MW")

# Update statuses (e.g., after validation)
book = update_all_statuses(book, BidStatus.VALIDATED)

# Export to pandas for analysis
df = orders_to_dataframe(book)
print(df[["bid_id", "bid_type", "bidding_zone", "status"]])
```

### Validating bids for EUPHEMIA compliance

```python
from nexa_bidkit import (
    validate_bid,
    validate_bids,
    validate_order_book_for_submission,
    get_validation_summary,
    EuphemiaValidationError,
    DataQualityError,
    TemporalValidationError,
)

# Validate individual bid
try:
    validate_bid(peak_bid)
    print("Bid is valid!")
except EuphemiaValidationError as e:
    print(f"EUPHEMIA compliance error: {e}")
except DataQualityError as e:
    print(f"Data quality issue: {e}")

# Batch validation (collects all errors)
results = validate_bids([must_run, peak_bid, ramp_up])
summary = get_validation_summary(results)

print(f"Validated {summary['total_bids']} bids")
print(f"Pass rate: {summary['pass_rate']:.1f}%")
print(f"Errors by type: {summary['error_types']}")

# Comprehensive validation before submission
gate_closure = datetime(2026, 3, 31, 12, 0, tzinfo=ZoneInfo("Europe/Oslo"))

try:
    validate_order_book_for_submission(
        book,
        gate_closure_time=gate_closure,
    )
    print("Order book ready for submission")
except ValidationError as e:
    print(f"Validation failed: {e}")
```

The validation module enforces:
- **EUPHEMIA rules**: Maximum curve steps (200), block duration limits (1-24 hours)
- **Data quality**: Minimum volumes (0.1 MW), reasonable price increments
- **Temporal constraints**: Gate closure deadlines, delivery periods within auction day
- **Portfolio limits**: Total volume sanity checks across bidding zones

## Core Concepts

### Market Time Units (MTU)

EU power markets transitioned to 15-minute MTUs on 30 Sept 2025. The library handles both:

- `MTUDuration.QUARTER_HOURLY` - 15-minute intervals (96 per day)
- `MTUDuration.HOURLY` - Hourly intervals (24 per day)

### Price-Quantity Curves

Merit-order curves represent supply or demand:

- **Supply curves**: Steps sorted ascending by price (cheapest generation first)
- **Demand curves**: Steps sorted descending by price (highest-value consumption first)

### EUPHEMIA Bid Types

- Simple hourly bids (price-quantity pairs per MTU)
- Block bids (fixed price/volume across consecutive MTUs)
- Linked block bids (parent-child relationships)
- Exclusive groups (mutually exclusive block bids)

## Development

### Setup

```bash
# Install poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Run tests
poetry run pytest

# Type checking
poetry run mypy src

# Linting
poetry run ruff check src
```

### Running tests

```bash
# All tests with coverage
make test

# Or using poetry directly
poetry run pytest tests/ -v
poetry run pytest --cov=nexa_bidkit --cov-report=term-missing
```

## License

MIT

## Contributing

This is an internal Phase Nexa project. For issues or questions, contact the Nexa team.
