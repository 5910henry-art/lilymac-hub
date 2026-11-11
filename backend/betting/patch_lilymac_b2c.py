import os
import re
import shutil
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
FILES = ["mpesa.py", "wallet.py", "admin.py"]

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

def backup(path):
    bak = f"{path}.bak_b2c_{stamp}"
    shutil.copy2(path, bak)
    print(f"BACKUP: {bak}")

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 match, found {count}"
        )
    return text.replace(old, new, 1)

for name in FILES:
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        raise RuntimeError(f"Missing file: {path}")
    backup(path)

mpesa_path = os.path.join(BASE, "mpesa.py")
wallet_path = os.path.join(BASE, "wallet.py")
admin_path = os.path.join(BASE, "admin.py")

mpesa = read(mpesa_path)
wallet = read(wallet_path)
admin = read(admin_path)

# ============================================================
# mpesa.py
# ============================================================

if "class B2CSubmissionError" not in mpesa:
    marker = "logger = logging.getLogger(__name__)"
    if marker not in mpesa:
        raise RuntimeError("mpesa.py: logger marker not found")

    mpesa = replace_once(
        mpesa,
        marker,
        '''logger = logging.getLogger(__name__)


class B2CSubmissionError(RuntimeError):
    """
    Raised when a B2C submission fails.

    ambiguous=True means the HTTP request may have reached Safaricom,
    but the client cannot know whether Safaricom accepted it. In that
    situation the withdrawal must NOT be automatically refunded.
    """

    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = bool(ambiguous)
''',
        "add B2CSubmissionError",
    )
else:
    print("mpesa.py: B2CSubmissionError already exists")

# Only change the B2C POST transport exception, not OAuth/STK exceptions.
old = '''    except requests.RequestException:
        raise RuntimeError("M-PESA B2C request could not be sent")
'''

new = '''    except requests.RequestException as exc:
        logger.exception("M-PESA B2C submission transport error")
        raise B2CSubmissionError(
            "M-PESA B2C submission status is unknown",
            ambiguous=True,
        ) from exc
'''

if old in mpesa:
    mpesa = replace_once(
        mpesa,
        old,
        new,
        "change B2C transport exception",
    )
else:
    print(
        "mpesa.py: exact B2C RequestException block not found; "
        "checking whether it is already patched"
    )
    if "B2C submission status is unknown" not in mpesa:
        raise RuntimeError(
            "mpesa.py: could not patch B2C transport exception"
        )

write(mpesa_path, mpesa)

# ============================================================
# wallet.py
# ============================================================

wallet = read(wallet_path)

# Add B2CSubmissionError to import.
if "from betting.mpesa import (" in wallet:
    block = re.search(
        r"from betting\.mpesa import \(\s*(.*?)\s*\)",
        wallet,
        re.S,
    )

    if block:
        imports = block.group(1)

        if "B2CSubmissionError" not in imports:
            new_imports = imports.rstrip() + ",\n    B2CSubmissionError"
            wallet = (
                wallet[:block.start(1)]
                + new_imports
                + wallet[block.end(1):]
            )
            print("wallet.py: added B2CSubmissionError import")
        else:
            print("wallet.py: B2CSubmissionError import already exists")
    else:
        raise RuntimeError("wallet.py: malformed betting.mpesa import")
else:
    raise RuntimeError("wallet.py: betting.mpesa import not found")

# Replace the broad submission exception handling.
#
# We locate the section beginning with the b2c_payment call and ending
# immediately before the successful submitted-state handling.
start_marker = "        try:\n            result = b2c_payment("
start = wallet.find(start_marker)

if start == -1:
    raise RuntimeError(
        "wallet.py: could not locate b2c_payment submission block"
    )

# Find the next successful-response handling marker.
end_candidates = [
    "        # Save successful submission response",
    "        # Save the successful submission response",
    "        withdrawal.status = \"submitted\"",
]

end = -1
end_marker = None

for marker in end_candidates:
    pos = wallet.find(marker, start)
    if pos != -1 and (end == -1 or pos < end):
        end = pos
        end_marker = marker

if end == -1:
    raise RuntimeError(
        "wallet.py: could not locate end of B2C submission block"
    )

old_block = wallet[start:end]

# Make sure this really contains exception handling before replacing it.
if "except" not in old_block:
    raise RuntimeError(
        "wallet.py: located B2C block has no exception handling"
    )

