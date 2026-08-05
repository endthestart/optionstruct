"""Exception hierarchy for optionstruct.

Two distinct families, kept separate on purpose (see the package README):

- ``StructureError``, the *shape* of a structure is malformed (no legs, mixed
  underlyings, a leg with non-positive quantity). Raised at construction time.
- ``PricingError``, the *market data* handed to the math is missing or
  unusable (no premium for a leg's symbol). Raised by the payoff/premium math.

Strategy-level judgments ("is this a valid short-put credit spread?") are NOT
errors from the core's point of view, they live in ``validators`` and only
raise when a caller explicitly asks to validate.
"""


class OptionStructError(Exception):
    """Base class for every error raised by optionstruct."""


class StructureError(OptionStructError, ValueError):
    """The legs handed to a Structure do not form a well-formed structure."""


class PricingError(OptionStructError, ValueError):
    """Market data required by the math is missing or unusable."""


class MissingPremiumError(PricingError):
    """No usable premium was supplied for a contract symbol."""


class InvalidPricingInputsError(PricingError):
    """Black-Scholes inputs are outside their valid domain (non-positive spot,
    strike, tenor, or volatility)."""


class CalendarNotSupportedError(OptionStructError, NotImplementedError):
    """Risk math was asked to evaluate a structure spanning expirations.

    The exact-payoff engine models value *at a single expiration*. Structures
    whose legs expire on different dates (calendars/diagonals) need a pricing
    model (Black-Scholes) to value the still-open leg at the near leg's
    expiration; that lands in a later pass. Structures may still be *built*
    with multiple expirations, only the risk math refuses them, loudly.
    """


class ValidationError(OptionStructError, ValueError):
    """An opt-in validator rejected a structure against a strategy's rules."""
