"""Bid validation rules for EUPHEMIA compliance and data quality.

This module provides validation functions that enforce EUPHEMIA market rules,
data quality checks, and business constraints beyond the basic Pydantic
field validation. Use these validators before submitting bids to ensure
compliance with European day-ahead market requirements.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from nexa_bidkit.bids import BlockBid, ExclusiveGroupBid, LinkedBlockBid, SimpleBid
from nexa_bidkit.orders import BidUnion, OrderBook
from nexa_bidkit.types import (
    BiddingZone,
    DeliveryPeriod,
    MTUDuration,
    MTUInterval,
    PriceQuantityCurve,
)

# ---------------------------------------------------------------------------
# EUPHEMIA constraints (based on PCR / EUPHEMIA Public Description)
# ---------------------------------------------------------------------------

# Maximum number of steps in a price-quantity curve
MAX_CURVE_STEPS = 200

# Block bid duration constraints
MIN_BLOCK_DURATION_HOURS = 1
MAX_BLOCK_DURATION_HOURS = 24

# Minimum volume per step/bid (MW) to avoid dust bids
MIN_BID_VOLUME_MW = Decimal("0.1")

# Maximum total volume per bid (MW) for reasonableness check
MAX_BID_VOLUME_MW = Decimal("50000")

# Price step increment threshold (EUR/MWh) for detecting suspiciously small steps
MIN_PRICE_STEP_INCREMENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Validation error classes
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Base exception for all validation errors."""

    pass


class EuphemiaValidationError(ValidationError):
    """Raised when a bid violates EUPHEMIA-specific rules."""

    pass


class DataQualityError(ValidationError):
    """Raised when bid data fails quality checks."""

    pass


class TemporalValidationError(ValidationError):
    """Raised when temporal constraints are violated."""

    pass


class PortfolioValidationError(ValidationError):
    """Raised when portfolio-level constraints are violated."""

    pass


# ---------------------------------------------------------------------------
# Price-quantity curve validation
# ---------------------------------------------------------------------------


def validate_curve_steps_count(curve: PriceQuantityCurve, max_steps: int = MAX_CURVE_STEPS) -> None:
    """Validate that a curve does not exceed maximum number of steps.

    Args:
        curve: Curve to validate.
        max_steps: Maximum allowed steps (default: 200).

    Raises:
        EuphemiaValidationError: If curve exceeds maximum steps.
    """
    if len(curve.steps) > max_steps:
        raise EuphemiaValidationError(
            f"Curve has {len(curve.steps)} steps, exceeds EUPHEMIA maximum of {max_steps}"
        )


def validate_curve_minimum_volume(
    curve: PriceQuantityCurve, min_volume: Decimal = MIN_BID_VOLUME_MW
) -> None:
    """Validate that all curve steps meet minimum volume threshold.

    Args:
        curve: Curve to validate.
        min_volume: Minimum volume per step in MW (default: 0.1 MW).

    Raises:
        DataQualityError: If any step has volume below threshold.
    """
    for i, step in enumerate(curve.steps):
        if step.volume < min_volume:
            raise DataQualityError(
                f"Curve step {i} has volume {step.volume} MW, below minimum {min_volume} MW"
            )


def validate_curve_total_volume(
    curve: PriceQuantityCurve, max_volume: Decimal = MAX_BID_VOLUME_MW
) -> None:
    """Validate that total curve volume does not exceed maximum.

    Args:
        curve: Curve to validate.
        max_volume: Maximum total volume in MW (default: 50,000 MW).

    Raises:
        DataQualityError: If total volume exceeds maximum.
    """
    total = curve.total_volume
    if total > max_volume:
        raise DataQualityError(f"Curve total volume {total} MW exceeds maximum {max_volume} MW")


def validate_price_step_increments(
    curve: PriceQuantityCurve, min_increment: Decimal = MIN_PRICE_STEP_INCREMENT
) -> None:
    """Validate that price steps have reasonable increments.

    Checks for suspiciously small price differences between consecutive steps
    which may indicate data quality issues.

    Args:
        curve: Curve to validate.
        min_increment: Minimum price increment in EUR/MWh (default: 0.01).

    Raises:
        DataQualityError: If consecutive steps have price difference below threshold.
    """
    if len(curve.steps) < 2:
        return

    for i in range(1, len(curve.steps)):
        prev_price = curve.steps[i - 1].price
        curr_price = curve.steps[i].price
        diff = abs(curr_price - prev_price)

        if Decimal("0") < diff < min_increment:
            raise DataQualityError(
                f"Curve steps {i - 1} and {i} have price difference {diff} EUR/MWh, "
                f"below minimum increment {min_increment} EUR/MWh"
            )


