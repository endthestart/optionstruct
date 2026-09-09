from datetime import date
from decimal import Decimal

import pytest

from optionstruct import (
    NICKEL,
    PENNY,
    Greeks,
    InvalidPricingInputsError,
    Leg,
    OptionContract,
    OptionType,
    PricingInputs,
    bs_delta,
    bs_gamma,
    bs_price,
    bs_theta,
    bs_vega,
    greeks,
    net_greeks,
    opening_limit_credit,
    round_to_tick,
)

D = Decimal


def _f(d: Decimal) -> float:
    return float(d)


def _inputs(option_type, **over):
    base = dict(
        option_type=option_type,
        spot=Decimal('100'),
        strike=Decimal('100'),
        time_to_expiration_years=Decimal('1'),
        volatility=Decimal('0.20'),
        risk_free_rate=Decimal('0.05'),
        dividend_yield=Decimal('0'),
    )
    base.update(over)
    return PricingInputs(**base)


# Textbook reference: S=K=100, T=1y, sigma=20%, r=5%, q=0
# d1=0.35, d2=0.15 -> N(d1)=0.63683, N(d2)=0.55962, phi(d1)=0.37524


def test_call_and_put_delta_match_textbook():
    assert _f(bs_delta(_inputs(OptionType.CALL))) == pytest.approx(0.63683, abs=5e-4)
    assert _f(bs_delta(_inputs(OptionType.PUT))) == pytest.approx(-0.36317, abs=5e-4)


def test_put_call_delta_parity():
    # call_delta - put_delta = e^{-qT} = 1.0 when q = 0
    call = _f(bs_delta(_inputs(OptionType.CALL)))
    put = _f(bs_delta(_inputs(OptionType.PUT)))
    assert call - put == pytest.approx(1.0, abs=1e-6)


def test_gamma_and_vega_are_side_independent_and_match_textbook():
    call_g = _f(bs_gamma(_inputs(OptionType.CALL)))
    put_g = _f(bs_gamma(_inputs(OptionType.PUT)))
    assert call_g == pytest.approx(put_g, abs=1e-9)
    assert call_g == pytest.approx(0.018762, abs=1e-5)

    call_v = _f(bs_vega(_inputs(OptionType.CALL)))
    put_v = _f(bs_vega(_inputs(OptionType.PUT)))
    assert call_v == pytest.approx(put_v, abs=1e-9)
    # per 1 percentage point of vol: raw 37.524 / 100
    assert call_v == pytest.approx(0.37524, abs=2e-4)


def test_theta_matches_textbook():
    # per calendar day: annualized / 365
    assert _f(bs_theta(_inputs(OptionType.CALL))) == pytest.approx(-6.414 / 365, abs=1e-4)
    assert _f(bs_theta(_inputs(OptionType.PUT))) == pytest.approx(-1.658 / 365, abs=1e-4)


def test_greeks_bundle_matches_individual_calls():
    inp = _inputs(OptionType.CALL)
    g = greeks(inp)
    assert g.delta == bs_delta(inp)
    assert g.gamma == bs_gamma(inp)
    assert g.theta == bs_theta(inp)
    assert g.vega == bs_vega(inp)


def test_provider_percentage_requires_explicit_conversion():
    as_frac = bs_delta(_inputs(OptionType.CALL, volatility=Decimal('0.20')))
    as_pct = bs_delta(_inputs(OptionType.CALL, volatility=Decimal('20') / Decimal('100')))
    assert as_frac == as_pct


def test_invalid_inputs_raise():
    with pytest.raises(InvalidPricingInputsError):
        bs_delta(_inputs(OptionType.CALL, volatility=Decimal('0')))
    with pytest.raises(InvalidPricingInputsError):
        bs_delta(_inputs(OptionType.CALL, time_to_expiration_years=Decimal('0')))
    with pytest.raises(InvalidPricingInputsError):
        bs_delta(_inputs(OptionType.CALL, spot=Decimal('0')))


