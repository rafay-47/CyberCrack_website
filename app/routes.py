from flask import Blueprint, render_template, send_from_directory, redirect, url_for, request, flash, current_app, jsonify, Response, session
import stripe
import os
from app.services.EmailService import EmailService
from app.services.StripeCheckout import StripeCheckout
from app.forms import PurchaseForm, ContactForm, JobScrapingForm
import jwt
from datetime import datetime, timedelta
from pathlib import Path
import secrets
import csv
from jobspy import scrape_jobs
import io
import urllib.parse
import time

main_blueprint = Blueprint('main', __name__)

def is_admin_email(email):
    """
    Check if an email is an admin email using environment variables
    Supports multiple admin emails separated by commas
    """
    admin_emails_str = os.environ.get('ADMIN_EMAILS', '')
    if not admin_emails_str:
        return False
    
    admin_emails = [email.strip().lower() for email in admin_emails_str.split(',')]
    return email.lower().strip() in admin_emails

def generate_admin_order_id():
    """Generate a unique order ID for admin-generated licenses"""
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    random_suffix = secrets.token_hex(4).upper()
    return f"ADMIN_{timestamp}_{random_suffix}"

@main_blueprint.route('/')
def index():
    return render_template('index.html')

@main_blueprint.route('/download')
def download():
    return render_template('download.html')

@main_blueprint.route('/download_manual')
def download_manual():
    try:
        return send_from_directory(
            current_app.static_folder,
            'user-manual/CyberCrack_User_Manual.txt',
            as_attachment=True,
            download_name='CyberCrack_User_Manual.txt'
        )
    except FileNotFoundError:
        flash('The user manual is not available for download at this time.', 'error')
        return redirect(url_for('main.download'))

@main_blueprint.route('/purchase', methods=['GET', 'POST'])
def purchase():
    form = PurchaseForm()
    if form.validate_on_submit():
        email = form.email.data.strip()
        name = form.name.data.strip()
        duration_hours = int(form.license_duration.data)
        
        # Pricing mapping
        pricing = {
            1: 9.99,
            2: 19.99,
            3: 29.99,
            4: 37.00,
            5: 45.00
        }
        
        amount = pricing.get(duration_hours, 9.99)
        
        # Check if this is an admin email
        if is_admin_email(email):
            # Admin email detected - generate license directly without payment
            return redirect(url_for('main.admin_license_success', 
                                   name=name, 
                                   email=email,
                                   hours=duration_hours))
        
        # Normal purchase flow for non-admin emails
        return redirect(url_for('main.create_checkout_session', 
                               name=name, 
                               email=email, 
                               amount=int(amount*100),
                               hours=duration_hours))
    return render_template('purchase.html', form=form)

@main_blueprint.route('/admin-license-success')
def admin_license_success():
    """Handle admin license generation without payment"""
    name = request.args.get('name')
    email = request.args.get('email')
    hours = int(request.args.get('hours', 1))
    
    # Double-check admin email for security
    if not is_admin_email(email):
        flash('Access denied. Invalid admin email.', 'error')
        return redirect(url_for('main.purchase'))
    
    try:
        # Generate license key with hours
        license_key = generate_license(email, hours=hours)
        
        # Generate admin order ID
        order_id = generate_admin_order_id()
        
        # Send license key via email
        email_service = EmailService()
        email_result = email_service.send_admin_license_email(
            to_email=email,
            to_name=name,
            license_key=license_key,
            order_id=order_id,
            valid_hours=hours
        )
        
        if email_result['success']:
            flash(f'Admin license generated successfully! License sent to {email}', 'success')
        else:
            flash(f'License generated (Order: {order_id}) but email failed: {email_result.get("error", "Unknown error")}', 'warning')
        
        # Log for admin reference (remove in production or use proper logging)
        print(f"Admin license generated - Email: {email}, Order: {order_id}, Key: {license_key}")
        
    except Exception as e:
        flash(f'Error generating admin license: {str(e)}', 'error')
        return redirect(url_for('main.purchase'))
    
    return render_template('admin_success.html', 
                          order_id=order_id, 
                          email=email, 
                          license_key=license_key,
                          valid_hours=hours)

@main_blueprint.route('/create-checkout-session')
def create_checkout_session():
    name = request.args.get('name')
    email = request.args.get('email')
    amount = request.args.get('amount', 999) # Default amount in cents (e.g., $9.99)	
    hours = int(request.args.get('hours', 1)) # Convert to int immediately
    
    # Create success and cancel URLs
    success_url = request.host_url + f'success?session_id={{CHECKOUT_SESSION_ID}}&hours={hours}'
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
            cancel_url=cancel_url,
            hours=hours  # Pass hours to Stripe metadata
        )
        
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return jsonify(error=str(e)), 403

