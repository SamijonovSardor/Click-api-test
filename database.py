from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Enum as SAEnum
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import enum

engine = create_engine("sqlite:///payments.db", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    WAITING = "waiting"       # Prepare received, waiting for Complete
    PAID = "paid"             # Complete received with success
    CANCELLED = "cancelled"   # Complete received with error
    REFUNDED = "refunded"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_email = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default=OrderStatus.PENDING)

    # Click transaction data
    click_trans_id = Column(Integer, nullable=True)
    click_paydoc_id = Column(Integer, nullable=True)
    merchant_prepare_id = Column(Integer, nullable=True)
    merchant_confirm_id = Column(Integer, nullable=True)
    card_token = Column(String, nullable=True)
    payment_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
