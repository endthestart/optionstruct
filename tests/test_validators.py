from datetime import date
from decimal import Decimal

import pytest

from optionstruct import (
    Leg,
    OptionContract,
    Structure,
    ValidationError,
    is_even_strike,
    is_odd_strike,
    validate_credit_spread,
    validate_vertical,
)

EXP = date(2026, 6, 19)


def _put(strike):
    return OptionContract('XSP', 'put', strike, EXP)


def _call(strike):
    return OptionContract('XSP', 'call', strike, EXP)


def _premiums(spread, short_px, long_px):
    short = next(leg for leg in spread.legs if leg.side.value == 'short')
    long_ = next(leg for leg in spread.legs if leg.side.value == 'long')
    return {short.contract.symbol: Decimal(short_px), long_.contract.symbol: Decimal(long_px)}


def test_validate_vertical_accepts_a_vertical_and_returns_it():
    spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    assert validate_vertical(spread) is spread


def test_validate_vertical_rejects_non_verticals():
    with pytest.raises(ValidationError):
        validate_vertical(Structure((Leg.short(_put('740')),)))  # one leg
    with pytest.raises(ValidationError):
        # ratio: unequal quantities
        validate_vertical(Structure((Leg.short(_put('740'), quantity=2), Leg.long(_put('735')))))


def test_validate_credit_spread_accepts_put_and_call_credit_spreads():
    put_spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    assert validate_credit_spread(put_spread, _premiums(put_spread, '2.00', '0.80')) is put_spread

    call_spread = Structure.vertical(Leg.short(_call('745')), Leg.long(_call('750')))
    assert validate_credit_spread(call_spread, _premiums(call_spread, '2.00', '0.80')) is call_spread


def test_validate_credit_spread_rejects_a_debit():
    # reversed premiums -> the "short" leg is cheaper -> net debit
    spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    with pytest.raises(ValidationError):
        validate_credit_spread(spread, _premiums(spread, '0.45', '1.50'))


def test_validate_credit_spread_rejects_inverted_strikes():
    # short put strike below long put strike is not a defined-risk credit spread
    spread = Structure.vertical(Leg.short(_put('735')), Leg.long(_put('740')))
    with pytest.raises(ValidationError):
        validate_credit_spread(spread, _premiums(spread, '2.00', '0.80'))


def test_a_credit_equal_to_the_width_is_refused():
    """The boundary, not just past it. A credit *equal* to the width would imply a
    structure that cannot lose, which means the quote is wrong rather than that free
    money was found. Accepting it sizes a position against a max loss of zero."""
    # 5-wide spread; 6.00 - 1.00 = a 5.00 credit, exactly the width.
    spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    with pytest.raises(ValidationError, match='less than the spread width'):
        validate_credit_spread(spread, _premiums(spread, '6.00', '1.00'))


def test_a_credit_one_cent_under_the_width_is_allowed():
    """The other side of the same boundary, so the check above is proved to be a
    boundary and not a blanket refusal of large credits."""
    spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    assert validate_credit_spread(spread, _premiums(spread, '5.99', '1.00')) is spread


def test_a_zero_net_credit_is_refused():
    """Exactly zero is not a credit. The guard is `net <= 0`, and a spread that
    collects nothing still ties up margin."""
    spread = Structure.vertical(Leg.short(_put('740')), Leg.long(_put('735')))
    with pytest.raises(ValidationError, match='positive credit'):
        validate_credit_spread(spread, _premiums(spread, '1.25', '1.25'))


# ── strike parity (cross-spread leg-netting prevention) ──────────────────────


def test_strike_parity_predicates():
    assert is_even_strike(Decimal('740')) and not is_odd_strike(Decimal('740'))
    assert is_odd_strike(Decimal('739')) and not is_even_strike(Decimal('739'))


def test_fractional_strikes_are_neither_parity():
    # A non-integer strike can't participate in the even/odd convention at all.
    assert not is_even_strike(Decimal('740.5'))
    assert not is_odd_strike(Decimal('740.5'))


def test_integral_valued_decimals_count_by_value_not_form():
    # 740.0 and 7.40E+2 are the same number as 740; parity follows the value.
    assert is_even_strike(Decimal('740.0'))
    assert is_even_strike(Decimal('7.40E+2'))
