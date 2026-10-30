import os
import math
import razorpay
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from forex_python.converter import CurrencyRates
from src.core.database import session
from src.app.middleware.auth import require_user
from src.app.payment.services import verify_and_update_credits
from src.app.user.model import User

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
        # 1. Divide by 100 since the amount received is in the minor unit (paisa/cents)
        amount_main_unit = body.amount / 100.0
        input_currency = body.currency.upper()

        # Calculate credits based on the main unit amount
        if amount_main_unit == 19.0:
            credits_to_add = 200
        elif amount_main_unit == 55.0:
            credits_to_add = 600
        else:
            credits_to_add = int((amount_main_unit / 3.0) * 22)
        
        # 2. Convert the amount to INR using forex-python
        c = CurrencyRates()
        if input_currency == "INR":
            amount_in_inr = amount_main_unit
        else:
            try:
                amount_in_inr = c.convert(input_currency, 'INR', amount_main_unit)
            except Exception:
                # Fallback conversion rate if live rates are unreachable
                amount_in_inr = amount_main_unit * 95.12 if input_currency == "USD" else amount_main_unit

        # 3. Razorpay expects the amount in paisa (smallest unit for INR), so multiply by 100 and cast to int
        amount_in_paisa = math.floor(amount_in_inr * 100)

        # 5. Send the converted INR amount in paisa to create the order
        order = client.order.create({
            "amount": amount_in_paisa,
            "currency": "INR",
            "payment_capture": 1,       # auto-capture
            "notes": {
                "credits": str(credits_to_add)
            }
        })
        
        return { 
            "order_id": order["id"], 
            "amount": order["amount"], 
            "currency": order["currency"],
            "credits": credits_to_add
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/payments/verify")
async def verify_payment(
    body: VerifyRequest,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    # Pass db and current_user to the service layer
    status = await verify_and_update_credits(
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        signature=body.razorpay_signature,
        db=db,
        current_user=current_user
    )
    
    return { 
        "status": status, 
        "message": "Payment verified and credits added successfully!",
        "current_credits": current_user.credits
    }