"""A single leg of a structure: a contract, a side, and a quantity."""

from dataclasses import dataclass

from optionstruct.contracts import OptionContract
from optionstruct.errors import StructureError
from optionstruct.types import LegSide


@dataclass(frozen=True, slots=True)
class Leg:
    contract: OptionContract
    side: LegSide
    quantity: int = 1

    def __post_init__(self) -> None:
        side = LegSide(self.side)
        if self.quantity <= 0:
            raise StructureError('quantity must be positive')
        object.__setattr__(self, 'side', side)

    @classmethod
    def long(cls, contract: OptionContract, quantity: int = 1) -> 'Leg':
        return cls(contract, LegSide.LONG, quantity)

    @classmethod
    def short(cls, contract: OptionContract, quantity: int = 1) -> 'Leg':
        return cls(contract, LegSide.SHORT, quantity)

    @property
    def signed_quantity(self) -> int:
        """Quantity carrying the ownership sign: +qty long, -qty short."""
        return self.side.sign * self.quantity