def generate_license(user_id, hours=1):
    """Generate a license key with specified usage hours (not expiration time)"""
    # Ensure hours is an integer
    hours = int(hours) if hours else 1
    
    # Load the private key (this should be kept secure)
    with open(Path(__file__).parent / 'static/keys/private.pem', "rb") as key_file:
        private_key = key_file.read()

    payload = {
        # Subject - typically user ID/Email or machine ID
        'sub': user_id,
        # Issued at time
        'iat': datetime.utcnow(),
        # License type - usage-based instead of time-based expiration
        'license_type': 'usage_hours',
        # Total usage hours allocated
        'usage_hours': hours,
        # Usage tracking (to be managed by the software)
        'used_hours': 0,
        # Optional: Add a reasonable expiration to prevent indefinite validity (e.g., 1 year)
        'exp': datetime.utcnow() + timedelta(days=365)
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
    hours = int(request.args.get('hours', 1)) # Convert to int immediately
    
    try:
        stripe_checkout = StripeCheckout()
        session = stripe_checkout.verify_payment(session_id)
        
        if session.payment_status == 'paid':
            # Get customer details from session metadata
            customer_email = session.metadata['email']
            customer_name = session.metadata['name']
            license_hours = int(session.metadata.get('hours', hours))
            
            # Generate license key with specified hours
            license_key = generate_license(customer_email, hours=license_hours)
            
            # Send license key via email with validation
            email_service = EmailService()
            email_result = email_service.send_license_email(
                to_email=customer_email,
                to_name=customer_name,
                license_key=license_key,
                order_id=session_id,
                valid_hours=license_hours
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
    
    return render_template('success.html', session_id=session_id, hours=hours)

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

@main_blueprint.route('/test-linkedin')
def test_linkedin():
    """Test page for LinkedIn integration"""
    return send_from_directory('.', 'linkedin_test.html')

@main_blueprint.route('/jobs/retrieve', methods=['POST'])
def retrieve_jobs():
    """Retrieve jobs data from localStorage (sent from frontend)"""
    try:
        print("=== /jobs/retrieve endpoint called ===")
        jobs_data = request.get_json()
        print(f"Received jobs_data: {jobs_data}")
        
        if not jobs_data or 'jobs' not in jobs_data:
            print("ERROR: No jobs data received or missing 'jobs' key")
            return jsonify({'error': 'No jobs data received'}), 400
        
        # Process and validate the jobs data
        jobs_list = jobs_data.get('jobs', [])
        print(f"Jobs list length: {len(jobs_list)}")
        
        search_info = {
            'search_term': jobs_data.get('searchTerm', ''),
            'location': jobs_data.get('location', ''),
            'sites': ['LinkedIn'],
            'results_count': len(jobs_list),
            'timestamp': jobs_data.get('timestamp'),
            'scraped_from_extension': True
        }
        print(f"Search info: {search_info}")
        
        # Validate job data structure
        validated_jobs = []
        for i, job in enumerate(jobs_list):
            print(f"Processing job {i+1}: {job.get('title', 'No title')} at {job.get('company', 'No company')}")
            validated_job = {
                'title': job.get('title', 'N/A'),
                'company': job.get('company', 'N/A'),
                'location': job.get('location', 'N/A'),
                'job_url': job.get('job_url', '#'),
                'description': job.get('description', ''),
                'salary_min': job.get('salary_min'),
                'salary_max': job.get('salary_max'),
                'job_type': job.get('job_type', 'Not specified'),
                'date_posted': job.get('date_posted', 'Recently'),
                'site': 'LinkedIn'
            }
            validated_jobs.append(validated_job)
        
        # Store in session for display
        session['scraped_jobs'] = validated_jobs
        session['search_info'] = search_info
        
        print(f"Stored {len(validated_jobs)} jobs in session")
        print("Session keys:", list(session.keys()))
        
        current_app.logger.info(f"Retrieved {len(validated_jobs)} jobs from extension")
        
        response_data = {
            'success': True,
            'jobs_count': len(validated_jobs),
            'redirect_url': url_for('main.jobs')
        }
        print(f"Returning response: {response_data}")
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"ERROR in /jobs/retrieve: {str(e)}")
        current_app.logger.error(f"Error retrieving jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500

@main_blueprint.route('/jobs', methods=['GET', 'POST'])
def jobs():
    print("=== /jobs route called ===")
    print(f"Request method: {request.method}")
    print(f"Session keys: {list(session.keys())}")
    
    form = JobScrapingForm()
    jobs_data = None
    search_info = None

    # Check for retrieved jobs from session (from extension)
    if 'scraped_jobs' in session:
        print("Found scraped_jobs in session!")
        jobs_data = session.pop('scraped_jobs')
        search_info = session.pop('search_info')
        print(f"Retrieved {len(jobs_data)} jobs from session")
        flash(f'Successfully retrieved {len(jobs_data)} jobs from LinkedIn via Chrome extension!', 'success')
    else:
        print("No scraped_jobs found in session")

    # Only process form on POST requests
    if request.method == 'POST' and form.validate_on_submit():
        print("Form submitted with data:", form.data)
        try:
            # Get form data
            sites = form.get_selected_sites()
            
            # Special case: If LinkedIn is selected, return LinkedIn URL for opening in new tab
            if len(sites) == 1 and sites[0] == 'linkedin':
                try:
                    # Get search parameters from the form
                    search_term = form.search_term.data or 'software engineer'
                    location = form.location.data or 'Singapore'
                    results_wanted = form.results_wanted.data or 50
                    
                    # Build LinkedIn jobs search URL with properly encoded parameters
                    # Add custom parameters to trigger the extension
                    # Use URL fragment (hash) instead of query params as it's more likely to be preserved
                    base_url = (f"https://www.linkedin.com/jobs/search/"
                              f"?keywords={urllib.parse.quote(search_term)}"
                              f"&location={urllib.parse.quote(location)}")
                    
                    # Add CyberCrack trigger in the URL fragment
                    fragment_data = {
                        'cybercrack_scraper': 'true',
                        'cybercrack_results': results_wanted,
                        'cybercrack_search_term': search_term,
                        'cybercrack_location': location,
                        'cybercrack_timestamp': int(time.time())
                    }
                    
                    fragment = '&'.join([f"{k}={urllib.parse.quote(str(v))}" for k, v in fragment_data.items()])
                    linkedin_url = f"{base_url}#cybercrack-{fragment}"
                    
                    # Debug: Print the generated URL
                    print(f"Generated LinkedIn URL: {linkedin_url}")
                    print(f"Search term: {search_term}")
                    print(f"Location: {location}")
                    print(f"Results wanted: {results_wanted}")
                    print(f"Is AJAX request: {request.headers.get('X-Requested-With') == 'XMLHttpRequest'}")
                    
                    # Check if this is an AJAX request
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        response_data = {'linkedin_url': linkedin_url}
                        print(f"Returning JSON response: {response_data}")
                        return jsonify(response_data)
                    else:
                        # Fallback: redirect if not AJAX request
                        print(f"Redirecting to: {linkedin_url}")
                        return redirect(linkedin_url)
                        
                except Exception as e:
                    print(f"Error generating LinkedIn URL: {str(e)}")
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'error': f'Error generating LinkedIn URL: {str(e)}'}), 500
                    else:
                        flash(f'Error generating LinkedIn URL: {str(e)}', 'error')
                        return render_template('jobs.html', form=form)
            
            # Validate that a site is selected
            if not sites:
                flash('Please select a job site.', 'error')
                return render_template('jobs.html', form=form)
            
            # Mandatory parameters
            search_term = form.search_term.data
            location = form.location.data
            results_wanted = form.results_wanted.data
            
            # Build parameters dict for jobspy
            params = {
                'site_name': sites,
                'search_term': search_term,
                'location': location,
                'results_wanted': results_wanted,
                'description_format': 'markdown',
                'verbose': 2
            }
            
            print(f"JobSpy parameters: {params}")
            
            # Scrape jobs using jobspy
            jobs = scrape_jobs(**params)

            print(f"Scraped {len(jobs)} jobs from {sites} for '{search_term}' in '{location}'")
            
            # Convert DataFrame to list of dictionaries for template rendering
            jobs_data = jobs.to_dict('records') if not jobs.empty else []
            
            # Store search information
            search_info = {
                'sites': sites,
                'search_term': search_term,
                'location': location,
                'results_count': len(jobs_data),
                'results_wanted': results_wanted
            }
            
            flash(f'Successfully scraped {len(jobs_data)} jobs!', 'success')
            
        except Exception as e:
            print(f"Error scraping jobs: {str(e)}")
            flash(f'Error scraping jobs: {str(e)}', 'error')
    
    return render_template('jobs.html', form=form, jobs_data=jobs_data, search_info=search_info)