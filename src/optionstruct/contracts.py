"""Option contracts and OCC symbol construction.

The multiplier lives on the contract (default 100) so the risk math can return
real dollar amounts without any caller remembering to multiply by 100.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from optionstruct.errors import StructureError
from optionstruct.types import OptionType

# An OCC symbol encodes the strike as (strike x 1000) in 8 zero-padded digits,
# e.g. a 740 strike -> "00740000".
OCC_STRIKE_MULTIPLIER = Decimal('1000')
# A standard listed equity/index option controls 100 shares of the underlying.
DEFAULT_MULTIPLIER = 100


def build_occ_symbol(
    underlying: str,
    expiration: date,
    option_type: OptionType | str,
    strike: Decimal | str | int,
) -> str:
    """Build a standard 21-character OCC option symbol.

    Format: 6-char root (space-padded) + YYMMDD + C/P + strike*1000 as 8 digits.
    This is the exchange-standard symbol, not any broker's proprietary format.
    """
    root = underlying.upper().ljust(6)[:6]
    expiry = expiration.strftime('%y%m%d')
    type_code = OptionType.normalize(option_type).value[0]
    strike_value = Decimal(str(strike))
    if strike_value <= 0:
        raise StructureError('strike must be positive')
    strike_code = int(
        (strike_value * OCC_STRIKE_MULTIPLIER).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    )
    return f'{root}{expiry}{type_code}{strike_code:08d}'


@dataclass(frozen=True, slots=True)
class OptionContract:
    """A single option contract: what you'd quote, route, and settle.

    Frozen and self-validating. ``symbol`` is derived (OCC) when left empty, so
    after construction it is always a non-empty string (typed ``str``, not
    ``str | None``). ``multiplier`` is shares-per-contract and drives
    dollar-denominated math.
    """

    underlying: str
    option_type: OptionType | str
    strike: Decimal | str | int
    expiration: date
    multiplier: int = DEFAULT_MULTIPLIER
    symbol: str = ''

    def __post_init__(self) -> None:
        underlying = self.underlying.upper()
        if not underlying:
            raise StructureError('underlying is required')
        option_type = OptionType.normalize(self.option_type)
        strike = Decimal(str(self.strike))
        if strike <= 0:
            raise StructureError('strike must be positive')
        if self.multiplier <= 0:
            raise StructureError('multiplier must be positive')
        symbol = self.symbol or build_occ_symbol(underlying, self.expiration, option_type, strike)
        object.__setattr__(self, 'underlying', underlying)
        object.__setattr__(self, 'option_type', option_type)
        object.__setattr__(self, 'strike', strike)
        object.__setattr__(self, 'symbol', symbol)

    def intrinsic_at(self, underlying_price: Decimal) -> Decimal:
        """Per-share intrinsic value if the underlying settled at this price.

        CALL: max(S - K, 0). PUT: max(K - S, 0). Never negative.
        """
        s = Decimal(str(underlying_price))
        if self.option_type == OptionType.CALL:
            return max(s - self.strike, Decimal(0))
        return max(self.strike - s, Decimal(0))
