from pathlib import Path
from datetime import datetime
import shutil
import sys

BASE = Path(".")
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

FILES = ["mpesa.py", "wallet.py", "admin.py"]

for name in FILES:
    p = BASE / name
    if not p.exists():
        raise SystemExit(f"ERROR: {name} not found")

    bak = BASE / f"{name}.bak_b2c_safe_{STAMP}"
    shutil.copy2(p, bak)
    print(f"Backup: {bak}")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: {label}: expected exactly 1 match, found {count}"
        )
    return text.replace(old, new, 1)


# ============================================================
# 1. mpesa.py
# ============================================================
p = BASE / "mpesa.py"
text = p.read_text()

if "class B2CSubmissionError" not in text:
    old = 'logger = logging.getLogger(__name__)'
    new = '''logger = logging.getLogger(__name__)


class B2CSubmissionError(RuntimeError):
    """
    Raised when a B2C submission fails.

    ambiguous=True means the request may have reached Safaricom,
    but the client cannot determine whether Safaricom accepted it.
    In that case the withdrawal must remain reserved.
    """

    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = bool(ambiguous)
'''
    text = replace_once(
        text,
        old,
        new,
        "mpesa.py logger/class insertion",
    )
    print("mpesa.py: added B2CSubmissionError")
else:
    print("mpesa.py: B2CSubmissionError already present")

old = '''    except requests.RequestException as exc:
        logger.exception(
            "M-PESA B2C request failed: %s",
            exc,
        )

        raise RuntimeError(
            "M-PESA B2C request could not be sent"
        ) from exc
'''

new = '''    except requests.RequestException as exc:
        logger.exception(
            "M-PESA B2C request failed: %s",
            exc,
        )

        raise B2CSubmissionError(
            "M-PESA B2C submission status is unknown",
            ambiguous=True,
        ) from exc
'''

if "M-PESA B2C submission status is unknown" not in text:
    text = replace_once(
        text,
        old,
        new,
        "mpesa.py B2C transport exception",
    )
    print("mpesa.py: patched ambiguous B2C transport failure")
else:
    print("mpesa.py: ambiguous transport failure already patched")

p.write_text(text)


# ============================================================
# 2. wallet.py
# ============================================================
p = BASE / "wallet.py"
text = p.read_text()

old = '''from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)
'''

new = '''from betting.mpesa import (
    normalize_phone,
    b2c_payment,
    B2CSubmissionError,
)
'''

if "B2CSubmissionError" not in text:
    text = replace_once(
        text,
        old,
        new,
        "wallet.py mpesa import",
    )
    print("wallet.py: added B2CSubmissionError import")
else:
    print("wallet.py: B2CSubmissionError import already present")


old = '''        except Exception as exc:

            logger.exception(
                "User B2C submission failed | "
                "withdrawal=%s",
                withdrawal.id,
            )

            try:
                current = (
                    db.session.query(
                        MpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        MpesaWithdrawal.id
                        == withdrawal.id
                    )
                    .first()
                )

                if current and current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    user = (
                        db.session.query(User)
                        .with_for_update()
                        .filter(User.id == uid)
                        .first()
                    )

                    original_tx = (
                        db.session.query(Transaction)
                        .with_for_update()
                        .filter(
                            Transaction.user_id == uid,
                            Transaction.reference == current.reference,
                            Transaction.type == "mpesa_withdrawal",
                        )
                        .first()
                    )

                    if not user:
                        raise RuntimeError(
                            "User disappeared during withdrawal refund"
                        )

                    if not original_tx:
                        raise RuntimeError(
                            "Original withdrawal transaction not found"
                        )

                    refund_amount = _money(current.amount)

                    user.balance = _money(
                        user.balance + refund_amount
                    )

                    original_tx.status = "failed"
                    original_tx.balance_after = user.balance

                    db.session.add(
                        Transaction(
                            user_id=uid,
                            type="mpesa_withdrawal_refund",
                            amount=refund_amount,
                            balance_after=user.balance,
                            description=(
                                "Refund for failed M-PESA withdrawal submission"
                            ),
                            reference=current.reference,
                            status="completed",
                        )
                    )

                    current.status = "failed"
                    current.result_description = str(exc)[:255]

                    db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to refund failed user B2C withdrawal"
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502
'''

