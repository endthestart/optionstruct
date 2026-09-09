"""Explicit fractional volatility and finite pricing boundaries."""

from dataclasses import replace
from decimal import Decimal as D
from itertools import pairwise

import pytest

from optionstruct import InvalidPricingInputsError, OptionType, PricingInputs, bs_price, greeks


def inputs(**changes):
    base = PricingInputs(OptionType.CALL, D('100'), D('100'), D('0.1'), D('1'),
                         D('0'), D('0'))
    return replace(base, **changes)


def test_fractional_volatility_is_continuous_above_one():
    prices = [bs_price(inputs(volatility=D(vol))) for vol in ('0.99', '1', '1.01', '1.2')]
    assert all(left < right for left, right in pairwise(prices))
    assert abs(prices[1] - D('12.56329388371082')) < D('0.00000001')


@pytest.mark.parametrize('field', ['spot', 'strike', 'time_to_expiration_years',
                                 'volatility', 'risk_free_rate', 'dividend_yield'])
@pytest.mark.parametrize('value', ['NaN', 'sNaN', 'Infinity', '-Infinity', '1e10000'])
def test_invalid_values_raise_a_typed_error(field, value):
    with pytest.raises(InvalidPricingInputsError):
        bs_price(inputs(**{field: D(value)}))
    with pytest.raises(InvalidPricingInputsError):
        greeks(inputs(**{field: D(value)}))


def test_greek_units_match_finite_differences_at_high_volatility():
    base = inputs(volatility=D('1.2'), risk_free_rate=D('0.04'), dividend_yield=D('0.01'))
    g = greeks(base)
    step = D('0.001')
    up, down = (bs_price(replace(base, spot=base.spot + step)),
                bs_price(replace(base, spot=base.spot - step)))
    assert abs(g.delta - (up - down) / (2 * step)) < D('0.000001')
    assert abs(g.gamma - (up - 2 * bs_price(base) + down) / step**2) < D('0.000001')
    up = bs_price(replace(base, volatility=base.volatility + step))
    down = bs_price(replace(base, volatility=base.volatility - step))
    assert abs(g.vega - (up - down) / (2 * step * 100)) < D('0.000001')
    time_step = D('0.00001')
    older = bs_price(replace(base, time_to_expiration_years=base.time_to_expiration_years - time_step))
    younger = bs_price(replace(base, time_to_expiration_years=base.time_to_expiration_years + time_step))
    assert abs(g.theta - (older - younger) / (2 * time_step * 365)) < D('0.000001')


def test_unrepresentable_intermediate_result_is_typed():
    with pytest.raises(InvalidPricingInputsError):
        greeks(inputs(spot=D('1e-300'), strike=D('1e-300'), time_to_expiration_years=D('1e-300')))
