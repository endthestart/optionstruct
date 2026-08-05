"""Pricing math, Black-Scholes greeks, tick-grid rounding, net book greeks.

Black-Scholes greeks for a single European option, pure functions.

For live trading the broker streams greeks directly, so this module is the
*fallback* (when a feed omits a greek) and the *offline* engine used where no
feed exists (e.g. calibrating strategy logic against historical data).

Computation is done in ``float`` (the closed forms need ``exp``/``log``/``erf``)
and wrapped back to ``Decimal`` at the boundary, so callers stay in Decimal.

Units and conventions are chosen so greeks aggregate cleanly and line up with the
values brokers stream:
- Rates and yields are fractions per year (0.045 = 4.5%). Volatility likewise is
  a fraction (0.18 = 18% annualized); a value > 1 is treated as a percentage and
  divided by 100, matching how chains sometimes report IV.
- ``delta`` is per $1 of underlying. ``gamma`` is per $1 (change in delta).
- ``vega`` is per 1 percentage point of volatility (i.e. dV/dσ ÷ 100).
- ``theta`` is per calendar day (i.e. the annualized dV/dt ÷ 365, typically
  negative).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from math import erf, exp, log, pi, sqrt

from optionstruct.contracts import OptionContract
from optionstruct.errors import InvalidPricingInputsError
from optionstruct.legs import Leg
from optionstruct.types import OptionType

# Common price-increment grids. Products vary (many index options trade in
# nickels); ``round_to_tick`` handles any grid.
PENNY = Decimal('0.01')
NICKEL = Decimal('0.05')

_SQRT_2 = sqrt(2.0)
_INV_SQRT_2PI = 1.0 / sqrt(2.0 * pi)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return _INV_SQRT_2PI * exp(-0.5 * x * x)


def _normalize_volatility(volatility: Decimal) -> Decimal:
    value = Decimal(str(volatility))
    if value <= 0:
        raise InvalidPricingInputsError('volatility must be positive')
    if value > 1:  # given as a percentage (e.g. 18 meaning 18%)
        value = value / Decimal('100')
    return value


@dataclass(frozen=True, slots=True)
class PricingInputs:
    """Everything Black-Scholes needs for one option.

    ``risk_free_rate`` and ``dividend_yield`` default to 0 so a caller can get
    quick greeks without sourcing rates; supply them for accuracy.
    """

    option_type: OptionType
    spot: Decimal
    strike: Decimal
    time_to_expiration_years: Decimal
    volatility: Decimal
    risk_free_rate: Decimal = Decimal(0)
    dividend_yield: Decimal = Decimal(0)

    @classmethod
    def from_contract(
        cls,
        contract: OptionContract,
        *,
        spot: Decimal,
        volatility: Decimal,
        as_of: date,
        risk_free_rate: Decimal = Decimal(0),
        dividend_yield: Decimal = Decimal(0),
    ) -> 'PricingInputs':
        """Build inputs from an OptionContract, deriving tenor from calendar days.

        Tenor uses a 365-day year: ``(expiration - as_of).days / 365``.
        """
        days = (contract.expiration - as_of).days
        return cls(
            option_type=OptionType.normalize(contract.option_type),
            spot=Decimal(str(spot)),
            strike=Decimal(str(contract.strike)),
            time_to_expiration_years=Decimal(days) / Decimal('365'),
            volatility=Decimal(str(volatility)),
            risk_free_rate=Decimal(str(risk_free_rate)),
            dividend_yield=Decimal(str(dividend_yield)),
        )


@dataclass(frozen=True, slots=True)
class Greeks:
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal


@dataclass(frozen=True, slots=True)
class _Terms:
    """Precomputed float terms shared by the greek formulas."""

    option_type: OptionType
    s: float
    k: float
    t: float
    sigma: float
    r: float
    q: float
    d1: float
    d2: float
    disc_q: float  # e^{-qT}
    disc_r: float  # e^{-rT}
    sqrt_t: float


def _terms(inputs: PricingInputs) -> _Terms:
    s = float(Decimal(str(inputs.spot)))
    k = float(Decimal(str(inputs.strike)))
    t = float(Decimal(str(inputs.time_to_expiration_years)))
    sigma = float(_normalize_volatility(inputs.volatility))
    if s <= 0 or k <= 0 or t <= 0:
        raise InvalidPricingInputsError('spot, strike, and tenor must be positive')
    r = float(Decimal(str(inputs.risk_free_rate)))
    q = float(Decimal(str(inputs.dividend_yield)))
    sqrt_t = sqrt(t)
    d1 = (log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return _Terms(
        option_type=OptionType.normalize(inputs.option_type),
        s=s, k=k, t=t, sigma=sigma, r=r, q=q,
        d1=d1, d2=d2, disc_q=exp(-q * t), disc_r=exp(-r * t), sqrt_t=sqrt_t,
    )


def _delta(tm: _Terms) -> float:
    if tm.option_type == OptionType.PUT:
        return tm.disc_q * (_norm_cdf(tm.d1) - 1.0)
    return tm.disc_q * _norm_cdf(tm.d1)


def _gamma(tm: _Terms) -> float:
    return tm.disc_q * _norm_pdf(tm.d1) / (tm.s * tm.sigma * tm.sqrt_t)


def _vega(tm: _Terms) -> float:
    # Raw dV/dsigma, then /100 for per-1-percentage-point (see module docstring).
    raw = tm.s * tm.disc_q * _norm_pdf(tm.d1) * tm.sqrt_t
    return raw / 100.0


def _theta(tm: _Terms) -> float:
    term1 = -tm.disc_q * tm.s * _norm_pdf(tm.d1) * tm.sigma / (2.0 * tm.sqrt_t)
    if tm.option_type == OptionType.PUT:
        annual = (
            term1
            + tm.r * tm.k * tm.disc_r * _norm_cdf(-tm.d2)
            - tm.q * tm.s * tm.disc_q * _norm_cdf(-tm.d1)
        )
    else:
        annual = (
            term1
            - tm.r * tm.k * tm.disc_r * _norm_cdf(tm.d2)
            + tm.q * tm.s * tm.disc_q * _norm_cdf(tm.d1)
        )
    # Annualized dV/dt, then /365 for per-calendar-day (see module docstring).
    return annual / 365.0


def bs_delta(inputs: PricingInputs) -> Decimal:
    return Decimal(str(_delta(_terms(inputs))))


def bs_gamma(inputs: PricingInputs) -> Decimal:
    return Decimal(str(_gamma(_terms(inputs))))


def bs_vega(inputs: PricingInputs) -> Decimal:
    return Decimal(str(_vega(_terms(inputs))))


def bs_theta(inputs: PricingInputs) -> Decimal:
    return Decimal(str(_theta(_terms(inputs))))


def greeks(inputs: PricingInputs) -> Greeks:
    """All four greeks in one pass (shares the d1/d2 computation)."""
    tm = _terms(inputs)
    return Greeks(
        delta=Decimal(str(_delta(tm))),
        gamma=Decimal(str(_gamma(tm))),
        theta=Decimal(str(_theta(tm))),
        vega=Decimal(str(_vega(tm))),
    )


def net_greeks(items: Iterable[tuple[Leg, Greeks]]) -> Greeks:
    """Net greeks across legs: each greek × contract multiplier × signed quantity
    (long +, short −), so the totals are share-equivalent and aggregate the way a
    book does. The caller supplies each leg's greeks (streamed or computed)."""
    delta = gamma = theta = vega = Decimal('0')
    for leg, g in items:
        factor = Decimal(leg.contract.multiplier) * leg.signed_quantity
        delta += g.delta * factor
        gamma += g.gamma * factor
        theta += g.theta * factor
        vega += g.vega * factor
    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega)