new = '''        except B2CSubmissionError as exc:

            logger.exception(
                "User B2C submission error | withdrawal=%s | ambiguous=%s",
                withdrawal.id,
                exc.ambiguous,
            )

            try:
                current = (
                    db.session.query(
                        MpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        MpesaWithdrawal.id
                        == withdrawal.id
                    )
                    .first()
                )

                if not current:
                    raise RuntimeError(
                        "Withdrawal record disappeared during B2C submission"
                    )

                if current.status in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    db.session.commit()
                    return jsonify({
                        "error": "M-PESA B2C request failed",
                        "withdrawal_id": withdrawal.id,
                        "status": current.status,
                    }), 502

                if exc.ambiguous:
                    current.status = "submission_unknown"
                    current.result_description = str(exc)[:255]

                    db.session.commit()

                    logger.warning(
                        "USER B2C submission UNKNOWN | withdrawal=%s | "
                        "funds remain reserved pending callback/reconciliation",
                        withdrawal.id,
                    )

                    return jsonify({
                        "message": (
                            "M-PESA request status is unknown; "
                            "funds remain reserved pending callback"
                        ),
                        "withdrawal_id": withdrawal.id,
                        "reference": current.reference,
                        "status": current.status,
                    }), 202

                # Non-ambiguous submission error: safe to refund.
                user = (
                    db.session.query(User)
                    .with_for_update()
                    .filter(User.id == uid)
                    .first()
                )

                original_tx = (
                    db.session.query(Transaction)
                    .with_for_update()
                    .filter(
                        Transaction.user_id == uid,
                        Transaction.reference == current.reference,
                        Transaction.type == "mpesa_withdrawal",
                    )
                    .first()
                )

                if not user:
                    raise RuntimeError(
                        "User disappeared during withdrawal refund"
                    )

                if not original_tx:
                    raise RuntimeError(
                        "Original withdrawal transaction not found"
                    )

                refund_amount = _money(current.amount)

                user.balance = _money(
                    user.balance + refund_amount
                )

                original_tx.status = "failed"
                original_tx.balance_after = user.balance

                db.session.add(
                    Transaction(
                        user_id=uid,
                        type="mpesa_withdrawal_refund",
                        amount=refund_amount,
                        balance_after=user.balance,
                        description=(
                            "Refund for failed M-PESA withdrawal submission"
                        ),
                        reference=current.reference,
                        status="completed",
                    )
                )

                current.status = "failed"
                current.result_description = str(exc)[:255]

                db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to process user B2C submission error | withdrawal=%s",
                    withdrawal.id,
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502

        except Exception as exc:

            logger.exception(
                "User B2C submission failed | "
                "withdrawal=%s",
                withdrawal.id,
            )

            try:
                current = (
                    db.session.query(
                        MpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        MpesaWithdrawal.id
                        == withdrawal.id
                    )
                    .first()
                )

                if current and current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    user = (
                        db.session.query(User)
                        .with_for_update()
                        .filter(User.id == uid)
                        .first()
                    )

                    original_tx = (
                        db.session.query(Transaction)
                        .with_for_update()
                        .filter(
                            Transaction.user_id == uid,
                            Transaction.reference == current.reference,
                            Transaction.type == "mpesa_withdrawal",
                        )
                        .first()
                    )

                    if not user:
                        raise RuntimeError(
                            "User disappeared during withdrawal refund"
                        )

                    if not original_tx:
                        raise RuntimeError(
                            "Original withdrawal transaction not found"
                        )

                    refund_amount = _money(current.amount)

                    user.balance = _money(
                        user.balance + refund_amount
                    )

                    original_tx.status = "failed"
                    original_tx.balance_after = user.balance

                    db.session.add(
                        Transaction(
                            user_id=uid,
                            type="mpesa_withdrawal_refund",
                            amount=refund_amount,
                            balance_after=user.balance,
                            description=(
                                "Refund for failed M-PESA withdrawal submission"
                            ),
                            reference=current.reference,
                            status="completed",
                        )
                    )

                    current.status = "failed"
                    current.result_description = str(exc)[:255]

                    db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to refund failed user B2C withdrawal"
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502
'''

if "except B2CSubmissionError as exc:" not in text:
    text = replace_once(
        text,
        old,
        new,
        "wallet.py B2C submission exception block",
    )
    print("wallet.py: patched submission uncertainty/refund handling")
else:
    print("wallet.py: B2C exception block already patched")


