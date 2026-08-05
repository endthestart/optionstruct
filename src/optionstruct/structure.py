"""A generic N-leg options structure and its derived risk figures.

A ``Structure`` is an ordered set of legs on a shared underlying; every risk
figure is computed from the legs by the exact payoff engine, with no
per-strategy formulas. Verticals, iron condors, and ratios all flow through the
same code path. Calendars/diagonals (multiple expirations) can be *built* but
the single-expiration risk math refuses them until pricing lands.

Construction is permissive on purpose (it will happily build a debit spread, a
ratio, a naked leg). "Is this the specific structure I intended to trade?" is a
separate, opt-in question answered by ``optionstruct.validators``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from optionstruct.errors import CalendarNotSupportedError, StructureError
from optionstruct.legs import Leg
from optionstruct.payoff import (
    RiskAmount,
    RiskProfile,
    net_premium,
    risk_profile,
)
from optionstruct.types import LegSide, OptionType


class StructureKind(StrEnum):
    VERTICAL = 'vertical'
    IRON_CONDOR = 'iron_condor'
    CALENDAR = 'calendar'
    RATIO = 'ratio'
    CUSTOM = 'custom'


def _infer_kind(legs: Sequence[Leg]) -> StructureKind:
    """Best-effort classification from leg shape. Advisory, not enforced.

    ``kind`` is informational only, no risk math depends on it (the payoff
    engine reads the legs directly), so a misclassification cannot produce a wrong
    number. Pass ``kind`` explicitly when you need it to be exact.
    """
    expirations = {leg.contract.expiration for leg in legs}
    if len(expirations) > 1:
        return StructureKind.CALENDAR

    sides = [leg.side for leg in legs]
    types = [leg.contract.option_type for leg in legs]
    quantities = {leg.quantity for leg in legs}

    if len(legs) == 2 and len(set(types)) == 1 and set(sides) == {LegSide.SHORT, LegSide.LONG}:
        # Equal quantities -> a plain vertical; unequal -> a ratio.
        return StructureKind.VERTICAL if len(quantities) == 1 else StructureKind.RATIO

    if len(legs) == 4:
        puts = [leg for leg in legs if leg.contract.option_type == OptionType.PUT]
        calls = [leg for leg in legs if leg.contract.option_type == OptionType.CALL]
        if len(puts) == 2 and len(calls) == 2:
            put_sides = {leg.side for leg in puts}
            call_sides = {leg.side for leg in calls}
            if put_sides == {LegSide.SHORT, LegSide.LONG} and call_sides == {LegSide.SHORT, LegSide.LONG}:
                return StructureKind.IRON_CONDOR

    # Unequal quantities across legs is the hallmark of a ratio spread.
    if len(quantities) > 1:
        return StructureKind.RATIO
    return StructureKind.CUSTOM


@dataclass(frozen=True, slots=True)
class Structure:
    legs: tuple[Leg, ...]
    kind: StructureKind

    def __init__(self, legs: Iterable[Leg], kind: StructureKind | None = None) -> None:
        legs = tuple(legs)
        if not legs:
            raise StructureError('a structure needs at least one leg')
        underlyings = {leg.contract.underlying for leg in legs}
        if len(underlyings) != 1:
            raise StructureError(f'all legs must share one underlying, got {sorted(underlyings)}')
        object.__setattr__(self, 'legs', legs)
        object.__setattr__(self, 'kind', kind or _infer_kind(legs))

    # ---- convenience constructors -------------------------------------------
    @classmethod
    def vertical(cls, short_leg: Leg, long_leg: Leg) -> 'Structure':
        """Two same-type, opposite-side legs. No credit/debit assumption made."""
        return cls((short_leg, long_leg), StructureKind.VERTICAL)

    @classmethod
    def iron_condor(
        cls,
        short_put: Leg,
        long_put: Leg,
        short_call: Leg,
        long_call: Leg,
    ) -> 'Structure':
        return cls((short_put, long_put, short_call, long_call), StructureKind.IRON_CONDOR)

    # ---- shape ---------------------------------------------------------------
    @property
    def underlying(self) -> str:
        return self.legs[0].contract.underlying

    @property
    def expirations(self) -> frozenset[date]:
        return frozenset(leg.contract.expiration for leg in self.legs)

    @property
    def is_single_expiration(self) -> bool:
        return len(self.expirations) == 1

    @property
    def strike_span(self) -> Decimal:
        """max strike minus min strike. For a 2-leg vertical this is the width."""
        strikes = [leg.contract.strike for leg in self.legs]
        return max(strikes) - min(strikes)

    @property
    def risk_width(self) -> Decimal:
        """The strike distance that bounds the loss, the widest single side.

        For a vertical this is ``strike_span``. For an iron condor it is emphatically
        not: ``strike_span`` there is the long call minus the long put, a number no
        side is ever that wide, and sizing against it would overstate max loss
        several-fold and refuse trades that fit.

        The condor can only be tested on one side at a time, so its loss is bounded
        by the wider wing alone, and the credit collected on *both* sides is
        subtracted from it, which is why a condor risks less than either of its
        spreads standing alone.

        Defined for structures whose every option type forms one short/long pair at
        equal quantity, verticals and iron condors. Anything else raises rather
        than returning a number that would be silently wrong.
        """
        self._require_single_expiration()
        widths: list[Decimal] = []
        for option_type in OptionType:
            legs = [leg for leg in self.legs if leg.contract.option_type == option_type]
            if not legs:
                continue
            sides = sorted(leg.side for leg in legs)
            if len(legs) != 2 or sides != [LegSide.LONG, LegSide.SHORT]:
                raise StructureError(
                    f'risk_width needs one short and one long per option type; '
                    f'{option_type.value} has {[leg.side.value for leg in legs]}'
                )
            if legs[0].quantity != legs[1].quantity:
                raise StructureError(
                    f'risk_width needs equal quantities per side; {option_type.value} '
                    f'has {legs[0].quantity} and {legs[1].quantity}'
                )
            widths.append(abs(legs[0].contract.strike - legs[1].contract.strike))
        if not widths:
            raise StructureError('risk_width needs at least one option leg')
        return max(widths)

    def _require_single_expiration(self) -> None:
        if not self.is_single_expiration:
            raise CalendarNotSupportedError(
                f'risk math needs a single expiration; structure spans {sorted(self.expirations)}'
            )

    # ---- derived risk (delegates to the exact payoff engine) -----------------
    def net_premium(self, premiums: Mapping[str, Decimal | str | int]) -> Decimal:
        """Open cash in dollars (credit positive). Valid across expirations."""
        return net_premium(self.legs, premiums)

    def risk(self, premiums: Mapping[str, Decimal | str | int]) -> RiskProfile:
        self._require_single_expiration()
        return risk_profile(self.legs, premiums)

    def max_loss(self, premiums: Mapping[str, Decimal | str | int]) -> RiskAmount:
        return self.risk(premiums).max_loss

    def max_profit(self, premiums: Mapping[str, Decimal | str | int]) -> RiskAmount:
        return self.risk(premiums).max_profit

    def breakevens(self, premiums: Mapping[str, Decimal | str | int]) -> tuple[Decimal, ...]:
        return self.risk(premiums).breakevens

    def margin(self, premiums: Mapping[str, Decimal | str | int]) -> RiskAmount:
        """Defined-risk margin = max loss. Undefined-risk returns UNBOUNDED.

        Naked/ratio margin is a broker-specific formula (e.g. a percentage of
        notional) and is intentionally left to an adapter, not guessed here.
        """
        return self.risk(premiums).max_loss


def combined_margin(
    structures: Sequence[Structure],
    premiums: Mapping[str, Decimal | str | int],
) -> RiskAmount:
    """Netted margin across structures on the same underlying and expiration.

    The correct netting *is* the payoff of all the legs together: a put spread
    plus a call spread can't both blow out at once, so the union's max loss is
    ``max(put-side, call-side)`` automatically, no special-casing. Requires a
    shared underlying and single shared expiration (the payoff engine's domain).
    """
    if not structures:
        return Decimal(0)
    all_legs = [leg for s in structures for leg in s.legs]
    underlyings = {leg.contract.underlying for leg in all_legs}
    if len(underlyings) != 1:
        raise StructureError(f'cannot net across underlyings {sorted(underlyings)}')
    expirations = {leg.contract.expiration for leg in all_legs}
    if len(expirations) != 1:
        raise CalendarNotSupportedError(
            f'cannot net across expirations {sorted(expirations)}'
        )
    return risk_profile(all_legs, premiums).max_loss
