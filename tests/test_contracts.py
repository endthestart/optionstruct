from datetime import date
from decimal import Decimal

import pytest

from optionstruct import (
    DEFAULT_MULTIPLIER,
    OptionContract,
    OptionType,
    StructureError,
    build_occ_symbol,
)


def test_occ_symbol_and_contract_normalization():
    # OCC format plus case and strike normalization, in one pass.
    symbol = build_occ_symbol('qqq', date(2026, 6, 19), 'put', Decimal('375'))
    assert symbol == 'QQQ   260619P00375000'

    contract = OptionContract(
        underlying='qqq', option_type='put', strike='375.00', expiration=date(2026, 6, 19)
    )
    assert contract.underlying == 'QQQ'
    assert contract.option_type == OptionType.PUT
    assert contract.strike == Decimal('375.00')
    assert contract.symbol == symbol
    assert contract.multiplier == DEFAULT_MULTIPLIER == 100


def test_multiplier_defaults_and_validation():
    exp = date(2026, 6, 19)
    assert OptionContract('XSP', 'put', '740', exp).multiplier == 100
    assert OptionContract('SPX', 'call', '5000', exp, multiplier=100).multiplier == 100
    with pytest.raises(StructureError):
        OptionContract('XSP', 'put', '740', exp, multiplier=0)


def test_non_positive_strike_rejected():
    with pytest.raises(StructureError):
        OptionContract('XSP', 'put', '0', date(2026, 6, 19))
    with pytest.raises(StructureError):
        build_occ_symbol('XSP', date(2026, 6, 19), 'put', Decimal('-1'))


def test_intrinsic_at():
    exp = date(2026, 6, 19)
    put = OptionContract('XSP', 'put', '740', exp)
    call = OptionContract('XSP', 'call', '740', exp)
    assert put.intrinsic_at(Decimal('730')) == Decimal('10')
    assert put.intrinsic_at(Decimal('750')) == Decimal('0')
    assert call.intrinsic_at(Decimal('750')) == Decimal('10')
    assert call.intrinsic_at(Decimal('730')) == Decimal('0')
