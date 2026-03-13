"""Utilities for constructing and manipulating price-quantity curves.

This module provides functions to build :class:`PriceQuantityCurve` objects
from pandas DataFrames and other data sources, apply transformations, and
convert curves back to tabular format.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

import pandas as pd

from nexa_bidkit.types import (
    CurveType,
    MTUInterval,
    PriceQuantityCurve,
    PriceQuantityStep,
)

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _to_decimal(value: Any) -> Decimal:
    """Convert a numeric value to Decimal.

    Args:
        value: A float, int, str, or Decimal.

    Returns:
        The value as a Decimal.

    Raises:
        ValueError: If the value cannot be converted to Decimal.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(value)
    if isinstance(value, float):
        # Convert via string to avoid binary precision issues
        return Decimal(str(value))
    raise ValueError(f"Cannot convert {type(value)} to Decimal")


def _sort_steps(steps: list[PriceQuantityStep], curve_type: CurveType) -> list[PriceQuantityStep]:
    """Sort steps according to curve type convention.

    Args:
        steps: List of steps to sort.
        curve_type: Type of curve (SUPPLY or DEMAND).

    Returns:
        Sorted list of steps. Supply curves are sorted ascending by price,
        demand curves descending by price.
    """
    if curve_type is CurveType.SUPPLY:
        return sorted(steps, key=lambda s: s.price)
    return sorted(steps, key=lambda s: s.price, reverse=True)


# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------


def empty_curve(curve_type: CurveType, mtu: MTUInterval) -> PriceQuantityCurve:
    """Create an empty curve with no steps.

    Args:
        curve_type: Type of curve (SUPPLY or DEMAND).
        mtu: MTU interval this curve applies to.

    Returns:
        An empty :class:`PriceQuantityCurve`.
    """
    return PriceQuantityCurve(curve_type=curve_type, steps=[], mtu=mtu)


def constant_curve(
    price: Decimal,
    volume: Decimal,
    curve_type: CurveType,
    mtu: MTUInterval,
) -> PriceQuantityCurve:
    """Create a curve with a single step.

    Args:
        price: Step price in EUR/MWh.
        volume: Step volume in MW.
        curve_type: Type of curve (SUPPLY or DEMAND).
        mtu: MTU interval this curve applies to.

    Returns:
        A :class:`PriceQuantityCurve` with one step.
    """
    step = PriceQuantityStep(price=price, volume=volume)
    return PriceQuantityCurve(curve_type=curve_type, steps=[step], mtu=mtu)


def linear_curve(
    start_price: Decimal,
    end_price: Decimal,
    volume_per_step: Decimal,
    num_steps: int,
    curve_type: CurveType,
    mtu: MTUInterval,
) -> PriceQuantityCurve:
    """Create a curve with evenly-spaced price steps.

    Args:
        start_price: Price of the first step in EUR/MWh.
        end_price: Price of the last step in EUR/MWh.
        volume_per_step: Volume for each step in MW.
        num_steps: Number of steps to create.
        curve_type: Type of curve (SUPPLY or DEMAND).
        mtu: MTU interval this curve applies to.

    Returns:
        A :class:`PriceQuantityCurve` with linearly-spaced steps.

    Raises:
        ValueError: If num_steps < 1.
    """
    if num_steps < 1:
        raise ValueError("num_steps must be at least 1")

    if num_steps == 1:
        return constant_curve(start_price, volume_per_step, curve_type, mtu)

    # Calculate price increment
    price_range = end_price - start_price
    increment = price_range / Decimal(num_steps - 1)

    steps = []
    for i in range(num_steps):
        price = start_price + increment * Decimal(i)
        steps.append(PriceQuantityStep(price=price, volume=volume_per_step))

    return PriceQuantityCurve(curve_type=curve_type, steps=steps, mtu=mtu)


# ---------------------------------------------------------------------------
# Construction from data
# ---------------------------------------------------------------------------


