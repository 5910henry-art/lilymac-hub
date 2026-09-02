# mpesa.py

import base64
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

MPESA_ENV = os.environ.get("MPESA_ENV", "sandbox").strip().lower()

if MPESA_ENV == "production":
    MPESA_BASE_URL = "https://api.safaricom.co.ke"
else:
    MPESA_BASE_URL = "https://sandbox.safaricom.co.ke"


MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "").strip()
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "").strip()
MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "").strip()
MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "").strip()
MPESA_CALLBACK_URL = os.environ.get("MPESA_CALLBACK_URL", "").strip()


# ============================================================
# PHONE NORMALIZATION
# ============================================================

def normalize_phone(phone):
    """
    Convert common Kenyan phone formats to:

        2547XXXXXXXX

    Accepted examples:

        0712345678
        712345678
        254712345678
        +254712345678
    """

    if phone is None:
        raise ValueError("phone number is required")

    value = str(phone).strip()

    # Remove spaces, +, -, parentheses, etc.
    digits = re.sub(r"\D", "", value)

    if digits.startswith("0"):
        digits = "254" + digits[1:]

    elif digits.startswith("7") or digits.startswith("1"):
        digits = "254" + digits

    # Already 254...
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValueError("invalid Kenyan phone number")

    return digits


# ============================================================
# CONFIG VALIDATION
# ============================================================

def _validate_config():
    missing = []

    if not MPESA_CONSUMER_KEY:
        missing.append("MPESA_CONSUMER_KEY")

    if not MPESA_CONSUMER_SECRET:
        missing.append("MPESA_CONSUMER_SECRET")

    if not MPESA_SHORTCODE:
        missing.append("MPESA_SHORTCODE")

    if not MPESA_PASSKEY:
        missing.append("MPESA_PASSKEY")

    if not MPESA_CALLBACK_URL:
        missing.append("MPESA_CALLBACK_URL")

    if missing:
        raise RuntimeError(
            "Missing M-PESA environment variables: "
            + ", ".join(missing)
        )


# ============================================================
# OAUTH ACCESS TOKEN
# ============================================================

def get_access_token():
    """
    Obtain a Daraja OAuth access token.
    """

    _validate_config()

    url = (
        f"{MPESA_BASE_URL}"
        "/oauth/v1/generate"
        "?grant_type=client_credentials"
    )

    try:
        response = requests.get(
            url,
            auth=(
                MPESA_CONSUMER_KEY,
                MPESA_CONSUMER_SECRET,
            ),
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        token = data.get("access_token")

        if not token:
            logger.error(
                "M-PESA OAuth response did not contain access_token: %s",
                data,
            )
            raise RuntimeError(
                "M-PESA authentication failed"
            )

        return token

    except requests.RequestException as exc:
        logger.exception(
            "M-PESA OAuth request failed: %s",
            exc,
        )
        raise RuntimeError(
            "M-PESA authentication request failed"
        ) from exc


# ============================================================
# STK PASSWORD
# ============================================================

def generate_stk_password():
    """
    Generate the Daraja STK password.

    Password =
        Base64(
            BusinessShortCode +
            PassKey +
            Timestamp
        )

    Timestamp is generated once and returned together with
    the password so the two cannot become mismatched.
    """

    _validate_config()

    timestamp = datetime.now(
        ZoneInfo("Africa/Nairobi")
    ).strftime("%Y%m%d%H%M%S")

    raw = (
        f"{MPESA_SHORTCODE}"
        f"{MPESA_PASSKEY}"
        f"{timestamp}"
    )

    password = base64.b64encode(
        raw.encode("utf-8")
    ).decode("utf-8")

    return password, timestamp


# ============================================================
# STK PUSH
# ============================================================

def stk_push(
    phone,
    amount,
    account_reference,
    transaction_description="Lilymac wallet deposit",
):
    """
    Send an M-PESA STK Push.

    Returns the decoded Safaricom response.
    """

    _validate_config()

    phone = normalize_phone(phone)

    # Daraja STK amount is a whole-number KES amount.
    amount = int(amount)

    if amount <= 0:
        raise ValueError("amount must be greater than zero")

    token = get_access_token()

    password, timestamp = generate_stk_password()

    url = (
        f"{MPESA_BASE_URL}"
        "/mpesa/stkpush/v1/processrequest"
    )

    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": MPESA_SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": MPESA_CALLBACK_URL,
        "AccountReference": str(account_reference)[:12],
        "TransactionDesc": str(
            transaction_description
        )[:100],
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30,
        )

        # Safaricom normally returns JSON even for errors.
        try:
            data = response.json()
        except ValueError:
            data = {
                "error": response.text
            }

        if response.status_code >= 400:
            logger.error(
                "M-PESA STK HTTP error | status=%s | response=%s",
                response.status_code,
                data,
            )

            raise RuntimeError(
                data.get(
                    "errorMessage",
                    "M-PESA STK request failed",
                )
            )

        logger.info(
            "M-PESA STK response | phone=%s | amount=%s | response=%s",
            phone,
            amount,
            data,
        )

        return data

    except requests.RequestException as exc:
        logger.exception(
            "M-PESA STK request failed: %s",
            exc,
        )

        raise RuntimeError(
            "M-PESA STK request could not be sent"
        ) from exc
