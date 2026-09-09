"""optionstruct, dependency-free modeling of multi-leg options structures.

Pure Python + Decimal. No pydantic, no Django, no broker SDK, no I/O. Build a
structure from legs, then ask it for exact expiration risk figures (max loss /
max profit / breakevens / margin) in real dollars.

    from datetime import date
    from decimal import Decimal
    from optionstruct import OptionContract, Leg, Structure, OptionType

    exp = date(2026, 8, 21)
    short = Leg.short(OptionContract("XSP", OptionType.PUT, "740", exp))
    long_ = Leg.long(OptionContract("XSP", OptionType.PUT, "735", exp))
    spread = Structure.vertical(short, long_)

    premiums = {short.contract.symbol: Decimal("3.00"), long_.contract.symbol: Decimal("1.50")}
    r = spread.risk(premiums)
    r.net_premium   # Decimal('150.00')   credit collected, dollars
    r.max_loss      # Decimal('350.00')
    r.max_profit    # Decimal('150.00')
    r.breakevens    # (Decimal('738.5'),)
"""

from optionstruct.contracts import DEFAULT_MULTIPLIER, OptionContract, build_occ_symbol
from optionstruct.errors import (
    CalendarNotSupportedError,
    InvalidPricingInputsError,
    MissingPremiumError,
    OptionStructError,
    PricingError,
    StructureError,
    ValidationError,
)
from optionstruct.legs import Leg
from optionstruct.payoff import (
    UNBOUNDED,
    RiskAmount,
    RiskProfile,
    UnboundedRisk,
    net_premium,
    pnl_at,
    risk_profile,
)
from optionstruct.pricing import (
    NICKEL,
    PENNY,
    Greeks,
    PricingInputs,
    bs_delta,
    bs_gamma,
    bs_price,
    bs_theta,
    bs_vega,
    greeks,
    net_greeks,
    opening_limit_credit,
    round_to_tick,
)
from optionstruct.structure import Structure, StructureKind, combined_margin
from optionstruct.types import (
    DTE,
    CashUSD,
    ContractQuantity,
    DeltaFraction,
    IVFraction,
    LegSide,
    Multiplier,
    OptionType,
    PremiumUSD,
    PriceEffect,
    StrikeUSD,
    WidthUSD,
)
from optionstruct.validators import (
    is_even_strike,
    is_odd_strike,
    validate_credit_spread,
    validate_vertical,
)

__version__ = '0.0.3'

__all__ = [
    'DEFAULT_MULTIPLIER',
    'DTE',
    'NICKEL',
    # order-limit price math
    'PENNY',
    'UNBOUNDED',
    'CalendarNotSupportedError',
    'CashUSD',
    'ContractQuantity',
    'DeltaFraction',
    'Greeks',
    'IVFraction',
    'InvalidPricingInputsError',
    'Leg',
    'LegSide',
    'MissingPremiumError',
    'Multiplier',
    # contracts / legs / structures
    'OptionContract',
    # errors
    'OptionStructError',
    # types
    'OptionType',
    'PremiumUSD',
    'PriceEffect',
    'PricingError',
    # pricing / greeks
    'PricingInputs',
    'RiskAmount',
    # payoff / risk
    'RiskProfile',
    'StrikeUSD',
    'Structure',
    'StructureError',
    'StructureKind',
    'UnboundedRisk',
    'ValidationError',
    'WidthUSD',
    '__version__',
    'bs_delta',
    'bs_gamma',
    'bs_price',
    'bs_theta',
    'bs_vega',
    'build_occ_symbol',
    'combined_margin',
    'greeks',
    'is_even_strike',
    'is_odd_strike',
    'net_greeks',
    'net_premium',
    'opening_limit_credit',
    'pnl_at',
    'risk_profile',
    'round_to_tick',
    'validate_credit_spread',
    # validators
    'validate_vertical',
]