def validate_price_quantity_curve(curve: PriceQuantityCurve) -> None:
    """Run all curve validation checks.

    Comprehensive validation combining EUPHEMIA compliance and data quality checks.

    Args:
        curve: Curve to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    validate_curve_steps_count(curve)
    validate_curve_minimum_volume(curve)
    validate_curve_total_volume(curve)
    validate_price_step_increments(curve)


# ---------------------------------------------------------------------------
# Block bid validation
# ---------------------------------------------------------------------------


def validate_block_duration(
    delivery_period: DeliveryPeriod,
    min_hours: int = MIN_BLOCK_DURATION_HOURS,
    max_hours: int = MAX_BLOCK_DURATION_HOURS,
) -> None:
    """Validate that block bid duration is within allowed range.

    Args:
        delivery_period: Delivery period to validate.
        min_hours: Minimum duration in hours (default: 1).
        max_hours: Maximum duration in hours (default: 24).

    Raises:
        EuphemiaValidationError: If duration is outside allowed range.
    """
    duration_hours = (delivery_period.end - delivery_period.start).total_seconds() / 3600

    if duration_hours < min_hours:
        raise EuphemiaValidationError(
            f"Block duration {duration_hours:.1f} hours is below minimum {min_hours} hours"
        )

    if duration_hours > max_hours:
        raise EuphemiaValidationError(
            f"Block duration {duration_hours:.1f} hours exceeds maximum {max_hours} hours"
        )


def validate_block_volume(
    volume: Decimal,
    min_volume: Decimal = MIN_BID_VOLUME_MW,
    max_volume: Decimal = MAX_BID_VOLUME_MW,
) -> None:
    """Validate that block bid volume is within reasonable range.

    Args:
        volume: Volume per MTU in MW.
        min_volume: Minimum volume (default: 0.1 MW).
        max_volume: Maximum volume (default: 50,000 MW).

    Raises:
        DataQualityError: If volume is outside allowed range.
    """
    if volume < min_volume:
        raise DataQualityError(f"Block volume {volume} MW is below minimum {min_volume} MW")

    if volume > max_volume:
        raise DataQualityError(f"Block volume {volume} MW exceeds maximum {max_volume} MW")


def validate_block_total_volume(
    volume_per_mtu: Decimal,
    mtu_count: int,
    max_total: Decimal = MAX_BID_VOLUME_MW * 24,
) -> None:
    """Validate that total block volume is reasonable.

    Args:
        volume_per_mtu: Volume per MTU in MW.
        mtu_count: Number of MTUs in delivery period.
        max_total: Maximum total volume in MWh (default: 1,200,000 MWh).

    Raises:
        DataQualityError: If total volume exceeds maximum.
    """
    total_volume = volume_per_mtu * mtu_count
    if total_volume > max_total:
        raise DataQualityError(
            f"Block total volume {total_volume} MWh exceeds maximum {max_total} MWh"
        )


def validate_block_bid(bid: BlockBid) -> None:
    """Run all block bid validation checks.

    Args:
        bid: Block bid to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    validate_block_duration(bid.delivery_period)
    validate_block_volume(bid.volume)
    validate_block_total_volume(bid.volume, bid.delivery_period.mtu_count)