new_block = '''        try:
            result = b2c_payment(
                phone,
                amount,
                originator_conversation_id=originator_id,
            )

        except B2CSubmissionError as exc:
            db.session.rollback()

            if exc.ambiguous:
                logger.error(
                    "B2C submission status UNKNOWN for withdrawal %s; "
                    "funds remain reserved pending callback/reconciliation",
                    reference,
                )

                withdrawal = (
                    MpesaWithdrawal.query
                    .filter_by(reference=reference)
                    .with_for_update()
                    .first()
                )

                if withdrawal and withdrawal.status not in {
                    "success",
                    "failed",
                    "timeout",
                }:
                    withdrawal.status = "submission_unknown"
                    withdrawal.description = str(exc)
                    db.session.commit()

                return jsonify({
                    "success": False,
                    "status": "submission_unknown",
                    "message": (
                        "M-PESA submission status is unknown. "
                        "Funds remain reserved while the transaction "
                        "is reconciled."
                    ),
                    "reference": reference,
                }), 202

            # Definite rejection: safe to refund.
            withdrawal = (
                MpesaWithdrawal.query
                .filter_by(reference=reference)
                .with_for_update()
                .first()
            )

            if withdrawal and withdrawal.status not in {
                "success",
                "failed",
                "timeout",
            }:
                user = (
                    User.query
                    .filter_by(id=uid)
                    .with_for_update()
                    .first()
                )

                original_tx = (
                    Transaction.query
                    .filter_by(
                        user_id=uid,
                        reference=reference,
                        type="mpesa_withdrawal",
                    )
                    .with_for_update()
                    .first()
                )

                if user and original_tx:
                    user.balance = (
                        to_decimal(user.balance) + amount
                    )
                    original_tx.status = "failed"
                    original_tx.balance_after = user.balance

                    db.session.add(
                        Transaction(
                            user_id=uid,
                            type="mpesa_withdrawal_refund",
                            amount=amount,
                            balance_after=user.balance,
                            description="Refund for rejected M-PESA B2C request",
                            reference=reference,
                            status="completed",
                        )
                    )

                if withdrawal:
                    withdrawal.status = "failed"
                    withdrawal.description = str(exc)

                db.session.commit()

            return jsonify({
                "success": False,
                "message": str(exc),
                "reference": reference,
            }), 502

        except Exception as exc:
            logger.exception(
                "Definite pre-submission B2C failure for %s",
                reference,
            )
            db.session.rollback()

            withdrawal = (
                MpesaWithdrawal.query
                .filter_by(reference=reference)
                .with_for_update()
                .first()
            )

            if withdrawal and withdrawal.status not in {
                "success",
                "failed",
                "timeout",
            }:
                user = (
                    User.query
                    .filter_by(id=uid)
                    .with_for_update()
                    .first()
                )

                original_tx = (
                    Transaction.query
                    .filter_by(
                        user_id=uid,
                        reference=reference,
                        type="mpesa_withdrawal",
                    )
                    .with_for_update()
                    .first()
                )

                if user and original_tx:
                    user.balance = (
                        to_decimal(user.balance) + amount
                    )
                    original_tx.status = "failed"
                    original_tx.balance_after = user.balance

                    db.session.add(
                        Transaction(
                            user_id=uid,
                            type="mpesa_withdrawal_refund",
                            amount=amount,
                            balance_after=user.balance,
                            description="Refund for failed M-PESA B2C submission",
                            reference=reference,
                            status="completed",
                        )
                    )

                withdrawal.status = "failed"
                withdrawal.description = str(exc)
                db.session.commit()

            return jsonify({
                "success": False,
                "message": "M-PESA withdrawal could not be submitted",
                "reference": reference,
            }), 502

'''

wallet = wallet[:start] + new_block + wallet[end:]

write(wallet_path, wallet)

# ============================================================
# admin.py
# ============================================================

admin = read(admin_path)

# Add B2CSubmissionError import.
if "from betting.mpesa import (" in admin:
    block = re.search(
        r"from betting\.mpesa import \(\s*(.*?)\s*\)",
        admin,
        re.S,
    )

    if block:
        imports = block.group(1)

        if "B2CSubmissionError" not in imports:
            new_imports = imports.rstrip() + ",\n    B2CSubmissionError"
            admin = (
                admin[:block.start(1)]
                + new_imports
                + admin[block.end(1):]
            )
            print("admin.py: added B2CSubmissionError import")
        else:
            print("admin.py: B2CSubmissionError import already exists")
    else:
        raise RuntimeError("admin.py: malformed betting.mpesa import")
else:
    raise RuntimeError("admin.py: betting.mpesa import not found")

# ------------------------------------------------------------
# Include submission_unknown in reserved house withdrawals.
# ------------------------------------------------------------

old_reserved = '''{"pending", "submitted", "processing"}'''

if old_reserved in admin:
    admin = replace_once(
        admin,
        old_reserved,
        '''{"pending", "submitted", "processing", "submission_unknown"}''',
        "include submission_unknown in house reservation",
    )
