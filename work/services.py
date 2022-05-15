from django.shortcuts import redirect
import os
import stripe
from dotenv import load_dotenv

load_dotenv()
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
stripe.api_key = STRIPE_API_KEY


def create_checkout_session(request):
    session = stripe.checkout.Session.create(
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "T-shirt",
                    },
                    "unit_amount": 2000,
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url="http://localhost:3000/pay/success",
        cancel_url="https://example.com/cancel",
    )

    return redirect(session.url, code=303)


