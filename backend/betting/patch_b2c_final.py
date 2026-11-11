from pathlib import Path
import re
from datetime import datetime

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

def backup(path):
    p = Path(path)
    b = p.with_name(f"{p.name}.bak_final_{STAMP}")
    b.write_text(p.read_text())
    print(f"BACKUP: {b}")

def write(path, text):
    Path(path).write_text(text)
    print(f"PATCHED: {path}")

# ============================================================
# WALLET.PY
# ============================================================

wallet = Path("wallet.py")
w = wallet.read_text()

backup(wallet)

# Add B2CSubmissionError import.
if "B2CSubmissionError" not in w:
    old = """from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)"""
    new = """from betting.mpesa import (
    normalize_phone,
    b2c_payment,
    B2CSubmissionError,
)"""
    if old not in w:
        raise RuntimeError("wallet.py: mpesa import block not found")
    w = w.replace(old, new, 1)
    print("wallet.py: added B2CSubmissionError import")
else:
    print("wallet.py: B2CSubmissionError import already present")

# Locate the B2C submission try/except specifically.
marker = """        try:

            response = b2c_payment("""
start = w.find(marker)

if start == -1:
    raise RuntimeError("wallet.py: B2C submission block not found")

except_pos = w.find("        except Exception as exc:", start)

if except_pos == -1:
    raise RuntimeError("wallet.py: B2C submission exception block not found")

# Only patch this exact exception clause.
replacement = """        except B2CSubmissionError as exc:

            logger.exception(
                "M-PESA B2C submission error | "
                "withdrawal=%s | user=%s | ambiguous=%s | error=%s",
                withdrawal.id,
                uid,
                exc.ambiguous,
                exc,
            )

            # ------------------------------------------------
            # IMPORTANT:
            #
            # If the HTTP request itself failed after it may
            # have reached Safaricom, we cannot safely refund.
            #
            # The withdrawal remains reserved until Safaricom
            # sends a callback. The callback can then finalize
            # it as success/failed/timeout.
            # ------------------------------------------------
            if exc.ambiguous:

                try:
                    current = (
                        db.session.query(MpesaWithdrawal)
                        .with_for_update()
                        .filter(
                            MpesaWithdrawal.id == withdrawal.id
                        )
                        .first()
                    )

                    if not current:
                        raise RuntimeError(
                            "withdrawal record disappeared"
                        )

                    if current.status not in (
                        "success",
                        "failed",
                        "timeout",
                    ):
                        current.status = "submission_unknown"
                        current.result_description = (
                            str(exc)[:255]
                        )

                        db.session.commit()

                        return _success(
                            {
                                "withdrawal_id": current.id,
                                "reference": current.reference,
                                "status": current.status,
                                "message": (
                                    "M-PESA submission status is "
                                    "unknown. Funds remain reserved "
                                    "pending Safaricom callback."
                                ),
                                "balance": _balance(
                                    current.user_id
                                ),
                            },
                            202,
                        )

                except Exception:
                    db.session.rollback()
                    logger.exception(
                        "Failed to mark ambiguous M-PESA "
                        "withdrawal | withdrawal=%s | user=%s",
                        withdrawal.id,
                        uid,
                    )

                    return _error(
                        "M-PESA submission status is unknown; "
                        "withdrawal remains reserved",
                        202,
                    )

            # A non-ambiguous B2C submission error means the
            # request was definitely not accepted, so the
            # reservation can be refunded safely.
            logger.warning(
                "Definite M-PESA B2C submission failure; "
                "refunding withdrawal=%s",
                withdrawal.id,
            )

            # Fall through to the existing refund handler.

        except Exception as exc:
"""

# Replace only the first generic except after the B2C call.
w = (
    w[:except_pos]
    + replacement
    + w[except_pos + len("        except Exception as exc:"):]
)

write(wallet, w)


# ============================================================
# ADMIN.PY
# ============================================================

admin = Path("admin.py")
a = admin.read_text()

backup(admin)

# Import B2CSubmissionError.
if "B2CSubmissionError" not in a:
    old = """from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)"""
    new = """from betting.mpesa import (
    normalize_phone,
    b2c_payment,
    B2CSubmissionError,
)"""
    if old not in a:
        raise RuntimeError("admin.py: mpesa import block not found")
    a = a.replace(old, new, 1)
    print("admin.py: added B2CSubmissionError import")
else:
    print("admin.py: B2CSubmissionError import already present")

# ------------------------------------------------------------
# Add submission_unknown to active/reserved statuses.
# ------------------------------------------------------------

a = a.replace(
    '"pending", "submitted", "processing"',
    '"pending", "submitted", "processing", "submission_unknown"',
)

a = a.replace(
    '"pending",\n        "submitted",\n        "processing",',
    '"pending",\n        "submitted",\n        "processing",\n        "submission_unknown",',
)

# ------------------------------------------------------------
# Add submission_unknown to admin withdrawal filter.
# ------------------------------------------------------------

a = a.replace(
    '"pending", "submitted", "processing", "timeout", "success", "failed"',
    '"pending", "submitted", "processing", "submission_unknown", '
    '"timeout", "success", "failed"',
)

