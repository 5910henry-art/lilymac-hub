from pathlib import Path
import re
import py_compile

# ============================================================
# WALLET
# ============================================================

p = Path("wallet.py")
w = p.read_text()

# The previous patch inserted a separate B2CSubmissionError
# except before the original generic refund handler.
#
# We want ONE exception handler:
#
#     except Exception as exc:
#         if isinstance(exc, B2CSubmissionError) and exc.ambiguous:
#             mark submission_unknown
#             DO NOT REFUND
#
#         otherwise execute the existing refund code.

old = """        except B2CSubmissionError as exc:

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

        except Exception as exc:
"""

if old not in w:
    raise RuntimeError(
        "wallet.py: expected previous B2C exception block was not found"
    )

new = """        except Exception as exc:

            # ------------------------------------------------
            # AMBIGUOUS B2C SUBMISSION
            #
            # The request may have reached Safaricom. NEVER
            # refund in this case. Keep the reservation until
            # the asynchronous callback resolves it.
            # ------------------------------------------------
            if isinstance(exc, B2CSubmissionError) and exc.ambiguous:

                logger.exception(
                    "M-PESA B2C submission status unknown | "
                    "withdrawal=%s | user=%s | error=%s",
                    withdrawal.id,
                    uid,
                    exc,
                )

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

                    db.session.rollback()

                    return _success(
                        {
                            "withdrawal_id": current.id,
                            "reference": current.reference,
                            "status": current.status,
                            "message": (
                                "Withdrawal was already finalized."
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

            # ------------------------------------------------
            # DEFINITE SUBMISSION FAILURE OR OTHER ERROR
            #
            # Continue with the existing refund handler below.
            # ------------------------------------------------

            logger.exception(
                "M-PESA B2C submission failed | "
                "withdrawal=%s | user=%s | error=%s",
                withdrawal.id,
                uid,
                exc,
            )

            # ------------------------------------------------
            # Submission failed.
            #
            # Lock withdrawal again before refunding.
            # ------------------------------------------------
"""

# The existing generic handler begins with exactly the same
# logger/refund block. We need replace the entire old inserted
# structure with the unified handler, but preserve the existing
# refund body after its logger.
#
# Locate the old block and extract the refund body from the old
# generic handler backup if possible. Since our current file has
# the refund body immediately after the second exception header,
# capture everything after that header.

# Find the second old generic handler in the original text.
second = w.find(
    "        except Exception as exc:",
    w.find("        except B2CSubmissionError as exc:")
)

if second == -1:
    raise RuntimeError(
        "wallet.py: original generic refund handler not found"
    )

# Find the refund body after the second exception header.
refund_body_start = second + len(
    "        except Exception as exc:"
)

refund_body = w[refund_body_start:]

# We only want the body through the end of this withdrawal route,
# before the successful-response code.
success_marker = """
        # ----------------------------------------------------
        # Save Safaricom response.
"""

success_pos = refund_body.find(success_marker)

if success_pos == -1:
    raise RuntimeError(
        "wallet.py: successful Safaricom response marker not found"
    )

refund_body = refund_body[:success_pos]

# Replace everything from the first B2C exception through the
# beginning of the successful-response section.
first = w.find("        except B2CSubmissionError as exc:")
if first == -1:
    raise RuntimeError(
        "wallet.py: B2CSubmissionError handler not found"
    )

end = second + len("        except Exception as exc:") + len(refund_body)

w = w[:first] + new + refund_body + w[end:]

p.write_text(w)
print("PATCHED: wallet.py")


# ============================================================
# ADMIN
# ============================================================

p = Path("admin.py")
a = p.read_text()

# Add import.
if "B2CSubmissionError" not in a:
    old_import = """from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)"""

    new_import = """from betting.mpesa import (
    normalize_phone,
    b2c_payment,
    B2CSubmissionError,
)"""

    if old_import not in a:
        raise RuntimeError(
            "admin.py: M-PESA import block not found"
        )

    a = a.replace(old_import, new_import, 1)
    print("PATCHED: admin.py B2CSubmissionError import")
else:
    print("admin.py: B2CSubmissionError import already present")


# Add submission_unknown to reserved house statuses.
a = a.replace(
    '                    "processing",\n',
    '                    "processing",\n                    "submission_unknown",\n',
    1,
)