else:
    print(
        "admin.py: reserved-status literal not found; "
        "checking whether already patched"
    )

# ------------------------------------------------------------
# Admin withdrawal status filter.
# ------------------------------------------------------------

old_statuses = '"pending", "submitted", "processing", "timeout", "success", "failed"'
new_statuses = '"pending", "submitted", "processing", "submission_unknown", "timeout", "success", "failed"'

if old_statuses in admin:
    admin = replace_once(
        admin,
        old_statuses,
        new_statuses,
        "add submission_unknown to admin statuses",
    )
elif "submission_unknown" not in admin:
    print(
        "admin.py: status filter literal not found; "
        "it may use a different formatting"
    )

# ------------------------------------------------------------
# Fix user success callback:
# NEVER replace internal reference with Safaricom TransactionID.
# ------------------------------------------------------------

bad_success = "transaction.reference = transaction_id"

if bad_success in admin:
    admin = admin.replace(
        bad_success,
        "# Keep transaction.reference as the internal withdrawal reference.\n"
        "# Safaricom TransactionID belongs in MpesaWithdrawal.mpesa_receipt.",
    )
    print("admin.py: fixed user callback reference overwrite")
else:
    print(
        "admin.py: transaction.reference overwrite already fixed "
        "or not present"
    )

# ------------------------------------------------------------
# Replace direct user callback failure refund with helper.
# ------------------------------------------------------------

failure_pattern = re.compile(
    r'''
(?P<indent>\s*)
user\s*=\s*\(
\s*User\.query
.*?
(?P<log>\s*logger\.(?:warning|info|error)\(
\s*["'].*?B2C.*?
.*?
\)\s*)
''',
    re.S | re.X,
)

# We do a more targeted replacement using the known duplicated block.
old_user_failure = '''            user = (
                User.query
                .filter_by(id=user_withdrawal.user_id)
                .with_for_update()
                .first()
            )

            transaction = (
                Transaction.query
                .filter_by(
                    user_id=user_withdrawal.user_id,
                    reference=user_withdrawal.reference,
                    type="mpesa_withdrawal",
                )
                .with_for_update()
                .first()
            )

            refunded = False

            if user and transaction:
                user.balance = (
                    to_decimal(user.balance) + user_withdrawal.amount
                )
                transaction.status = "failed"
                transaction.balance_after = user.balance
                refunded = True

            user_withdrawal.status = "failed"
            user_withdrawal.result_code = result_code
            user_withdrawal.result_description = result_description

            db.session.commit()

            logger.warning(
                "User B2C payout failed: %s amount=%s refunded=%s",
                result_code,
                user_withdrawal.amount,
                refunded,
            )
'''

new_user_failure = '''            refunded = _refund_user_withdrawal(
                user_withdrawal,
                reason=(
                    f"M-PESA B2C callback failure "
                    f"ResultCode={result_code}: {result_description}"
                ),
            )

            user_withdrawal.status = "failed"
            user_withdrawal.result_code = result_code
            user_withdrawal.result_description = result_description

            db.session.commit()

            logger.warning(
                "User B2C payout failed: %s amount=%s refunded=%s",
                result_code,
                user_withdrawal.amount,
                refunded,
            )
'''

if old_user_failure in admin:
    admin = replace_once(
        admin,
        old_user_failure,
        new_user_failure,
        "user callback failure refund helper",
    )
else:
    print(
        "admin.py: exact user callback failure block not found. "
        "This may already be patched or formatted differently."
    )

# ------------------------------------------------------------
# Make _refund_user_withdrawal create an explicit refund ledger entry.
# ------------------------------------------------------------

helper_start = admin.find("def _refund_user_withdrawal(")

if helper_start == -1:
    raise RuntimeError(
        "admin.py: _refund_user_withdrawal() not found"
    )

next_def = admin.find("\ndef ", helper_start + 5)

if next_def == -1:
    helper_end = len(admin)
else:
    helper_end = next_def + 1

helper = admin[helper_start:helper_end]

if "mpesa_withdrawal_refund" not in helper:
    marker = '''            original_tx.status = "failed"
            original_tx.balance_after = user.balance
'''

    if marker not in helper:
        raise RuntimeError(
            "admin.py: could not locate user refund helper transaction block"
        )

    replacement = marker + '''
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
'''

    helper = replace_once(
        helper,
        marker,
        replacement,
        "add callback/timeout refund transaction",
    )

    admin = admin[:helper_start] + helper + admin[helper_end:]
    print("admin.py: added explicit user refund transaction")
else:
    print("admin.py: user refund transaction already exists")

