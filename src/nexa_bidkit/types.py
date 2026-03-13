"""Core domain types for nexa-bidkit.

Defines enumerations, value types, and Pydantic models for European power
market auction bidding: MTU intervals, bidding zones, price-quantity curves,
and the bid types supported by EUPHEMIA.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Price / volume constrained types
# ---------------------------------------------------------------------------

# EUPHEMIA price bounds (EUR/MWh). Negative prices are allowed.
MIN_PRICE = Decimal("-9999.99")
MAX_PRICE = Decimal("9999.99")

# Volume in MW. Must be non-negative for a valid bid step.
MIN_VOLUME = Decimal("0")
MAX_VOLUME = Decimal("99999")

Price = Annotated[Decimal, Field(ge=MIN_PRICE, le=MAX_PRICE)]
Volume = Annotated[Decimal, Field(ge=MIN_VOLUME, le=MAX_VOLUME)]


# ---------------------------------------------------------------------------
# MTU (Market Time Unit)
# ---------------------------------------------------------------------------


class MTUDuration(str, Enum):
    """Duration of a single Market Time Unit.

    EU power markets standardised on 15-minute MTUs on 30 Sept 2025,
    but legacy hourly resolution is still used in some contexts (e.g.
    block bids with hourly granularity, older market data).
    """

    HOURLY = "PT1H"
    QUARTER_HOURLY = "PT15M"

    @property
    def timedelta(self) -> timedelta:
        """Return the duration as a :class:`datetime.timedelta`."""
        if self is MTUDuration.HOURLY:
            return timedelta(hours=1)
        return timedelta(minutes=15)

    @property
    def per_day(self) -> int:
        """Number of MTUs in a standard (non-DST-transition) day."""
        if self is MTUDuration.HOURLY:
            return 24
        return 96


class MTUInterval(BaseModel):
    """A single closed-open Market Time Unit interval ``[start, end)``.

    Attributes:
        start: Timezone-aware start of the interval (inclusive).
        end: Timezone-aware end of the interval (exclusive).
        duration: MTU resolution; derived from ``end - start`` if omitted.
    """

    start: datetime
    end: datetime
    duration: MTUDuration

    model_config = {"frozen": True}

    @field_validator("start", "end", mode="before")
    @classmethod
    def require_timezone(cls, v: datetime) -> datetime:
        """Reject naive datetimes."""
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("MTUInterval requires timezone-aware datetimes")
        return v

    @model_validator(mode="after")
    def validate_interval(self) -> MTUInterval:
        """Check end > start and that the span matches the declared duration."""
        if self.end <= self.start:
            raise ValueError("end must be strictly after start")
        span = self.end - self.start
        if span != self.duration.timedelta:
            raise ValueError(
                f"Interval span {span} does not match duration {self.duration.value} "
                f"({self.duration.timedelta})"
            )
        return self

    @classmethod
    def from_start(cls, start: datetime, duration: MTUDuration) -> MTUInterval:
        """Construct an interval from a start datetime and duration.

        Args:
            start: Timezone-aware start of the interval.
            duration: MTU resolution.

        Returns:
            A new :class:`MTUInterval`.
        """
        return cls(start=start, end=start + duration.timedelta, duration=duration)


# ---------------------------------------------------------------------------
# Bidding zones
# ---------------------------------------------------------------------------


class BiddingZone(str, Enum):
    """EIC-style bidding zone identifiers for European power markets.

    Nordic countries use sub-national price zones (e.g. NO1-NO5, SE1-SE4).
    Central Western Europe (CWE) and other regions use country-level zones.
    """

    # --- Nordic ---
    NO1 = "NO1"
    NO2 = "NO2"
    NO3 = "NO3"
    NO4 = "NO4"
    NO5 = "NO5"
    SE1 = "SE1"
    SE2 = "SE2"
    SE3 = "SE3"
    SE4 = "SE4"
    FI = "FI"
    DK1 = "DK1"
    DK2 = "DK2"

    # --- Central Western Europe (CWE) ---
    DE_LU = "DE-LU"
    FR = "FR"
    BE = "BE"
    NL = "NL"
    AT = "AT"

    # --- Central Eastern Europe (CEE) ---
    PL = "PL"
    CZ = "CZ"
    SK = "SK"
    HU = "HU"
    RO = "RO"

    # --- Iberian Peninsula (MIBEL) ---
    ES = "ES"
    PT = "PT"

    # --- Italy ---
    IT_NORD = "IT-NORD"
    IT_CNOR = "IT-CNOR"
    IT_CSUD = "IT-CSUD"
    IT_SUD = "IT-SUD"
    IT_SICI = "IT-SICI"
    IT_SARD = "IT-SARD"

    # --- Great Britain (not part of EUPHEMIA but included for completeness) ---
    GB = "GB"

    # --- Baltics ---
    EE = "EE"
    LV = "LV"
    LT = "LT"


# ---------------------------------------------------------------------------
# Price-quantity curve step
# ---------------------------------------------------------------------------


class PriceQuantityStep(BaseModel):
    """A single step on a price-quantity (merit-order) curve.

    Represents the willingness to buy/sell ``volume`` MW at up to ``price``
    EUR/MWh. Steps are assembled into :class:`PriceQuantityCurve` objects.

    Attributes:
        price: Limit price in EUR/MWh. Negative prices are valid.
        volume: Volume in MW. Must be >= 0.
    """

    price: Price
    volume: Volume

    model_config = {"frozen": True}


class CurveType(str, Enum):
    """Whether a curve represents supply (sell) or demand (buy) orders."""

    SUPPLY = "SUPPLY"
    DEMAND = "DEMAND"


class PriceQuantityCurve(BaseModel):
    """An ordered merit-order curve consisting of price-quantity steps.

    For a **supply** curve steps should be sorted ascending by price
    (cheapest generation first). For a **demand** curve steps should be
    sorted descending by price (highest-value consumption first).

    Attributes:
        curve_type: ``SUPPLY`` or ``DEMAND``.
        steps: Ordered list of :class:`PriceQuantityStep` objects.
        mtu: The MTU interval this curve applies to.
    """

    curve_type: CurveType
    steps: list[PriceQuantityStep] = Field(default_factory=list)
    mtu: MTUInterval

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def validate_step_ordering(self) -> PriceQuantityCurve:
        """Enforce monotonic price ordering appropriate to curve type."""
        prices = [s.price for s in self.steps]
        if self.curve_type is CurveType.SUPPLY:
            if prices != sorted(prices):
                raise ValueError("Supply curve steps must be sorted ascending by price")
        else:
            if prices != sorted(prices, reverse=True):
                raise ValueError("Demand curve steps must be sorted descending by price")
        return self

    @property
    def total_volume(self) -> Decimal:
        """Sum of all step volumes in MW."""
        return sum((s.volume for s in self.steps), Decimal("0"))

    @property
    def min_price(self) -> Decimal | None:
        """Minimum price on the curve, or ``None`` if curve is empty."""
        return min((s.price for s in self.steps), default=None)

    @property
    def max_price(self) -> Decimal | None:
        """Maximum price on the curve, or ``None`` if curve is empty."""
        return max((s.price for s in self.steps), default=None)


# ---------------------------------------------------------------------------
# EUPHEMIA bid type identifiers
# ---------------------------------------------------------------------------


class BidType(str, Enum):
    """EUPHEMIA-recognised bid types.

    References:
        PCR / EUPHEMIA Public Description v3.x, Section 3 (Order Types).
    """

    SIMPLE_HOURLY = "SIMPLE_HOURLY"
    """Simple price-quantity curve bid submitted per MTU."""

    BLOCK = "BLOCK"
    """Fixed price and volume across a contiguous range of MTUs."""

    LINKED_BLOCK = "LINKED_BLOCK"
    """Block bid with a dependency on a parent block bid."""

    EXCLUSIVE_GROUP = "EXCLUSIVE_GROUP"
    """Set of mutually exclusive block bids; at most one may be accepted."""


# ---------------------------------------------------------------------------
# Bid direction
# ---------------------------------------------------------------------------


class Direction(str, Enum):
    """Whether a bid represents a buy (demand) or sell (supply) order."""

    BUY = "BUY"
    SELL = "SELL"


# ---------------------------------------------------------------------------
# Bid status (lifecycle)
# ---------------------------------------------------------------------------


class BidStatus(str, Enum):
    """Lifecycle status of a submitted bid."""

    DRAFT = "DRAFT"
    """Bid has been constructed but not yet validated or submitted."""

    VALIDATED = "VALIDATED"
    """Bid has passed all local validation checks."""

    SUBMITTED = "SUBMITTED"
    """Bid has been transmitted to the exchange."""

    ACCEPTED = "ACCEPTED"
    """Bid was accepted (fully or partially) in the auction."""

    REJECTED = "REJECTED"
    """Bid was rejected by the exchange."""

    WITHDRAWN = "WITHDRAWN"
    """Bid was withdrawn before the gate-closure time."""


# ---------------------------------------------------------------------------
# Delivery period
# ---------------------------------------------------------------------------


class DeliveryPeriod(BaseModel):
    """The contiguous sequence of MTUs covered by a block/linked/exclusive bid.

    Attributes:
        start: Timezone-aware start of the first MTU (inclusive).
        end: Timezone-aware end of the last MTU (exclusive).
        duration: MTU resolution used throughout the period.
    """

    start: datetime
    end: datetime
    duration: MTUDuration

    model_config = {"frozen": True}

    @field_validator("start", "end", mode="before")
    @classmethod
    def require_timezone(cls, v: datetime) -> datetime:
        """Reject naive datetimes."""
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("DeliveryPeriod requires timezone-aware datetimes")
        return v

    @model_validator(mode="after")
    def validate_period(self) -> DeliveryPeriod:
        """Check end > start and that the span is a whole number of MTUs."""
        if self.end <= self.start:
            raise ValueError("end must be strictly after start")
        span = self.end - self.start
        mtu_td = self.duration.timedelta
        total_seconds = int(span.total_seconds())
        mtu_seconds = int(mtu_td.total_seconds())
        if total_seconds % mtu_seconds != 0:
            raise ValueError(
                f"DeliveryPeriod span {span} is not a whole number of {self.duration.value} MTUs"
            )
        return self

    @property
    def mtu_count(self) -> int:
        """Number of MTUs in this delivery period."""
        span = self.end - self.start
        return int(span.total_seconds()) // int(self.duration.timedelta.total_seconds())

    def mtu_intervals(self) -> list[MTUInterval]:
        """Return an ordered list of :class:`MTUInterval` objects.

        Returns:
            All MTU intervals within this delivery period, in chronological order.
        """
        intervals = []
        current = self.start
        while current < self.end:
            intervals.append(MTUInterval.from_start(current, self.duration))
            current += self.duration.timedelta
        return intervals
