import stripe
import os
from dotenv import load_dotenv
load_dotenv()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

class StripeCheckout:
    def __init__(self, api_key=None):
        """Initialize the Stripe checkout service with an API key"""
        self.api_key = api_key or os.environ.get(
            'STRIPE_SECRET_KEY', 
            STRIPE_SECRET_KEY
        )
        stripe.api_key = self.api_key
    
    def create_session(self, name, email, amount=999, success_url=None, cancel_url=None, hours=1):
        """Create a Stripe checkout session"""
        try:
            # Ensure hours is an integer
            hours = int(hours) if hours else 1
            
            # Format product description based on hours
            hours_text = f"{hours} hour{'s' if hours > 1 else ''}"
            product_description = f'AI Security Interview Preparation Software - {hours_text} license'
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {
                                'name': f'CyberCrack License ({hours_text})',
                                'description': product_description,
                            },
                            'unit_amount': int(amount),
                        },
                        'quantity': 1,
                    },
                ],
                metadata={
                    'name': name,
                    'email': email,
                    'hours': str(hours),
                },
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return checkout_session
        except Exception as e:
            raise e
    
    def verify_payment(self, session_id):
        """Verify if a payment was successful"""
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            return session
        except stripe.error.StripeError as e:
            raise e