# ------------------------------------------------------------
# House B2C submission exception.
# ------------------------------------------------------------

call_start = a.find(
    "            response = b2c_payment(",
    a.find("# Submit to Safaricom AFTER reservation commit.")
)

if call_start == -1:
    raise RuntimeError(
        "admin.py: house b2c_payment call not found"
    )

except_start = a.find(
    "        except Exception as exc:",
    call_start
)

if except_start == -1:
    raise RuntimeError(
        "admin.py: house B2C exception not found"
    )

save_marker = """
        # ------------------------------------------------
        # Save Safaricom response.
"""

save_pos = a.find(save_marker, except_start)

if save_pos == -1:
    raise RuntimeError(
        "admin.py: house Save Safaricom response marker not found"
    )

old_exception = a[except_start:save_pos]

# Preserve the existing definite-failure refund logic, but put
# an ambiguity branch before it.
#
# Strip the first exception header and use the existing body as
# the definite-error path.

old_body = old_exception[
    len("        except Exception as exc:")
:]

new_exception = """        except B2CSubmissionError as exc:

            logger.exception(
                "House B2C submission status unknown | "
                "withdrawal=%s | error=%s",
                withdrawal.id,
                exc,
            )

            # The request may have reached Safaricom.
            # DO NOT refund an ambiguous submission.
            try:
                current = (
                    db.session.query(
                        HouseMpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        HouseMpesaWithdrawal.id
                        == withdrawal.id
                    )
                    .first()
                )

                if not current:
                    raise RuntimeError(
                        "house withdrawal record disappeared"
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

                    return jsonify({
                        "success": True,
                        "message": (
                            "M-PESA submission status is unknown; "
                            "house funds remain reserved pending "
                            "Safaricom callback"
                        ),
                        "status": "submission_unknown",
                        "withdrawal_id": current.id,
                        "reference": current.reference,
                    }), 202

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to mark ambiguous house "
                    "B2C withdrawal | withdrawal=%s",
                    withdrawal.id,
                )

                return jsonify({
                    "error": (
                        "M-PESA submission status is unknown; "
                        "house funds remain reserved"
                    ),
                    "withdrawal_id": withdrawal.id,
                }), 202

            # A non-ambiguous B2CSubmissionError is a definite
            # submission failure, so refund it using the same
            # path as the generic failure handler.

            logger.error(
                "Definite house B2C submission failure | "
                "withdrawal=%s | error=%s",
                withdrawal.id,
                exc,
            )

            # Re-use the existing refund logic below.
            # Convert to a normal exception for that path.
            exc = RuntimeError(str(exc))

        except Exception as exc:
"""

# Instead of trying to duplicate the refund body, we need a
# unified handler. Therefore use a single generic handler and
# inspect ambiguity at the top.
#
# Build this from the existing refund body.

# Remove the original exception header from old_body and keep
# everything after the logger through return.
# The old body already has all refund operations.
unified = """        except Exception as exc:

            # ------------------------------------------------
            # AMBIGUOUS SUBMISSION
            # ------------------------------------------------
            if isinstance(exc, B2CSubmissionError) and exc.ambiguous:

                logger.exception(
                    "House B2C submission status unknown | "
                    "withdrawal=%s | error=%s",
                    withdrawal.id,
                    exc,
                )

                try:
                    current = (
                        db.session.query(
                            HouseMpesaWithdrawal
                        )
                        .with_for_update()
                        .filter(
                            HouseMpesaWithdrawal.id
                            == withdrawal.id
                        )
                        .first()
                    )

                    if not current:
                        raise RuntimeError(
                            "house withdrawal record disappeared"
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

                        return jsonify({
                            "success": True,
                            "message": (
                                "M-PESA submission status is unknown; "
                                "house funds remain reserved pending "
                                "Safaricom callback"
                            ),
                            "status": "submission_unknown",
                            "withdrawal_id": current.id,
                            "reference": current.reference,
                        }), 202

                    db.session.rollback()

                    return jsonify({
                        "success": True,
                        "status": current.status,
                        "withdrawal_id": current.id,
                        "reference": current.reference,
                    }), 202

                except Exception:
                    db.session.rollback()
                    logger.exception(
                        "Failed to mark ambiguous house "
                        "B2C withdrawal | withdrawal=%s",
                        withdrawal.id,
                    )

                    return jsonify({
                        "error": (
                            "M-PESA submission status is unknown; "
                            "house funds remain reserved"
                        ),
                        "withdrawal_id": withdrawal.id,
                    }), 202

            # ------------------------------------------------
            # DEFINITE FAILURE / NORMAL ERROR
            # Existing refund logic follows.
            # ------------------------------------------------
"""