def test_from_contract_derives_tenor_from_calendar_days():
    contract = OptionContract('XSP', 'put', '740', date(2027, 1, 1))
    inp = PricingInputs.from_contract(
        contract, spot=Decimal('745'), volatility=Decimal('0.18'), as_of=date(2026, 1, 1)
    )
    assert inp.time_to_expiration_years == Decimal('365') / Decimal('365')  # 1 year
    assert inp.strike == Decimal('740')
    assert inp.option_type == OptionType.PUT
    # a realistic OTM put delta is small and negative
    d = _f(bs_delta(inp))
    assert -1 < d < 0


def test_deep_itm_call_delta_approaches_one():
    inp = _inputs(OptionType.CALL, spot=Decimal('200'), strike=Decimal('100'))
    assert _f(bs_delta(inp)) == pytest.approx(1.0, abs=1e-3)


# ── net_greeks (book aggregation: greek x multiplier x signed quantity) ──────


def _greeks(delta, gamma='0', theta='0', vega='0') -> Greeks:
    return Greeks(delta=Decimal(delta), gamma=Decimal(gamma),
                  theta=Decimal(theta), vega=Decimal(vega))


def _put_leg(strike, side, qty=1, multiplier=100) -> Leg:
    contract = OptionContract('XSP', OptionType.PUT, Decimal(str(strike)),
                              date(2026, 8, 31), multiplier=multiplier)
    return Leg.short(contract, qty) if side == 'short' else Leg.long(contract, qty)


def test_net_greeks_signs_shorts_negative_and_scales_by_multiplier():
    # one short put at -0.40 delta: -0.40 x 100 x -1 = +40 share-equivalent delta
    total = net_greeks([(_put_leg(740, 'short'), _greeks('-0.40'))])
    assert total.delta == Decimal('40.00')


def test_net_greeks_nets_a_credit_spread():
    # Raw contract thetas are negative on both legs (options decay); the short
    # leg's sign flip is what makes a credit spread net theta-positive.
    total = net_greeks([
        (_put_leg(740, 'short'), _greeks('-0.40', theta='-0.05')),
        (_put_leg(735, 'long'), _greeks('-0.25', theta='-0.03')),
    ])
    assert total.delta == Decimal('15.00')     # (-0.40 x -100) + (-0.25 x 100)
    assert total.theta == Decimal('2.00')      # (-0.05 x -100) + (-0.03 x 100)


def test_net_greeks_scales_with_quantity_and_is_empty_at_zero_legs():
    total = net_greeks([(_put_leg(740, 'short', qty=3), _greeks('-0.40'))])
    assert total.delta == Decimal('120.00')
    empty = net_greeks([])
    assert empty.delta == empty.gamma == empty.theta == empty.vega == Decimal('0')


# ── order-limit price math ───────────────────────────────────────────────────


def test_round_to_tick_grids():
    from decimal import ROUND_DOWN

    assert round_to_tick(Decimal('1.337'), PENNY, ROUND_DOWN) == Decimal('1.33')
    assert round_to_tick(Decimal('1.337'), NICKEL, ROUND_DOWN) == Decimal('1.30')
    assert round_to_tick(Decimal('1.36'), NICKEL, ROUND_DOWN) == Decimal('1.35')


def test_offset_shaves_credit_toward_natural():
    # mid 1.34, natural 1.20, offset 0.03 -> 1.31 (still above natural)
    limit = opening_limit_credit(Decimal('1.34'), Decimal('1.20'), entry_offset=Decimal('0.03'))
    assert limit == Decimal('1.31')


def test_zero_offset_prices_at_mid():
    limit = opening_limit_credit(Decimal('1.34'), Decimal('1.20'), entry_offset=Decimal('0'))
    assert limit == Decimal('1.34')


def test_offset_is_floored_at_natural_credit():
    # A large offset can't push the demanded credit below the immediate-fill price.
    limit = opening_limit_credit(Decimal('1.34'), Decimal('1.28'), entry_offset=Decimal('0.25'))
    assert limit == Decimal('1.28')


