from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_money(value: Decimal | int | str) -> Decimal:
    """Round to cents using half-up rounding, the convention customers expect on a receipt.

    Floats are rejected: ``2.675`` as a float is ``2.67499999...`` and would round down.
    """
    if isinstance(value, float):
        raise TypeError("Use Decimal or str for money, never float")
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
