"""Normalised reporting categories for payment allocations.

Source of the raw value: polaris_installments.name (free text typed in
Propone, ~265 spellings) together with polaris_installments.installment_type.
Allocation amounts come from polaris_adjusted_installments, where late-payment
charges and taxes are separate columns and get their own category.

installment_type codes, as observed in the data:
  0 = Down Payment, 1 = regular/custom schedule (free-text names),
  2 = Possession, 3 = Refund Installment, 4 = Installment N,
  5 = Sales Tax / PRA, 6 = Income Tax / 236K, 7 = test values (grey, blue, black)

Business rule: only Installment and Possession are target-related. Target Achieved
is the Installment + Possession money actually deposited in the month (Verified /
Received) on bookings in the target list. Every other category is shown as
"Other collections" and is never counted as achievement. Propone's stored
achieved_amount is kept only as a reference figure.

Anything not matched stays in "Other" until it is reviewed. /api/categories/mapping
lists every raw value with its category.
"""
import re

INSTALLMENT = "Installment"
POSSESSION = "Possession"
DOWN_PAYMENT = "Down Payment"
ESCALATION = "Escalation"
ADJUSTMENT = "Adjustment Cost"
LATE_PAYMENT = "Late Payment"
TAX_236K = "236K Tax"
TAX_PRA = "PRA Tax"
TAX_OTHER = "Other Tax"
TRANSFER_FEE = "Transfer Fee"
CANCELLATION = "Cancellation Fee"
REFUND = "Refund"
UNALLOCATED = "Unallocated"
OTHER = "Other"

TARGET_RELATED = (INSTALLMENT, POSSESSION)
CATEGORY_ORDER = [INSTALLMENT, POSSESSION, DOWN_PAYMENT, ESCALATION, ADJUSTMENT, LATE_PAYMENT,
                  TAX_236K, TAX_PRA, TAX_OTHER, TRANSFER_FEE, CANCELLATION, REFUND, UNALLOCATED, OTHER]


def group_of(category: str) -> str:
    return "target" if category in TARGET_RELATED else "other"


_TYPE_CATEGORY = {0: DOWN_PAYMENT, 2: POSSESSION, 3: REFUND, 4: INSTALLMENT, 5: TAX_PRA, 6: TAX_236K, 7: OTHER}

_HAS_236 = r"(^|[^0-9])236([^0-9]|$)"
_HAS_PRA = r"pra\b|pratax|\brpa\b"
_RULES = [  # (category, pattern) checked in order on the lower-cased name
    (REFUND, r"refund"),
    (TRANSFER_FEE, r"transfer\s*fee"),
    (LATE_PAYMENT, r"late\s*payment"),
    (TAX_OTHER, rf"(?=.*({_HAS_236}))(?=.*({_HAS_PRA}))"),  # "Tax 236 k and PRA": both taxes in one line
    (TAX_236K, _HAS_236),
    (TAX_PRA, _HAS_PRA),
    (TAX_OTHER, r"\btax|\bfed\b"),
    (DOWN_PAYMENT, r"down\s*payment|\bdp\b"),
    (POSSESSION, r"poss?ess?io?n?|posession|possesion"),
    (ESCALATION, r"escalation"),
    (ADJUSTMENT, r"a?d?j[a-z]*ustm[a-z0-9]*\s*cost|adjustm\d*ent\s*cost"),
    (INSTALLMENT, r"ins?t?a?l+m?e?n?t|instal+ment|installmant|insatllment|installmnt|installent"
                  r"|developer|customer|customes|client|balloon|ballon|half\s*yearly|quarterly"
                  r"|old\s*plan|amount\s*paid|paid\s*amount|^paid\b"),
]
_COMPILED = [(cat, re.compile(p)) for cat, p in _RULES]


def categorize(name, installment_type) -> str:
    """Category for one installment (raw name + type code)."""
    try:
        t = int(installment_type) if installment_type is not None else None
    except (TypeError, ValueError):
        t = None
    if t in _TYPE_CATEGORY:
        return _TYPE_CATEGORY[t]
    text = re.sub(r"\s+", " ", str(name or "")).strip().lower()
    for cat, rx in _COMPILED:
        if rx.search(text):
            return cat
    return OTHER


# Components of one allocation row in polaris_adjusted_installments.
LATE_RAW = "Late payment charges (overdue_charges)"
INCOME_TAX_RAW = "Income tax 236K (income_tax)"
SALES_TAX_RAW = "Sales tax PRA (sales_tax)"
CANCELLATION_RAW = "Cancellation fee (cancellation_fee)"
TRANSFER_RAW = "Transfer payment (payment_type 3, no installment allocation)"
UNALLOCATED_RAW = "Payment not allocated to an installment"