def test_opening_credit_rounds_down_toward_fill():
    # A fill-now sell rounds DOWN, never up: 1.335 -> 1.33 (not 1.34). Demanding
    # more than the target would fight the offset.
    limit = opening_limit_credit(Decimal('1.345'), Decimal('1.00'), entry_offset=Decimal('0.01'))
    assert limit == Decimal('1.33')
    # even with no offset, the opening order is priced to fill (down, not nearest)
    assert opening_limit_credit(Decimal('1.339'), Decimal('1.00'), entry_offset=Decimal('0')) \
        == Decimal('1.33')


def test_opening_credit_on_nickel_tick():
    # 1.34 - 0.03 = 1.31 -> rounded down to a 5-cent grid = 1.30
    limit = opening_limit_credit(Decimal('1.34'), Decimal('1.00'),
                                 entry_offset=Decimal('0.03'), tick=NICKEL)
    assert limit == Decimal('1.30')


def test_tick_rounding_can_land_below_the_natural_floor():
    """Documents the one place the natural-credit floor does not survive: the floor
    bounds the *offset*, and the tick rounding is applied afterwards. Off-grid
    naturals therefore round down past themselves, safe (a lower ask fills sooner)
    but worth pinning so nobody 'fixes' it into rounding up."""
    limit = opening_limit_credit(Decimal('1.34'), Decimal('1.28'),
                                 entry_offset=Decimal('0.25'), tick=NICKEL)
    assert limit == Decimal('1.25')
    assert limit < Decimal('1.28')


# ── bs_price ─────────────────────────────────────────────────────────────────


def _bs(option_type, *, s='100', k='100', t='1', vol='0.20', r='0', q='0'):
    return PricingInputs(
        option_type=option_type, spot=D(s), strike=D(k),
        time_to_expiration_years=D(t), volatility=D(vol),
        risk_free_rate=D(r), dividend_yield=D(q))


def test_bs_price_matches_a_published_reference():
    """S=100, K=100, T=1, sigma=20%, r=5%, q=0 — the standard textbook case.
    Call 10.4506, put 5.5735 (Hull, Options Futures and Other Derivatives)."""
    call = bs_price(_bs(OptionType.CALL, r='0.05'))
    put = bs_price(_bs(OptionType.PUT, r='0.05'))
    assert abs(float(call) - 10.4506) < 0.001
    assert abs(float(put) - 5.5735) < 0.001


def test_put_call_parity_holds():
    """C - P = S e^{-qT} - K e^{-rT}. Parity is arbitrage, not a model choice, so
    a violation means the discounting is wrong rather than the volatility."""
    import math
    c = float(bs_price(_bs(OptionType.CALL, s='105', k='100', r='0.04', q='0.02')))
    p = float(bs_price(_bs(OptionType.PUT, s='105', k='100', r='0.04', q='0.02')))
    expected = 105 * math.exp(-0.02) - 100 * math.exp(-0.04)
    assert abs((c - p) - expected) < 1e-9


def test_price_is_never_below_intrinsic():
    """A deep ITM option cannot be worth less than exercising it."""
    deep = bs_price(_bs(OptionType.CALL, s='150', k='100', t='0.5', vol='0.15'))
    assert float(deep) >= 50 - 1e-9


def test_price_rises_with_volatility_for_both_rights():
    for right in (OptionType.CALL, OptionType.PUT):
        low = bs_price(_bs(right, vol='0.10'))
        high = bs_price(_bs(right, vol='0.40'))
        assert high > low, f'{right} must be worth more at higher vol'


def test_price_refuses_a_non_positive_tenor_rather_than_guessing():
    """At expiry there is no theoretical price, only intrinsic — which is what
    `payoff` is for. Returning something here would invent a number."""
    import pytest
    with pytest.raises(InvalidPricingInputsError):
        bs_price(_bs(OptionType.CALL, t='0'))
