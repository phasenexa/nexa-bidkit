"""Tests for curves module."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from nexa_bidkit.curves import (
    aggregate_by_price,
    clip_curve,
    constant_curve,
    empty_curve,
    filter_zero_volume,
    from_dataframe,
    from_dict_list,
    from_series_pair,
    get_curve_summary,
    linear_curve,
    merge_curves,
    scale_curve,
    to_dataframe,
    validate_dataframe_schema,
)
from nexa_bidkit.types import (
    CurveType,
    MTUDuration,
    MTUInterval,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_mtu() -> MTUInterval:
    """Sample MTU interval for testing."""
    return MTUInterval.from_start(
        datetime(2026, 4, 1, 13, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        MTUDuration.QUARTER_HOURLY,
    )


@pytest.fixture
def sample_supply_df() -> pd.DataFrame:
    """Sample DataFrame for supply curve."""
    return pd.DataFrame(
        {
            "price": [10.5, 25.0, 45.0, 80.0],
            "volume": [50, 100, 75, 25],
        }
    )


@pytest.fixture
def sample_demand_df() -> pd.DataFrame:
    """Sample DataFrame for demand curve."""
    return pd.DataFrame(
        {
            "price": [100.0, 75.0, 50.0, 25.0],
            "volume": [20, 40, 60, 80],
        }
    )


# ---------------------------------------------------------------------------
# Basic construction tests
# ---------------------------------------------------------------------------


def test_from_dataframe_supply_curve(sample_supply_df, sample_mtu):
    """Build a valid supply curve from DataFrame."""
    curve = from_dataframe(sample_supply_df, CurveType.SUPPLY, sample_mtu)

    assert curve.curve_type == CurveType.SUPPLY
    assert len(curve.steps) == 4
    assert curve.mtu == sample_mtu
    assert curve.total_volume == Decimal("250")
    # Should be sorted ascending
    assert curve.steps[0].price == Decimal("10.5")
    assert curve.steps[-1].price == Decimal("80.0")


def test_from_dataframe_demand_curve(sample_demand_df, sample_mtu):
    """Build a valid demand curve from DataFrame."""
    curve = from_dataframe(sample_demand_df, CurveType.DEMAND, sample_mtu)

    assert curve.curve_type == CurveType.DEMAND
    assert len(curve.steps) == 4
    assert curve.total_volume == Decimal("200")
    # Should be sorted descending
    assert curve.steps[0].price == Decimal("100.0")
    assert curve.steps[-1].price == Decimal("25.0")


def test_from_dataframe_sorts_steps(sample_mtu):
    """Verify automatic sorting of steps."""
    # Unsorted supply data
    df = pd.DataFrame({"price": [50, 10, 80, 25], "volume": [100, 50, 25, 75]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    # Should be sorted ascending
    prices = [s.price for s in curve.steps]
    assert prices == sorted(prices)


def test_from_dataframe_missing_columns(sample_mtu):
    """Raise ValueError for missing columns."""
    df = pd.DataFrame({"price": [10, 20]})  # Missing volume column

    with pytest.raises(ValueError, match="missing required column: volume"):
        from_dataframe(df, CurveType.SUPPLY, sample_mtu)


def test_from_dataframe_float_conversion(sample_mtu):
    """Accept and convert float to Decimal."""
    df = pd.DataFrame({"price": [10.1, 20.2], "volume": [100.5, 200.7]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    # Should convert without precision errors
    assert curve.steps[0].price == Decimal("10.1")
    assert curve.steps[0].volume == Decimal("100.5")


def test_from_series_pair(sample_mtu):
    """Construction from two Series."""
    prices = pd.Series([10, 20, 30])
    volumes = pd.Series([100, 200, 300])

    curve = from_series_pair(prices, volumes, CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 3
    assert curve.total_volume == Decimal("600")


def test_from_series_pair_length_mismatch(sample_mtu):
    """Raise ValueError for mismatched Series lengths."""
    prices = pd.Series([10, 20])
    volumes = pd.Series([100, 200, 300])

    with pytest.raises(ValueError, match="different lengths"):
        from_series_pair(prices, volumes, CurveType.SUPPLY, sample_mtu)


def test_from_dict_list(sample_mtu):
    """Construction from list of dicts."""
    steps = [
        {"price": 10, "volume": 100},
        {"price": 20, "volume": 200},
        {"price": 30, "volume": 300},
    ]

    curve = from_dict_list(steps, CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 3
    assert curve.total_volume == Decimal("600")


def test_from_dict_list_missing_key(sample_mtu):
    """Raise ValueError for missing keys."""
    steps = [{"price": 10}]  # Missing volume

    with pytest.raises(ValueError, match="missing required key: volume"):
        from_dict_list(steps, CurveType.SUPPLY, sample_mtu)


def test_from_dict_list_custom_keys(sample_mtu):
    """Use custom keys for price/volume."""
    steps = [{"p": 10, "v": 100}, {"p": 20, "v": 200}]

    curve = from_dict_list(steps, CurveType.SUPPLY, sample_mtu, price_key="p", volume_key="v")

    assert len(curve.steps) == 2


# ---------------------------------------------------------------------------
# Pattern generator tests
# ---------------------------------------------------------------------------


def test_empty_curve(sample_mtu):
    """Create curve with zero steps."""
    curve = empty_curve(CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 0
    assert curve.total_volume == Decimal("0")
    assert curve.min_price is None
    assert curve.max_price is None


def test_constant_curve(sample_mtu):
    """Create curve with single step."""
    curve = constant_curve(Decimal("50"), Decimal("100"), CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 1
    assert curve.steps[0].price == Decimal("50")
    assert curve.steps[0].volume == Decimal("100")


def test_linear_curve(sample_mtu):
    """Create curve with multiple evenly-spaced steps."""
    curve = linear_curve(
        Decimal("10"),
        Decimal("50"),
        Decimal("100"),
        5,
        CurveType.SUPPLY,
        sample_mtu,
    )

    assert len(curve.steps) == 5
    assert curve.steps[0].price == Decimal("10")
    assert curve.steps[-1].price == Decimal("50")
    # Check even spacing
    assert curve.steps[1].price == Decimal("20")
    assert curve.steps[2].price == Decimal("30")
    assert curve.steps[3].price == Decimal("40")


def test_linear_curve_single_step(sample_mtu):
    """Linear curve with num_steps=1 creates constant curve."""
    curve = linear_curve(
        Decimal("25"),
        Decimal("75"),  # end_price is ignored
        Decimal("100"),
        1,
        CurveType.SUPPLY,
        sample_mtu,
    )

    assert len(curve.steps) == 1
    assert curve.steps[0].price == Decimal("25")


def test_linear_curve_invalid_num_steps(sample_mtu):
    """Raise for num_steps < 1."""
    with pytest.raises(ValueError, match="num_steps must be at least 1"):
        linear_curve(
            Decimal("10"),
            Decimal("50"),
            Decimal("100"),
            0,
            CurveType.SUPPLY,
            sample_mtu,
        )


# ---------------------------------------------------------------------------
# Transformation tests
# ---------------------------------------------------------------------------


def test_filter_zero_volume(sample_mtu):
    """Remove zero-volume steps."""
    df = pd.DataFrame({"price": [10, 20, 30, 40], "volume": [100, 0, 200, 0]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    filtered = filter_zero_volume(curve)

    assert len(filtered.steps) == 2
    assert filtered.total_volume == Decimal("300")
    assert filtered.steps[0].volume == Decimal("100")
    assert filtered.steps[1].volume == Decimal("200")


def test_filter_zero_volume_empty(sample_mtu):
    """Handle empty input."""
    curve = empty_curve(CurveType.SUPPLY, sample_mtu)
    filtered = filter_zero_volume(curve)

    assert len(filtered.steps) == 0


def test_scale_curve(sample_mtu):
    """Multiply volumes by factor."""
    df = pd.DataFrame({"price": [10, 20], "volume": [100, 200]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    scaled = scale_curve(curve, Decimal("2"))

    assert scaled.steps[0].volume == Decimal("200")
    assert scaled.steps[1].volume == Decimal("400")
    assert scaled.total_volume == Decimal("600")


def test_scale_curve_negative_factor(sample_mtu):
    """Raise ValueError for negative factor."""
    curve = empty_curve(CurveType.SUPPLY, sample_mtu)

    with pytest.raises(ValueError, match="must be non-negative"):
        scale_curve(curve, Decimal("-1"))


def test_clip_curve_price_bounds(sample_mtu):
    """Filter by min/max price."""
    df = pd.DataFrame({"price": [10, 20, 30, 40, 50], "volume": [100, 100, 100, 100, 100]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    clipped = clip_curve(curve, min_price=Decimal("20"), max_price=Decimal("40"))

    assert len(clipped.steps) == 3
    assert clipped.steps[0].price == Decimal("20")
    assert clipped.steps[-1].price == Decimal("40")


def test_clip_curve_max_volume(sample_mtu):
    """Truncate total volume."""
    df = pd.DataFrame({"price": [10, 20, 30], "volume": [100, 100, 100]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    clipped = clip_curve(curve, max_volume=Decimal("250"))

    assert clipped.total_volume == Decimal("250")
    assert len(clipped.steps) == 3
    # First two steps are full, third is partial
    assert clipped.steps[0].volume == Decimal("100")
    assert clipped.steps[1].volume == Decimal("100")
    assert clipped.steps[2].volume == Decimal("50")


def test_clip_curve_max_volume_exact(sample_mtu):
    """Max volume exactly matches step boundary."""
    df = pd.DataFrame({"price": [10, 20, 30], "volume": [100, 100, 100]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    clipped = clip_curve(curve, max_volume=Decimal("200"))

    assert clipped.total_volume == Decimal("200")
    assert len(clipped.steps) == 2


def test_aggregate_by_price(sample_mtu):
    """Consolidate duplicate prices."""
    df = pd.DataFrame({"price": [10, 20, 10, 20, 10], "volume": [100, 200, 50, 100, 25]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    aggregated = aggregate_by_price(curve)

    assert len(aggregated.steps) == 2
    # Price 10: 100 + 50 + 25 = 175
    # Price 20: 200 + 100 = 300
    assert aggregated.steps[0].price == Decimal("10")
    assert aggregated.steps[0].volume == Decimal("175")
    assert aggregated.steps[1].price == Decimal("20")
    assert aggregated.steps[1].volume == Decimal("300")


def test_aggregate_by_price_empty(sample_mtu):
    """Handle empty curve."""
    curve = empty_curve(CurveType.SUPPLY, sample_mtu)
    aggregated = aggregate_by_price(curve)

    assert len(aggregated.steps) == 0


# ---------------------------------------------------------------------------
# Aggregation tests
# ---------------------------------------------------------------------------


def test_merge_curves_sum(sample_mtu):
    """Combine curves with volume summation."""
    df1 = pd.DataFrame({"price": [10, 20], "volume": [100, 200]})
    df2 = pd.DataFrame({"price": [10, 30], "volume": [50, 150]})

    curve1 = from_dataframe(df1, CurveType.SUPPLY, sample_mtu)
    curve2 = from_dataframe(df2, CurveType.SUPPLY, sample_mtu)

    merged = merge_curves([curve1, curve2], aggregation="sum")

    assert len(merged.steps) == 3
    # Price 10: 100 + 50 = 150
    # Price 20: 200
    # Price 30: 150
    assert merged.steps[0].price == Decimal("10")
    assert merged.steps[0].volume == Decimal("150")
    assert merged.total_volume == Decimal("500")


def test_merge_curves_stack(sample_mtu):
    """Concatenate steps without aggregation."""
    df1 = pd.DataFrame({"price": [10, 20], "volume": [100, 200]})
    df2 = pd.DataFrame({"price": [10, 30], "volume": [50, 150]})

    curve1 = from_dataframe(df1, CurveType.SUPPLY, sample_mtu)
    curve2 = from_dataframe(df2, CurveType.SUPPLY, sample_mtu)

    merged = merge_curves([curve1, curve2], aggregation="stack")

    # Should have 4 steps (no aggregation)
    assert len(merged.steps) == 4
    assert merged.total_volume == Decimal("500")
    # Should be sorted
    prices = [s.price for s in merged.steps]
    assert prices == sorted(prices)


def test_merge_curves_incompatible_types(sample_mtu):
    """Raise for mixed supply/demand."""
    curve1 = empty_curve(CurveType.SUPPLY, sample_mtu)
    curve2 = empty_curve(CurveType.DEMAND, sample_mtu)

    with pytest.raises(ValueError, match="different types"):
        merge_curves([curve1, curve2])


def test_merge_curves_incompatible_mtus(sample_mtu):
    """Raise for different MTUs."""
    mtu2 = MTUInterval.from_start(
        datetime(2026, 4, 1, 14, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        MTUDuration.QUARTER_HOURLY,
    )

    curve1 = empty_curve(CurveType.SUPPLY, sample_mtu)
    curve2 = empty_curve(CurveType.SUPPLY, mtu2)

    with pytest.raises(ValueError, match="different MTUs"):
        merge_curves([curve1, curve2])


def test_merge_empty_list():
    """Handle empty curve list."""
    with pytest.raises(ValueError, match="Cannot merge empty list"):
        merge_curves([])


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


def test_to_dataframe(sample_mtu):
    """Export curve to DataFrame."""
    df_in = pd.DataFrame({"price": [10, 20, 30], "volume": [100, 200, 300]})
    curve = from_dataframe(df_in, CurveType.SUPPLY, sample_mtu)

    df_out = to_dataframe(curve)

    assert len(df_out) == 3
    assert list(df_out.columns) == ["price", "volume"]
    assert df_out["price"].tolist() == [Decimal("10"), Decimal("20"), Decimal("30")]
    assert df_out["volume"].tolist() == [Decimal("100"), Decimal("200"), Decimal("300")]


def test_to_dataframe_with_mtu(sample_mtu):
    """Include MTU columns in export."""
    curve = constant_curve(Decimal("50"), Decimal("100"), CurveType.SUPPLY, sample_mtu)

    df = to_dataframe(curve, include_mtu=True)

    assert "mtu_start" in df.columns
    assert "mtu_end" in df.columns
    assert df["mtu_start"].iloc[0] == sample_mtu.start
    assert df["mtu_end"].iloc[0] == sample_mtu.end


def test_to_dataframe_empty(sample_mtu):
    """Export empty curve."""
    curve = empty_curve(CurveType.SUPPLY, sample_mtu)

    df = to_dataframe(curve)

    assert len(df) == 0
    assert list(df.columns) == ["price", "volume"]


def test_roundtrip_dataframe(sample_mtu):
    """Round-trip through DataFrame."""
    original = linear_curve(
        Decimal("10"),
        Decimal("50"),
        Decimal("100"),
        5,
        CurveType.SUPPLY,
        sample_mtu,
    )

    df = to_dataframe(original)
    reconstructed = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    assert len(reconstructed.steps) == len(original.steps)
    assert reconstructed.total_volume == original.total_volume
    for orig_step, recon_step in zip(original.steps, reconstructed.steps, strict=False):
        assert orig_step.price == recon_step.price
        assert orig_step.volume == recon_step.volume


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------


@given(
    factor=st.decimals(
        min_value=Decimal("0.1"),
        max_value=Decimal("10"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    )
)
def test_scale_inverse_property(factor):
    """Scaling and inverse scaling preserves volume."""
    # Create MTU inline instead of using fixture
    mtu = MTUInterval.from_start(
        datetime(2026, 4, 1, 13, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        MTUDuration.QUARTER_HOURLY,
    )
    df = pd.DataFrame({"price": [10, 20], "volume": [100, 200]})
    curve = from_dataframe(df, CurveType.SUPPLY, mtu)

    scaled = scale_curve(curve, factor)
    inverse_factor = Decimal("1") / factor
    unscaled = scale_curve(scaled, inverse_factor)

    # Should be approximately equal (within rounding)
    assert abs(unscaled.total_volume - curve.total_volume) < Decimal("0.01")


@given(
    num_curves=st.integers(min_value=1, max_value=5),
    volumes=st.lists(
        st.decimals(
            min_value=Decimal("10"),
            max_value=Decimal("1000"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        ),
        min_size=1,
        max_size=10,
    ),
)
def test_merge_total_volume_property(num_curves, volumes):
    """Merged volume equals sum of input volumes."""
    # Create MTU inline instead of using fixture
    mtu = MTUInterval.from_start(
        datetime(2026, 4, 1, 13, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        MTUDuration.QUARTER_HOURLY,
    )
    curves = []
    expected_total = Decimal("0")

    for _i in range(num_curves):
        steps_data = [
            {"price": j * 10, "volume": volumes[j % len(volumes)]} for j in range(len(volumes))
        ]
        curve = from_dict_list(steps_data, CurveType.SUPPLY, mtu)
        curves.append(curve)
        expected_total += curve.total_volume

    merged = merge_curves(curves, aggregation="stack")

    assert merged.total_volume == expected_total


@given(
    max_vol=st.decimals(
        min_value=Decimal("50"),
        max_value=Decimal("500"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    )
)
def test_clip_monotonicity(max_vol):
    """Smaller max_volume produces smaller total_volume."""
    # Create MTU inline instead of using fixture
    mtu = MTUInterval.from_start(
        datetime(2026, 4, 1, 13, 0, tzinfo=ZoneInfo("Europe/Oslo")),
        MTUDuration.QUARTER_HOURLY,
    )
    df = pd.DataFrame({"price": [10, 20, 30, 40, 50], "volume": [100, 100, 100, 100, 100]})
    curve = from_dataframe(df, CurveType.SUPPLY, mtu)

    clipped = clip_curve(curve, max_volume=max_vol)

    assert clipped.total_volume <= max_vol
    assert clipped.total_volume <= curve.total_volume


def test_filter_preserves_ordering(sample_mtu):
    """Filter maintains price order."""
    df = pd.DataFrame({"price": [10, 20, 30, 40], "volume": [100, 0, 200, 0]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    filtered = filter_zero_volume(curve)

    prices = [s.price for s in filtered.steps]
    assert prices == sorted(prices)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_from_dataframe_empty(sample_mtu):
    """Empty DataFrame produces empty curve."""
    df = pd.DataFrame({"price": [], "volume": []})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 0


def test_from_dataframe_single_row(sample_mtu):
    """Single-row DataFrame."""
    df = pd.DataFrame({"price": [50], "volume": [100]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 1
    assert curve.steps[0].price == Decimal("50")
    assert curve.steps[0].volume == Decimal("100")


def test_from_dataframe_duplicate_prices(sample_mtu):
    """Multiple steps at same price."""
    df = pd.DataFrame({"price": [10, 10, 10], "volume": [100, 200, 300]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    # Should preserve all steps (aggregation is separate function)
    assert len(curve.steps) == 3
    assert curve.total_volume == Decimal("600")


def test_from_dataframe_negative_prices(sample_mtu):
    """Negative prices are valid in power markets."""
    df = pd.DataFrame({"price": [-50, -25, 0, 25, 50], "volume": [100, 100, 100, 100, 100]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    assert len(curve.steps) == 5
    assert curve.min_price == Decimal("-50")


def test_decimal_precision():
    """Float conversion handles binary precision issues."""
    # Classic float precision problem: 0.1 + 0.2 != 0.3
    from nexa_bidkit.curves import _to_decimal

    result = _to_decimal(0.1) + _to_decimal(0.2)
    assert result == Decimal("0.3")


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


def test_validate_dataframe_schema_valid():
    """Valid DataFrame passes validation."""
    df = pd.DataFrame({"price": [10, 20], "volume": [100, 200]})

    # Should not raise
    validate_dataframe_schema(df, allow_float=True)


def test_validate_dataframe_schema_missing_column():
    """Raise for missing columns."""
    df = pd.DataFrame({"price": [10, 20]})

    with pytest.raises(ValueError, match="missing required column: volume"):
        validate_dataframe_schema(df)


def test_validate_dataframe_schema_custom_columns():
    """Validate with custom column names."""
    df = pd.DataFrame({"p": [10, 20], "v": [100, 200]})

    # Should not raise
    validate_dataframe_schema(df, price_col="p", volume_col="v", allow_float=True)


def test_get_curve_summary(sample_mtu):
    """Verify summary statistics."""
    df = pd.DataFrame({"price": [10, 20, 30], "volume": [100, 200, 300]})
    curve = from_dataframe(df, CurveType.SUPPLY, sample_mtu)

    summary = get_curve_summary(curve)

    assert summary["num_steps"] == 3
    assert summary["total_volume"] == Decimal("600")
    assert summary["min_price"] == Decimal("10")
    assert summary["max_price"] == Decimal("30")
    assert summary["curve_type"] == "SUPPLY"
    # Volume-weighted avg: (10*100 + 20*200 + 30*300) / 600 = 23.333...
    assert summary["avg_price"] is not None
    assert abs(summary["avg_price"] - Decimal("23.33")) < Decimal("0.01")


def test_get_curve_summary_empty(sample_mtu):
    """Summary for empty curve."""
    curve = empty_curve(CurveType.SUPPLY, sample_mtu)

    summary = get_curve_summary(curve)

    assert summary["num_steps"] == 0
    assert summary["total_volume"] == Decimal("0")
    assert summary["min_price"] is None
    assert summary["max_price"] is None
    assert summary["avg_price"] is None
