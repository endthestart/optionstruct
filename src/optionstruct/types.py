"""Semantic types and enums shared across the package."""

from decimal import Decimal
from enum import StrEnum
from typing import NewType

# Semantic aliases: these are documentation with teeth. A ``StrikeUSD`` is a
# Decimal, but reading ``strike: StrikeUSD`` at a call site tells you what the
# number *means* and keeps strike/premium/width from being silently swapped.
StrikeUSD = NewType('StrikeUSD', Decimal)
PremiumUSD = NewType('PremiumUSD', Decimal)
WidthUSD = NewType('WidthUSD', Decimal)
CashUSD = NewType('CashUSD', Decimal)
DeltaFraction = NewType('DeltaFraction', Decimal)
IVFraction = NewType('IVFraction', Decimal)
DTE = NewType('DTE', int)  # days to expiration
ContractQuantity = NewType('ContractQuantity', int)
Multiplier = NewType('Multiplier', int)


class OptionType(StrEnum):
    CALL = 'CALL'
    PUT = 'PUT'

    @classmethod
    def normalize(cls, value: 'str | OptionType') -> 'OptionType':
        return cls(str(value).upper())


class LegSide(StrEnum):
    LONG = 'long'
    SHORT = 'short'

    @property
    def sign(self) -> int:
        """+1 for a long leg, -1 for a short leg.

        This is the *ownership* sign: a long holder receives an option's value,
        a short holder owes it. Cash conventions that differ (a short leg
        *collects* premium at open) are applied where that cash flow is
        computed, not here.
        """
        return 1 if self is LegSide.LONG else -1


class PriceEffect(StrEnum):
    CREDIT = 'credit'
    DEBIT = 'debit'
    EVEN = 'even'

    @classmethod
    def of(cls, net_cash: Decimal) -> 'PriceEffect':
        """Classify a signed net cash flow (credit positive) as a price effect."""
        if net_cash > 0:
            return cls.CREDIT
        if net_cash < 0:
            return cls.DEBIT
        return cls.EVEN
