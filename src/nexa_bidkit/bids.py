"""Bid objects for European power market auctions.

Provides Pydantic models for EUPHEMIA-compatible bid types:
- SimpleBid: price-quantity curve per MTU
- BlockBid: fixed price/volume across contiguous MTUs
- LinkedBlockBid: block bid with parent dependency
- ExclusiveGroupBid: mutually exclusive block bids
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from nexa_bidkit.types import (
    BiddingZone,
    BidStatus,
    BidType,
    CurveType,
    DeliveryPeriod,
    Direction,
    Price,
    PriceQuantityCurve,
    Volume,
)

# ---------------------------------------------------------------------------
# SimpleBid - price-quantity curve per MTU
# ---------------------------------------------------------------------------


class SimpleBid(BaseModel):
    """Simple price-quantity curve bid for a single MTU.

    Represents a merit-order curve submitted for a specific market time unit.
    The direction (BUY/SELL) must match the curve type (DEMAND/SUPPLY).

    Attributes:
        bid_id: Unique identifier for this bid.
        bidding_zone: Market zone where energy will be delivered.
        direction: BUY (demand) or SELL (supply).
        curve: Price-quantity curve with embedded MTU interval.
        status: Lifecycle status of the bid.
        bid_type: Fixed discriminator (SIMPLE_HOURLY).
        metadata: Optional arbitrary metadata for tracking.
    """

    bid_id: str
    bidding_zone: BiddingZone
    direction: Direction
    curve: PriceQuantityCurve
    status: BidStatus = BidStatus.DRAFT
    bid_type: Literal[BidType.SIMPLE_HOURLY] = BidType.SIMPLE_HOURLY
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("bid_id")
    @classmethod
    def validate_bid_id(cls, v: str) -> str:
        """Ensure bid_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("bid_id must be a non-empty string")
        return v

    @model_validator(mode="after")
    def validate_direction_matches_curve(self) -> SimpleBid:
        """Ensure curve type matches direction (SUPPLY=SELL, DEMAND=BUY)."""
        expected_curve_type = (
            CurveType.SUPPLY if self.direction == Direction.SELL else CurveType.DEMAND
        )
        if self.curve.curve_type != expected_curve_type:
            raise ValueError(
                f"Direction {self.direction.value} requires curve type "
                f"{expected_curve_type.value}, got {self.curve.curve_type.value}"
            )
        return self


# ---------------------------------------------------------------------------
# BlockBid - fixed price/volume across contiguous MTUs
# ---------------------------------------------------------------------------


