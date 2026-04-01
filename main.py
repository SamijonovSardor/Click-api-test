from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
from urllib.parse import urlencode

from config import (
    CLICK_MERCHANT_ID,
    CLICK_SERVICE_ID,
    BASE_URL,
    SUBSCRIPTION_PRICE,
)
from database import init_db, get_db, Order, OrderStatus
from click_service import handle_prepare, handle_complete

app = FastAPI(title="Click Payment Test")
templates = Environment(loader=FileSystemLoader("templates"), autoescape=True)


@app.on_event("startup")
def startup():
    init_db()
    print(f"Server started at {BASE_URL}")
    print(f"Merchant ID: {CLICK_MERCHANT_ID}")
    print(f"Service ID: {CLICK_SERVICE_ID}")
    print(f"Subscription price: {SUBSCRIPTION_PRICE} so'm")


# ─── Pages ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home(db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.created_at.desc()).limit(20).all()
    template = templates.get_template("index.html")
    return template.render(
        orders=orders,
        price=SUBSCRIPTION_PRICE,
        OrderStatus=OrderStatus,
    )


@app.post("/create-order")
def create_order(email: str = Form(...), db: Session = Depends(get_db)):
    """Create order and redirect to Click payment page."""
    order = Order(
        user_email=email,
        amount=SUBSCRIPTION_PRICE,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Build Click payment URL
    params = {
        "service_id": CLICK_SERVICE_ID,
        "merchant_id": CLICK_MERCHANT_ID,
        "amount": f"{order.amount:.2f}",
        "transaction_param": str(order.id),
        "return_url": f"{BASE_URL}/payment-result/{order.id}",
    }
    click_url = f"https://my.click.uz/services/pay?{urlencode(params)}"

    print(f"[ORDER] #{order.id} created for {email} — {order.amount} so'm")
    print(f"[ORDER] Payment URL: {click_url}")

    return RedirectResponse(url=click_url, status_code=303)


@app.get("/payment-result/{order_id}", response_class=HTMLResponse)
def payment_result(order_id: int, db: Session = Depends(get_db)):
    """Return page after Click payment (redirect from Click)."""
    order = db.query(Order).filter(Order.id == order_id).first()
    template = templates.get_template("result.html")
    return template.render(order=order, OrderStatus=OrderStatus)


@app.get("/order/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, db: Session = Depends(get_db)):
    """Check order status."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return HTMLResponse("<h1>Order not found</h1>", status_code=404)
    template = templates.get_template("result.html")
    return template.render(order=order, OrderStatus=OrderStatus)


# ─── Click SHOP-API Callbacks ─────────────────────────────

@app.post("/click/prepare")
async def click_prepare(request: Request, db: Session = Depends(get_db)):
    """
    Click Prepare callback (action=0).
    Click sends form-encoded POST data.
    """
    form = await request.form()
    data = dict(form)
    print(f"[CLICK PREPARE] Received: {data}")
    result = handle_prepare(data, db)
    print(f"[CLICK PREPARE] Response: {result}")
    return result


@app.post("/click/complete")
async def click_complete(request: Request, db: Session = Depends(get_db)):
    """
    Click Complete callback (action=1).
    Click sends form-encoded POST data.
    """
    form = await request.form()
    data = dict(form)
    print(f"[CLICK COMPLETE] Received: {data}")
    result = handle_complete(data, db)
    print(f"[CLICK COMPLETE] Response: {result}")
    return result


# ─── Test Endpoint (simulate Click callbacks locally) ─────

@app.post("/test/simulate-payment/{order_id}")
def simulate_payment(order_id: int, db: Session = Depends(get_db)):
    """
    Simulate a full Click payment flow for testing.
    This mimics what Click would send to Prepare/Complete endpoints.
    """
    import hashlib
    from datetime import datetime

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return {"error": "Order not found"}
    if order.status == OrderStatus.PAID:
        return {"error": "Already paid"}

    from config import CLICK_SECRET_KEY

    click_trans_id = 100000 + order_id  # Fake Click trans ID
    sign_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Step 1: Simulate Prepare
    prepare_sign = hashlib.md5(
        f"{click_trans_id}{CLICK_SERVICE_ID}{CLICK_SECRET_KEY}"
        f"{order_id}{order.amount}{0}{sign_time}".encode()
    ).hexdigest()

    prepare_data = {
        "click_trans_id": str(click_trans_id),
        "service_id": str(CLICK_SERVICE_ID),
        "click_paydoc_id": str(200000 + order_id),
        "merchant_trans_id": str(order_id),
        "amount": str(order.amount),
        "action": "0",
        "error": "0",
        "error_note": "",
        "sign_time": sign_time,
        "sign_string": prepare_sign,
    }

    prepare_result = handle_prepare(prepare_data, db)

    if prepare_result["error"] != 0:
        return {"step": "prepare", "error": prepare_result}

    # Step 2: Simulate Complete
    merchant_prepare_id = prepare_result["merchant_prepare_id"]
    complete_sign = hashlib.md5(
        f"{click_trans_id}{CLICK_SERVICE_ID}{CLICK_SECRET_KEY}"
        f"{order_id}{merchant_prepare_id}{order.amount}{1}{sign_time}".encode()
    ).hexdigest()

    complete_data = {
        "click_trans_id": str(click_trans_id),
        "service_id": str(CLICK_SERVICE_ID),
        "click_paydoc_id": str(200000 + order_id),
        "merchant_trans_id": str(order_id),
        "merchant_prepare_id": str(merchant_prepare_id),
        "amount": str(order.amount),
        "action": "1",
        "error": "0",
        "error_note": "",
        "sign_time": sign_time,
        "sign_string": complete_sign,
    }

    complete_result = handle_complete(complete_data, db)

    return {
        "prepare": prepare_result,
        "complete": complete_result,
        "order_status": order.status,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
