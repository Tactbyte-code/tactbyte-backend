import razorpay
import hmac, hashlib
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os

router = APIRouter()

client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_KEY_SECRET")
))

class OrderRequest(BaseModel):
    amount: int       
    currency: str = "INR"

class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

@router.post("/payments/create-order")
def create_order(body: OrderRequest):
    try:
        order = client.order.create({
            "amount": body.amount,
            "currency": body.currency,
            "payment_capture": 1       # auto-capture
        })
        return { "order_id": order["id"], "amount": order["amount"], "currency": order["currency"] }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/payments/verify")
def verify_payment(body: VerifyRequest):
    message = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    secret = os.getenv("RAZORPAY_KEY_SECRET").encode()

    generated = hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()

    if generated != body.razorpay_signature:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # ✅ Payment verified — update your DB here (mark plan as active, etc.)
    return { "status": "verified" }