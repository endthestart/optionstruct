# optionstruct

Dependency-free, broker-agnostic modeling of multi-leg options structures in
pure Python. Build a structure from legs, then ask it for exact
expiration-payoff risk figures in real dollars: max loss, max profit,
breakevens, defined-risk margin.

- No dependencies. Stdlib + `Decimal` only. No pydantic, no Django, no
  broker SDK, no network or disk I/O. Adapters that talk to a broker live in
  optional extras and are never imported by the core.
- Exact, not sampled. Expiration P&L is piecewise-linear with kinks only at
  strikes, so max/min and breakevens are computed at the vertices, no grids,
  no approximation. Unbounded-risk structures (naked/ratio legs) report
  `UNBOUNDED` rather than a fake large number.
- Construct, then validate. The core builds any structure without judgment
  (verticals, condors, ratios, debit or credit). Strategy checks such as "is this
  a short-put credit spread I'd actually trade?" are opt-in validators you call
  when you want them.

```python
from datetime import date
from decimal import Decimal
from optionstruct import OptionContract, Leg, Structure, OptionType

exp = date(2026, 8, 21)
short = Leg.short(OptionContract("XSP", OptionType.PUT, "740", exp))
long_ = Leg.long(OptionContract("XSP", OptionType.PUT, "735", exp))
spread = Structure.vertical(short, long_)

premiums = {
    short.contract.symbol: Decimal("3.00"),
    long_.contract.symbol: Decimal("1.50"),
}
r = spread.risk(premiums)
r.net_premium   # Decimal('150.00'), the credit collected, in dollars
r.max_loss      # Decimal('350.00')
r.max_profit    # Decimal('150.00')
r.breakevens    # (Decimal('738.5'),)
```

## Model

| Piece | What it is |
|---|---|
| `OptionContract` | underlying, type, strike, expiration, multiplier (default 100), OCC symbol |
| `Leg` | a contract + side (long/short) + quantity |
| `Structure` | N legs on one underlying + an inferred/declared `StructureKind` |
| `RiskProfile` | `net_premium`, `max_profit`, `max_loss`, `breakevens` (from `structure.risk(premiums)`) |
| `validate_*` | opt-in strategy validators, raise `ValidationError` |
| `is_even_strike` / `is_odd_strike` | strike-parity predicates for leg-netting-safe strike selection |
| `combined_margin` | netted margin across structures on one underlying+expiration |
| `PricingInputs` / `greeks` | pure Black-Scholes `delta`/`gamma`/`theta`/`vega` for one option |
| `net_greeks` | net greeks across legs (greek × multiplier × signed quantity) |
| `round_to_tick` / `opening_limit_credit` | limit-price math on an arbitrary tick grid |

Premiums are supplied per-share, keyed by contract symbol; the package never
fetches prices. Dollar figures apply each contract's multiplier and quantity.

## Greeks

`optionstruct.pricing` provides pure Black-Scholes greeks (`bs_delta`,
`bs_gamma`, `bs_theta`, `bs_vega`, or `greeks()` for all four) from a
`PricingInputs`. Units: delta/gamma per $1 underlying, vega per 1 percentage
point of vol, theta per calendar day. Rates/yield default to 0. This is for
offline and fallback use; live systems typically read greeks from a data feed.

`net_greeks` aggregates a book: it takes `(Leg, Greeks)` pairs and sums each
greek as `greek × multiplier × signed_quantity`, so shorts subtract and the
totals are share-equivalent. It does not care whether the greeks were streamed
from a feed or computed here, so a live system can use it with its own values.

## Order-limit pricing

`round_to_tick(value, tick, rounding)` rounds to any price grid (penny, nickel,
…). `opening_limit_credit(mid, natural, entry_offset=...)` prices a credit
structure's opening order: it shaves the demanded credit from the mid toward the
natural (immediate-fill) credit by an offset, floors that offset at natural so it
never gives up more than crossing the spread would, and rounds down. A fill-now
sell must never round to demand more than intended. The offset value itself is
policy and belongs to the caller.

## Scope

Same-expiration structures are fully supported. Calendars and diagonals (legs at
different expirations) can be built, but the risk math raises
`CalendarNotSupportedError`: valuing the still-open leg at the near leg's
expiration needs a pricing model, which lands in a later release.

The package is intentionally broker-free and contains no order adapter.
`examples/broker_mapping.py` shows the pure `Structure`→order-legs mapping a
broker adapter performs, without importing any SDK.

## License

MIT.
