"""
Click Merchant API — Card Token operations.
Allows accepting card payments directly on your site (no redirect to Click).

Flow:
  1. Request token: send card number + expire date → Click sends SMS to cardholder
  2. Verify token: send SMS code → token becomes active
  3. Pay with token: charge the card
"""

import hashlib
import time
import httpx
from config import CLICK_MERCHANT_USER_ID, CLICK_SECRET_KEY, CLICK_SERVICE_ID

BASE_URL = "https://api.click.uz/v2/merchant"


def _auth_header() -> dict:
    """Build Click Merchant API auth header."""
    timestamp = str(int(time.time()))
    digest = hashlib.sha1((timestamp + CLICK_SECRET_KEY).encode()).hexdigest()
    auth = f"{CLICK_MERCHANT_USER_ID}:{digest}:{timestamp}"
    return {
        "Auth": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def request_card_token(card_number: str, expire_date: str, temporary: int = 1) -> dict:
    """
    Step 1: Request a card token.
    Click will send SMS code to the cardholder's phone.

    Args:
        card_number: Full card number (e.g. "8600123456789012")
        expire_date: Expiry in MMYY format (e.g. "0399")
        temporary: 1 = one-time token, 0 = permanent token

    Returns: {"card_token": "...", "phone_number": "998***99"}
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/card_token/request",
            headers=_auth_header(),
            json={
                "service_id": int(CLICK_SERVICE_ID),
                "card_number": card_number,
                "expire_date": expire_date,
                "temporary": temporary,
            },
        )
        data = resp.json()
        print(f"[CLICK API] card_token/request: {data}")
        return data


async def verify_card_token(card_token: str, sms_code: str) -> dict:
    """
    Step 2: Verify card token with SMS code.

    Returns: {"card_token": "...", "phone_number": "..."}
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/card_token/verify",
            headers=_auth_header(),
            json={
                "service_id": int(CLICK_SERVICE_ID),
                "card_token": card_token,
                "sms_code": str(sms_code),
            },
        )
        data = resp.json()
        print(f"[CLICK API] card_token/verify: {data}")
        return data


async def pay_with_token(card_token: str, amount: float, transaction_id: str) -> dict:
    """
    Step 3: Charge the card using verified token.

    Returns: {"payment_id": ..., "payment_status": ...}
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/card_token/payment",
            headers=_auth_header(),
            json={
                "service_id": int(CLICK_SERVICE_ID),
                "card_token": card_token,
                "amount": amount,
                "transaction_parameter": transaction_id,
            },
        )
        data = resp.json()
        print(f"[CLICK API] card_token/payment: {data}")
        return data


async def create_invoice(phone_number: str, amount: float, merchant_trans_id: str) -> dict:
    """
    Create invoice — sends push notification to user's Click app.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/invoice/create",
            headers=_auth_header(),
            json={
                "service_id": int(CLICK_SERVICE_ID),
                "amount": amount,
                "phone_number": phone_number,
                "merchant_trans_id": merchant_trans_id,
            },
        )
        data = resp.json()
        print(f"[CLICK API] invoice/create: {data}")
        return data
