"""Tests for nexa_bidkit.types — core domain types."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from nexa_bidkit.types import (
    BiddingZone,
    BidStatus,
    BidType,
    CurveType,
    DeliveryPeriod,
    Direction,
    MTUDuration,
    MTUInterval,
    PriceQuantityCurve,
    PriceQuantityStep,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = UTC
CET = timezone(timedelta(hours=1), "CET")

# A fixed aware datetime to anchor tests
T0 = datetime(2025, 10, 1, 0, 0, 0, tzinfo=UTC)


def step(price: str, volume: str) -> PriceQuantityStep:
    return PriceQuantityStep(price=Decimal(price), volume=Decimal(volume))


def quarter_interval(start: datetime = T0) -> MTUInterval:
    return MTUInterval.from_start(start, MTUDuration.QUARTER_HOURLY)


def hourly_interval(start: datetime = T0) -> MTUInterval:
    return MTUInterval.from_start(start, MTUDuration.HOURLY)


# ---------------------------------------------------------------------------
# MTUDuration
# ---------------------------------------------------------------------------


class TestMTUDuration:
    def test_hourly_timedelta(self) -> None:
        assert MTUDuration.HOURLY.timedelta == timedelta(hours=1)

    def test_quarter_hourly_timedelta(self) -> None:
        assert MTUDuration.QUARTER_HOURLY.timedelta == timedelta(minutes=15)

    def test_hourly_per_day(self) -> None:
        assert MTUDuration.HOURLY.per_day == 24

    def test_quarter_hourly_per_day(self) -> None:
        assert MTUDuration.QUARTER_HOURLY.per_day == 96

    def test_values_are_iso8601_durations(self) -> None:
        assert MTUDuration.HOURLY.value == "PT1H"
        assert MTUDuration.QUARTER_HOURLY.value == "PT15M"


# ---------------------------------------------------------------------------
# MTUInterval
# ---------------------------------------------------------------------------


class TestMTUInterval:
    def test_valid_quarter_hourly(self) -> None:
        iv = quarter_interval()
        assert iv.start == T0
        assert iv.end == T0 + timedelta(minutes=15)
        assert iv.duration is MTUDuration.QUARTER_HOURLY

    def test_valid_hourly(self) -> None:
        iv = hourly_interval()
        assert iv.end == T0 + timedelta(hours=1)

    def test_from_start_quarter(self) -> None:
        iv = MTUInterval.from_start(T0, MTUDuration.QUARTER_HOURLY)
        assert iv.end - iv.start == timedelta(minutes=15)

    def test_from_start_hourly(self) -> None:
        iv = MTUInterval.from_start(T0, MTUDuration.HOURLY)
        assert iv.end - iv.start == timedelta(hours=1)

    def test_naive_start_rejected(self) -> None:
        naive = datetime(2025, 10, 1, 0, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            MTUInterval(
                start=naive,
                end=naive + timedelta(hours=1),
                duration=MTUDuration.HOURLY,
            )

    def test_naive_end_rejected(self) -> None:
        naive = datetime(2025, 10, 1, 1, 0, 0)
        with pytest.raises(ValidationError, match="timezone-aware"):
            MTUInterval(
                start=T0,
                end=naive,
                duration=MTUDuration.HOURLY,
            )

    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError, match="end must be strictly after start"):
            MTUInterval(
                start=T0 + timedelta(hours=1),
                end=T0,
                duration=MTUDuration.HOURLY,
            )

    def test_span_mismatch_rejected(self) -> None:
        # Declare HOURLY but give a 15-min span
        with pytest.raises(ValidationError, match="does not match duration"):
            MTUInterval(
                start=T0,
                end=T0 + timedelta(minutes=15),
                duration=MTUDuration.HOURLY,
            )

    def test_frozen(self) -> None:
        iv = quarter_interval()
        with pytest.raises(ValidationError):
            iv.start = T0 + timedelta(hours=1)  # type: ignore[misc]

    def test_cet_timezone_accepted(self) -> None:
        start_cet = datetime(2025, 10, 1, 1, 0, 0, tzinfo=CET)
        iv = MTUInterval.from_start(start_cet, MTUDuration.HOURLY)
        assert iv.start.tzinfo is not None


# ---------------------------------------------------------------------------
# BiddingZone
# ---------------------------------------------------------------------------


class TestBiddingZone:
    def test_nordic_zones_present(self) -> None:
        zones = [
            "NO1",
            "NO2",
            "NO3",
            "NO4",
            "NO5",
            "SE1",
            "SE2",
            "SE3",
            "SE4",
            "FI",
            "DK1",
            "DK2",
        ]
        for zone in zones:
            assert BiddingZone(zone).value == zone

    def test_cwe_zones_present(self) -> None:
        assert BiddingZone.DE_LU.value == "DE-LU"
        assert BiddingZone.FR.value == "FR"
        assert BiddingZone.BE.value == "BE"

    def test_italian_zones_present(self) -> None:
        assert BiddingZone.IT_NORD.value == "IT-NORD"
        assert BiddingZone.IT_SUD.value == "IT-SUD"

    def test_is_string_subclass(self) -> None:
        assert isinstance(BiddingZone.NO1, str)
        assert BiddingZone.NO1 == "NO1"

    def test_invalid_zone_raises(self) -> None:
        with pytest.raises(ValueError):
            BiddingZone("XX99")


# ---------------------------------------------------------------------------
# PriceQuantityStep
# ---------------------------------------------------------------------------


class TestPriceQuantityStep:
    def test_valid_step(self) -> None:
        s = step("50.00", "100")
        assert s.price == Decimal("50.00")
        assert s.volume == Decimal("100")

    def test_negative_price_allowed(self) -> None:
        s = step("-500", "200")
        assert s.price == Decimal("-500")

    def test_zero_volume_allowed(self) -> None:
        s = step("10", "0")
        assert s.volume == Decimal("0")

    def test_price_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            step("10000", "100")

    def test_price_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            step("-10000", "100")

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            step("10", "-1")

    def test_frozen(self) -> None:
        s = step("10", "50")
        with pytest.raises(ValidationError):
            s.price = Decimal("20")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PriceQuantityCurve
# ---------------------------------------------------------------------------


class TestPriceQuantityCurve:
    def test_valid_supply_curve(self) -> None:
        mtu = quarter_interval()
        curve = PriceQuantityCurve(
            curve_type=CurveType.SUPPLY,
            steps=[step("10", "100"), step("20", "200"), step("30", "50")],
            mtu=mtu,
        )
        assert curve.total_volume == Decimal("350")
        assert curve.min_price == Decimal("10")
        assert curve.max_price == Decimal("30")

    def test_valid_demand_curve(self) -> None:
        mtu = quarter_interval()
        curve = PriceQuantityCurve(
            curve_type=CurveType.DEMAND,
            steps=[step("80", "150"), step("50", "100"), step("20", "50")],
            mtu=mtu,
        )
        assert curve.total_volume == Decimal("300")

    def test_empty_supply_curve_allowed(self) -> None:
        curve = PriceQuantityCurve(curve_type=CurveType.SUPPLY, mtu=quarter_interval())
        assert curve.total_volume == Decimal("0")
        assert curve.min_price is None
        assert curve.max_price is None

    def test_supply_curve_wrong_order_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ascending"):
            PriceQuantityCurve(
                curve_type=CurveType.SUPPLY,
                steps=[step("30", "100"), step("10", "200")],
                mtu=quarter_interval(),
            )

    def test_demand_curve_wrong_order_rejected(self) -> None:
        with pytest.raises(ValidationError, match="descending"):
            PriceQuantityCurve(
                curve_type=CurveType.DEMAND,
                steps=[step("10", "100"), step("50", "200")],
                mtu=quarter_interval(),
            )

    def test_supply_curve_equal_prices_allowed(self) -> None:
        # Ties are valid (same price, different volumes)
        curve = PriceQuantityCurve(
            curve_type=CurveType.SUPPLY,
            steps=[step("50", "100"), step("50", "200")],
            mtu=quarter_interval(),
        )
        assert len(curve.steps) == 2

    def test_frozen(self) -> None:
        curve = PriceQuantityCurve(curve_type=CurveType.SUPPLY, mtu=quarter_interval())
        with pytest.raises(ValidationError):
            curve.curve_type = CurveType.DEMAND  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DeliveryPeriod
# ---------------------------------------------------------------------------


class TestDeliveryPeriod:
    def test_single_quarter_mtu(self) -> None:
        dp = DeliveryPeriod(
            start=T0, end=T0 + timedelta(minutes=15), duration=MTUDuration.QUARTER_HOURLY
        )
        assert dp.mtu_count == 1

    def test_full_day_hourly(self) -> None:
        dp = DeliveryPeriod(start=T0, end=T0 + timedelta(hours=24), duration=MTUDuration.HOURLY)
        assert dp.mtu_count == 24

    def test_full_day_quarter_hourly(self) -> None:
        dp = DeliveryPeriod(
            start=T0, end=T0 + timedelta(hours=24), duration=MTUDuration.QUARTER_HOURLY
        )
        assert dp.mtu_count == 96

    def test_mtu_intervals_count(self) -> None:
        dp = DeliveryPeriod(
            start=T0, end=T0 + timedelta(hours=4), duration=MTUDuration.QUARTER_HOURLY
        )
        intervals = dp.mtu_intervals()
        assert len(intervals) == 16

    def test_mtu_intervals_contiguous(self) -> None:
        dp = DeliveryPeriod(start=T0, end=T0 + timedelta(hours=3), duration=MTUDuration.HOURLY)
        intervals = dp.mtu_intervals()
        for i in range(len(intervals) - 1):
            assert intervals[i].end == intervals[i + 1].start

    def test_mtu_intervals_first_and_last(self) -> None:
        dp = DeliveryPeriod(start=T0, end=T0 + timedelta(hours=2), duration=MTUDuration.HOURLY)
        intervals = dp.mtu_intervals()
        assert intervals[0].start == T0
        assert intervals[-1].end == T0 + timedelta(hours=2)

    def test_naive_start_rejected(self) -> None:
        naive = datetime(2025, 10, 1)
        with pytest.raises(ValidationError, match="timezone-aware"):
            DeliveryPeriod(start=naive, end=naive + timedelta(hours=1), duration=MTUDuration.HOURLY)

    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError, match="end must be strictly after start"):
            DeliveryPeriod(start=T0 + timedelta(hours=1), end=T0, duration=MTUDuration.HOURLY)

    def test_non_integer_mtu_count_rejected(self) -> None:
        # 45 minutes is not a whole number of hourly MTUs
        with pytest.raises(ValidationError, match="whole number"):
            DeliveryPeriod(
                start=T0,
                end=T0 + timedelta(minutes=45),
                duration=MTUDuration.HOURLY,
            )

    def test_frozen(self) -> None:
        dp = DeliveryPeriod(start=T0, end=T0 + timedelta(hours=1), duration=MTUDuration.HOURLY)
        with pytest.raises(ValidationError):
            dp.start = T0 + timedelta(hours=1)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Enums: BidType, Direction, BidStatus
# ---------------------------------------------------------------------------


class TestBidType:
    def test_all_values(self) -> None:
        assert BidType.SIMPLE_HOURLY.value == "SIMPLE_HOURLY"
        assert BidType.BLOCK.value == "BLOCK"
        assert BidType.LINKED_BLOCK.value == "LINKED_BLOCK"
        assert BidType.EXCLUSIVE_GROUP.value == "EXCLUSIVE_GROUP"

    def test_is_string(self) -> None:
        assert isinstance(BidType.BLOCK, str)


class TestDirection:
    def test_values(self) -> None:
        assert Direction.BUY.value == "BUY"
        assert Direction.SELL.value == "SELL"


class TestBidStatus:
    def test_all_statuses_present(self) -> None:
        expected = {"DRAFT", "VALIDATED", "SUBMITTED", "ACCEPTED", "REJECTED", "WITHDRAWN"}
        assert {s.value for s in BidStatus} == expected
