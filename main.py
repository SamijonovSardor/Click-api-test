from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
from datetime import datetime

from config import CLICK_MERCHANT_ID, CLICK_SERVICE_ID, BASE_URL, SUBSCRIPTION_PRICE
from database import init_db, get_db, Order, OrderStatus
from click_service import handle_prepare, handle_complete

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


# ─── Create order and redirect to Click ──────────────────

@app.post("/api/create-order")
def api_create_order(email: str = Form(...), db: Session = Depends(get_db)):
    """Create order and redirect to Click payment page."""
    order = Order(
        user_email=email,
        amount=SUBSCRIPTION_PRICE,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    print(f"[ORDER] #{order.id} created for {email} — {order.amount} so'm")

    # Build Click payment URL
    click_url = (
        f"https://my.click.uz/services/pay"
        f"?service_id={CLICK_SERVICE_ID}"
        f"&merchant_id={CLICK_MERCHANT_ID}"
        f"&amount={int(order.amount)}"
        f"&transaction_param={order.id}"
        f"&return_url={BASE_URL}/payment-result/{order.id}"
    )

    return RedirectResponse(url=click_url, status_code=303)


# ─── Click SHOP-API Callbacks ────────────────────────────

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