def validate_linked_block_bid(bid: LinkedBlockBid) -> None:
    """Run all linked block bid validation checks.

    Args:
        bid: Linked block bid to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    validate_block_duration(bid.delivery_period)
    validate_block_volume(bid.volume)
    validate_block_total_volume(bid.volume, bid.delivery_period.mtu_count)


# ---------------------------------------------------------------------------
# Temporal validation
# ---------------------------------------------------------------------------


def validate_delivery_within_day(
    delivery_period: DeliveryPeriod,
    auction_day: datetime,
) -> None:
    """Validate that delivery period falls within the auction day.

    Day-ahead auctions typically require all delivery to be within a single
    calendar day in the delivery zone's local time.

    Args:
        delivery_period: Delivery period to validate.
        auction_day: Start of the auction day (timezone-aware, midnight).

    Raises:
        TemporalValidationError: If delivery period extends beyond auction day.
    """
    if auction_day.tzinfo is None:
        raise ValueError("auction_day must be timezone-aware")

    auction_day_end = auction_day + timedelta(days=1)

    if delivery_period.start < auction_day:
        raise TemporalValidationError(
            f"Delivery period starts {delivery_period.start} before auction day {auction_day}"
        )

    if delivery_period.end > auction_day_end:
        raise TemporalValidationError(
            f"Delivery period ends {delivery_period.end} after auction day {auction_day_end}"
        )


def validate_mtu_within_day(mtu: MTUInterval, auction_day: datetime) -> None:
    """Validate that MTU falls within the auction day.

    Args:
        mtu: MTU interval to validate.
        auction_day: Start of the auction day (timezone-aware, midnight).

    Raises:
        TemporalValidationError: If MTU is outside auction day.
    """
    if auction_day.tzinfo is None:
        raise ValueError("auction_day must be timezone-aware")

    auction_day_end = auction_day + timedelta(days=1)

    if mtu.start < auction_day or mtu.end > auction_day_end:
        raise TemporalValidationError(
            f"MTU interval {mtu.start} - {mtu.end} is outside auction day "
            f"{auction_day} - {auction_day_end}"
        )


def validate_gate_closure(
    submission_time: datetime,
    gate_closure_time: datetime,
) -> None:
    """Validate that bid is submitted before gate closure.

    Args:
        submission_time: Time of bid submission (timezone-aware).
        gate_closure_time: Gate closure deadline (timezone-aware).

    Raises:
        TemporalValidationError: If submission is after gate closure.
    """
    if submission_time.tzinfo is None or gate_closure_time.tzinfo is None:
        raise ValueError("Both times must be timezone-aware")

    if submission_time >= gate_closure_time:
        raise TemporalValidationError(
            f"Bid submitted at {submission_time} is after gate closure at {gate_closure_time}"
        )


# ---------------------------------------------------------------------------
# MTU resolution validation
# ---------------------------------------------------------------------------


def validate_mtu_resolution_for_zone(
    duration: MTUDuration,
    bidding_zone: BiddingZone,
    require_15min: bool = True,
) -> None:
    """Validate MTU resolution is appropriate for bidding zone.

    As of 30 Sept 2025, all EU markets transitioned to 15-minute MTUs.
    Some legacy applications may still use hourly resolution.

    Args:
        duration: MTU duration to validate.
        bidding_zone: Bidding zone for context.
        require_15min: If True, enforce 15-minute MTUs (default: True).

    Raises:
        EuphemiaValidationError: If MTU resolution is not allowed.
    """
    if require_15min and duration != MTUDuration.QUARTER_HOURLY:
        raise EuphemiaValidationError(
            f"Bidding zone {bidding_zone.value} requires 15-minute MTUs (PT15M), "
            f"got {duration.value}"
        )


# ---------------------------------------------------------------------------
# Simple bid validation
# ---------------------------------------------------------------------------


def validate_simple_bid(bid: SimpleBid) -> None:
    """Run all simple bid validation checks.

    Args:
        bid: Simple bid to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    validate_price_quantity_curve(bid.curve)


# ---------------------------------------------------------------------------
# Exclusive group validation
# ---------------------------------------------------------------------------


def validate_exclusive_group_volumes(group: ExclusiveGroupBid) -> None:
    """Validate that exclusive group member volumes are reasonable.

    Checks that no single member dominates the group, which could indicate
    a data quality issue.

    Args:
        group: Exclusive group bid to validate.

    Raises:
        DataQualityError: If volume distribution is unreasonable.
    """
    if len(group.block_bids) < 2:
        return

    volumes = [bid.total_volume for bid in group.block_bids]
    max_volume = max(volumes)
    total_volume = sum(volumes)

    # Check if one member is > 95% of total (likely a data error)
    if max_volume > total_volume * Decimal("0.95"):
        raise DataQualityError(
            f"Exclusive group {group.group_id} has one member representing "
            f"{float(max_volume / total_volume * 100):.1f}% of total volume"
        )


def validate_exclusive_group_bid(group: ExclusiveGroupBid) -> None:
    """Run all exclusive group bid validation checks.

    Args:
        group: Exclusive group bid to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    # Validate each member block bid
    for member in group.block_bids:
        validate_block_bid(member)

    # Validate group-level constraints
    validate_exclusive_group_volumes(group)


# ---------------------------------------------------------------------------
# Bid dispatch validation
# ---------------------------------------------------------------------------


def validate_bid(bid: BidUnion) -> None:
    """Validate any bid type with appropriate checks.

    Dispatches to type-specific validators based on bid type.

    Args:
        bid: Bid to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    if isinstance(bid, SimpleBid):
        validate_simple_bid(bid)
    elif isinstance(bid, BlockBid):
        validate_block_bid(bid)
    elif isinstance(bid, LinkedBlockBid):
        validate_linked_block_bid(bid)
    elif isinstance(bid, ExclusiveGroupBid):
        validate_exclusive_group_bid(bid)
    else:
        raise ValueError(f"Unknown bid type: {type(bid)}")


# ---------------------------------------------------------------------------
# Order book / portfolio validation
# ---------------------------------------------------------------------------


