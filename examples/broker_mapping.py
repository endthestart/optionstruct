"""Example: map a Structure to broker order legs, with no broker SDK.

optionstruct is deliberately broker-free. A real adapter (for instance
a broker adapter) performs exactly this shape of mapping and
then hands the results to its broker SDK. This file shows the pure part so the
mapping is legible without any dependency.

Run: ``python broker_mapping.py``
"""

from datetime import date
from decimal import Decimal

from optionstruct import Leg, LegSide, OptionContract, OptionType, Structure

# Opening actions per leg side. A broker adapter maps these to its own action
# type (e.g. an OrderAction.SELL_TO_OPEN enum); here they are plain strings.
OPEN_ACTION = {LegSide.SHORT: 'SELL_TO_OPEN', LegSide.LONG: 'BUY_TO_OPEN'}


def opening_legs(structure: Structure, contracts: int = 1) -> list[dict]:
    """The per-leg order instructions a broker adapter would submit to open."""
    return [
        {
            'symbol': leg.contract.symbol,          # OCC symbol, broker-agnostic
            'action': OPEN_ACTION[leg.side],
            'quantity': leg.quantity * contracts,
        }
        for leg in structure.legs
    ]


if __name__ == '__main__':
    exp = date(2026, 8, 21)
    spread = Structure.vertical(
        Leg.short(OptionContract('XSP', OptionType.PUT, '740', exp)),
        Leg.long(OptionContract('XSP', OptionType.PUT, '735', exp)),
    )

    premiums = {
        spread.legs[0].contract.symbol: Decimal('3.00'),
        spread.legs[1].contract.symbol: Decimal('1.50'),
    }
    risk = spread.risk(premiums)
    print(f'{spread.kind} on {spread.underlying}: '
          f'credit ${risk.net_premium}, max loss ${risk.max_loss}, '
          f'breakeven {risk.breakevens[0]}')
    print('Opening legs a broker adapter would submit:')
    for order_leg in opening_legs(spread, contracts=1):
        print('  ', order_leg)
