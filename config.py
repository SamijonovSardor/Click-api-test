import os
from dotenv import load_dotenv

load_dotenv()

CLICK_MERCHANT_ID = os.getenv("CLICK_MERCHANT_ID")
CLICK_SERVICE_ID = os.getenv("CLICK_SERVICE_ID")
CLICK_MERCHANT_USER_ID = os.getenv("CLICK_MERCHANT_USER_ID")
CLICK_SECRET_KEY = os.getenv("CLICK_SECRET_KEY")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
SUBSCRIPTION_PRICE = int(os.getenv("SUBSCRIPTION_PRICE", "50000"))
