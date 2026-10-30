import os
import razorpay
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.user.model import User

client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_KEY_SECRET")
))

async def verify_and_update_credits(order_id: str, payment_id: str, signature: str, db: AsyncSession, current_user: User):
    try:
        # 1. Verify signature securely using Razorpay's official utility
        client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        })
        
        # 2. Fetch complete payment details from Razorpay API
        payment_details = client.payment.fetch(payment_id)
        
        # 3. Extract credits directly from the payment notes
        notes = payment_details.get("notes", {})
        
        # 4. Parse the credit count safely
        try:
            credits_to_add = int(notes.get("credits", 0))
        except ValueError:
            credits_to_add = 0
            
        if credits_to_add <= 0:
            raise ValueError("No valid credits found in payment notes.")

        # 5. Update the authenticated user directly
        current_user.credits = (current_user.credits or 0) + credits_to_add
        
        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)

        return "done"

    except razorpay.errors.SignatureVerificationError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))