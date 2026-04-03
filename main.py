from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
from datetime import datetime

from config import CLICK_SERVICE_ID, BASE_URL, SUBSCRIPTION_PRICE
from database import init_db, get_db, Order, OrderStatus
from click_service import handle_prepare, handle_complete
from click_merchant_api import request_card_token, verify_card_token, pay_with_token, check_payment_status
import asyncio

app = FastAPI(title="Click Payment Test")
templates = Environment(loader=FileSystemLoader("templates"), autoescape=True)


@app.on_event("startup")
def startup():
    init_db()
    print(f"Server started at {BASE_URL}")
    print(f"Subscription price: {SUBSCRIPTION_PRICE} so'm")


# ─── Pages ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home(db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.created_at.desc()).limit(20).all()
    template = templates.get_template("index.html")
    return template.render(orders=orders, price=SUBSCRIPTION_PRICE, OrderStatus=OrderStatus)


@app.get("/payment-result/{order_id}", response_class=HTMLResponse)
def payment_result(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    template = templates.get_template("result.html")
    return template.render(order=order, OrderStatus=OrderStatus)


# ─── Card Token Payment Flow (on-site) ───────────────────

@app.post("/api/create-order")
def api_create_order(email: str = Form(...), db: Session = Depends(get_db)):
    """Create order and return order ID."""
    order = Order(
        user_email=email,
        amount=SUBSCRIPTION_PRICE,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    print(f"[ORDER] #{order.id} created for {email} — {order.amount} so'm")
    return {"order_id": order.id, "amount": order.amount}


@app.post("/api/card-token/request")
async def api_request_token(
    order_id: int = Form(...),
    card_number: str = Form(...),
    expire_date: str = Form(...),
    db: Session = Depends(get_db),
):
    """Step 1: Send card info to Click, get token, SMS sent to cardholder."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return JSONResponse({"error": "Order not found"}, status_code=404)
    if order.status == OrderStatus.PAID:
        return JSONResponse({"error": "Already paid"}, status_code=400)

    # Clean card number (remove spaces)
    card_number = card_number.replace(" ", "")

    result = await request_card_token(card_number, expire_date)

    if result.get("error_code", -1) != 0:
        return JSONResponse({
            "error": result.get("error_note", "Card token request failed"),
            "error_code": result.get("error_code"),
        }, status_code=400)

    # Save token to order
    order.card_token = result["card_token"]
    db.commit()

    return {
        "success": True,
        "phone_number": result.get("phone_number", "***"),
        "card_token": result["card_token"],
    }


@app.post("/api/card-token/verify")
async def api_verify_token(
    order_id: int = Form(...),
    sms_code: str = Form(...),
    db: Session = Depends(get_db),
):
    """Step 2: Verify SMS code."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or not order.card_token:
        return JSONResponse({"error": "Order or token not found"}, status_code=404)

    result = await verify_card_token(order.card_token, sms_code)

    if result.get("error_code", -1) != 0:
        return JSONResponse({
            "error": result.get("error_note", "SMS verification failed"),
            "error_code": result.get("error_code"),
        }, status_code=400)

    return {"success": True}


@app.post("/api/card-token/pay")
async def api_pay_with_token(
    order_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Step 3: Charge the card."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or not order.card_token:
        return JSONResponse({"error": "Order or token not found"}, status_code=404)
    if order.status == OrderStatus.PAID:
        return JSONResponse({"error": "Already paid"}, status_code=400)

    result = await pay_with_token(order.card_token, order.amount, str(order.id))

    error_code = result.get("error_code", -1)
    payment_id = result.get("payment_id")

    # -501 means payment status unknown — check status after a short delay
    if error_code == -501 and payment_id:
        order.payment_id = payment_id
        db.commit()
        await asyncio.sleep(2)
        status = await check_payment_status(str(payment_id))
        payment_status = status.get("payment_status")
        if payment_status == 2:  # 2 = successful
            order.status = OrderStatus.PAID
            order.paid_at = datetime.utcnow()
            db.commit()
            print(f"[PAYMENT] Order #{order.id} PAID (after status check) — payment_id: {payment_id}")
            return {"success": True, "payment_id": payment_id}
        else:
            order.status = OrderStatus.WAITING
            db.commit()
            print(f"[PAYMENT] Order #{order.id} status unknown — payment_status: {payment_status}")
            return {"success": True, "payment_id": payment_id, "status": "pending"}

    if error_code != 0:
        order.status = OrderStatus.CANCELLED
        db.commit()
        return JSONResponse({
            "error": result.get("error_note", "Payment failed"),
            "error_code": error_code,
        }, status_code=400)

    # Payment successful
    order.status = OrderStatus.PAID
    order.payment_id = payment_id
    order.paid_at = datetime.utcnow()
    db.commit()

    print(f"[PAYMENT] Order #{order.id} PAID — payment_id: {payment_id}")

    return {"success": True, "payment_id": payment_id}


# ─── Click SHOP-API Callbacks (kept for compatibility) ────

@app.post("/click/prepare")
async def click_prepare(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = dict(form)
    print(f"[CLICK PREPARE] {data}")
    return handle_prepare(data, db)


@app.post("/click/complete")
async def click_complete(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = dict(form)
    print(f"[CLICK COMPLETE] {data}")
    return handle_complete(data, db)


# ─── Test simulate (kept) ─────────────────────────────────

@app.post("/test/simulate-payment/{order_id}")
def simulate_payment(order_id: int, db: Session = Depends(get_db)):
    import hashlib
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return {"error": "Order not found"}
    if order.status == OrderStatus.PAID:
        return {"error": "Already paid"}

    from config import CLICK_SECRET_KEY
    click_trans_id = 100000 + order_id
    sign_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    prepare_sign = hashlib.md5(
        f"{click_trans_id}{CLICK_SERVICE_ID}{CLICK_SECRET_KEY}"
        f"{order_id}{order.amount}{0}{sign_time}".encode()
    ).hexdigest()
    prepare_data = {
        "click_trans_id": str(click_trans_id), "service_id": str(CLICK_SERVICE_ID),
        "click_paydoc_id": str(200000 + order_id), "merchant_trans_id": str(order_id),
        "amount": str(order.amount), "action": "0", "error": "0", "error_note": "",
        "sign_time": sign_time, "sign_string": prepare_sign,
    }
    prepare_result = handle_prepare(prepare_data, db)
    if prepare_result["error"] != 0:
        return {"step": "prepare", "error": prepare_result}

    merchant_prepare_id = prepare_result["merchant_prepare_id"]
    complete_sign = hashlib.md5(
        f"{click_trans_id}{CLICK_SERVICE_ID}{CLICK_SECRET_KEY}"
        f"{order_id}{merchant_prepare_id}{order.amount}{1}{sign_time}".encode()
    ).hexdigest()
    complete_data = {
        "click_trans_id": str(click_trans_id), "service_id": str(CLICK_SERVICE_ID),
        "click_paydoc_id": str(200000 + order_id), "merchant_trans_id": str(order_id),
        "merchant_prepare_id": str(merchant_prepare_id), "amount": str(order.amount),
        "action": "1", "error": "0", "error_note": "", "sign_time": sign_time,
        "sign_string": complete_sign,
    }
    complete_result = handle_complete(complete_data, db)
    return {"prepare": prepare_result, "complete": complete_result, "order_status": order.status}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