# Make /admin status filtering include submission_unknown.
p.write_text(text)


# ============================================================
# 3. admin.py
# ============================================================
p = BASE / "admin.py"
text = p.read_text()

old = '''from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)
'''

new = '''from betting.mpesa import (
    normalize_phone,
    b2c_payment,
    B2CSubmissionError,
)
'''

if "B2CSubmissionError" not in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py mpesa import",
    )
    print("admin.py: added B2CSubmissionError import")
else:
    print("admin.py: B2CSubmissionError import already present")


old = '''                [
                    "pending",
                    "submitted",
                    "processing",
                ]
'''

new = '''                [
                    "pending",
                    "submitted",
                    "processing",
                    "submission_unknown",
                ]
'''

if '"submission_unknown"' not in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py reserved house statuses",
    )
    print("admin.py: added submission_unknown to reserved house statuses")
else:
    print("admin.py: submission_unknown already present somewhere")


old = '''                "submitted",
                "processing",
                "timeout",
                "success",
                "failed",
            }
'''

new = '''                "submitted",
                "processing",
                "submission_unknown",
                "timeout",
                "success",
                "failed",
            }
'''

if '"submission_unknown"' not in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py allowed withdrawal statuses",
    )
    print("admin.py: added submission_unknown to admin filter statuses")
else:
    # Verify the actual filter block contains it.
    if '"submission_unknown"' not in text[
        text.find("allowed_statuses = {"):
        text.find("allowed_statuses = {") + 500
    ]:
        raise SystemExit(
            "ERROR: admin.py allowed status block was not patched correctly"
        )


old = '''        except Exception as exc:

            logger.exception(
                "House B2C submission failed | "
                "withdrawal=%s",
                withdrawal.id,
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

                if current and current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    house = (
                        db.session.query(HouseWallet)
                        .with_for_update()
                        .filter(HouseWallet.id == 1)
                        .first()
                    )

                    if not house:
                        raise RuntimeError(
                            "House wallet is not initialized"
                        )

                    refund_amount = _money(
                        current.amount
                    )

                    house.balance = _money(
                        house.balance
                        + refund_amount
                    )

                    db.session.add(
                        HouseTransaction(
                            type="mpesa_payout_refund",
                            amount=refund_amount,
                            balance_after=house.balance,
                            reference=current.reference,
                            description=(
                                "Refund for failed house "
                                "M-PESA B2C payout submission"
                            ),
                        )
                    )

                    current.status = "failed"
                    current.result_description = str(
                        exc
                    )[:255]

                    db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to refund failed house B2C "
                    "withdrawal"
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502
'''

new = '''        except B2CSubmissionError as exc:

            logger.exception(
                "House B2C submission error | withdrawal=%s | ambiguous=%s",
                withdrawal.id,
                exc.ambiguous,
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
                        "House withdrawal record disappeared during B2C submission"
                    )

                if current.status in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    db.session.commit()

                    return jsonify({
                        "error": "M-PESA B2C request failed",
                        "withdrawal_id": withdrawal.id,
                        "status": current.status,
                    }), 502

                if exc.ambiguous:
                    current.status = "submission_unknown"
                    current.result_description = str(exc)[:255]

                    db.session.commit()

                    logger.warning(
                        "HOUSE B2C submission UNKNOWN | withdrawal=%s | "
                        "funds remain reserved pending callback/reconciliation",
                        withdrawal.id,
                    )

                    return jsonify({
                        "message": (
                            "M-PESA request status is unknown; "
                            "house funds remain reserved pending callback"
                        ),
                        "withdrawal_id": withdrawal.id,
                        "reference": current.reference,
                        "status": current.status,
                    }), 202

                # Non-ambiguous submission error: safe to refund.
                house = (
                    db.session.query(HouseWallet)
                    .with_for_update()
                    .filter(HouseWallet.id == 1)
                    .first()
                )

                if not house:
                    raise RuntimeError(
                        "House wallet is not initialized"
                    )

                refund_amount = _money(current.amount)

                house.balance = _money(
                    house.balance + refund_amount
                )

                db.session.add(
                    HouseTransaction(
                        type="mpesa_payout_refund",
                        amount=refund_amount,
                        balance_after=house.balance,
                        reference=current.reference,
                        description=(
                            "Refund for failed house "
                            "M-PESA B2C payout submission"
                        ),
                    )
                )

                current.status = "failed"
                current.result_description = str(exc)[:255]

                db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to process house B2C submission error | withdrawal=%s",
                    withdrawal.id,
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502

        except Exception as exc:

            logger.exception(
                "House B2C submission failed | "
                "withdrawal=%s",
                withdrawal.id,
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

                if current and current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    house = (
                        db.session.query(HouseWallet)
                        .with_for_update()
                        .filter(HouseWallet.id == 1)
                        .first()
                    )

                    if not house:
                        raise RuntimeError(
                            "House wallet is not initialized"
                        )

                    refund_amount = _money(
                        current.amount
                    )

                    house.balance = _money(
                        house.balance
                        + refund_amount
                    )

                    db.session.add(
                        HouseTransaction(
                            type="mpesa_payout_refund",
                            amount=refund_amount,
                            balance_after=house.balance,
                            reference=current.reference,
                            description=(
                                "Refund for failed house "
                                "M-PESA B2C payout submission"
                            ),
                        )
                    )

                    current.status = "failed"
                    current.result_description = str(
                        exc
                    )[:255]

                    db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to refund failed house B2C "
                    "withdrawal"
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502
'''

