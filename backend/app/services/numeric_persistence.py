"""Exact PostgreSQL NUMERIC(38,12) persistence boundary."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext


NUMERIC_38_12_QUANTUM = Decimal("0.000000000001")
NUMERIC_38_12_MAX = Decimal("99999999999999999999999999.999999999999")


def persist_numeric_38_12(value: Decimal | int | str) -> Decimal:
    """Return the single value safe to use in both audit JSON and the DB column."""
    candidate = value if isinstance(value, Decimal) else Decimal(str(value))
    if not candidate.is_finite():
        raise ValueError("numeric persistence requires a finite decimal")
    try:
        with localcontext() as context:
            context.prec = 80
            persisted = candidate.quantize(NUMERIC_38_12_QUANTUM, rounding=ROUND_HALF_UP)
            if abs(persisted) > NUMERIC_38_12_MAX:
                raise ValueError("numeric value is outside NUMERIC(38,12)")
    except InvalidOperation as error:
        raise ValueError("numeric value is outside NUMERIC(38,12)") from error
    return persisted
