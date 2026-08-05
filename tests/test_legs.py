from datetime import date

import pytest

from optionstruct import Leg, LegSide, OptionContract, StructureError

EXP = date(2026, 6, 19)


def _contract(strike='740', option_type='put'):
    return OptionContract('XSP', option_type, strike, EXP)


def test_long_short_constructors_and_signed_quantity():
    short = Leg.short(_contract(), quantity=3)
    long_ = Leg.long(_contract('735'))
    assert short.side == LegSide.SHORT
    assert short.signed_quantity == -3
    assert long_.side == LegSide.LONG
    assert long_.quantity == 1
    assert long_.signed_quantity == 1


def test_quantity_must_be_positive():
    with pytest.raises(StructureError):
        Leg(_contract(), LegSide.SHORT, 0)
    with pytest.raises(StructureError):
        Leg(_contract(), LegSide.SHORT, -2)


def test_side_sign():
    assert LegSide.LONG.sign == 1
    assert LegSide.SHORT.sign == -1