# ── order-limit price math (tick grids) ─────────────────────────────────────────


def round_to_tick(value: Decimal, tick: Decimal, rounding: str) -> Decimal:
    """Round ``value`` to the nearest ``tick`` grid using ``rounding``.

    Works for any grid (penny, nickel, …): rounds ``value / tick`` to an integer
    number of ticks, then scales back. e.g. round_to_tick(1.337, 0.05, DOWN) =
    1.30; round_to_tick(1.337, 0.01, DOWN) = 1.33.
    """
    ticks = (value / tick).quantize(Decimal('1'), rounding=rounding)
    return ticks * tick


def opening_limit_credit(
    mid_credit: Decimal,
    natural_credit: Decimal,
    *,
    entry_offset: Decimal,
    tick: Decimal = PENNY,
) -> Decimal:
    """The opening (immediate) limit credit after applying an entry offset.

    ``mid_credit`` = short.mid - long.mid; ``natural_credit`` = short.bid -
    long.ask (the immediate-fill credit). The offset lowers the demanded credit
    toward natural and stops there, the *offset* never pushes it below.

    Rounded down to the tick: this is a fill-now sell order, so the limit is the
    *minimum* acceptable credit and must never round to demand more than the
    offset-adjusted target. Note that the rounding itself can land up to one tick
    below ``natural_credit`` when natural is not on the grid (e.g. natural 1.28 on
    a nickel tick returns 1.25). That is the safe direction, a lower ask fills
    sooner, but it means the natural floor bounds the offset, not the result.
    """
    adjusted = max(mid_credit - entry_offset, natural_credit)
    return round_to_tick(adjusted, tick, ROUND_DOWN)