class BlockBid(BaseModel):
    """Block bid with fixed price and volume across contiguous MTUs.

    Represents an all-or-nothing (or partially-fillable) bid for a
    contiguous delivery period with a single limit price and volume.

    Attributes:
        bid_id: Unique identifier for this bid.
        bidding_zone: Market zone where energy will be delivered.
        direction: BUY (demand) or SELL (supply).
        delivery_period: Contiguous sequence of MTUs for delivery.
        price: Fixed limit price in EUR/MWh for all MTUs.
        volume: Fixed volume in MW for each MTU in the period.
        min_acceptance_ratio: Minimum partial fill ratio (0.0 to 1.0).
        status: Lifecycle status of the bid.
        bid_type: Fixed discriminator (BLOCK).
        metadata: Optional arbitrary metadata for tracking.
    """

    bid_id: str
    bidding_zone: BiddingZone
    direction: Direction
    delivery_period: DeliveryPeriod
    price: Price
    volume: Volume
    min_acceptance_ratio: Decimal = Decimal("1.0")
    status: BidStatus = BidStatus.DRAFT
    bid_type: Literal[BidType.BLOCK] = BidType.BLOCK
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("bid_id")
    @classmethod
    def validate_bid_id(cls, v: str) -> str:
        """Ensure bid_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("bid_id must be a non-empty string")
        return v

    @field_validator("min_acceptance_ratio")
    @classmethod
    def validate_min_acceptance_ratio(cls, v: Decimal) -> Decimal:
        """Ensure min_acceptance_ratio is between 0.0 and 1.0."""
        if v < Decimal("0.0") or v > Decimal("1.0"):
            raise ValueError(
                f"min_acceptance_ratio must be between 0.0 and 1.0, got {v}"
            )
        return v

    @property
    def total_volume(self) -> Decimal:
        """Total volume across all MTUs in the delivery period (MW)."""
        return self.volume * self.delivery_period.mtu_count

    @property
    def is_indivisible(self) -> bool:
        """Whether this block is indivisible (all-or-nothing)."""
        return self.min_acceptance_ratio == Decimal("1.0")


# ---------------------------------------------------------------------------
# LinkedBlockBid - block bid with parent dependency
# ---------------------------------------------------------------------------


class LinkedBlockBid(BaseModel):
    """Linked block bid with dependency on a parent block bid.

    Can only be accepted if the parent block bid is (fully or partially)
    accepted. Used to model operational constraints like ramp-up requirements.

    Attributes:
        bid_id: Unique identifier for this bid.
        bidding_zone: Market zone where energy will be delivered.
        direction: BUY (demand) or SELL (supply).
        delivery_period: Contiguous sequence of MTUs for delivery.
        price: Fixed limit price in EUR/MWh for all MTUs.
        volume: Fixed volume in MW for each MTU in the period.
        parent_bid_id: Reference to parent block bid ID.
        min_acceptance_ratio: Minimum partial fill ratio (0.0 to 1.0).
        status: Lifecycle status of the bid.
        bid_type: Fixed discriminator (LINKED_BLOCK).
        metadata: Optional arbitrary metadata for tracking.
    """

    bid_id: str
    bidding_zone: BiddingZone
    direction: Direction
    delivery_period: DeliveryPeriod
    price: Price
    volume: Volume
    parent_bid_id: str
    min_acceptance_ratio: Decimal = Decimal("1.0")
    status: BidStatus = BidStatus.DRAFT
    bid_type: Literal[BidType.LINKED_BLOCK] = BidType.LINKED_BLOCK
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("bid_id", "parent_bid_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        """Ensure IDs are non-empty."""
        if not v or not v.strip():
            raise ValueError("IDs must be non-empty strings")
        return v

    @field_validator("min_acceptance_ratio")
    @classmethod
    def validate_min_acceptance_ratio(cls, v: Decimal) -> Decimal:
        """Ensure min_acceptance_ratio is between 0.0 and 1.0."""
        if v < Decimal("0.0") or v > Decimal("1.0"):
            raise ValueError(
                f"min_acceptance_ratio must be between 0.0 and 1.0, got {v}"
            )
        return v

    @model_validator(mode="after")
    def validate_no_self_reference(self) -> LinkedBlockBid:
        """Ensure bid does not reference itself as parent."""
        if self.bid_id == self.parent_bid_id:
            raise ValueError("LinkedBlockBid cannot reference itself as parent")
        return self

    @property
    def total_volume(self) -> Decimal:
        """Total volume across all MTUs in the delivery period (MW)."""
        return self.volume * self.delivery_period.mtu_count

    @property
    def is_indivisible(self) -> bool:
        """Whether this block is indivisible (all-or-nothing)."""
        return self.min_acceptance_ratio == Decimal("1.0")


# ---------------------------------------------------------------------------
# ExclusiveGroupBid - mutually exclusive block bids
# ---------------------------------------------------------------------------


class ExclusiveGroupBid(BaseModel):
    """Collection of mutually exclusive block bids.

    At most one block bid from the group may be accepted. All member bids
    must share the same bidding zone and direction. Only pure BlockBid
    instances are allowed (no LinkedBlockBid).

    Attributes:
        group_id: Unique identifier for this exclusive group.
        bidding_zone: Market zone (derived from first block, all must match).
        direction: BUY or SELL (derived from first block, all must match).
        block_bids: List of mutually exclusive BlockBid instances (2+ required).
        status: Lifecycle status of the group.
        bid_type: Fixed discriminator (EXCLUSIVE_GROUP).
        metadata: Optional arbitrary metadata for tracking.
    """

    group_id: str
    bidding_zone: BiddingZone
    direction: Direction
    block_bids: list[BlockBid]
    status: BidStatus = BidStatus.DRAFT
    bid_type: Literal[BidType.EXCLUSIVE_GROUP] = BidType.EXCLUSIVE_GROUP
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("group_id")
    @classmethod
    def validate_group_id(cls, v: str) -> str:
        """Ensure group_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("group_id must be a non-empty string")
        return v

    @field_validator("block_bids")
    @classmethod
    def validate_minimum_blocks(cls, v: list[BlockBid]) -> list[BlockBid]:
        """Ensure at least 2 block bids are provided."""
        if len(v) < 2:
            raise ValueError(
                f"ExclusiveGroupBid requires at least 2 block bids, got {len(v)}"
            )
        return v

    @model_validator(mode="after")
    def validate_consistency(self) -> ExclusiveGroupBid:
        """Validate zone/direction consistency and unique bid IDs."""
        # Check all blocks share same bidding zone
        zones = {block.bidding_zone for block in self.block_bids}
        if len(zones) > 1:
            raise ValueError(
                f"All block bids must have the same bidding zone, got {zones}"
            )
        if zones and zones.pop() != self.bidding_zone:
            raise ValueError(
                f"Block bids zone {zones} does not match group zone {self.bidding_zone}"
            )

        # Check all blocks share same direction
        directions = {block.direction for block in self.block_bids}
        if len(directions) > 1:
            raise ValueError(
                f"All block bids must have the same direction, got {directions}"
            )
        if directions and directions.pop() != self.direction:
            raise ValueError(
                f"Block bids direction does not match group direction {self.direction}"
            )

        # Check all bid_ids are unique
        bid_ids = [block.bid_id for block in self.block_bids]
        if len(bid_ids) != len(set(bid_ids)):
            duplicates = {bid_id for bid_id in bid_ids if bid_ids.count(bid_id) > 1}
            raise ValueError(f"Duplicate bid_ids found in group: {duplicates}")

        # Check all blocks are pure BlockBid (bid_type == BLOCK)
        non_block = [
            block.bid_id
            for block in self.block_bids
            if block.bid_type != BidType.BLOCK
        ]
        if non_block:
            raise ValueError(
                f"ExclusiveGroupBid can only contain pure BlockBid instances, "
                f"found non-BLOCK bid_types: {non_block}"
            )

        return self

    @property
    def member_count(self) -> int:
        """Number of block bids in the exclusive group."""
        return len(self.block_bids)

    @property
    def all_bid_ids(self) -> list[str]:
        """List of all member bid IDs in the group."""
        return [block.bid_id for block in self.block_bids]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def generate_bid_id(prefix: str = "bid") -> str:
    """Generate a unique bid ID using UUID4.

    Args:
        prefix: Optional prefix for the ID (default: "bid").

    Returns:
        Unique bid ID string in the format "{prefix}_{uuid}".
    """
    return f"{prefix}_{uuid.uuid4()}"


