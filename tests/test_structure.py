from datetime import date
from decimal import Decimal

import pytest

from optionstruct import (
    CalendarNotSupportedError,
    Leg,
    OptionContract,
    Structure,
    StructureError,
    StructureKind,
    combined_margin,
)

EXP = date(2026, 6, 19)
FAR = date(2026, 7, 17)


def _put(strike, exp=EXP, underlying='XSP'):
    return OptionContract(underlying, 'put', strike, exp)


def _call(strike, exp=EXP):
    return OptionContract('XSP', 'call', strike, exp)


def test_empty_structure_rejected():
    with pytest.raises(StructureError):
        Structure(())


def test_mixed_underlyings_rejected():
    a = Leg.short(_put('740', underlying='XSP'))
    b = Leg.long(_put('735', underlying='SPX'))
    with pytest.raises(StructureError):
        Structure((a, b))


def test_kind_inference():
    """Every case goes through the bare ``Structure(...)`` constructor on purpose.

    ``Structure.vertical`` and ``Structure.iron_condor`` pass ``kind`` explicitly,
    so asserting on the ``kind`` of a structure built that way proves only that the
    constructor stored its argument. It cannot detect broken inference.
    """
    # calendar: two expirations
    cal = Structure((Leg.short(_put('740', exp=EXP)), Leg.long(_put('740', exp=FAR))))
    assert cal.kind == StructureKind.CALENDAR
    # ratio: unequal quantities
    ratio = Structure((Leg.short(_put('740'), quantity=2), Leg.long(_put('735'))))
    assert ratio.kind == StructureKind.RATIO
    # custom: a lone leg
    assert Structure((Leg.short(_put('740')),)).kind == StructureKind.CUSTOM
    # vertical: two same-type legs, opposite sides, equal quantities
    vert = Structure((Leg.short(_put('740')), Leg.long(_put('735'))))
    assert vert.kind == StructureKind.VERTICAL
    # iron condor: a short/long pair on each side, one expiration
    condor = Structure((Leg.short(_put('740')), Leg.long(_put('735')),
                        Leg.short(_call('750')), Leg.long(_call('755'))))
    assert condor.kind == StructureKind.IRON_CONDOR


def test_calendar_can_be_built_but_risk_math_refuses():
    cal = Structure((Leg.short(_put('740', exp=EXP)), Leg.long(_put('740', exp=FAR))))
    assert not cal.is_single_expiration
    assert cal.expirations == frozenset({EXP, FAR})
    premiums = {leg.contract.symbol: Decimal('2.00') for leg in cal.legs}
    with pytest.raises(CalendarNotSupportedError):
        cal.risk(premiums)
    # net premium is still valid across expirations
    assert cal.net_premium(premiums) == Decimal('0')  # short 2.00 - long 2.00, *100


def test_combined_margin_nets_put_and_call_spreads():
    # A put spread and a call spread opened separately net to max(side), not sum.
    put_spread = Structure.vertical(Leg.short(_put('730')), Leg.long(_put('725')))
    call_spread = Structure.vertical(Leg.short(_call('770')), Leg.long(_call('775')))
    premiums = {
        put_spread.legs[0].contract.symbol: Decimal('2.00'),
        put_spread.legs[1].contract.symbol: Decimal('1.00'),
        call_spread.legs[0].contract.symbol: Decimal('2.00'),
        call_spread.legs[1].contract.symbol: Decimal('1.00'),
    }
    # Each alone risks 400 (5-wide, 1.00 credit -> 400). Summed naively = 800.
    assert put_spread.max_loss(premiums) == Decimal('400.00')
    assert call_spread.max_loss(premiums) == Decimal('400.00')
    # Netted (they can't both blow out) = 300, same as the equivalent condor.
    assert combined_margin([put_spread, call_spread], premiums) == Decimal('300.00')


def test_combined_margin_refuses_cross_expiration():
    near = Structure.vertical(Leg.short(_put('730', exp=EXP)), Leg.long(_put('725', exp=EXP)))
    far = Structure.vertical(Leg.short(_call('770', exp=FAR)), Leg.long(_call('775', exp=FAR)))
    premiums = {
        near.legs[0].contract.symbol: Decimal('2.00'),
        near.legs[1].contract.symbol: Decimal('1.00'),
        far.legs[0].contract.symbol: Decimal('2.00'),
        far.legs[1].contract.symbol: Decimal('1.00'),
    }
    with pytest.raises(CalendarNotSupportedError):
        combined_margin([near, far], premiums)


# ── risk_width: the strike distance that actually bounds the loss ─────────────