# Existing old_body starts with logger and comments, so append it.
a = a[:except_start] + unified + old_body + a[save_pos:]


# ------------------------------------------------------------
# Fix timeout ordering.
# ------------------------------------------------------------

old = """                house_withdrawal.status = "timeout"
                house_withdrawal.result_code = result_code
"""

new = """                house_withdrawal.result_code = result_code
"""

if old in a:
    a = a.replace(old, new, 1)

old = """                refunded = _refund_house_payout(
                    house_withdrawal,
                    reason="Refund for M-PESA B2C house payout timeout",
                )

                db.session.commit()
"""

new = """                refunded = _refund_house_payout(
                    house_withdrawal,
                    reason="Refund for M-PESA B2C house payout timeout",
                )

                house_withdrawal.status = "timeout"

                db.session.commit()
"""

if old not in a:
    raise RuntimeError(
        "admin.py: house timeout refund block not found"
    )

a = a.replace(old, new, 1)


# User timeout: move status assignment after refund.
old = """                user_withdrawal.status = "timeout"
                user_withdrawal.result_code = result_code
"""

new = """                user_withdrawal.result_code = result_code
"""

if old in a:
    a = a.replace(old, new, 1)

old = """                refunded = _refund_user_withdrawal(
                    user_withdrawal,
                    reason="Refund for M-PESA B2C user withdrawal timeout",
                )

                db.session.commit()
"""

new = """                refunded = _refund_user_withdrawal(
                    user_withdrawal,
                    reason="Refund for M-PESA B2C user withdrawal timeout",
                )

                user_withdrawal.status = "timeout"

                db.session.commit()
"""

if old not in a:
    # Try alternate formatting.
    pattern = re.compile(
        r'(                refunded = _refund_user_withdrawal\(\n'
        r'                    user_withdrawal,\n'
        r'                    reason=.*?\n'
        r'                \)\n'
        r')(\n                db\.session\.commit\(\))',
        re.S,
    )

    m = pattern.search(a)

    if not m:
        raise RuntimeError(
            "admin.py: user timeout refund block not found"
        )

    replacement = (
        m.group(1)
        + '\n                user_withdrawal.status = "timeout"'
        + m.group(2)
    )

    a = a[:m.start()] + replacement + a[m.end():]
else:
    a = a.replace(old, new, 1)


# ------------------------------------------------------------
# Add explicit user refund transaction if missing.
# ------------------------------------------------------------

if "type=\"mpesa_withdrawal_refund\"" not in a:
    needle = """        transaction.status = "failed"
        transaction.balance_after = user.balance

        return True
"""

    replacement = """        transaction.status = "failed"
        transaction.balance_after = user.balance

        db.session.add(
            Transaction(
                user_id=user.id,
                type="mpesa_withdrawal_refund",
                amount=withdrawal.amount,
                balance_after=user.balance,
                description=reason,
                reference=withdrawal.reference,
                status="completed",
            )
        )

        return True
"""

    if needle not in a:
        raise RuntimeError(
            "admin.py: user refund helper insertion point not found"
        )

    a = a.replace(needle, replacement, 1)


# ------------------------------------------------------------
# Make helpers understand submission_unknown is active.
# They still refuse final states only.
# ------------------------------------------------------------

# Add submission_unknown to admin withdrawals allowed statuses
# if an explicit list exists.
a = a.replace(
    '"processing", "timeout", "success", "failed"',
    '"processing", "submission_unknown", "timeout", "success", "failed"',
)

a = a.replace(
    '"processing",\n                    "timeout",',
    '"processing",\n                    "submission_unknown",\n                    "timeout",',
)

p.write_text(a)
print("PATCHED: admin.py")


# ============================================================
# VALIDATE
# ============================================================

for name in ("mpesa.py", "wallet.py", "admin.py"):
    py_compile.compile(name, doraise=True)
    print("OK:", name)

print()
print("FINAL B2C PATCH VALIDATION PASSED")