def simple_bid_from_curve(
    curve: PriceQuantityCurve,
    bidding_zone: BiddingZone,
    bid_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SimpleBid:
    """Create a SimpleBid from a price-quantity curve.

    Automatically derives direction from curve_type (SUPPLY->SELL, DEMAND->BUY).
    Generates bid_id if not provided.

    Args:
        curve: Price-quantity curve with embedded MTU.
        bidding_zone: Market zone.
        bid_id: Optional explicit bid ID (auto-generated if None).
        metadata: Optional metadata dict.

    Returns:
        Validated SimpleBid instance.
    """
    direction = Direction.SELL if curve.curve_type == CurveType.SUPPLY else Direction.BUY
    return SimpleBid(
        bid_id=bid_id or generate_bid_id("simple"),
        bidding_zone=bidding_zone,
        direction=direction,
        curve=curve,
        metadata=metadata or {},
    )


def block_bid(
    bidding_zone: BiddingZone,
    direction: Direction,
    delivery_period: DeliveryPeriod,
    price: Decimal,
    volume: Decimal,
    min_acceptance_ratio: Decimal = Decimal("1.0"),
    bid_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BlockBid:
    """Create a BlockBid with sensible defaults.

    Args:
        bidding_zone: Market zone.
        direction: BUY or SELL.
        delivery_period: Contiguous delivery MTUs.
        price: Limit price in EUR/MWh.
        volume: Volume per MTU in MW.
        min_acceptance_ratio: Minimum partial fill ratio (default 1.0 = indivisible).
        bid_id: Optional explicit bid ID (auto-generated if None).
        metadata: Optional metadata dict.

    Returns:
        Validated BlockBid instance.
    """
    return BlockBid(
        bid_id=bid_id or generate_bid_id("block"),
        bidding_zone=bidding_zone,
        direction=direction,
        delivery_period=delivery_period,
        price=price,
        volume=volume,
        min_acceptance_ratio=min_acceptance_ratio,
        metadata=metadata or {},
    )


def indivisible_block_bid(
    bidding_zone: BiddingZone,
    direction: Direction,
    delivery_period: DeliveryPeriod,
    price: Decimal,
    volume: Decimal,
    bid_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BlockBid:
    """Create an indivisible BlockBid (all-or-nothing).

    Convenience wrapper setting min_acceptance_ratio=1.0.

    Args:
        bidding_zone: Market zone.
        direction: BUY or SELL.
        delivery_period: Contiguous delivery MTUs.
        price: Limit price in EUR/MWh.
        volume: Volume per MTU in MW.
        bid_id: Optional explicit bid ID (auto-generated if None).
        metadata: Optional metadata dict.

    Returns:
        Validated indivisible BlockBid instance.
    """
    return block_bid(
        bidding_zone=bidding_zone,
        direction=direction,
        delivery_period=delivery_period,
        price=price,
        volume=volume,
        min_acceptance_ratio=Decimal("1.0"),
        bid_id=bid_id,
        metadata=metadata,
    )


def linked_block_bid(
    parent_bid_id: str,
    bidding_zone: BiddingZone,
    direction: Direction,
    delivery_period: DeliveryPeriod,
    price: Decimal,
    volume: Decimal,
    min_acceptance_ratio: Decimal = Decimal("1.0"),
    bid_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LinkedBlockBid:
    """Create a LinkedBlockBid dependent on a parent block.

    Args:
        parent_bid_id: ID of the parent BlockBid.
        bidding_zone: Market zone.
        direction: BUY or SELL.
        delivery_period: Contiguous delivery MTUs.
        price: Limit price in EUR/MWh.
        volume: Volume per MTU in MW.
        min_acceptance_ratio: Minimum partial fill ratio (default 1.0).
        bid_id: Optional explicit bid ID (auto-generated if None).
        metadata: Optional metadata dict.

    Returns:
        Validated LinkedBlockBid instance.
    """
    return LinkedBlockBid(
        bid_id=bid_id or generate_bid_id("linked"),
        bidding_zone=bidding_zone,
        direction=direction,
        delivery_period=delivery_period,
        price=price,
        volume=volume,
        parent_bid_id=parent_bid_id,
        min_acceptance_ratio=min_acceptance_ratio,
        metadata=metadata or {},
    )


def exclusive_group(
    block_bids: list[BlockBid],
    group_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExclusiveGroupBid:
    """Create an ExclusiveGroupBid from a list of block bids.

    Derives bidding_zone and direction from first block bid (validates all match).

    Args:
        block_bids: List of mutually exclusive BlockBid instances (2+ required).
        group_id: Optional explicit group ID (auto-generated if None).
        metadata: Optional metadata dict.

    Returns:
        Validated ExclusiveGroupBid instance.

    Raises:
        ValueError: If fewer than 2 block_bids provided.
    """
    if len(block_bids) < 2:
        raise ValueError(
            f"exclusive_group requires at least 2 block bids, got {len(block_bids)}"
        )

    first_block = block_bids[0]
    return ExclusiveGroupBid(
        group_id=group_id or generate_bid_id("group"),
        bidding_zone=first_block.bidding_zone,
        direction=first_block.direction,
        block_bids=block_bids,
        metadata=metadata or {},
    )


def with_status(
    bid: SimpleBid | BlockBid | LinkedBlockBid,
    status: BidStatus,
) -> SimpleBid | BlockBid | LinkedBlockBid:
    """Create a copy of a bid with updated status.

    Since bids are frozen, this creates a new instance.

    Args:
        bid: Original bid instance.
        status: New status.

    Returns:
        New bid instance with updated status.
    """
    return bid.model_copy(update={"status": status})


def validate_bid_collection(
    bids: list[SimpleBid | BlockBid | LinkedBlockBid],
) -> None:
    """Validate a collection of bids for internal consistency.

    Checks:
    - All bid_ids are unique
    - All linked block bids reference valid parent_bid_ids in the collection
    - No circular dependencies in linked bids

    Args:
        bids: Collection of bids to validate.

    Raises:
        ValueError: If validation fails with descriptive message.
    """
    # Check all bid_ids are unique
    bid_ids = [bid.bid_id for bid in bids]
    if len(bid_ids) != len(set(bid_ids)):
        duplicates = {bid_id for bid_id in bid_ids if bid_ids.count(bid_id) > 1}
        raise ValueError(f"Duplicate bid_ids found in collection: {duplicates}")

    # Build a map of bid_id -> bid for parent lookups
    bid_map = {bid.bid_id: bid for bid in bids}

    # Check all linked bids reference valid parents
    linked_bids = [bid for bid in bids if isinstance(bid, LinkedBlockBid)]
    for linked_bid in linked_bids:
        if linked_bid.parent_bid_id not in bid_map:
            raise ValueError(
                f"LinkedBlockBid {linked_bid.bid_id} references non-existent "
                f"parent {linked_bid.parent_bid_id}"
            )

    # Check for circular dependencies using DFS
    def has_cycle(bid_id: str, visited: set[str], rec_stack: set[str]) -> bool:
        """Detect cycles in the parent-child dependency graph."""
        visited.add(bid_id)
        rec_stack.add(bid_id)

        bid = bid_map[bid_id]
        if isinstance(bid, LinkedBlockBid):
            parent_id = bid.parent_bid_id
            if parent_id in bid_map:
                if parent_id not in visited:
                    if has_cycle(parent_id, visited, rec_stack):
                        return True
                elif parent_id in rec_stack:
                    return True

        rec_stack.remove(bid_id)
        return False

    visited: set[str] = set()
    for linked_bid in linked_bids:
        if linked_bid.bid_id not in visited and has_cycle(
            linked_bid.bid_id, visited, set()
        ):
            raise ValueError(
                f"Circular dependency detected involving bid {linked_bid.bid_id}"
            )


__all__ = [
    "SimpleBid",
    "BlockBid",
    "LinkedBlockBid",
    "ExclusiveGroupBid",
    "generate_bid_id",
    "simple_bid_from_curve",
    "block_bid",
    "indivisible_block_bid",
    "linked_block_bid",
    "exclusive_group",
    "with_status",
    "validate_bid_collection",
]
