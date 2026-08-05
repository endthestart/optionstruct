"""Exact expiration-payoff math for a set of same-expiration legs.

The profit/loss of a European-style structure *at expiration* is a continuous,
piecewise-linear function of the settlement price S, with kinks only at the leg
strikes. That single fact drives everything here, exactly (no sampling grid):

- Extrema (max profit / max loss) of a piecewise-linear function occur at a
  vertex or at a domain edge. The vertices are the strikes; the low edge is
  S = 0 (an evaluable point, puts are most valuable there, calls worthless);
  the high edge is S -> +inf, where only calls still have slope. So we evaluate
  P&L at S = 0 and every strike, then read the slope beyond the highest strike
  to decide whether profit or loss runs to infinity.
- Breakevens are the zero-crossings of that same curve, found by linear
  interpolation between adjacent vertices (plus the unbounded tail). For a plain
  2-leg vertical this reduces to the familiar "short strike -/+ credit per
  share"; the general form is needed for multi-breakeven shapes (condors) and
  ratios. Cost is O(legs^2) with legs <= ~6, i.e. negligible, and it needs no
  per-strategy special cases.

Sign conventions (kept deliberately explicit):
- *Net premium*: a SHORT leg collects premium (cash in, +), a LONG leg pays it
  (cash out, -). Credit is positive, debit negative.
- *Settlement* at expiration: a LONG holder receives the option's intrinsic
  value (+), a SHORT holder owes it (-). This is ``LegSide.sign``.

Everything is in real dollars: per-share figures are multiplied by each leg's
contract multiplier and quantity. All functions assume a single expiration;
callers spanning expirations must guard first (``Structure`` raises
``CalendarNotSupportedError``).
"""

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from optionstruct.errors import MissingPremiumError
from optionstruct.legs import Leg
from optionstruct.types import OptionType

_ZERO: Final = Decimal(0)


class UnboundedRisk:
    """Sentinel for a risk figure that runs to infinity (naked/ratio legs).

    Truthy, and prints as ``UNBOUNDED``. Compared by identity via the module
    singleton ``UNBOUNDED``; ``max_loss``/``max_profit`` return either a
    ``Decimal`` or this sentinel, never a fake large number.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return 'UNBOUNDED'


UNBOUNDED: Final = UnboundedRisk()

RiskAmount = Decimal | UnboundedRisk


def premium_for(symbol: str, premiums: Mapping[str, Decimal | str | int]) -> Decimal:
    """Look up a leg's per-share premium, rejecting missing/non-positive data.

    This is *data* validation (a real option quote is positive), not a strategy
    judgment, hence it lives with the math and raises a pricing error.
    """
    if symbol not in premiums or premiums[symbol] is None:
        raise MissingPremiumError(f'missing premium for {symbol}')
    premium = Decimal(str(premiums[symbol]))
    if premium <= 0:
        raise MissingPremiumError(f'non-positive premium for {symbol}')
    return premium


def net_premium(legs: Sequence[Leg], premiums: Mapping[str, Decimal | str | int]) -> Decimal:
    """Net cash to open, in dollars (credit positive, debit negative).

    Short legs collect premium, long legs pay it, the *opposite* of the
    ownership sign, so the cash sign is ``-leg.side.sign``.
    """
    total = _ZERO
    for leg in legs:
        premium = premium_for(leg.contract.symbol, premiums)
        cash_sign = -leg.side.sign  # SHORT collects (+), LONG pays (-)
        total += cash_sign * premium * leg.contract.multiplier * leg.quantity
    return total


def _settlement_at(legs: Sequence[Leg], underlying_price: Decimal) -> Decimal:
    """Dollar settlement value of the legs if the underlying settles at S."""
    total = _ZERO
    for leg in legs:
        intrinsic = leg.contract.intrinsic_at(underlying_price)
        total += leg.side.sign * intrinsic * leg.contract.multiplier * leg.quantity
    return total


def pnl_at(
    legs: Sequence[Leg],
    premiums: Mapping[str, Decimal | str | int],
    underlying_price: Decimal | str | int,
) -> Decimal:
    """Total profit/loss in dollars if the underlying settles at a given price."""
    s = Decimal(str(underlying_price))
    return net_premium(legs, premiums) + _settlement_at(legs, s)


def _high_side_slope(legs: Sequence[Leg]) -> int:
    """d(P&L)/dS in the region above the highest strike (S -> +inf).

    Only calls contribute there (puts are worthless above their strike). A
    positive slope means profit -> +inf; negative means loss -> -inf.
    """
    slope = 0
    for leg in legs:
        if leg.contract.option_type == OptionType.CALL:
            slope += leg.side.sign * leg.contract.multiplier * leg.quantity
    return slope


@dataclass(frozen=True, slots=True)
class RiskProfile:
    """The expiration risk picture for a structure at a given set of premiums."""

    net_premium: Decimal          # cash to open, credit positive
    max_profit: RiskAmount        # positive dollars, or UNBOUNDED
    max_loss: RiskAmount          # positive dollars, or UNBOUNDED
    breakevens: tuple[Decimal, ...]

    @property
    def is_defined_risk(self) -> bool:
        return self.max_loss is not UNBOUNDED


def risk_profile(
    legs: Sequence[Leg],
    premiums: Mapping[str, Decimal | str | int],
) -> RiskProfile:
    """Compute net premium, max profit, max loss, and breakevens, exactly."""
    net = net_premium(legs, premiums)

    # Finite vertices: S = 0 and every distinct strike. P&L is linear between
    # them, so extrema over [0, max_strike] live at one of these points.
    strikes = sorted({leg.contract.strike for leg in legs})
    vertices = [_ZERO, *strikes] if strikes and strikes[0] != _ZERO else list(strikes)
    if not vertices:  # defensive: no legs
        return RiskProfile(net, max(net, _ZERO), max(-net, _ZERO), ())

    pnls = [(v, net + _settlement_at(legs, v)) for v in vertices]
    best_finite = max(p for _, p in pnls)
    worst_finite = min(p for _, p in pnls)

    slope = _high_side_slope(legs)
    max_profit: RiskAmount = UNBOUNDED if slope > 0 else max(best_finite, _ZERO)
    max_loss: RiskAmount = UNBOUNDED if slope < 0 else max(-worst_finite, _ZERO)

    breakevens = _breakevens(pnls, slope)
    return RiskProfile(net, max_profit, max_loss, breakevens)


def _breakevens(pnls: Sequence[tuple[Decimal, Decimal]], high_slope: int) -> tuple[Decimal, ...]:
    """Zero-crossings of the piecewise-linear P&L curve, sorted ascending."""
    crossings: list[Decimal] = []
    for (s0, p0), (s1, p1) in itertools.pairwise(pnls):
        if p0 == _ZERO:
            crossings.append(s0)
        elif (p0 < _ZERO < p1) or (p0 > _ZERO > p1):
            crossings.append(s0 + (s1 - s0) * (-p0) / (p1 - p0))
    # Last finite vertex sitting exactly on zero.
    s_last, p_last = pnls[-1]
    if p_last == _ZERO:
        crossings.append(s_last)
    # Unbounded tail beyond the highest strike can cross zero once more.
    elif high_slope != 0:
        s_cross = s_last - p_last / Decimal(high_slope)
        if s_cross > s_last:
            crossings.append(s_cross)
    return tuple(sorted(set(crossings)))