def validate_dataframe_schema(
    df: pd.DataFrame,
    price_col: str = "price",
    volume_col: str = "volume",
    allow_float: bool = False,
) -> None:
    """Validate that a DataFrame has the required columns for curve construction.

    Args:
        df: DataFrame to validate.
        price_col: Name of the price column.
        volume_col: Name of the volume column.
        allow_float: If True, allow float dtype (will be converted to Decimal).
            If False, raise ValueError for float columns.

    Raises:
        ValueError: If required columns are missing or have invalid dtypes.
    """
    # Check required columns exist
    if price_col not in df.columns:
        raise ValueError(f"DataFrame missing required column: {price_col}")
    if volume_col not in df.columns:
        raise ValueError(f"DataFrame missing required column: {volume_col}")

    # Check dtypes if not allowing float
    if not allow_float:
        price_dtype = df[price_col].dtype
        volume_dtype = df[volume_col].dtype
        if price_dtype == "float64" or volume_dtype == "float64":
            raise ValueError(
                f"Float columns not allowed (use allow_float=True to convert): "
                f"{price_col}={price_dtype}, {volume_col}={volume_dtype}"
            )


def from_dict_list(
    steps: list[dict[str, Any]],
    curve_type: CurveType,
    mtu: MTUInterval,
    price_key: str = "price",
    volume_key: str = "volume",
) -> PriceQuantityCurve:
    """Build a curve from a list of dictionaries.

    Args:
        steps: List of dicts, each containing price and volume keys.
        curve_type: Type of curve (SUPPLY or DEMAND).
        mtu: MTU interval this curve applies to.
        price_key: Dictionary key for price values.
        volume_key: Dictionary key for volume values.

    Returns:
        A validated :class:`PriceQuantityCurve`.

    Raises:
        ValueError: If any dict is missing required keys.
    """
    step_objects = []
    for i, step_dict in enumerate(steps):
        if price_key not in step_dict:
            raise ValueError(f"Step {i} missing required key: {price_key}")
        if volume_key not in step_dict:
            raise ValueError(f"Step {i} missing required key: {volume_key}")

        price = _to_decimal(step_dict[price_key])
        volume = _to_decimal(step_dict[volume_key])
        step_objects.append(PriceQuantityStep(price=price, volume=volume))

    # Sort steps according to curve type
    step_objects = _sort_steps(step_objects, curve_type)

    return PriceQuantityCurve(curve_type=curve_type, steps=step_objects, mtu=mtu)


def from_series_pair(
    prices: pd.Series,
    volumes: pd.Series,
    curve_type: CurveType,
    mtu: MTUInterval,
) -> PriceQuantityCurve:
    """Build a curve from two pandas Series.

    Args:
        prices: Series of prices in EUR/MWh.
        volumes: Series of volumes in MW.
        curve_type: Type of curve (SUPPLY or DEMAND).
        mtu: MTU interval this curve applies to.

    Returns:
        A validated :class:`PriceQuantityCurve`.

    Raises:
        ValueError: If Series have different lengths.
    """
    if len(prices) != len(volumes):
        raise ValueError(
            f"Price and volume series have different lengths: {len(prices)} vs {len(volumes)}"
        )

    steps = []
    for price, volume in zip(prices, volumes, strict=False):
        steps.append(PriceQuantityStep(price=_to_decimal(price), volume=_to_decimal(volume)))

    # Sort steps according to curve type
    steps = _sort_steps(steps, curve_type)

    return PriceQuantityCurve(curve_type=curve_type, steps=steps, mtu=mtu)