# ------------------------------------------------------------
# Fix timeout callbacks.
#
# The refund helper must run BEFORE setting status=timeout,
# because the helper intentionally refuses to refund final states.
# ------------------------------------------------------------

old_house_timeout = '''            house_withdrawal.status = "timeout"
            house_withdrawal.result_code = result_code
            house_withdrawal.result_description = result_description

            _refund_house_payout(
                house_withdrawal,
                reason="M-PESA B2C timeout",
            )

            db.session.commit()
'''

new_house_timeout = '''            house_withdrawal.result_code = result_code
            house_withdrawal.result_description = result_description

            _refund_house_payout(
                house_withdrawal,
                reason="M-PESA B2C timeout",
            )

            house_withdrawal.status = "timeout"

            db.session.commit()
'''

if old_house_timeout in admin:
    admin = replace_once(
        admin,
        old_house_timeout,
        new_house_timeout,
        "fix house timeout refund ordering",
    )
else:
    print(
        "admin.py: house timeout block not found; "
        "checking whether already fixed"
    )

old_user_timeout = '''            user_withdrawal.status = "timeout"
            user_withdrawal.result_code = result_code
            user_withdrawal.result_description = result_description

            _refund_user_withdrawal(
                user_withdrawal,
                reason="M-PESA B2C timeout",
            )

            db.session.commit()
'''

new_user_timeout = '''            user_withdrawal.result_code = result_code
            user_withdrawal.result_description = result_description

            _refund_user_withdrawal(
                user_withdrawal,
                reason="M-PESA B2C timeout",
            )

            user_withdrawal.status = "timeout"

            db.session.commit()
'''

if old_user_timeout in admin:
    admin = replace_once(
        admin,
        old_user_timeout,
        new_user_timeout,
        "fix user timeout refund ordering",
    )
else:
    print(
        "admin.py: user timeout block not found; "
        "checking whether already fixed"
    )

# ------------------------------------------------------------
# House B2C submission handling.
#
# We locate the b2c_payment() call inside the house payout route
# and add the ambiguous submission branch if it isn't already there.
# ------------------------------------------------------------

if "submission_unknown" not in admin:
    raise RuntimeError(
        "admin.py: submission_unknown was not added successfully"
    )

# Find the house payout route.
house_route_start = admin.find("/admin/house-mpesa/payout")

if house_route_start == -1:
    raise RuntimeError(
        "admin.py: house payout route not found"
    )

# Find its b2c_payment call.
house_call = admin.find("b2c_payment(", house_route_start)

if house_call == -1:
    raise RuntimeError(
        "admin.py: house payout b2c_payment call not found"
    )

# Find the surrounding except Exception block.
house_except = admin.find(
    "        except Exception as exc:",
    house_call,
)

if house_except == -1:
    house_except = admin.find(
        "    except Exception as exc:",
        house_call,
    )

if house_except == -1:
    raise RuntimeError(
        "admin.py: house payout exception block not found"
    )

# Locate the next return after the exception block.
house_return = admin.find(
    "        return jsonify",
    house_except,
)

if house_return == -1:
    house_return = admin.find(
        "    return jsonify",
        house_except,
    )

# If already patched, don't insert a duplicate.
house_exception_region = admin[house_except:house_return if house_return != -1 else house_except + 5000]

if "B2CSubmissionError" not in house_exception_region:
    old_except_prefix = admin[house_except:house_except + len("        except Exception as exc:")]

    new_except_prefix = '''        except B2CSubmissionError as exc:
            db.session.rollback()

            if exc.ambiguous:
                logger.error(
                    "House B2C submission status UNKNOWN for withdrawal %s; "
                    "funds remain reserved pending callback/reconciliation",
                    house_withdrawal.reference,
                )

                locked = (
                    HouseMpesaWithdrawal.query
                    .filter_by(reference=house_withdrawal.reference)
                    .with_for_update()
                    .first()
                )

                if locked and locked.status not in {
                    "success",
                    "failed",
                    "timeout",
                }:
                    locked.status = "submission_unknown"
                    locked.description = str(exc)
                    db.session.commit()

                return jsonify({
                    "success": False,
                    "status": "submission_unknown",
                    "message": (
                        "M-PESA submission status is unknown. "
                        "House funds remain reserved pending reconciliation."
                    ),
                    "reference": house_withdrawal.reference,
                }), 202

            raise
'''

    admin = (
        admin[:house_except]
        + new_except_prefix
        + admin[house_except + len("        except Exception as exc:"):]
    )

    print("admin.py: added ambiguous house B2C handling")
else:
    print("admin.py: house ambiguous B2C handling already exists")

write(admin_path, admin)

print("\nALL TEXT PATCHES APPLIED.")
print("Backups created with suffix:")
print(f"  .bak_b2c_{stamp}")