def test_a_vertical_risk_width_is_its_span():
    vertical = Structure.vertical(Leg.short(_put(740)), Leg.long(_put(735)))
    assert vertical.risk_width == Decimal(5)
    assert vertical.risk_width == vertical.strike_span


def test_a_condor_risk_width_is_the_wider_wing_not_the_whole_span():
    """The reason this property exists. `strike_span` on a condor is the long call
    minus the long put, a distance no side is ever that wide. Sizing a position
    against it overstates max loss several-fold; sizing against the *narrower* wing
    understates it, which is the direction that loses money."""
    condor = Structure.iron_condor(
        Leg.short(_put(730)), Leg.long(_put(725)),      # 5 wide
        Leg.short(_call(750)), Leg.long(_call(757)),    # 7 wide
    )
    assert condor.risk_width == Decimal(7)
    assert condor.strike_span == Decimal(32)


def test_a_symmetric_condor_risk_width_is_the_shared_width():
    condor = Structure.iron_condor(
        Leg.short(_put(730)), Leg.long(_put(725)),
        Leg.short(_call(750)), Leg.long(_call(755)),
    )
    assert condor.risk_width == Decimal(5)


def test_risk_width_refuses_a_shape_it_cannot_bound():
    """A naked short has no long to measure against. Returning its strike, or zero,
    would be a number that reads as a bounded loss."""
    with pytest.raises(StructureError, match='one short and one long'):
        _ = Structure((Leg.short(_put(740)),)).risk_width


def test_risk_width_refuses_unequal_quantities():
    """A ratio's loss is not bounded by the strike distance at all."""
    ratio = Structure((Leg.short(_put(740), quantity=2), Leg.long(_put(735))))
    with pytest.raises(StructureError, match='equal quantities'):
        _ = ratio.risk_width


def test_risk_width_refuses_multiple_expirations():
    with pytest.raises(CalendarNotSupportedError):
        _ = Structure((Leg.short(_put(740)), Leg.long(_put(740, exp=FAR)))).risk_width


def test_a_condor_loses_less_than_either_spread_standing_alone():
    """Both credits are collected but only one side can be tested, so the condor's
    max loss is the wider width minus BOTH credits, strictly less than the wider
    spread alone. This is the whole capital-efficiency argument for the structure."""
    condor = Structure.iron_condor(
        Leg.short(_put(730)), Leg.long(_put(725)),
        Leg.short(_call(750)), Leg.long(_call(757)),
    )
    premiums = {
        _put(730).symbol: Decimal('2.00'), _put(725).symbol: Decimal('1.20'),
        _call(750).symbol: Decimal('1.80'), _call(757).symbol: Decimal('0.90'),
    }
    call_side = Structure.vertical(Leg.short(_call(750)), Leg.long(_call(757)))
    assert condor.max_loss(premiums) == Decimal('530.00')
    assert call_side.max_loss(premiums) == Decimal('610.00')
    assert condor.max_loss(premiums) < call_side.max_loss(premiums)
    # And nothing like the sum of the two sides, which is how a condor gets
    # margined by a system that treats it as two independent spreads.
    put_side = Structure.vertical(Leg.short(_put(730)), Leg.long(_put(725)))
    assert condor.max_loss(premiums) < put_side.max_loss(premiums) + call_side.max_loss(premiums)


# ── price effect ─────────────────────────────────────────────────────────────


def test_price_effect_classifies_a_signed_cash_flow():
    """The sign convention the whole package runs on: credit positive, debit
    negative. `PriceEffect` is exported public API and nothing else asserts it, so
    an inverted comparison here would flip credit and debit everywhere a caller
    reports them, with every risk figure still computing correctly."""
    from optionstruct import PriceEffect

    assert PriceEffect.of(Decimal('150.00')) is PriceEffect.CREDIT
    assert PriceEffect.of(Decimal('-150.00')) is PriceEffect.DEBIT
    assert PriceEffect.of(Decimal('0')) is PriceEffect.EVEN


def test_price_effect_agrees_with_a_real_spread_s_net_premium():
    """Tied to actual structure output, so the two cannot drift apart."""
    from optionstruct import PriceEffect

    credit_spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    premiums = {_put('740').symbol: Decimal('2.00'), _put('735').symbol: Decimal('0.80')}
    assert PriceEffect.of(credit_spread.net_premium(premiums)) is PriceEffect.CREDIT

    # Same legs, reversed prices: the short leg is now the cheaper one.
    debit = {_put('740').symbol: Decimal('0.80'), _put('735').symbol: Decimal('2.00')}
    assert PriceEffect.of(credit_spread.net_premium(debit)) is PriceEffect.DEBIT