def from_dataframe(
    df: pd.DataFrame,
    curve_type: CurveType,
    mtu: MTUInterval,
    price_col: str = "price",
    volume_col: str = "volume",
    validate: bool = True,
) -> PriceQuantityCurve:
    """Build a curve from a pandas DataFrame.

    This is the main API for constructing curves from tabular data.

    Args:
        df: DataFrame with price and volume columns.
        curve_type: Type of curve (SUPPLY or DEMAND).
        mtu: MTU interval this curve applies to.
        price_col: Name of the price column.
        volume_col: Name of the volume column.
        validate: If True, validate DataFrame schema before construction.

    Returns:
        A validated :class:`PriceQuantityCurve` with steps sorted according
        to curve type.

    Raises:
        ValueError: If required columns are missing.
    """
    if validate:
        # Allow float dtype but convert to Decimal
        validate_dataframe_schema(df, price_col, volume_col, allow_float=True)

    # Handle empty DataFrame
    if df.empty:
        return empty_curve(curve_type, mtu)

    # Extract series and delegate to from_series_pair
    return from_series_pair(df[price_col], df[volume_col], curve_type, mtu)


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------


def filter_zero_volume(curve: PriceQuantityCurve) -> PriceQuantityCurve:
    """Remove steps with zero volume.

    Args:
        curve: Input curve.

    Returns:
        A new curve with zero-volume steps removed.
    """
    filtered_steps = [s for s in curve.steps if s.volume > 0]
    return PriceQuantityCurve(
        curve_type=curve.curve_type,
        steps=filtered_steps,
        mtu=curve.mtu,
    )


def scale_curve(curve: PriceQuantityCurve, factor: Decimal) -> PriceQuantityCurve:
    """Multiply all volumes by a scaling factor.

    Args:
        curve: Input curve.
        factor: Scaling factor to apply to all volumes.

    Returns:
        A new curve with scaled volumes.

    Raises:
        ValueError: If factor is negative.
    """
    if factor < 0:
        raise ValueError("Scaling factor must be non-negative")

    scaled_steps = [PriceQuantityStep(price=s.price, volume=s.volume * factor) for s in curve.steps]
    return PriceQuantityCurve(
        curve_type=curve.curve_type,
        steps=scaled_steps,
        mtu=curve.mtu,
    )


def clip_curve(
    curve: PriceQuantityCurve,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    max_volume: Decimal | None = None,
) -> PriceQuantityCurve:
    """Limit curve to specified price and volume bounds.

    Args:
        curve: Input curve.
        min_price: If specified, remove steps below this price.
        max_price: If specified, remove steps above this price.
        max_volume: If specified, truncate total volume to this limit.

    Returns:
        A new curve with steps filtered by bounds.
    """
    steps = curve.steps

    # Filter by price bounds
    if min_price is not None:
        steps = [s for s in steps if s.price >= min_price]
    if max_price is not None:
        steps = [s for s in steps if s.price <= max_price]

    # Truncate by volume if needed
    if max_volume is not None:
        cumulative = Decimal("0")
        truncated_steps = []
        for step in steps:
            if cumulative >= max_volume:
                break
            remaining = max_volume - cumulative
            if step.volume <= remaining:
                truncated_steps.append(step)
                cumulative += step.volume
            else:
                # Partial step
                truncated_steps.append(PriceQuantityStep(price=step.price, volume=remaining))
                break
        steps = truncated_steps

    return PriceQuantityCurve(
        curve_type=curve.curve_type,
        steps=steps,
        mtu=curve.mtu,
    )