def validate_order_book_volumes(order_book: OrderBook) -> None:
    """Validate that order book total volumes are reasonable.

    Performs portfolio-level sanity checks on aggregate volumes.

    Args:
        order_book: Order book to validate.

    Raises:
        PortfolioValidationError: If portfolio volumes are unreasonable.
    """
    from nexa_bidkit.orders import total_volume_by_zone

    volumes = total_volume_by_zone(order_book)

    # Check for extremely large portfolio volumes (> 1,000,000 MW)
    max_portfolio_volume = Decimal("1000000")
    for zone, volume in volumes.items():
        if volume > max_portfolio_volume:
            raise PortfolioValidationError(
                f"Total volume for zone {zone.value} is {volume} MW, "
                f"exceeds reasonable maximum {max_portfolio_volume} MW"
            )


def validate_order_book_bids(order_book: OrderBook) -> None:
    """Validate all bids in an order book.

    Runs individual bid validation and portfolio-level checks.

    Args:
        order_book: Order book to validate.

    Raises:
        ValidationError: If any validation check fails.
    """
    # Validate each bid individually
    for bid in order_book.bids:
        validate_bid(bid)

    # Run portfolio-level validation
    validate_order_book_volumes(order_book)


def validate_order_book_for_submission(
    order_book: OrderBook,
    gate_closure_time: datetime,
    submission_time: datetime | None = None,
) -> None:
    """Comprehensive validation before submitting order book to exchange.

    Validates all bids and checks gate closure constraint.

    Args:
        order_book: Order book to validate for submission.
        gate_closure_time: Gate closure deadline (timezone-aware).
        submission_time: Time of submission (timezone-aware). If None, uses current UTC time.

    Raises:
        ValidationError: If any validation check fails.
    """
    from datetime import UTC

    if submission_time is None:
        submission_time = datetime.now(UTC)

    # Validate gate closure
    validate_gate_closure(submission_time, gate_closure_time)

    # Validate all bids
    validate_order_book_bids(order_book)


# ---------------------------------------------------------------------------
# Batch validation
# ---------------------------------------------------------------------------


def validate_bids(bids: list[BidUnion]) -> list[tuple[BidUnion, Exception | None]]:
    """Validate a list of bids and return results.

    Useful for batch validation where you want to collect all errors
    rather than failing on the first error.

    Args:
        bids: List of bids to validate.

    Returns:
        List of tuples (bid, error) where error is None if validation passed,
        or the exception if validation failed.
    """
    results: list[tuple[BidUnion, Exception | None]] = []

    for bid in bids:
        try:
            validate_bid(bid)
            results.append((bid, None))
        except Exception as e:
            results.append((bid, e))

    return results


def get_validation_summary(
    validation_results: list[tuple[BidUnion, Exception | None]],
) -> dict[str, Any]:
    """Generate summary statistics from batch validation results.

    Args:
        validation_results: Results from validate_bids().

    Returns:
        Dictionary with summary statistics:
            - total_bids: Total number of bids validated
            - passed: Number of bids that passed validation
            - failed: Number of bids that failed validation
            - error_types: Count of each error type
            - pass_rate: Percentage of bids that passed
    """
    total = len(validation_results)
    passed = sum(1 for _, err in validation_results if err is None)
    failed = total - passed

    error_types: dict[str, int] = {}
    for _, err in validation_results:
        if err is not None:
            error_type = type(err).__name__
            error_types[error_type] = error_types.get(error_type, 0) + 1

    return {
        "total_bids": total,
        "passed": passed,
        "failed": failed,
        "error_types": error_types,
        "pass_rate": (passed / total * 100) if total > 0 else 0.0,
    }


__all__ = [
    # Constants
    "MAX_CURVE_STEPS",
    "MIN_BLOCK_DURATION_HOURS",
    "MAX_BLOCK_DURATION_HOURS",
    "MIN_BID_VOLUME_MW",
    "MAX_BID_VOLUME_MW",
    "MIN_PRICE_STEP_INCREMENT",
    # Exceptions
    "ValidationError",
    "EuphemiaValidationError",
    "DataQualityError",
    "TemporalValidationError",
    "PortfolioValidationError",
    # Curve validation
    "validate_curve_steps_count",
    "validate_curve_minimum_volume",
    "validate_curve_total_volume",
    "validate_price_step_increments",
    "validate_price_quantity_curve",
    # Block bid validation
    "validate_block_duration",
    "validate_block_volume",
    "validate_block_total_volume",
    "validate_block_bid",
    "validate_linked_block_bid",
    # Temporal validation
    "validate_delivery_within_day",
    "validate_mtu_within_day",
    "validate_gate_closure",
    # MTU resolution validation
    "validate_mtu_resolution_for_zone",
    # Simple bid validation
    "validate_simple_bid",
    # Exclusive group validation
    "validate_exclusive_group_volumes",
    "validate_exclusive_group_bid",
    # Bid dispatch validation
    "validate_bid",
    # Order book validation
    "validate_order_book_volumes",
    "validate_order_book_bids",
    "validate_order_book_for_submission",
    # Batch validation
    "validate_bids",
    "get_validation_summary",
]
