"""Opt-in strategy validators.

The core builds any structure without judgment (separation of responsibility:
construct the structure, then validate it). These functions answer strategy
questions, "is this actually a short put credit spread I'd trade?", and raise
``ValidationError`` when the answer is no. Nothing in the core calls them; a
strategy layer calls the one it needs.

Each validator returns the structure on success so it can be used inline::

    spread = validate_credit_spread(Structure.vertical(short, long), premiums)
"""

from collections.abc import Mapping
from decimal import Decimal

from optionstruct.errors import ValidationError
from optionstruct.payoff import UNBOUNDED
from optionstruct.structure import Structure
from optionstruct.types import LegSide, OptionType


def is_even_strike(strike: Decimal) -> bool:
    """True for an even integer strike (e.g. 740). Non-integer strikes are neither.

    Strike-parity selection (shorts on one parity, longs on the other) keeps
    same-strike legs of different spreads from netting against each other at the
    broker."""
    return strike == strike.to_integral_value() and int(strike) % 2 == 0


def is_odd_strike(strike: Decimal) -> bool:
    """True for an odd integer strike (e.g. 739)."""
    return strike == strike.to_integral_value() and int(strike) % 2 == 1


def validate_vertical(structure: Structure) -> Structure:
    """A vertical: two legs, same underlying+expiration+type, opposite sides."""
    legs = structure.legs
    if len(legs) != 2:
        raise ValidationError(f'a vertical has exactly two legs, got {len(legs)}')
    if not structure.is_single_expiration:
        raise ValidationError('a vertical must share one expiration')
    if {leg.side for leg in legs} != {LegSide.SHORT, LegSide.LONG}:
        raise ValidationError('a vertical needs one short and one long leg')
    if len({leg.contract.option_type for leg in legs}) != 1:
        raise ValidationError('a vertical needs both legs the same option type')
    if len({leg.quantity for leg in legs}) != 1:
        raise ValidationError('a vertical needs equal quantities on both legs (else it is a ratio)')
    return structure


def validate_credit_spread(
    structure: Structure,
    premiums: Mapping[str, Decimal | str | int],
) -> Structure:
    """A defined-risk credit spread: a vertical that collects a net credit and
    whose credit is strictly less than its width.

    Checked only when a caller asks for it, against a structure that was built
    independently, construction stays permissive, judgment stays opt-in. Works for
    short put verticals *and* short call verticals (either is a credit spread).
    """
    validate_vertical(structure)
    net = structure.net_premium(premiums)
    if net <= 0:
        raise ValidationError(f'a credit spread must collect a positive credit, got {net}')

    short_leg = next(leg for leg in structure.legs if leg.side == LegSide.SHORT)
    long_leg = next(leg for leg in structure.legs if leg.side == LegSide.LONG)
    option_type = short_leg.contract.option_type

    # Strike ordering that makes the spread defined-risk (long strike is the
    # protective wing further from the money than the short strike).
    short_k = short_leg.contract.strike
    long_k = long_leg.contract.strike
    if option_type == OptionType.PUT and not short_k > long_k:
        raise ValidationError('short put credit spread needs short strike above long strike')
    if option_type == OptionType.CALL and not short_k < long_k:
        raise ValidationError('short call credit spread needs short strike below long strike')

    risk = structure.risk(premiums)
    if risk.max_loss is UNBOUNDED:
        raise ValidationError('a credit spread must be defined-risk')
    # width * multiplier is the theoretical ceiling; a credit >= width is
    # impossible/mispriced and would imply a risk-free structure.
    width_dollars = structure.strike_span * short_leg.contract.multiplier * short_leg.quantity
    if net >= width_dollars:
        raise ValidationError('credit must be less than the spread width')
    return structure
