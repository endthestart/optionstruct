from datetime import date
from decimal import Decimal

import pytest

from optionstruct import (
    UNBOUNDED,
    Leg,
    MissingPremiumError,
    OptionContract,
    Structure,
    StructureKind,
)

EXP = date(2026, 6, 19)


def _put(strike):
    return OptionContract('XSP', 'put', strike, EXP)


def _call(strike):
    return OptionContract('XSP', 'call', strike, EXP)


def test_short_put_vertical_dollar_math_matches_v2_scaled_by_multiplier():
    # The canonical case (QQQ 375/370, credit 1.05, per-share max loss 3.95),
    # now in real dollars: * 100 multiplier.
    short = Leg.short(OptionContract('QQQ', 'put', '375', EXP))
    long_ = Leg.long(OptionContract('QQQ', 'put', '370', EXP))
    spread = Structure.vertical(short, long_)
    premiums = {short.contract.symbol: Decimal('1.50'), long_.contract.symbol: Decimal('0.45')}

    r = spread.risk(premiums)
    assert r.net_premium == Decimal('105.00')     # 1.05 credit * 100
    assert r.max_loss == Decimal('395.00')         # 3.95 * 100
    assert r.max_profit == Decimal('105.00')
    assert r.breakevens == (Decimal('373.95'),)    # 375 - 1.05
    assert r.is_defined_risk
    assert spread.strike_span == Decimal('5')
    assert spread.kind == StructureKind.VERTICAL


def test_breakeven_matches_simple_vertical_formula():
    # Owner's worked example: sell 700 put / buy 695 put for $1.70 credit,
    # risking $3.30. Breakeven is 700 - 1.70 = 698.30 (short strike - credit).
    short = Leg.short(_put('700'))
    long_ = Leg.long(_put('695'))
    spread = Structure.vertical(short, long_)
    premiums = {short.contract.symbol: Decimal('2.00'), long_.contract.symbol: Decimal('0.30')}

    r = spread.risk(premiums)
    assert r.net_premium == Decimal('170.00')       # 1.70 credit * 100
    assert r.max_loss == Decimal('330.00')          # (5 - 1.70) * 100
    assert r.breakevens == (Decimal('698.30'),)     # 700 - 1.70


def test_short_call_vertical_is_a_credit_spread_too():
    short = Leg.short(_call('745'))
    long_ = Leg.long(_call('750'))
    spread = Structure.vertical(short, long_)
    premiums = {short.contract.symbol: Decimal('3.00'), long_.contract.symbol: Decimal('1.50')}

    r = spread.risk(premiums)
    assert r.net_premium == Decimal('150.00')
    assert r.max_profit == Decimal('150.00')
    assert r.max_loss == Decimal('350.00')          # (5 - 1.50) * 100
    assert r.breakevens == (Decimal('746.5'),)      # 745 + 1.50


def test_iron_condor_max_loss_is_one_side_not_the_sum():
    sp = Leg.short(_put('730'))
    lp = Leg.long(_put('725'))
    sc = Leg.short(_call('770'))
    lc = Leg.long(_call('775'))
    ic = Structure.iron_condor(sp, lp, sc, lc)
    premiums = {
        sp.contract.symbol: Decimal('2.00'),
        lp.contract.symbol: Decimal('1.00'),
        sc.contract.symbol: Decimal('2.00'),
        lc.contract.symbol: Decimal('1.00'),
    }
    r = ic.risk(premiums)
    assert ic.kind == StructureKind.IRON_CONDOR
    assert r.net_premium == Decimal('200.00')       # 1.00 + 1.00 credit, * 100
    assert r.max_profit == Decimal('200.00')
    assert r.max_loss == Decimal('300.00')          # (5 - 2.00) * 100, NOT 600
    assert r.breakevens == (Decimal('728'), Decimal('772'))


def test_debit_spread_is_built_and_priced_permissively():
    # Same strikes, reversed sides -> a long put debit spread. The core does
    # not refuse it; net premium is negative (a debit).
    long_ = Leg.long(OptionContract('QQQ', 'put', '375', EXP))
    short = Leg.short(OptionContract('QQQ', 'put', '370', EXP))
    spread = Structure.vertical(short, long_)
    premiums = {long_.contract.symbol: Decimal('1.50'), short.contract.symbol: Decimal('0.45')}

    r = spread.risk(premiums)
    assert r.net_premium == Decimal('-105.00')      # debit paid
    assert r.max_loss == Decimal('105.00')          # can only lose the debit
    assert r.max_profit == Decimal('395.00')        # (5 - 1.05) * 100
    assert r.breakevens == (Decimal('373.95'),)


def test_naked_short_call_has_unbounded_loss():
    short = Leg.short(_call('745'))
    naked = Structure((short,))
    premiums = {short.contract.symbol: Decimal('3.00')}

    r = naked.risk(premiums)
    assert r.max_loss is UNBOUNDED
    assert not r.is_defined_risk
    assert r.max_profit == Decimal('300.00')        # keep the premium at best
    assert r.breakevens == (Decimal('748'),)        # 745 + 3.00


def test_call_ratio_spread_unbounded_and_classified():
    short = Leg.short(_call('745'), quantity=2)
    long_ = Leg.long(_call('750'), quantity=1)
    ratio = Structure((short, long_))
    premiums = {short.contract.symbol: Decimal('3.00'), long_.contract.symbol: Decimal('1.50')}

    r = ratio.risk(premiums)
    assert ratio.kind == StructureKind.RATIO
    assert r.max_loss is UNBOUNDED                   # net short one extra call above


def test_missing_premium_raises_instead_of_defaulting_to_zero():
    short = Leg.short(_put('740'))
    long_ = Leg.long(_put('735'))
    spread = Structure.vertical(short, long_)
    with pytest.raises(MissingPremiumError):
        spread.risk({short.contract.symbol: Decimal('2.00')})  # long premium missing


def test_non_positive_premium_rejected():
    short = Leg.short(_put('740'))
    long_ = Leg.long(_put('735'))
    spread = Structure.vertical(short, long_)
    with pytest.raises(MissingPremiumError):
        spread.risk({short.contract.symbol: Decimal('2.00'), long_.contract.symbol: Decimal('0')})
