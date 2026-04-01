"""
Click.uz SHOP-API (Prepare/Complete) handler.

Click sends POST requests to our server:
  1. Prepare (action=0) — validate order before charging
  2. Complete (action=1) — confirm payment after charging

Sign verification:
  Prepare:  md5(click_trans_id + service_id + secret_key + merchant_trans_id + amount + action + sign_time)
  Complete: md5(click_trans_id + service_id + secret_key + merchant_trans_id + merchant_prepare_id + amount + action + sign_time)
"""

import hashlib
from datetime import datetime
from sqlalchemy.orm import Session
from database import Order, OrderStatus
from config import CLICK_SECRET_KEY, CLICK_SERVICE_ID


# ─── Error codes ──────────────────────────────────────────
ERROR_SUCCESS = 0
ERROR_SIGN_CHECK_FAILED = -1
ERROR_INCORRECT_AMOUNT = -2
ERROR_ACTION_NOT_FOUND = -3
ERROR_ALREADY_PAID = -4
ERROR_USER_NOT_FOUND = -5
ERROR_TRANSACTION_NOT_FOUND = -6
ERROR_UPDATE_FAILED = -7
ERROR_BAD_REQUEST = -8
ERROR_CANCELLED = -9


def verify_sign(data: dict, action: int) -> bool:
    """Verify Click's sign_string."""
    if action == 0:
        # Prepare
        sign_source = (
            f"{data['click_trans_id']}"
            f"{data['service_id']}"
            f"{CLICK_SECRET_KEY}"
            f"{data['merchant_trans_id']}"
            f"{data['amount']}"
            f"{data['action']}"
            f"{data['sign_time']}"
        )
    else:
        # Complete
        sign_source = (
            f"{data['click_trans_id']}"
            f"{data['service_id']}"
            f"{CLICK_SECRET_KEY}"
            f"{data['merchant_trans_id']}"
            f"{data['merchant_prepare_id']}"
            f"{data['amount']}"
            f"{data['action']}"
            f"{data['sign_time']}"
        )

    expected = hashlib.md5(sign_source.encode("utf-8")).hexdigest()
    return expected == data.get("sign_string", "")


def handle_prepare(data: dict, db: Session) -> dict:
    """
    Handle Prepare request (action=0).
    Validate order and return merchant_prepare_id.
    """
    click_trans_id = int(data["click_trans_id"])
    merchant_trans_id = data["merchant_trans_id"]
    amount = float(data["amount"])
    action = int(data["action"])

    # 1. Verify signature
    if not verify_sign(data, action):
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": 0,
            "error": ERROR_SIGN_CHECK_FAILED,
            "error_note": "SIGN CHECK FAILED",
        }

    # 2. Find order
    order = db.query(Order).filter(Order.id == int(merchant_trans_id)).first()
    if not order:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": 0,
            "error": ERROR_USER_NOT_FOUND,
            "error_note": "Order not found",
        }

    # 3. Check if already paid
    if order.status == OrderStatus.PAID:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": 0,
            "error": ERROR_ALREADY_PAID,
            "error_note": "Already paid",
        }

    # 4. Verify amount
    if abs(order.amount - amount) > 0.01:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": 0,
            "error": ERROR_INCORRECT_AMOUNT,
            "error_note": "Incorrect amount",
        }

    # 5. Save Click data and update status
    order.click_trans_id = click_trans_id
    order.click_paydoc_id = int(data.get("click_paydoc_id", 0))
    order.status = OrderStatus.WAITING
    order.merchant_prepare_id = order.id  # Use order ID as prepare ID
    db.commit()

    print(f"[PREPARE] Order #{order.id} — waiting for payment ({amount} so'm)")

    return {
        "click_trans_id": click_trans_id,
        "merchant_trans_id": merchant_trans_id,
        "merchant_prepare_id": order.merchant_prepare_id,
        "error": ERROR_SUCCESS,
        "error_note": "Success",
    }


def handle_complete(data: dict, db: Session) -> dict:
    """
    Handle Complete request (action=1).
    Confirm or cancel payment based on Click's error code.
    """
    click_trans_id = int(data["click_trans_id"])
    merchant_trans_id = data["merchant_trans_id"]
    merchant_prepare_id = int(data.get("merchant_prepare_id", 0))
    amount = float(data["amount"])
    action = int(data["action"])
    click_error = int(data.get("error", 0))

    # 1. Verify signature
    if not verify_sign(data, action):
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": None,
            "error": ERROR_SIGN_CHECK_FAILED,
            "error_note": "SIGN CHECK FAILED",
        }

    # 2. Find order
    order = db.query(Order).filter(Order.id == int(merchant_trans_id)).first()
    if not order:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": None,
            "error": ERROR_USER_NOT_FOUND,
            "error_note": "Order not found",
        }

    # 3. Verify prepare_id matches
    if order.merchant_prepare_id != merchant_prepare_id:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": None,
            "error": ERROR_TRANSACTION_NOT_FOUND,
            "error_note": "Prepare ID mismatch",
        }

    # 4. Check if already paid
    if order.status == OrderStatus.PAID:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": order.merchant_confirm_id,
            "error": ERROR_ALREADY_PAID,
            "error_note": "Already paid",
        }

    # 5. Process result
    if click_error < 0:
        # Payment failed on Click side — cancel
        order.status = OrderStatus.CANCELLED
        db.commit()
        print(f"[COMPLETE] Order #{order.id} — CANCELLED (Click error: {click_error})")
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": None,
            "error": ERROR_CANCELLED,
            "error_note": "Transaction cancelled",
        }

    # Payment succeeded
    order.status = OrderStatus.PAID
    order.paid_at = datetime.utcnow()
    order.merchant_confirm_id = order.id
    db.commit()

    print(f"[COMPLETE] Order #{order.id} — PAID ({amount} so'm)")

    return {
        "click_trans_id": click_trans_id,
        "merchant_trans_id": merchant_trans_id,
        "merchant_confirm_id": order.merchant_confirm_id,
        "error": ERROR_SUCCESS,
        "error_note": "Success",
    }