if "except B2CSubmissionError as exc:" not in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py B2C submission exception block",
    )
    print("admin.py: patched submission uncertainty/refund handling")
else:
    print("admin.py: B2C exception block already patched")


# ------------------------------------------------------------
# Replace user callback failure block.
# ------------------------------------------------------------
old = '''                else:
                    # ----------------------------------------------
                    # USER PAYOUT FAILURE
                    # ----------------------------------------------
                    user = (
                        db.session.query(User)
                        .with_for_update()
                        .filter(
                            User.id == user_withdrawal.user_id
                        )
                        .first()
                    )

                    if not user:
                        raise RuntimeError(
                            f"User {user_withdrawal.user_id} was not found"
                        )

                    user.balance = (
                        user.balance or 0
                    ) + user_withdrawal.amount

                    user_withdrawal.status = "failed"
                    transaction.status = "failed"
                    transaction.balance_after = user.balance

                    logger.warning(
                        "USER B2C PAYOUT FAILED | id=%s | user_id=%s | "
                        "result_code=%s | amount_refunded=%s",
                        user_withdrawal.id,
                        user_withdrawal.user_id,
                        result_code,
                        user_withdrawal.amount,
                    )
'''

new = '''                else:
                    # ----------------------------------------------
                    # USER PAYOUT FAILURE
                    # ----------------------------------------------
                    refunded = _refund_user_withdrawal(
                        user_withdrawal,
                        reason=(
                            "Refund for failed M-PESA B2C user withdrawal "
                            f"(ResultCode={result_code})"
                        ),
                    )

                    user_withdrawal.status = "failed"

                    logger.warning(
                        "USER B2C PAYOUT FAILED | id=%s | user_id=%s | "
                        "result_code=%s | amount_refunded=%s",
                        user_withdrawal.id,
                        user_withdrawal.user_id,
                        result_code,
                        user_withdrawal.amount if refunded else Decimal("0.00"),
                    )
'''

if "amount_refunded=%s" in text and "refunded = _refund_user_withdrawal(" not in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py user callback failure block",
    )
    print("admin.py: user callback now uses refund helper")


# ------------------------------------------------------------
# Keep internal transaction.reference untouched on success.
# ------------------------------------------------------------
old = '''                    if transaction_id:
                        transaction.reference = transaction_id
'''

new = '''                    # Keep the internal withdrawal reference intact.
                    # Safaricom's final TransactionID belongs in
                    # MpesaWithdrawal.mpesa_receipt.
'''

if old in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py transaction reference overwrite",
    )
    print("admin.py: stopped overwriting internal transaction reference")
elif "Keep the internal withdrawal reference intact." in text:
    print("admin.py: transaction reference overwrite already removed")
else:
    raise SystemExit(
        "ERROR: admin.py user success transaction reference block not found"
    )


# ------------------------------------------------------------
# Fix HOUSE timeout: refund BEFORE marking timeout.
# ------------------------------------------------------------
old = '''                house_withdrawal.status = "timeout"
                house_withdrawal.result_code = result_code
                house_withdrawal.result_description = str(
                    result_description
                    or "M-PESA B2C timeout"
                )[:255]

                if conversation_id:
                    house_withdrawal.conversation_id = str(
                        conversation_id
                    )

                refunded = _refund_house_payout(
                    house_withdrawal,
                    reason="Refund for M-PESA B2C house payout timeout",
                )

                db.session.commit()
'''

