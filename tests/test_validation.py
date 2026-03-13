"""Tests for nexa_bidkit.validation — EUPHEMIA compliance and data quality validation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nexa_bidkit.bids import (
    BlockBid,
    LinkedBlockBid,
    SimpleBid,
    block_bid,
    exclusive_group,
    simple_bid_from_curve,
)
from nexa_bidkit.orders import create_order_book
from nexa_bidkit.types import (
    BiddingZone,
    CurveType,
    DeliveryPeriod,
    Direction,
    MTUDuration,
    MTUInterval,
    PriceQuantityCurve,
    PriceQuantityStep,
)
from nexa_bidkit.validation import (
    MAX_BID_VOLUME_MW,
    MAX_BLOCK_DURATION_HOURS,
    MAX_CURVE_STEPS,
    MIN_BID_VOLUME_MW,
    MIN_BLOCK_DURATION_HOURS,
    MIN_PRICE_STEP_INCREMENT,
    DataQualityError,
    EuphemiaValidationError,
    PortfolioValidationError,
    TemporalValidationError,
    ValidationError,
    get_validation_summary,
    validate_bid,
    validate_bids,
    validate_block_bid,
    validate_block_duration,
    validate_block_total_volume,
    validate_block_volume,
    validate_curve_minimum_volume,
    validate_curve_steps_count,
    validate_curve_total_volume,
    validate_delivery_within_day,
    validate_exclusive_group_bid,
    validate_exclusive_group_volumes,
    validate_gate_closure,
    validate_linked_block_bid,
    validate_mtu_resolution_for_zone,
    validate_mtu_within_day,
    validate_order_book_bids,
    validate_order_book_for_submission,
    validate_order_book_volumes,
    validate_price_quantity_curve,
    validate_price_step_increments,
    validate_simple_bid,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed aware datetime to anchor tests (1 April 2026, midnight UTC)
AUCTION_DAY = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
T0 = AUCTION_DAY + timedelta(hours=10)


def step(price: str, volume: str) -> PriceQuantityStep:
    """Create a price-quantity step."""
    return PriceQuantityStep(price=Decimal(price), volume=Decimal(volume))


def quarter_interval(start: datetime = T0) -> MTUInterval:
    """Create a quarter-hourly MTU interval."""
    return MTUInterval.from_start(start, MTUDuration.QUARTER_HOURLY)


def hourly_interval(start: datetime = T0) -> MTUInterval:
    """Create an hourly MTU interval."""
    return MTUInterval.from_start(start, MTUDuration.HOURLY)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_mtu() -> MTUInterval:
    """Sample quarter-hourly MTU."""
    return quarter_interval()


@pytest.fixture
def sample_delivery_period() -> DeliveryPeriod:
    """Sample 4-hour delivery period."""
    return DeliveryPeriod(
        start=AUCTION_DAY + timedelta(hours=10),
        end=AUCTION_DAY + timedelta(hours=14),
        duration=MTUDuration.QUARTER_HOURLY,
    )


@pytest.fixture
def valid_supply_curve(sample_mtu: MTUInterval) -> PriceQuantityCurve:
    """Valid supply curve that passes all validation."""
    return PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[
            step("10.0", "50"),
            step("25.0", "100"),
            step("45.0", "75"),
        ],
        mtu=sample_mtu,
    )


@pytest.fixture
def valid_block_bid(sample_delivery_period: DeliveryPeriod) -> BlockBid:
    """Valid block bid that passes all validation."""
    return block_bid(
        bidding_zone=BiddingZone.NO1,
        direction=Direction.SELL,
        delivery_period=sample_delivery_period,
        price=Decimal("50.0"),
        volume=Decimal("100.0"),
    )


@pytest.fixture
def valid_simple_bid(valid_supply_curve: PriceQuantityCurve) -> SimpleBid:
    """Valid simple bid that passes all validation."""
    return simple_bid_from_curve(valid_supply_curve, BiddingZone.NO1)


# ---------------------------------------------------------------------------
# Test: Curve validation
# ---------------------------------------------------------------------------


def test_validate_curve_steps_count_passes_under_limit(valid_supply_curve: PriceQuantityCurve):
    """Curve with steps under limit passes validation."""
    validate_curve_steps_count(valid_supply_curve)  # Should not raise


def test_validate_curve_steps_count_fails_over_limit(sample_mtu: MTUInterval):
    """Curve with too many steps raises EuphemiaValidationError."""
    # Create curve with MAX_CURVE_STEPS + 1 steps
    steps = [step("10.0", "1.0") for _ in range(MAX_CURVE_STEPS + 1)]
    curve = PriceQuantityCurve(curve_type=CurveType.SUPPLY, steps=steps, mtu=sample_mtu)

    with pytest.raises(EuphemiaValidationError, match="exceeds EUPHEMIA maximum"):
        validate_curve_steps_count(curve)


def test_validate_curve_minimum_volume_passes(valid_supply_curve: PriceQuantityCurve):
    """Curve with volumes above minimum passes validation."""
    validate_curve_minimum_volume(valid_supply_curve)


def test_validate_curve_minimum_volume_fails_below_threshold(sample_mtu: MTUInterval):
    """Curve with volume below minimum raises DataQualityError."""
    curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[step("10.0", "0.05")],  # Below MIN_BID_VOLUME_MW (0.1)
        mtu=sample_mtu,
    )

    with pytest.raises(DataQualityError, match="below minimum"):
        validate_curve_minimum_volume(curve)


def test_validate_curve_total_volume_passes(valid_supply_curve: PriceQuantityCurve):
    """Curve with reasonable total volume passes validation."""
    validate_curve_total_volume(valid_supply_curve)


def test_validate_curve_total_volume_fails_excessive(sample_mtu: MTUInterval):
    """Curve with excessive total volume raises DataQualityError."""
    curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[step("10.0", str(MAX_BID_VOLUME_MW + 1))],
        mtu=sample_mtu,
    )

    with pytest.raises(DataQualityError, match="exceeds maximum"):
        validate_curve_total_volume(curve)


def test_validate_price_step_increments_passes(valid_supply_curve: PriceQuantityCurve):
    """Curve with reasonable price increments passes validation."""
    validate_price_step_increments(valid_supply_curve)


def test_validate_price_step_increments_fails_tiny_increment(sample_mtu: MTUInterval):
    """Curve with suspiciously small price increments raises DataQualityError."""
    curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[
            step("10.000", "50"),
            step("10.001", "100"),  # 0.001 EUR/MWh increment (< 0.01)
        ],
        mtu=sample_mtu,
    )

    with pytest.raises(DataQualityError, match="below minimum increment"):
        validate_price_step_increments(curve)


def test_validate_price_step_increments_allows_equal_prices(sample_mtu: MTUInterval):
    """Curve with equal prices (zero increment) is allowed."""
    curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY,
        steps=[
            step("10.0", "50"),
            step("10.0", "100"),  # Same price
        ],
        mtu=sample_mtu,
    )

    validate_price_step_increments(curve)  # Should not raise


def test_validate_price_quantity_curve_comprehensive(valid_supply_curve: PriceQuantityCurve):
    """Comprehensive curve validation passes for valid curve."""
    validate_price_quantity_curve(valid_supply_curve)


# ---------------------------------------------------------------------------
# Test: Block bid validation
# ---------------------------------------------------------------------------


def test_validate_block_duration_passes(sample_delivery_period: DeliveryPeriod):
    """Delivery period with valid duration passes validation."""
    validate_block_duration(sample_delivery_period)


def test_validate_block_duration_fails_too_short():
    """Delivery period shorter than minimum raises EuphemiaValidationError."""
    # 30 minute period (< 1 hour minimum)
    short_period = DeliveryPeriod(
        start=AUCTION_DAY,
        end=AUCTION_DAY + timedelta(minutes=30),
        duration=MTUDuration.QUARTER_HOURLY,
    )

    with pytest.raises(EuphemiaValidationError, match="below minimum"):
        validate_block_duration(short_period)


def test_validate_block_duration_fails_too_long():
    """Delivery period longer than maximum raises EuphemiaValidationError."""
    # 25 hour period (> 24 hour maximum)
    long_period = DeliveryPeriod(
        start=AUCTION_DAY,
        end=AUCTION_DAY + timedelta(hours=25),
        duration=MTUDuration.QUARTER_HOURLY,
    )

    with pytest.raises(EuphemiaValidationError, match="exceeds maximum"):
        validate_block_duration(long_period)


def test_validate_block_volume_passes():
    """Block volume within range passes validation."""
    validate_block_volume(Decimal("100.0"))


def test_validate_block_volume_fails_too_small():
    """Block volume below minimum raises DataQualityError."""
    with pytest.raises(DataQualityError, match="below minimum"):
        validate_block_volume(Decimal("0.05"))


def test_validate_block_volume_fails_too_large():
    """Block volume above maximum raises DataQualityError."""
    with pytest.raises(DataQualityError, match="exceeds maximum"):
        validate_block_volume(MAX_BID_VOLUME_MW + 1)


def test_validate_block_total_volume_passes():
    """Reasonable total block volume passes validation."""
    validate_block_total_volume(Decimal("100.0"), 24)  # 100 MW * 24 MTUs


def test_validate_block_total_volume_fails_excessive():
    """Excessive total block volume raises DataQualityError."""
    with pytest.raises(DataQualityError, match="exceeds maximum"):
        validate_block_total_volume(Decimal("100000.0"), 100)


def test_validate_block_bid_comprehensive(valid_block_bid: BlockBid):
    """Comprehensive block bid validation passes for valid bid."""
    validate_block_bid(valid_block_bid)


def test_validate_linked_block_bid_comprehensive(sample_delivery_period: DeliveryPeriod):
    """Comprehensive linked block bid validation passes for valid bid."""
    parent = block_bid(
        bidding_zone=BiddingZone.NO1,
        direction=Direction.SELL,
        delivery_period=sample_delivery_period,
        price=Decimal("50.0"),
        volume=Decimal("100.0"),
        bid_id="parent-1",
    )

    linked = LinkedBlockBid(
        bid_id="linked-1",
        bidding_zone=BiddingZone.NO1,
        direction=Direction.SELL,
        delivery_period=sample_delivery_period,
        price=Decimal("45.0"),
        volume=Decimal("50.0"),
        parent_bid_id=parent.bid_id,
    )

    validate_linked_block_bid(linked)


# ---------------------------------------------------------------------------
# Test: Temporal validation
# ---------------------------------------------------------------------------


def test_validate_delivery_within_day_passes():
    """Delivery period within auction day passes validation."""
    period = DeliveryPeriod(
        start=AUCTION_DAY + timedelta(hours=10),
        end=AUCTION_DAY + timedelta(hours=14),
        duration=MTUDuration.QUARTER_HOURLY,
    )

    validate_delivery_within_day(period, AUCTION_DAY)


def test_validate_delivery_within_day_fails_starts_before():
    """Delivery period starting before auction day raises TemporalValidationError."""
    period = DeliveryPeriod(
        start=AUCTION_DAY - timedelta(hours=1),
        end=AUCTION_DAY + timedelta(hours=4),
        duration=MTUDuration.QUARTER_HOURLY,
    )

    with pytest.raises(TemporalValidationError, match="before auction day"):
        validate_delivery_within_day(period, AUCTION_DAY)


def test_validate_delivery_within_day_fails_ends_after():
    """Delivery period ending after auction day raises TemporalValidationError."""
    period = DeliveryPeriod(
        start=AUCTION_DAY + timedelta(hours=20),
        end=AUCTION_DAY + timedelta(hours=25),  # Next day
        duration=MTUDuration.QUARTER_HOURLY,
    )

    with pytest.raises(TemporalValidationError, match="after auction day"):
        validate_delivery_within_day(period, AUCTION_DAY)


def test_validate_mtu_within_day_passes():
    """MTU within auction day passes validation."""
    mtu = quarter_interval(AUCTION_DAY + timedelta(hours=12))
    validate_mtu_within_day(mtu, AUCTION_DAY)


def test_validate_mtu_within_day_fails():
    """MTU outside auction day raises TemporalValidationError."""
    mtu = quarter_interval(AUCTION_DAY + timedelta(hours=25))  # Next day

    with pytest.raises(TemporalValidationError, match="outside auction day"):
        validate_mtu_within_day(mtu, AUCTION_DAY)


def test_validate_gate_closure_passes():
    """Submission before gate closure passes validation."""
    submission = AUCTION_DAY - timedelta(hours=2)
    gate_closure = AUCTION_DAY - timedelta(hours=1)

    validate_gate_closure(submission, gate_closure)


def test_validate_gate_closure_fails():
    """Submission after gate closure raises TemporalValidationError."""
    submission = AUCTION_DAY - timedelta(hours=1)
    gate_closure = AUCTION_DAY - timedelta(hours=2)

    with pytest.raises(TemporalValidationError, match="after gate closure"):
        validate_gate_closure(submission, gate_closure)


def test_validate_gate_closure_requires_timezone_aware():
    """Gate closure validation requires timezone-aware datetimes."""
    naive_dt = datetime(2026, 4, 1, 10, 0, 0)  # No timezone
    aware_dt = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="timezone-aware"):
        validate_gate_closure(naive_dt, aware_dt)


# ---------------------------------------------------------------------------
# Test: MTU resolution validation
# ---------------------------------------------------------------------------


def test_validate_mtu_resolution_for_zone_passes_15min():
    """15-minute MTU resolution passes validation for all zones."""
    validate_mtu_resolution_for_zone(MTUDuration.QUARTER_HOURLY, BiddingZone.NO1)


def test_validate_mtu_resolution_for_zone_fails_hourly_when_required():
    """Hourly MTU raises EuphemiaValidationError when 15-min required."""
    with pytest.raises(EuphemiaValidationError, match="requires 15-minute MTUs"):
        validate_mtu_resolution_for_zone(MTUDuration.HOURLY, BiddingZone.DE_LU, require_15min=True)


def test_validate_mtu_resolution_for_zone_allows_hourly_when_not_required():
    """Hourly MTU passes when 15-min not required."""
    validate_mtu_resolution_for_zone(MTUDuration.HOURLY, BiddingZone.NO1, require_15min=False)


# ---------------------------------------------------------------------------
# Test: Simple bid validation
# ---------------------------------------------------------------------------


def test_validate_simple_bid_passes(valid_simple_bid: SimpleBid):
    """Valid simple bid passes validation."""
    validate_simple_bid(valid_simple_bid)


def test_validate_simple_bid_fails_invalid_curve(sample_mtu: MTUInterval):
    """Simple bid with invalid curve raises ValidationError."""
    # Create curve with too many steps
    steps = [step("10.0", "1.0") for _ in range(MAX_CURVE_STEPS + 1)]
    invalid_curve = PriceQuantityCurve(curve_type=CurveType.SUPPLY, steps=steps, mtu=sample_mtu)
    bad_bid = simple_bid_from_curve(invalid_curve, BiddingZone.NO1)

    with pytest.raises(EuphemiaValidationError):
        validate_simple_bid(bad_bid)


# ---------------------------------------------------------------------------
# Test: Exclusive group validation
# ---------------------------------------------------------------------------


def test_validate_exclusive_group_volumes_passes(sample_delivery_period: DeliveryPeriod):
    """Exclusive group with balanced volumes passes validation."""
    blocks = [
        block_bid(
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=sample_delivery_period,
            price=Decimal("50.0"),
            volume=Decimal("100.0"),
            bid_id=f"block-{i}",
        )
        for i in range(3)
    ]

    group = exclusive_group(blocks)
    validate_exclusive_group_volumes(group)


def test_validate_exclusive_group_volumes_fails_one_dominates(
    sample_delivery_period: DeliveryPeriod,
):
    """Exclusive group with one dominant member raises DataQualityError."""
    blocks = [
        block_bid(
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=sample_delivery_period,
            price=Decimal("50.0"),
            volume=Decimal("10000.0"),  # Dominant
            bid_id="block-1",
        ),
        block_bid(
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=sample_delivery_period,
            price=Decimal("45.0"),
            volume=Decimal("10.0"),  # Tiny
            bid_id="block-2",
        ),
    ]

    group = exclusive_group(blocks)

    with pytest.raises(DataQualityError, match="one member representing"):
        validate_exclusive_group_volumes(group)


def test_validate_exclusive_group_bid_comprehensive(sample_delivery_period: DeliveryPeriod):
    """Comprehensive exclusive group validation passes for valid group."""
    blocks = [
        block_bid(
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=sample_delivery_period,
            price=Decimal(str(50 + i * 10)),
            volume=Decimal("100.0"),
            bid_id=f"block-{i}",
        )
        for i in range(3)
    ]

    group = exclusive_group(blocks)
    validate_exclusive_group_bid(group)


# ---------------------------------------------------------------------------
# Test: Bid dispatch validation
# ---------------------------------------------------------------------------


def test_validate_bid_dispatches_correctly(valid_simple_bid: SimpleBid):
    """validate_bid dispatches to correct validator based on type."""
    validate_bid(valid_simple_bid)  # Should delegate to validate_simple_bid


def test_validate_bid_raises_for_unknown_type():
    """validate_bid raises ValueError for unknown bid types."""

    class FakeBid:
        pass

    with pytest.raises(ValueError, match="Unknown bid type"):
        validate_bid(FakeBid())  # type: ignore


# ---------------------------------------------------------------------------
# Test: Order book validation
# ---------------------------------------------------------------------------


def test_validate_order_book_volumes_passes(valid_simple_bid: SimpleBid):
    """Order book with reasonable volumes passes validation."""
    order_book = create_order_book(bids=[valid_simple_bid])
    validate_order_book_volumes(order_book)


def test_validate_order_book_volumes_fails_excessive():
    """Order book with excessive volumes raises PortfolioValidationError."""
    # Create many huge bids to exceed portfolio limit
    huge_period = DeliveryPeriod(
        start=AUCTION_DAY,
        end=AUCTION_DAY + timedelta(hours=24),
        duration=MTUDuration.QUARTER_HOURLY,
    )

    huge_bids = [
        block_bid(
            bidding_zone=BiddingZone.NO1,
            direction=Direction.SELL,
            delivery_period=huge_period,
            price=Decimal("50.0"),
            volume=Decimal("50000.0"),  # 50 GW per MTU
            bid_id=f"huge-{i}",
        )
        for i in range(25)  # 25 bids * 50 GW * 96 MTUs = massive volume
    ]

    order_book = create_order_book(bids=huge_bids)

    with pytest.raises(PortfolioValidationError, match="exceeds reasonable maximum"):
        validate_order_book_volumes(order_book)


def test_validate_order_book_bids_comprehensive(
    valid_simple_bid: SimpleBid, valid_block_bid: BlockBid
):
    """Comprehensive order book validation passes for valid bids."""
    order_book = create_order_book(bids=[valid_simple_bid, valid_block_bid])
    validate_order_book_bids(order_book)


def test_validate_order_book_for_submission_passes(valid_simple_bid: SimpleBid):
    """Order book validation for submission passes when valid."""
    order_book = create_order_book(bids=[valid_simple_bid])
    submission_time = AUCTION_DAY - timedelta(hours=2)
    gate_closure = AUCTION_DAY - timedelta(hours=1)

    validate_order_book_for_submission(order_book, gate_closure, submission_time)


def test_validate_order_book_for_submission_fails_after_gate_closure(
    valid_simple_bid: SimpleBid,
):
    """Order book validation fails when submitted after gate closure."""
    order_book = create_order_book(bids=[valid_simple_bid])
    submission_time = AUCTION_DAY
    gate_closure = AUCTION_DAY - timedelta(hours=1)

    with pytest.raises(TemporalValidationError, match="after gate closure"):
        validate_order_book_for_submission(order_book, gate_closure, submission_time)


# ---------------------------------------------------------------------------
# Test: Batch validation
# ---------------------------------------------------------------------------


def test_validate_bids_all_valid(valid_simple_bid: SimpleBid, valid_block_bid: BlockBid):
    """Batch validation returns no errors for all valid bids."""
    results = validate_bids([valid_simple_bid, valid_block_bid])

    assert len(results) == 2
    assert all(error is None for _, error in results)


def test_validate_bids_mixed_results(valid_simple_bid: SimpleBid, sample_mtu: MTUInterval):
    """Batch validation collects errors without failing early."""
    # Create invalid curve with too many steps
    invalid_steps = [step("10.0", "1.0") for _ in range(MAX_CURVE_STEPS + 1)]
    invalid_curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY, steps=invalid_steps, mtu=sample_mtu
    )
    invalid_bid = simple_bid_from_curve(invalid_curve, BiddingZone.NO1)

    results = validate_bids([valid_simple_bid, invalid_bid])

    assert len(results) == 2
    assert results[0][1] is None  # First bid valid
    assert isinstance(results[1][1], EuphemiaValidationError)  # Second bid invalid


def test_get_validation_summary_all_passed(valid_simple_bid: SimpleBid, valid_block_bid: BlockBid):
    """Validation summary shows 100% pass rate for valid bids."""
    results = validate_bids([valid_simple_bid, valid_block_bid])
    summary = get_validation_summary(results)

    assert summary["total_bids"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["pass_rate"] == 100.0
    assert summary["error_types"] == {}


def test_get_validation_summary_mixed(valid_simple_bid: SimpleBid, sample_mtu: MTUInterval):
    """Validation summary shows correct stats for mixed results."""
    # Create invalid bid
    invalid_steps = [step("10.0", "1.0") for _ in range(MAX_CURVE_STEPS + 1)]
    invalid_curve = PriceQuantityCurve(
        curve_type=CurveType.SUPPLY, steps=invalid_steps, mtu=sample_mtu
    )
    invalid_bid = simple_bid_from_curve(invalid_curve, BiddingZone.NO1)

    results = validate_bids([valid_simple_bid, invalid_bid])
    summary = get_validation_summary(results)

    assert summary["total_bids"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate"] == 50.0
    assert "EuphemiaValidationError" in summary["error_types"]


def test_get_validation_summary_empty():
    """Validation summary handles empty results."""
    summary = get_validation_summary([])

    assert summary["total_bids"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["pass_rate"] == 0.0


# ---------------------------------------------------------------------------
# Test: Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy():
    """Validation exceptions inherit from ValidationError."""
    assert issubclass(EuphemiaValidationError, ValidationError)
    assert issubclass(DataQualityError, ValidationError)
    assert issubclass(TemporalValidationError, ValidationError)
    assert issubclass(PortfolioValidationError, ValidationError)


# ---------------------------------------------------------------------------
# Test: Constants
# ---------------------------------------------------------------------------


def test_validation_constants_are_reasonable():
    """Validation constants have reasonable values."""
    assert MAX_CURVE_STEPS == 200
    assert MIN_BLOCK_DURATION_HOURS == 1
    assert MAX_BLOCK_DURATION_HOURS == 24
    assert Decimal("0.1") == MIN_BID_VOLUME_MW
    assert Decimal("50000") == MAX_BID_VOLUME_MW
    assert Decimal("0.01") == MIN_PRICE_STEP_INCREMENT