def aggregate_by_price(curve: PriceQuantityCurve) -> PriceQuantityCurve:
    """Consolidate steps with identical prices.

    Args:
        curve: Input curve.

    Returns:
        A new curve with volumes aggregated by price.
    """
    if not curve.steps:
        return curve

    # Group by price and sum volumes
    price_volumes: dict[Decimal, Decimal] = {}
    for step in curve.steps:
        price_volumes[step.price] = price_volumes.get(step.price, Decimal("0")) + step.volume

    # Create new steps
    steps = [
        PriceQuantityStep(price=price, volume=volume) for price, volume in price_volumes.items()
    ]

    # Sort according to curve type
    steps = _sort_steps(steps, curve.curve_type)

    return PriceQuantityCurve(
        curve_type=curve.curve_type,
        steps=steps,
        mtu=curve.mtu,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def merge_curves(
    curves: list[PriceQuantityCurve],
    aggregation: Literal["sum", "stack"] = "sum",
) -> PriceQuantityCurve:
    """Combine multiple curves for the same MTU.

    Args:
        curves: List of curves to merge. Must all have the same curve_type and mtu.
        aggregation: Aggregation mode:
            - "sum": Aggregate volumes by price (default).
            - "stack": Concatenate all steps and re-sort.

    Returns:
        A merged curve.

    Raises:
        ValueError: If curves list is empty, or if curves have incompatible
            types or MTUs.
    """
    if not curves:
        raise ValueError("Cannot merge empty list of curves")

    # Validate all curves have same type and MTU
    first = curves[0]
    for curve in curves[1:]:
        if curve.curve_type != first.curve_type:
            raise ValueError(
                f"Cannot merge curves with different types: "
                f"{first.curve_type} vs {curve.curve_type}"
            )
        if curve.mtu != first.mtu:
            raise ValueError(f"Cannot merge curves with different MTUs: {first.mtu} vs {curve.mtu}")

    # Collect all steps
    all_steps = []
    for curve in curves:
        all_steps.extend(curve.steps)

    if aggregation == "sum":
        # Create temporary curve and aggregate by price
        temp_curve = PriceQuantityCurve(
            curve_type=first.curve_type,
            steps=_sort_steps(all_steps, first.curve_type),
            mtu=first.mtu,
        )
        return aggregate_by_price(temp_curve)
    else:  # stack
        # Just sort and return
        return PriceQuantityCurve(
            curve_type=first.curve_type,
            steps=_sort_steps(all_steps, first.curve_type),
            mtu=first.mtu,
        )


# ---------------------------------------------------------------------------
# Conversion and utilities
# ---------------------------------------------------------------------------


def to_dataframe(
    curve: PriceQuantityCurve,
    include_mtu: bool = False,
) -> pd.DataFrame:
    """Convert a curve to a pandas DataFrame.

    Args:
        curve: Curve to convert.
        include_mtu: If True, include MTU start/end columns.

    Returns:
        DataFrame with price and volume columns (and optionally MTU columns).
    """
    if not curve.steps:
        # Return empty DataFrame with correct columns
        cols = ["price", "volume"]
        if include_mtu:
            cols.extend(["mtu_start", "mtu_end"])
        return pd.DataFrame(columns=cols)

    data: dict[str, list[Any]] = {
        "price": [s.price for s in curve.steps],
        "volume": [s.volume for s in curve.steps],
    }

    if include_mtu:
        data["mtu_start"] = [curve.mtu.start] * len(curve.steps)
        data["mtu_end"] = [curve.mtu.end] * len(curve.steps)

    return pd.DataFrame(data)


def get_curve_summary(curve: PriceQuantityCurve) -> dict[str, Any]:
    """Generate descriptive statistics for a curve.

    Args:
        curve: Curve to summarize.

    Returns:
        Dictionary with summary statistics:
            - num_steps: Number of steps
            - total_volume: Sum of volumes
            - min_price: Minimum price
            - max_price: Maximum price
            - avg_price: Volume-weighted average price (None if empty)
            - curve_type: Type of curve
    """
    summary = {
        "num_steps": len(curve.steps),
        "total_volume": curve.total_volume,
        "min_price": curve.min_price,
        "max_price": curve.max_price,
        "curve_type": curve.curve_type.value,
    }

    # Calculate volume-weighted average price
    if curve.steps and curve.total_volume > 0:
        weighted_sum = sum(s.price * s.volume for s in curve.steps)
        summary["avg_price"] = weighted_sum / curve.total_volume
    else:
        summary["avg_price"] = None

    return summary
