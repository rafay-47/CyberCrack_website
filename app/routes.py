from flask import Blueprint, render_template, send_from_directory, redirect, url_for, request, flash, current_app, jsonify
import stripe
import os
from app.services.EmailService import EmailService
from app.services.StripeCheckout import StripeCheckout
from app.forms import PurchaseForm, ContactForm
import jwt
from datetime import datetime, timedelta
from pathlib import Path


main_blueprint = Blueprint('main', __name__)

@main_blueprint.route('/')
def index():
    return render_template('index.html')

@main_blueprint.route('/download')
def download():
    # This will be implemented later
    return render_template('download.html')

@main_blueprint.route('/purchase', methods=['GET', 'POST'])
def purchase():
    form = PurchaseForm()
    if form.validate_on_submit():
        return redirect(url_for('main.create_checkout_session', 
                               name=form.name.data, 
                               email=form.email.data, 
                               amount=int(form.amount.data*100)))
    return render_template('purchase.html', form=form)


@main_blueprint.route('/create-checkout-session')
def create_checkout_session():
    name = request.args.get('name')
    email = request.args.get('email')
    amount = request.args.get('amount', 999) # Default amount in cents (e.g., $9.99)	
    
    # Create success and cancel URLs
    success_url = request.host_url + 'success?session_id={CHECKOUT_SESSION_ID}'
    cancel_url = request.host_url + 'cancel'
    
    try:
        # Initialize the Stripe checkout service
        stripe_checkout = StripeCheckout()
        
        # Create checkout session
        checkout_session = stripe_checkout.create_session(
            name=name,
            email=email,
            amount=amount,
            success_url=success_url,
            cancel_url=cancel_url
        )
        
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return jsonify(error=str(e)), 403



def generate_license(user_id, valid_days=30):
    """Generate a license key valid for the specified number of days"""
    # Load the private key (this should be kept secure)
    with open(Path(__file__).parent / 'static/keys/private.pem', "rb") as key_file:
        private_key = key_file.read()

    payload = {
        # Subject - typically user ID/Email or machine ID
        'sub': user_id,
        # Issued at time
        'iat': datetime.utcnow(),
        # Expiration time
        'exp': datetime.utcnow() + timedelta(days=valid_days)
    }
    
    # Create the JWT token
    token = jwt.encode(
        payload,
        private_key,
        algorithm="RS256"
    )
    
    return token


@main_blueprint.route('/success')
def success():
    session_id = request.args.get('session_id')
    
    try:
        stripe_checkout = StripeCheckout()
        session = stripe_checkout.verify_payment(session_id)
        
        if session.payment_status == 'paid':
            # Get customer details from session metadata
            customer_email = session.metadata['email']
            customer_name = session.metadata['name']
            
            # Generate license key
            license_key = generate_license(customer_email)
            
            # Send license key via email with validation
            email_service = EmailService()
            email_result = email_service.send_license_email(
                to_email=customer_email,
                to_name=customer_name,
                license_key=license_key,
                order_id=session_id
            )
            
            if email_result['success']:
                flash('Payment successful! Your license key has been sent to your email.', 'success')
            else:
                # Handle email validation or sending errors
                error_message = email_result.get('error', 'Unknown error')
                if 'validation failed' in error_message.lower():
                    flash(f'Payment successful! However, there was an issue with your email address: {error_message}. Please contact support with your order ID: {session_id}', 'warning')
                else:
                    flash('Payment successful! There was an issue sending your license key. Please contact support.', 'warning')
                
                # Log the error for manual follow-up
                #print(f"Email error for order {session_id}: {error_message}")
                
            # Log the license key (for debugging)
            #print(f"Generated license key for {customer_email}: {license_key}")
            
        else:
            flash('Payment not completed. Please try again.', 'error')
    except stripe.error.StripeError as e:
        # Handle Stripe errors
        flash('An error occurred while processing your payment. Please try again.', 'error')
    
    return render_template('success.html', session_id=session_id)

@main_blueprint.route('/cancel')
def cancel():
    return render_template('cancel.html')


@main_blueprint.route('/download_file')
def download_file():
    try:
        return send_from_directory(
            current_app.config['DOWNLOAD_FOLDER'], 
            'cybercrack.exe',  # Replace with your actual filename
            as_attachment=True
        )
    except FileNotFoundError:
        flash('The requested file is not available for download at this time.', 'error')
        return redirect(url_for('main.download'))


@main_blueprint.route('/contact', methods=['GET', 'POST'])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        # Send email with the contact form data
        email_service = EmailService()
        email_result = email_service.send_contact_email(
            from_email=form.email.data,
            from_name=form.name.data,
            message=form.message.data
        )
        
        if email_result['success']:
            flash('Your message has been sent successfully! We will get back to you soon.', 'success')
            return redirect(url_for('main.contact'))
        else:
            flash('There was an issue sending your message. Please try again later.', 'error')
    
    return render_template('contact.html', form=form)