a = a.replace(
    '"pending",\n                "submitted",\n                "processing",\n                "timeout",',
    '"pending",\n                "submitted",\n                "processing",\n                "submission_unknown",\n                "timeout",',
)

# ------------------------------------------------------------
# HOUSE PAYOUT:
# Patch only the B2C submission exception.
# ------------------------------------------------------------

house_marker = """        try:

            response = b2c_payment("""
house_start = a.find(house_marker)

if house_start == -1:
    raise RuntimeError(
        "admin.py: house B2C submission block not found"
    )

house_except = a.find(
    "        except Exception as exc:",
    house_start,
)

if house_except == -1:
    raise RuntimeError(
        "admin.py: house B2C exception block not found"
    )

# Find the next major route/helper boundary so we can replace
# only the exception header and insert an ambiguity branch.
# The existing refund code remains intact.
house_body_end_candidates = [
    a.find("\n        return jsonify(", house_except),
    a.find("\n\n    @", house_except),
]

house_end = min(
    x for x in house_body_end_candidates if x != -1
)

house_exception_body = a[house_except:house_end]

if "if exc.ambiguous:" not in house_exception_body:
    injected = """        except B2CSubmissionError as exc:

            logger.exception(
                "House M-PESA B2C submission error | "
                "withdrawal=%s | ambiguous=%s | error=%s",
                house_withdrawal.id,
                exc.ambiguous,
                exc,
            )

            # Safaricom may have received the request even though
            # the HTTP client did not receive a definitive answer.
            # NEVER refund an ambiguous submission.
            if exc.ambiguous:

                house_withdrawal.status = "submission_unknown"
                house_withdrawal.result_description = (
                    str(exc)[:255]
                )

                db.session.commit()

                return jsonify(
                    {
                        "success": True,
                        "message": (
                            "M-PESA submission status is unknown; "
                            "house funds remain reserved pending "
                            "Safaricom callback"
                        ),
                        "status": "submission_unknown",
                        "withdrawal_id": house_withdrawal.id,
                        "reference": house_withdrawal.reference,
                    }
                ), 202

            # Definite submission failure:
            # continue into the existing refund logic.

        except Exception as exc:
"""

    a = (
        a[:house_except]
        + injected
        + house_exception_body[
            len("        except Exception as exc:") + 1:
        ]
        + a[house_end:]
    )

    print("admin.py: patched house B2C ambiguity handling")
else:
    print("admin.py: house ambiguity handling already present")

# ------------------------------------------------------------
# Fix timeout ordering.
#
# Existing code incorrectly does:
#   status = timeout
#   refund(...)
#
# The helper refuses to refund a timeout, so refund must happen
# BEFORE final timeout status.
# ------------------------------------------------------------

a = a.replace(
    """        house_withdrawal.status = "timeout"
        _refund_house_payout(
            house_withdrawal,
            "M-PESA B2C payout timed out",
        )""",
    """        _refund_house_payout(
            house_withdrawal,
            "M-PESA B2C payout timed out",
        )
        house_withdrawal.status = "timeout" """,
)

a = a.replace(
    """        user_withdrawal.status = "timeout"
        _refund_user_withdrawal(
            user_withdrawal,
            "M-PESA B2C withdrawal timed out",
        )""",
    """        _refund_user_withdrawal(
            user_withdrawal,
            "M-PESA B2C withdrawal timed out",
        )
        user_withdrawal.status = "timeout" """,
)

# ------------------------------------------------------------
# Make refund helper recognize submission_unknown as refundable
# only when explicitly invoked for a definite callback failure/
# timeout. This is intentionally NOT used by the ambiguous
# submission path above.
# ------------------------------------------------------------

# Add explicit refund transaction to user refund helper.
if "mpesa_withdrawal_refund" not in a:
    needle = """            locked_tx.status = "failed"
            locked_tx.balance_after = locked_user.balance

            withdrawal.status = "failed"
"""

    replacement = """            locked_tx.status = "failed"
            locked_tx.balance_after = locked_user.balance

            db.session.add(
                Transaction(
                    user_id=locked_user.id,
                    type="mpesa_withdrawal_refund",
                    amount=amount,
                    balance_after=locked_user.balance,
                    description=reason,
                    reference=withdrawal.reference,
                    status="completed",
                )
            )

            withdrawal.status = "failed"
"""

    if needle in a:
        a = a.replace(needle, replacement, 1)
        print("admin.py: added explicit user withdrawal refund transaction")
    else:
        print(
            "WARNING: admin.py user refund transaction insertion "
            "pattern not found; inspect helper manually"
        )

write(admin, a)


# ============================================================
# VALIDATION
# ============================================================

print()
print("Running syntax validation...")

import py_compile

for name in ("mpesa.py", "wallet.py", "admin.py"):
    py_compile.compile(name, doraise=True)
    print(f"OK: {name}")

print()
print("PATCH COMPLETE")
print(f"Backups use suffix: .bak_final_{STAMP}")