new = '''                house_withdrawal.result_code = result_code
                house_withdrawal.result_description = str(
                    result_description
                    or "M-PESA B2C timeout"
                )[:255]

                if conversation_id:
                    house_withdrawal.conversation_id = str(
                        conversation_id
                    )

                refunded = _refund_house_payout(
                    house_withdrawal,
                    reason="Refund for M-PESA B2C house payout timeout",
                )

                house_withdrawal.status = "timeout"

                db.session.commit()
'''

if old in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py house timeout order",
    )
    print("admin.py: fixed house timeout refund order")
elif "house_withdrawal.status = \"timeout\"" in text and text.find("house_withdrawal.status = \"timeout\"") > text.find("_refund_house_payout("):
    print("admin.py: house timeout order appears already fixed")
else:
    raise SystemExit(
        "ERROR: admin.py house timeout block not found"
    )


# ------------------------------------------------------------
# Fix USER timeout: refund BEFORE marking timeout.
# ------------------------------------------------------------
old = '''                user_withdrawal.status = "timeout"
                user_withdrawal.result_code = result_code
                user_withdrawal.result_description = str(
                    result_description
                    or "M-PESA B2C timeout"
                )[:255]

                if conversation_id:
                    user_withdrawal.conversation_id = str(
                        conversation_id
                    )

                _refund_user_withdrawal(
                    user_withdrawal,
                    reason="Refund for M-PESA B2C user withdrawal timeout",
                )

                db.session.commit()
'''

new = '''                user_withdrawal.result_code = result_code
                user_withdrawal.result_description = str(
                    result_description
                    or "M-PESA B2C timeout"
                )[:255]

                if conversation_id:
                    user_withdrawal.conversation_id = str(
                        conversation_id
                    )

                refunded = _refund_user_withdrawal(
                    user_withdrawal,
                    reason="Refund for M-PESA B2C user withdrawal timeout",
                )

                user_withdrawal.status = "timeout"

                db.session.commit()
'''

if old in text:
    text = replace_once(
        text,
        old,
        new,
        "admin.py user timeout order",
    )
    print("admin.py: fixed user timeout refund order")
else:
    # Already patched case.
    snippet = text[
        max(0, text.find("user_withdrawal.result_code = result_code") - 100):
        text.find("user_withdrawal.result_code = result_code") + 1200
    ]
    if (
        "refunded = _refund_user_withdrawal(" not in snippet
        or 'user_withdrawal.status = "timeout"' not in snippet
    ):
        raise SystemExit(
            "ERROR: admin.py user timeout block not found"
        )


# ------------------------------------------------------------
# Add explicit refund transaction to _refund_user_withdrawal.
# ------------------------------------------------------------
old = '''        user.balance = (user.balance or 0) + withdrawal.amount
        transaction.status = "failed"
        transaction.balance_after = user.balance

        return True
'''

new = '''        refund_amount = _money(withdrawal.amount)

        user.balance = _money(
            (user.balance or 0) + refund_amount
        )

        transaction.status = "failed"
        transaction.balance_after = user.balance

        db.session.add(
            Transaction(
                user_id=withdrawal.user_id,
                type="mpesa_withdrawal_refund",
                amount=refund_amount,
                balance_after=user.balance,
                description=reason,
                reference=withdrawal.reference,
                status="completed",
            )
        )

        return True
'''

if "type=\"mpesa_withdrawal_refund\"" not in text[
    text.find("def _refund_user_withdrawal"):
    text.find("@app.route(\"/mpesa/b2c/result\"")
]:
    text = replace_once(
        text,
        old,
        new,
        "admin.py user refund helper",
    )
    print("admin.py: added explicit user refund transaction")
else:
    print("admin.py: user refund transaction already present")


p.write_text(text)

print()
print("PATCH COMPLETE")
print()
print("Run these checks next:")
print("  python -m py_compile mpesa.py wallet.py admin.py")
print("  grep -n -A12 -B3 'class B2CSubmissionError' mpesa.py")
print("  grep -n -E 'submission_unknown|mpesa_withdrawal_refund' wallet.py admin.py")
print("  grep -n -A10 -B5 'transaction.reference' admin.py")
