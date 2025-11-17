from flask import Blueprint, render_template, render_template_string, send_from_directory, redirect, url_for, request, flash, current_app, jsonify, Response, session
import stripe
import os
from werkzeug.utils import secure_filename
from app.services.EmailService import EmailService
from app.services.StripeCheckout import StripeCheckout
from app.forms import PurchaseForm, ContactForm, JobScrapingForm
import jwt
from datetime import datetime, timedelta
import json
from pathlib import Path
import secrets
from app.services.jobspy_service import fetch_jobs_from_jobspy
from app.services.job_analyzer import OptimizedJobAnalyzer
from app.services.resume_improver import ResumeImprover
from app.services.latex_resume_generator import LaTeXResumeGenerator
import logging
from pathlib import Path as _Path
from app.services.resume_parser import parse_resume, _read_text_from_file
from app.services.ai_resume_parser import parse_text as ai_parse_text
from app.services.normalize_parser import normalize
from app.models import db, User, Profile
from sqlalchemy import text
import uuid
from app.forms import LoginForm, SignupForm
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import OperationalError

main_blueprint = Blueprint('main', __name__)

# Logger for this module
_logger = logging.getLogger(__name__)

# Lazily initialize the heavy JobAnalyzer to avoid loading large NLP models at import time.
# This prevents worker startup timeouts and high memory usage when handling light requests
# (e.g., public pages, login/signup) that don't need the analyzer.
_JOB_ANALYZER = None
_JOB_ANALYZER_LOCK = None

def get_job_analyzer():
    """Thread-safe lazy initializer for OptimizedJobAnalyzer.

    Returns the singleton analyzer instance or None if initialization failed.
    """
    global _JOB_ANALYZER, _JOB_ANALYZER_LOCK
    if _JOB_ANALYZER is not None:
        return _JOB_ANALYZER

    # Lazy-create the lock only when needed (avoid importing threading at top-level unnecessarily)
    if _JOB_ANALYZER_LOCK is None:
        import threading
        _JOB_ANALYZER_LOCK = threading.Lock()

    with _JOB_ANALYZER_LOCK:
        if _JOB_ANALYZER is not None:
            return _JOB_ANALYZER
        try:
            _JOB_ANALYZER = OptimizedJobAnalyzer(
                spacy_model='en_core_web_sm',
                fast_mode=True,
                confidence_threshold=0.25,
                cache_size=256,
                enable_threading=True,
                max_workers=4
            )
            _logger.info('JobAnalyzer initialized lazily')
        except Exception as _init_err:
            _JOB_ANALYZER = None
            _logger.warning(f'JobAnalyzer failed to initialize lazily: {_init_err}', exc_info=True)
        return _JOB_ANALYZER

# DO NOT initialize at module load - keep truly lazy


# Helper utilities to persist large scraped job payloads to server-side cache files
def _ensure_job_cache_dir():
    cache_dir = _Path(current_app.instance_path) / 'job_cache'
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # best-effort: ignore if cannot create (app may be read-only)
        pass
    return cache_dir


def _save_jobs_to_cache(jobs_data, search_info=None):
    """Save jobs_data and search_info into a JSON file under instance/job_cache.

    Returns the relative cache filename (not full path) used as a session key.
    """
    cache_dir = _ensure_job_cache_dir()
    fname = f"jobs_{uuid.uuid4().hex}.json"
    dest = cache_dir / fname
    
    # Add timestamp for cache expiration management
    payload = {
        'jobs': jobs_data or [], 
        'search_info': search_info or {},
        'created_at': datetime.utcnow().isoformat(),
        'expires_at': (datetime.utcnow() + timedelta(hours=24)).isoformat()  # 24 hour expiration
    }
    
    try:
        with dest.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=None, default=str)
            
        # Cleanup old cache files (keep only last 50 files)
        _cleanup_old_cache_files(cache_dir)
        
        return fname
    except Exception as e:
        current_app.logger.warning('Failed to write job cache file: %s', e, exc_info=True)
        return None


def _load_jobs_from_cache(fname):
    cache_dir = _Path(current_app.instance_path) / 'job_cache'
    if not fname:
        return None, None
    path = cache_dir / fname
    if not path.exists():
        return None, None
    try:
        with path.open('r', encoding='utf-8') as f:
            payload = json.load(f)
            
        # Check expiration if timestamp exists
        expires_at = payload.get('expires_at')
        if expires_at:
            from datetime import datetime
            expiry_time = datetime.fromisoformat(expires_at)
            if datetime.utcnow() > expiry_time:
                current_app.logger.info('Cache file %s expired, removing', fname)
                try:
                    path.unlink()
                except Exception:
                    pass
                return None, None
                
        return payload.get('jobs', []), payload.get('search_info')
    except Exception as e:
        current_app.logger.warning('Failed to read job cache file %s: %s', fname, e, exc_info=True)
        return None, None


def _cleanup_old_cache_files(cache_dir):
    """Keep only the most recent cache files to prevent disk bloat"""
    try:
        cache_files = list(cache_dir.glob('jobs_*.json'))
        if len(cache_files) > 50:  # Keep only 50 most recent files
            # Sort by modification time, newest first
            cache_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            # Remove older files
            for old_file in cache_files[50:]:
                try:
                    old_file.unlink()
                    current_app.logger.debug('Cleaned up old cache file: %s', old_file.name)
                except Exception as e:
                    current_app.logger.warning('Failed to remove old cache file %s: %s', old_file, e)
                    
    except Exception as e:
        current_app.logger.warning('Cache cleanup failed: %s', e)

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
        
        # Validate and deduplicate job data structure
        validated_jobs = []
        seen_jobs = set()  # For deduplication by title+company combination
        
        for i, job in enumerate(jobs_list):
            print(f"Processing job {i+1}: {job.get('title', 'No title')} at {job.get('company', 'No company')}")
            
            # Create deduplication key
            title = job.get('title', 'N/A').strip().lower()
            company = job.get('company', 'N/A').strip().lower()
            dedupe_key = f"{title}|{company}"
            
            # Skip duplicates
            if dedupe_key in seen_jobs:
                print(f"Skipping duplicate job: {title} at {company}")
                continue
            
            seen_jobs.add(dedupe_key)
            
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
        
        # Persist the validated jobs to a server-side cache file and store only the
        # cache filename in the session to avoid large cookie sizes.
        cache_fname = _save_jobs_to_cache(validated_jobs, search_info)
        if cache_fname:
            session['scraped_jobs_cache'] = cache_fname

        print(f"Stored {len(validated_jobs)} jobs in server cache: {cache_fname}")
        print("Session keys:", list(session.keys()))

        current_app.logger.info(f"Retrieved {len(validated_jobs)} jobs from extension")

        response_data = {
            'success': True,
            'jobs_count': len(validated_jobs),
            'redirect_url': url_for('main.jobs_list')
        }
        print(f"Returning response: {response_data}")
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"ERROR in /jobs/retrieve: {str(e)}")
        current_app.logger.error(f"Error retrieving jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500

@main_blueprint.route('/jobs', methods=['GET', 'POST'])
@login_required
def jobs():
    print("=== /jobs route called ===")
    print(f"Request method: {request.method}")
    print(f"Session keys: {list(session.keys())}")
    
    form = JobScrapingForm()
    jobs_data = None
    search_info = None
    profiles = []

    if request.method == 'POST' and form.validate_on_submit():
        try:
            # Get all filter parameters from the form
            job_site = request.form.get('job_site')
            search_term = form.search_term.data
            location = form.location.data
            results_wanted = int(request.form.get('results_wanted', form.results_wanted.data))
            job_type = request.form.get('job_type')  # From additional filters
            work_type = request.form.get('work_type')  # From additional filters
            hours_old_str = request.form.get('hours_old')  # From additional filters
            hours_old = int(hours_old_str) if hours_old_str and hours_old_str.isdigit() else None

            if not job_site:
                flash('Please select a job site.', 'error')
                return render_template('jobs.html', form=form)

            jobs = None
            sites = []
            if job_site == 'all':
                # Use jobspy for all platforms via service with filters
                jobs = fetch_jobs_from_jobspy(
                    site_names=['indeed', 'linkedin', 'glassdoor'],
                    search_term=search_term,
                    location=location,
                    results_wanted=results_wanted,
                    job_type=job_type,
                    work_type=work_type,
                    hours_old=hours_old
                )
                sites = ['Indeed', 'LinkedIn', 'Glassdoor']
            else:
                # For individual platforms, also apply filters
                site_mapping = {
                    'indeed': 'indeed',
                    'linkedin': 'linkedin', 
                    'glassdoor': 'glassdoor',
                    'google': 'google'
                }
                if job_site in site_mapping:
                    jobs = fetch_jobs_from_jobspy(
                        site_names=[site_mapping[job_site]],
                        search_term=search_term,
                        location=location,
                        results_wanted=results_wanted,
                        job_type=job_type,
                        work_type=work_type,
                        hours_old=hours_old
                    )
                    sites = [job_site.capitalize()]
                else:
                    jobs = None
                    sites = [job_site.capitalize()]
                    flash(f'Unsupported job site: {job_site}', 'error')

            jobs_data = jobs.to_dict('records') if jobs is not None and not jobs.empty else []
            
            # Deduplicate scraped jobs
            if jobs_data:
                deduplicated_jobs = []
                seen_jobs = set()
                
                for job in jobs_data:
                    title = str(job.get('title', 'N/A')).strip().lower()
                    company = str(job.get('company', 'N/A')).strip().lower()
                    dedupe_key = f"{title}|{company}"
                    
                    if dedupe_key not in seen_jobs:
                        seen_jobs.add(dedupe_key)
                        deduplicated_jobs.append(job)
                
                jobs_data = deduplicated_jobs
                current_app.logger.info(f"Deduplication: {len(deduplicated_jobs)} unique jobs out of original {len(jobs.to_dict('records') if jobs is not None and not jobs.empty else [])}")
            
            # Persist the currently selected profile ID so the jobs list page can use it for comparisons
            selected_profile = request.form.get('profile') or request.form.get('profile_id')
            if selected_profile:
                session['selected_profile'] = selected_profile
            # Skip job analyzer during scraping for better performance
            # Skills will be extracted during job comparison instead
            search_info = {
                'sites': sites,
                'search_term': search_term,
                'location': location,
                'results_count': len(jobs_data),
                'results_wanted': results_wanted,
                'job_type': job_type,
                'work_type': work_type,
                'hours_old': hours_old
            }
            if jobs is not None:
                flash(f'Successfully scraped {len(jobs_data)} jobs!', 'success')
            # Persist scraped jobs and search info to a server-side cache file
            # instead of placing the full payload into the cookie-backed session.
            try:
                cache_fname = _save_jobs_to_cache(jobs_data, search_info)
                if cache_fname:
                    session['scraped_jobs_cache'] = cache_fname
                    current_app.logger.debug('Persisted scraped jobs into server cache: %s', cache_fname)
            except Exception as _sess_err:
                current_app.logger.warning('Failed to persist scraped jobs into server cache: %s', _sess_err)
        except Exception as e:
            print(f"Error scraping jobs: {str(e)}")
            flash(f'Error scraping jobs: {str(e)}', 'error')

    # If user is logged in, load their profiles
    try:
        if current_user and getattr(current_user, 'is_authenticated', False):
            # current_user.get_id() may return string UUID
            uid = current_user.get_id()
            try:
                # Try using as-is; SQLAlchemy can accept UUID string for UUID column
                profiles = Profile.query.filter_by(user_id=uid).all()
            except Exception:
                # Fallback: convert to uuid.UUID object
                profiles = Profile.query.filter_by(user_id=uuid.UUID(uid)).all()
    except Exception:
        profiles = []
    # Log a compact, JSON-serializable summary of profiles passed to the template
    try:
        profiles_debug = []
        for p in profiles or []:
            profiles_debug.append({
                'id': str(p.id),
                'resume_filename': p.resume_filename,
                'name': p.name,
                'headline': p.headline,
                'location': p.location,
                'extracted_keywords_present': bool(p.extracted_keywords)
            })
        current_app.logger.debug('Rendering jobs page with profiles: %s', json.dumps(profiles_debug))
    except Exception:
        current_app.logger.debug('Failed to build profiles debug summary', exc_info=True)

    # If server-side scraping produced jobs_data, redirect users to the dedicated jobs list page
    if jobs_data:
        return redirect(url_for('main.jobs_list'))

    return render_template('jobs.html', form=form, jobs_data=jobs_data, search_info=search_info, profiles=profiles)


@main_blueprint.route('/jobs/list', methods=['GET', 'POST'])
@login_required
def jobs_list():
    """Render a separate page showing scraped jobs stored in the session.

    If no scraped jobs are available, redirect back to the scraping page.
    """
    if request.method == 'POST':
        # Handle batch job application
        profile_id = request.form.get('profile_id')
        selected_job_indices = request.form.getlist('selected_jobs[]')

        if not profile_id:
            flash('Please select a profile', 'error')
            return redirect(url_for('main.jobs_list'))

        if not selected_job_indices:
            flash('Please select at least one job', 'error')
            return redirect(url_for('main.jobs_list'))

        # Get profile data
        profile = Profile.query.get(profile_id)
        if not profile or profile.user_id != current_user.id:
            flash('Profile not found or access denied', 'error')
            return redirect(url_for('main.jobs_list'))

        # Load cached jobs
        cache_fname = session.get('scraped_jobs_cache')
        if not cache_fname:
            flash('No jobs found. Please search for jobs first.', 'error')
            return redirect(url_for('main.jobs'))

        jobs_data, search_info = _load_jobs_from_cache(cache_fname)
        if not jobs_data:
            flash('Job data expired. Please search for jobs again.', 'error')
            return redirect(url_for('main.jobs'))

        # Convert selected indices to job objects
        selected_jobs = []
        for index_str in selected_job_indices:
            try:
                index = int(index_str)
                if 0 <= index < len(jobs_data):
                    selected_jobs.append(jobs_data[index])
            except (ValueError, IndexError):
                continue

        if not selected_jobs:
            flash('No valid jobs selected', 'error')
            return redirect(url_for('main.jobs_list'))

        # Convert profile to dictionary
        profile_data = {
            'name': profile.name,
            'first_name': profile.first_name,
            'last_name': profile.last_name,
            'email': profile.email,
            'phone': profile.phone,
            'headline': profile.headline,
            'location': profile.location,
            'address': profile.address,
            'city': profile.city,
            'state': profile.state,
            'zip_code': profile.zip_code,
            'linkedin': profile.linkedin,
            'github': profile.github,
            'website': profile.website,
            'summary': profile.summary,
            'ethnicity': profile.ethnicity,
            'gender': profile.gender,
            'lgbtq': profile.lgbtq,
            'work_authorization': profile.work_authorization,
            'visa_sponsorship': profile.visa_sponsorship,
            'disability': profile.disability,
            'veteran': profile.veteran,
            'skills': profile.skills or [],
            'work_experience': profile.work_experience or [],
            'education': profile.education or [],
            'projects': profile.projects or [],
            'certifications': profile.certifications or [],
            'languages': profile.languages or [],
            'links': profile.links or [],
            'extracted_keywords': profile.extracted_keywords or []
        }

        # Initialize batch processor
        from app.services.batch_resume_improver import BatchResumeImprover
        batch_processor = BatchResumeImprover()

        # Process jobs in batch with progress feedback
        flash(f'Starting batch processing for {len(selected_jobs)} jobs...', 'info')

        try:
            # Define progress callback for user feedback
            def progress_callback(progress_pct, current_results):
                # This could be enhanced with WebSocket for real-time updates
                current_app.logger.info(f"Batch progress: {progress_pct:.1f}% - {current_results.get('processed_jobs', 0)}/{current_results.get('total_jobs', 0)} jobs processed")
            
            # Process jobs in batch with progress tracking
            flash('Processing your applications...', 'info')
            results = batch_processor.process_jobs_batch(profile_data, selected_jobs, progress_callback)

            # Save results
            batch_processor.save_batch_results(results['batch_id'], results)

            # Store batch ID in session for results page
            session['current_batch_id'] = results['batch_id']

            # Provide user feedback
            if results['successful_jobs'] > 0:
                flash(f'Successfully processed {results["successful_jobs"]} job applications!', 'success')
            
            if results['failed_jobs'] > 0:
                flash(f'{results["failed_jobs"]} job applications failed to process', 'warning')

            return redirect(url_for('main.batch_results'))
            
        except Exception as batch_error:
            current_app.logger.error(f'Batch processing failed: {batch_error}', exc_info=True)
            flash('Failed to process job applications. Please try again.', 'error')
            return redirect(url_for('main.jobs_list'))

    # GET request - display jobs list
    # Get all user profiles for selection
    profiles = []
    try:
        profiles = Profile.query.filter_by(user_id=current_user.id).all()
    except Exception as e:
        current_app.logger.error(f'Failed to fetch profiles: {e}')
        flash('Error loading profiles', 'error')

    # Prefer server-side cached payload to avoid large session cookies
    cache_fname = session.get('scraped_jobs_cache')
    jobs_data = None
    search_info = None
    if cache_fname:
        jobs_data, search_info = _load_jobs_from_cache(cache_fname)

    # Backwards compatibility: if older code stored payload directly in session
    if not jobs_data:
        jobs_data = session.get('scraped_jobs')
        search_info = session.get('search_info')

    if not jobs_data:
        flash('No scraped jobs found. Please perform a job scrape first.', 'error')
        return redirect(url_for('main.jobs'))

    return render_template('jobs_list.html', jobs_data=jobs_data, search_info=search_info, profiles=profiles)


@main_blueprint.route('/job_detail', methods=['GET', 'POST'])
@login_required
def job_detail():
    """Render a job vs profile comparison page.

    Expects a POST request containing 'job_json' (JSON string of the job dict)
    and optional 'profile_id' (UUID string) to load a Profile from DB.
    """
    if request.method == 'POST':
        job_json = request.form.get('job_json')
        profile_id = request.form.get('profile_id') or request.form.get('profile')

        if not job_json:
            flash('Job data missing for comparison', 'error')
            return redirect(url_for('main.jobs'))

        try:
            job = json.loads(job_json)
        except Exception as e:
            current_app.logger.warning(f'Failed to decode job JSON: {e}')
            flash('Invalid job data provided', 'error')
            return redirect(url_for('main.jobs'))

        profile = None
        if profile_id:
            try:
                profile = Profile.query.get(profile_id)
            except OperationalError as oe:
                # Try a single retry after disposing engine in case DB connection was dropped
                current_app.logger.warning('OperationalError loading Profile, attempting reconnect: %s', oe, exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass
                try:
                    db.engine.dispose()
                except Exception:
                    pass
                try:
                    profile = Profile.query.get(profile_id)
                except Exception as e2:
                    current_app.logger.error('Failed to load profile after retry: %s', e2, exc_info=True)
                    profile = None
            except Exception:
                profile = None

        # Build simple skill/keyword sets for comparison
        def make_string_set(vals):
            s = set()
            if not vals:
                return s
            # vals can be list or comma separated string
            if isinstance(vals, str):
                parts = [p.strip() for p in vals.split(',') if p.strip()]
            elif isinstance(vals, list):
                parts = []
                for v in vals:
                    if not v:
                        continue
                    if isinstance(v, dict):
                        # skill objects may have 'name' key
                        parts.append(str(v.get('name') or v.get('surface_form') or ''))
                    else:
                        parts.append(str(v))
                parts = [p for p in parts if p]
            else:
                parts = []

            for p in parts:
                s.add(p.lower())
            return s

        # Extract job skills using the analyzer during comparison with caching
        job_skill_objs = job.get('extracted_skills') or []
        job_skill_set = make_string_set(job_skill_objs)
        
        # If no pre-extracted skills, run the analyzer now with caching
        if not job_skill_set:
            # Create cache key based on job content
            title = job.get('title') or ''
            company = job.get('company') or ''
            description = job.get('description') or ''
            text_to_analyze = f"{title} {company} {description}".strip()
            
            # Simple cache key based on job URL or content hash
            import hashlib
            cache_key = job.get('job_url') or hashlib.md5(text_to_analyze.encode()).hexdigest()[:16]
            
            # Check if we have cached analysis in session (user-specific)
            user_cache_key = f'job_skill_cache_{current_user.id if current_user and current_user.is_authenticated else "anon"}'
            cached_analyses = session.get(user_cache_key, {})
            
            if cache_key in cached_analyses:
                job_skill_objs = cached_analyses[cache_key]
                job['extracted_skills'] = job_skill_objs
                job_skill_set = make_string_set(job_skill_objs)
                current_app.logger.info(f"Used cached skills for job: {title}")
            else:
                analyzer = get_job_analyzer()  # Use the lazy-loaded analyzer
                if analyzer is not None:
                    try:
                        if text_to_analyze:
                            current_app.logger.info(f"Running job analysis for comparison with job: {title}")
                            analysis = analyzer.analyze_job_posting(
                                text_to_analyze, 
                                job_id=job.get('job_url') or f"comparison_job_{job.get('title', 'unknown')}"
                            )
                            
                            # Extract skills for comparison
                            if analysis.skills:
                                job_skill_objs = [
                                    {
                                        'name': s.name,
                                        'surface_form': s.surface_form,
                                        'confidence': round(s.confidence, 2),
                                        'type': s.skill_type,
                                        'source': s.source
                                    } for s in analysis.skills
                                ]
                                # Add extracted skills to job data for template display
                                job['extracted_skills'] = job_skill_objs
                                job_skill_set = make_string_set(job_skill_objs)
                                
                                # Cache the result (limit cache size to prevent session bloat)
                                if len(cached_analyses) < 20:  # Limit cache size
                                    cached_analyses[cache_key] = job_skill_objs
                                    session[user_cache_key] = cached_analyses
                                
                                current_app.logger.info(f"Extracted and cached {len(job_skill_objs)} skills for job comparison")
                            else:
                                current_app.logger.info("No skills extracted by analyzer")
                    except Exception as e:
                        current_app.logger.warning(f"Job analysis failed during comparison: {e}")
                else:
                    current_app.logger.warning('JobAnalyzer not available for comparison')

        # Profile skills/keywords
        profile_skill_set = set()
        if profile:
            try:
                profile_skill_set |= make_string_set(profile.skills)
                profile_skill_set |= make_string_set(profile.extracted_keywords)
            except OperationalError as oe:
                current_app.logger.warning('OperationalError reading Profile fields, attempting reconnect: %s', oe, exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass
                try:
                    db.engine.dispose()
                except Exception:
                    pass
                # best-effort: leave profile_skill_set empty if retry fails

        # Fallback: try to pull some tokens from job.description if still no skills
        if not job_skill_set:
            desc = job.get('description') or ''
            # simple tokenization: split by non-word, take most common words >3 letters
            import re, collections
            tokens = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", desc)]
            freq = collections.Counter(tokens)
            common = [w for w, _ in freq.most_common(20)]
            job_skill_set = set(common)
            current_app.logger.info(f"Used fallback tokenization, extracted {len(common)} tokens")

        matched = sorted(list(job_skill_set & profile_skill_set))

        job_count = len(job_skill_set)
        profile_count = len(profile_skill_set)
        match_count = len(matched)

        job_coverage = round((match_count / job_count) * 100, 1) if job_count else 0.0
        profile_coverage = round((match_count / profile_count) * 100, 1) if profile_count else 0.0

        # A simple combined score (average of coverages)
        score = round(((job_coverage)), 1)

        match_info = {
            'matched_skills': matched,
            'job_skill_count': job_count,
            'profile_skill_count': profile_count,
            'match_count': match_count,
            'job_coverage': job_coverage,
            'profile_coverage': profile_coverage,
            'score': score
        }

        try:
            return render_template('job_detail.html', job=job, profile=profile, match=match_info)
        except OperationalError as oe:
            current_app.logger.error('OperationalError rendering job_detail: %s', oe, exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass
            try:
                db.engine.dispose()
            except Exception:
                pass
            flash('Database connection lost while preparing the comparison. Please try again.', 'error')
            return redirect(url_for('main.jobs'))

    # If GET, redirect back to jobs page
    return redirect(url_for('main.jobs'))


@main_blueprint.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        current_app.logger.info('Login attempt for email=%s', email)
        try:
            user = User.query.filter_by(email=email).first()
        except OperationalError as oe:
            current_app.logger.error('OperationalError during login DB query', exc_info=oe)
            try:
                db.session.rollback()
            except Exception:
                pass
            try:
                db.engine.dispose()
            except Exception:
                pass
            flash('Database connection error. Please try again shortly.', 'error')
            return render_template('login.html', form=form)

        if user and user.password_hash and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            current_app.logger.info('User logged in: %s', email)
            flash('Logged in successfully', 'success')
            return redirect(url_for('main.jobs'))
        current_app.logger.info('Failed login for email=%s', email)
        flash('Invalid credentials', 'error')
    return render_template('login.html', form=form)


@main_blueprint.route('/signup', methods=['GET', 'POST'])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        username = form.username.data.strip()
        current_app.logger.info('Signup attempt: username=%s email=%s', username, email)
        try:
            existing = User.query.filter((User.email==email) | (User.username==username)).first()
        except OperationalError as oe:
            current_app.logger.error('OperationalError during signup existence check', exc_info=oe)
            try:
                db.session.rollback()
            except Exception:
                pass
            try:
                db.engine.dispose()
            except Exception:
                pass
            flash('Database connection error. Please try again shortly.', 'error')
            return render_template('signup.html', form=form)

        if existing:
            current_app.logger.info('Signup blocked - existing user: %s or %s', username, email)
            flash('User with that email or username already exists', 'error')
            return render_template('signup.html', form=form)

        user = User(username=username, email=email, password_hash=generate_password_hash(form.password.data))
        try:
            db.session.add(user)
            db.session.commit()
            login_user(user)
            current_app.logger.info('Account created: %s', email)
            flash('Account created', 'success')
            return redirect(url_for('main.jobs'))
        except OperationalError as oe:
            current_app.logger.error('OperationalError during signup commit', exc_info=oe)
            try:
                db.session.rollback()
            except Exception:
                pass
            try:
                db.engine.dispose()
            except Exception:
                pass
            flash('Database error creating account. Please try again later.', 'error')
            return render_template('signup.html', form=form)
    return render_template('signup.html', form=form)


@main_blueprint.route('/logout')
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('main.index'))


@main_blueprint.route('/add_profile', methods=['GET', 'POST'])
def add_profile():
    """Render add_profile form and handle resume upload."""
    if request.method == 'POST':
        # Basic personal info
        first_name = request.form.get('first_name') or None
        last_name = request.form.get('last_name') or None
        email = request.form.get('email') or None
        phone = request.form.get('phone') or None
        headline = request.form.get('headline') or None
        location = request.form.get('location') or None
        
        # Contact info
        address = request.form.get('address') or None
        city = request.form.get('city') or None
        state = request.form.get('state') or None
        zip_code = request.form.get('zip_code') or None
        linkedin = request.form.get('linkedin') or None
        github = request.form.get('github') or None
        website = request.form.get('website') or None
        
        # Summary
        summary = request.form.get('summary') or None
        
        # Demographic info
        ethnicity = request.form.get('ethnicity') or None
        gender = request.form.get('gender') or None
        lgbtq = request.form.get('lgbtq') or None
        work_authorization = request.form.get('work_authorization') or None
        visa_sponsorship = request.form.get('visa_sponsorship') or None
        disability = request.form.get('disability') or None
        veteran = request.form.get('veteran') or None

        # Handle file uploads
        resume = request.files.get('resume')
        cover_letter = request.files.get('cover_letter')
        upload_folder = Path(current_app.static_folder) / 'uploads' / 'profiles'
        upload_folder.mkdir(parents=True, exist_ok=True)

        saved_resume_filename = None
        saved_cover_letter_filename = None
        
        if resume:
            filename = secure_filename(resume.filename)
            if filename:
                saved_path = upload_folder / f"resume_{filename}"
                resume.save(saved_path)
                saved_resume_filename = str(saved_path.relative_to(Path(current_app.static_folder)))
        
        if cover_letter:
            filename = secure_filename(cover_letter.filename)
            if filename:
                saved_path = upload_folder / f"cover_{filename}"
                cover_letter.save(saved_path)
                saved_cover_letter_filename = str(saved_path.relative_to(Path(current_app.static_folder)))

        # If a resume file was uploaded, attempt to reuse a cached parse or parse once and cache result
        extracted_keywords = None
        parsed_data = None
        try:
            if saved_filename:
                full_saved_path = Path(current_app.static_folder) / saved_filename
                cache_path = full_saved_path.with_name(full_saved_path.name + '.parsed.json')

                # If a cached parse exists (created by the parse endpoint), reuse it to avoid another LLM call
                if cache_path.exists():
                    try:
                        with cache_path.open('r', encoding='utf-8') as cj:
                            parsed_cached = json.load(cj)
                        if parsed_cached and isinstance(parsed_cached, dict):
                            # parsed_cached is expected to already be normalized by the parse endpoint
                            parsed_data = parsed_cached
                            extracted_keywords = parsed_cached.get('extracted_keywords')
                    except Exception:
                        extracted_keywords = None

                # If no cache, perform a single parse here (AI first, then local fallback) and write cache
                if not parsed_data and not cache_path.exists():
                    try:
                        # Read file text for AI parsing - ignore binary errors
                        with open(full_saved_path, 'r', encoding='utf-8', errors='ignore') as f:
                            text = f.read()

                        parsed_raw = ai_parse_text(text)
                        parsed_norm = normalize(parsed_raw) if parsed_raw else None

                        # If AI parser didn't return structured result, fallback to local parser
                        if not parsed_norm or parsed_norm.get('raw'):
                            try:
                                local_raw = parse_resume(str(full_saved_path))
                                parsed_norm = normalize(local_raw)
                            except Exception:
                                parsed_norm = parsed_norm or {}

                        # Save cache if we got a dict
                        if isinstance(parsed_norm, dict):
                            try:
                                with cache_path.open('w', encoding='utf-8') as cj:
                                    json.dump(parsed_norm, cj)
                            except Exception:
                                current_app.logger.debug('Failed to write parse cache', exc_info=True)

                        if isinstance(parsed_norm, dict):
                            parsed_data = parsed_norm
                            extracted_keywords = parsed_norm.get('extracted_keywords')
                    except Exception:
                        extracted_keywords = None

                # Ensure keywords are a list of strings if present
                if extracted_keywords and not isinstance(extracted_keywords, list):
                    if isinstance(extracted_keywords, str):
                        extracted_keywords = [k.strip() for k in extracted_keywords.split(',') if k.strip()]
                    else:
                        extracted_keywords = None
        except Exception:
            extracted_keywords = None

        # Parse repeatable fields from the form
        def first_nonempty(list_vals):
            for v in list_vals:
                if v and v.strip():
                    return v.strip()
            return None

        # Skills
        skills = request.form.getlist('skill[]') or request.form.getlist('skill') or []
        skills = [s for s in skills if s and s.strip()]

        # Work experience
        titles = request.form.getlist('work_title[]')
        companies = request.form.getlist('work_company[]')
        locations = request.form.getlist('work_location[]')
        experience_types = request.form.getlist('work_experience_type[]')
        starts = request.form.getlist('work_start[]')
        ends = request.form.getlist('work_end[]')
        descriptions = request.form.getlist('work_description[]')
        work_items = []
        max_work = max(len(titles), len(companies), len(locations), len(experience_types), len(starts), len(ends), len(descriptions)) if any([titles, companies, locations, experience_types, starts, ends, descriptions]) else 0
        for i in range(max_work):
            item = {
                'title': (titles[i] if i < len(titles) else '') or '',
                'company': (companies[i] if i < len(companies) else '') or '',
                'location': (locations[i] if i < len(locations) else '') or '',
                'experienceType': (experience_types[i] if i < len(experience_types) else '') or '',
                'start': (starts[i] if i < len(starts) else '') or '',
                'end': (ends[i] if i < len(ends) else '') or '',
                'description': ((descriptions[i] if i < len(descriptions) else '') or '').strip()
            }
            if any(item.values()):
                work_items.append(item)

        # Education
        schools = request.form.getlist('edu_school[]')
        majors = request.form.getlist('edu_major[]')
        degree_types = request.form.getlist('edu_degree_type[]')
        gpas = request.form.getlist('edu_gpa[]')
        edu_starts = request.form.getlist('edu_start[]')
        edu_ends = request.form.getlist('edu_end[]')
        edu_descs = request.form.getlist('edu_description[]')
        edu_items = []
        max_edu = max(len(schools), len(majors), len(degree_types), len(gpas), len(edu_starts), len(edu_ends), len(edu_descs)) if any([schools, majors, degree_types, gpas, edu_starts, edu_ends, edu_descs]) else 0
        for i in range(max_edu):
            item = {
                'school': (schools[i] if i < len(schools) else '') or '',
                'major': (majors[i] if i < len(majors) else '') or '',
                'degreetype': (degree_types[i] if i < len(degree_types) else '') or '',
                'gpa': (gpas[i] if i < len(gpas) else '') or '',
                'start': (edu_starts[i] if i < len(edu_starts) else '') or '',
                'end': (edu_ends[i] if i < len(edu_ends) else '') or '',
                'description': ((edu_descs[i] if i < len(edu_descs) else '') or '').strip()
            }
            if any(item.values()):
                edu_items.append(item)

        # Projects
        project_titles = request.form.getlist('project_title[]')
        project_links = request.form.getlist('project_link[]')
        project_descs = request.form.getlist('project_description[]')
        project_items = []
        max_proj = max(len(project_titles), len(project_links), len(project_descs)) if any([project_titles, project_links, project_descs]) else 0
        for i in range(max_proj):
            item = {
                'title': (project_titles[i] if i < len(project_titles) else '') or '',
                'link': (project_links[i] if i < len(project_links) else '') or '',
                'description': ((project_descs[i] if i < len(project_descs) else '') or '').strip()
            }
            if any(item.values()):
                project_items.append(item)

        certifications = request.form.getlist('certification[]') or []
        certifications = [c for c in certifications if c and c.strip()]

        languages = request.form.getlist('language[]') or []
        languages = [l for l in languages if l and l.strip()]

        links = request.form.getlist('link[]') or []
        links = [lnk.strip() for lnk in links if lnk and lnk.strip()]

        # Extract title from parsed data if available and not manually provided
        title = None
        if parsed_data and isinstance(parsed_data, dict):
            # Try to get title from parsed data (before it gets normalized to headline)
            title = parsed_data.get('title') or parsed_data.get('headline')
        
        # Use manual form inputs if provided, otherwise use parsed data defaults
        final_name = f"{first_name or ''} {last_name or ''}".strip() or (parsed_data.get('name') if parsed_data else None)
        final_email = email or (parsed_data.get('email') if parsed_data else None)
        final_phone = phone or (parsed_data.get('phone') if parsed_data else None)
        final_headline = headline or (parsed_data.get('headline') if parsed_data else None)
        final_location = location or (parsed_data.get('location') if parsed_data else None)

        # Persist to DB
        try:
            user_id = None
            if current_user and getattr(current_user, 'is_authenticated', False):
                user_id = current_user.get_id()

            profile = Profile(
                user_id=user_id,
                resume_filename=saved_resume_filename,
                cover_letter_filename=saved_cover_letter_filename,
                title=title,
                name=final_name,
                first_name=first_name,
                last_name=last_name,
                email=final_email,
                phone=final_phone,
                headline=final_headline,
                location=final_location,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                linkedin=linkedin,
                github=github,
                website=website,
                summary=summary,
                ethnicity=ethnicity,
                gender=gender,
                lgbtq=lgbtq,
                work_authorization=work_authorization,
                visa_sponsorship=visa_sponsorship,
                disability=disability,
                veteran=veteran,
                skills=skills or (parsed_data.get('skills') if parsed_data else None),
                work_experience=work_items or (parsed_data.get('work_experience') if parsed_data else None),
                education=edu_items or (parsed_data.get('education') if parsed_data else None),
                projects=project_items or (parsed_data.get('projects') if parsed_data else None),
                certifications=certifications or (parsed_data.get('certifications') if parsed_data else None),
                languages=languages or (parsed_data.get('languages') if parsed_data else None),
                links=links or (parsed_data.get('links') if parsed_data else None),
                extracted_keywords=extracted_keywords or None
            )
            db.session.add(profile)
            db.session.commit()
            flash('Profile saved successfully.', 'success')
            return redirect(url_for('main.jobs'))
        except Exception as e:
            current_app.logger.error(f'Failed to save profile: {e}', exc_info=True)
            db.session.rollback()
            flash('Failed to save profile. See server logs for details.', 'error')
            return redirect(url_for('main.add_profile'))

    return render_template('add_profile.html')


@main_blueprint.route('/parse_resume', methods=['POST'])
def parse_resume_route():
    """Accepts a resume upload and returns parsed fields as JSON."""
    if 'resume' not in request.files:
        return jsonify({'error': 'No resume file provided.'}), 400

    resume = request.files['resume']
    if resume.filename == '':
        return jsonify({'error': 'Empty filename.'}), 400

    upload_folder = Path(current_app.static_folder) / 'uploads' / 'profiles'
    upload_folder.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(resume.filename)
    saved_path = upload_folder / filename
    resume.save(saved_path)

    

    try:
        # Extract text from the saved resume file (supports .txt/.pdf/.docx)
        extracted_text = None
        extracted_links = []
        try:
            extracted_text, extracted_links = _read_text_from_file(str(saved_path))
        except Exception as text_exc:
            current_app.logger.warning(f'Text extraction failed: {text_exc}')
            extracted_text = None
            extracted_links = []

        parsed = None
        
        # Try AI parsing first if text was extracted
        if extracted_text and extracted_text.strip():
            try:
                current_app.logger.info('Attempting AI parsing...')
                parsed_raw = ai_parse_text(extracted_text)
                parsed = normalize(parsed_raw)
                
                # Validate AI parsing result
                if parsed and isinstance(parsed, dict) and not parsed.get('raw'):
                    current_app.logger.info('AI parsing successful')
                    
                    # Check for completeness - merge with local parser if needed
                    critical_sections = ['work_experience', 'education', 'projects']
                    missing_sections = [k for k in critical_sections if not parsed.get(k)]
                    
                    if missing_sections:
                        current_app.logger.info(f'AI parsing missing sections: {missing_sections}, attempting merge with local parser')
                        try:
                            local_raw = parse_resume(str(saved_path))
                            local_norm = normalize(local_raw)
                            
                            # Merge missing sections from local parser
                            merge_keys = ['work_experience', 'education', 'projects', 'skills', 'summary', 'certifications', 'languages']
                            for key in merge_keys:
                                ai_value = parsed.get(key)
                                local_value = local_norm.get(key)
                                
                                # Use local value if AI value is missing or empty
                                if (not ai_value or ai_value == []) and local_value:
                                    parsed[key] = local_value
                                    current_app.logger.info(f'Merged {key} from local parser')
                                    
                        except Exception as merge_exc:
                            current_app.logger.warning(f'Local parser merge failed: {merge_exc}')
                else:
                    current_app.logger.warning('AI parsing returned incomplete result')
                    parsed = None
                    
            except Exception as ai_exc:
                current_app.logger.warning(f'AI parser failed: {ai_exc}')
                parsed = None

        # Fallback to local parser if AI parsing failed or no text extracted
        if not parsed:
            try:
                current_app.logger.info('Using local parser fallback')
                parsed_raw = parse_resume(str(saved_path))
                parsed = normalize(parsed_raw)
                current_app.logger.info('Local parser completed successfully')
            except Exception as local_exc:
                current_app.logger.error(f'Local parser also failed: {local_exc}')
                return jsonify({'error': f'Resume parsing failed: {local_exc}'}), 500

        # Validate final result
        if not parsed or not isinstance(parsed, dict):
            return jsonify({'error': 'Failed to parse resume - invalid result format'}), 500

        # Merge any file-extracted links (from PDF annotations or DOCX rels) into the final parsed links
        try:
            if 'links' not in parsed or not isinstance(parsed.get('links'), list):
                parsed['links'] = []
            for fl in (extracted_links or []):
                if fl and fl not in parsed['links']:
                    parsed['links'].append(fl)
        except Exception as merge_links_exc:
            current_app.logger.warning(f'Failed to merge extracted links: {merge_links_exc}')

        # Log result for debugging (safely)
        try:
            result_summary = {
                'fields_found': [k for k, v in parsed.items() if v],
                'work_items': len(parsed.get('work_experience', [])),
                'education_items': len(parsed.get('education', [])),
                'project_items': len(parsed.get('projects', [])),
                'skills_count': len(parsed.get('skills', []))
            }
            current_app.logger.info(f'Parsing result: {result_summary}')
        except Exception:
            pass

        # Cache the normalized parse result next to the uploaded file so subsequent handlers reuse it
        try:
            cache_file = saved_path.with_name(saved_path.name + '.parsed.json')
            with cache_file.open('w', encoding='utf-8') as cj:
                json.dump(parsed, cj)
        except Exception:
            current_app.logger.debug('Failed to write parse cache file', exc_info=True)

        return jsonify({'success': True, 'data': parsed})
        
    except Exception as e:
        current_app.logger.error(f'Resume parsing error: {e}', exc_info=True)
        return jsonify({'error': f'An error occurred while parsing the resume: {str(e)}'}), 500
    finally:
        # Clean up uploaded file
        try:
            if saved_path.exists():
                saved_path.unlink()
                current_app.logger.info('Cleaned up temporary file')
        except Exception as cleanup_exc:
            current_app.logger.warning(f'Failed to clean up file: {cleanup_exc}')


# ================================
# RESUME IMPROVEMENT ROUTES
# ================================

@main_blueprint.route('/improve_profile', methods=['GET', 'POST'])
def improve_profile():
    """Profile improvement page - analyze profile against job description"""
    if request.method == 'GET':
        # Get all profiles for selection
        profiles = []
        try:
            profiles = Profile.query.all()
        except Exception as e:
            current_app.logger.error(f'Failed to fetch profiles: {e}')
            flash('Error loading profiles', 'error')
        
        return render_template('improve_profile.html', profiles=profiles)
    
    # POST - Analyze profile improvement
    try:
        profile_id = request.form.get('profile_id')
        job_description = request.form.get('job_description', '').strip()
        
        if not profile_id or not job_description:
            flash('Please select a profile and provide a job description', 'error')
            return redirect(url_for('main.improve_profile'))
        
        # Get profile data
        profile = Profile.query.get(profile_id)
        if not profile:
            flash('Profile not found', 'error')
            return redirect(url_for('main.improve_profile'))
        
        # Convert profile to dictionary
        profile_data = {
            'name': profile.name,
            'first_name': profile.first_name,
            'last_name': profile.last_name,
            'email': profile.email,
            'phone': profile.phone,
            'headline': profile.headline,
            'location': profile.location,
            'address': profile.address,
            'city': profile.city,
            'state': profile.state,
            'zip_code': profile.zip_code,
            'linkedin': profile.linkedin,
            'github': profile.github,
            'website': profile.website,
            'summary': profile.summary,
            'ethnicity': profile.ethnicity,
            'gender': profile.gender,
            'lgbtq': profile.lgbtq,
            'work_authorization': profile.work_authorization,
            'visa_sponsorship': profile.visa_sponsorship,
            'disability': profile.disability,
            'veteran': profile.veteran,
            'skills': profile.skills or [],
            'work_experience': profile.work_experience or [],
            'education': profile.education or [],
            'projects': profile.projects or [],
            'certifications': profile.certifications or [],
            'languages': profile.languages or [],
            'links': profile.links or [],
            'extracted_keywords': profile.extracted_keywords or []
        }
        
        # Initialize resume improver
        improver = ResumeImprover()
        
        # Analyze and get improvements
        analysis = improver.analyze_and_improve(profile_data, job_description)
        
        # Get prioritized improvement list for UI
        improvements = improver.get_improvement_priority_list(analysis)
        
        # Generate improved profile preview
        improved_profile = improver.generate_improved_profile(profile_data, analysis)
        
        # Persist analysis server-side to avoid oversized cookie sessions
        # Write improvement data to a temporary JSON file and keep only a token in session
        import uuid, json
        from pathlib import Path
        improvement_payload = {
            'profile_id': profile_id,
            'job_description': job_description,
            'original_profile': profile_data,
            'improved_profile': improved_profile,
            'analysis': {
                'overall_match_score': analysis.overall_match_score,
                'missing_skills': analysis.missing_skills,
                'keyword_gaps': analysis.keyword_gaps,
                'industry_alignment': analysis.industry_alignment,
                'experience_level_match': analysis.experience_level_match,
                'summary': analysis.summary,
                'action_items': analysis.action_items
            },
            'improvements': improvements
        }

        # Create temp directory under instance path
        tmp_dir = Path(current_app.instance_path) / 'tmp' / 'improvements'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        token = str(uuid.uuid4())
        payload_path = tmp_dir / f'{token}.json'
        with open(payload_path, 'w', encoding='utf-8') as f:
            json.dump(improvement_payload, f, ensure_ascii=False)

        # Keep only the token in session
        session['improvement_token'] = token

        return render_template('improvement_results.html', 
                             profile=profile,
                             job_description=job_description,
                             analysis=analysis,
                             improvements=improvements,
                             improved_profile=improved_profile,
                             improvement_token=token)
        
    except Exception as e:
        current_app.logger.error(f'Profile improvement analysis failed: {e}', exc_info=True)
        flash('Analysis failed. Please try again.', 'error')
        return redirect(url_for('main.improve_profile'))


@main_blueprint.route('/generate_resume_pdf', methods=['POST'])
def generate_resume_pdf():
    """Generate PDF resume from improved profile"""
    try:
        current_app.logger.info('PDF generation request received')
        
        # Retrieve token from form or session
        token = request.form.get('improvement_token') or session.get('improvement_token')
        if not token:
            current_app.logger.warning('No improvement token found in request or session')
            flash('No improvement analysis found. Please analyze your profile first.', 'error')
            return redirect(url_for('main.improve_profile'))

        # Load improvement payload from disk
        from pathlib import Path
        import json
        payload_path = Path(current_app.instance_path) / 'tmp' / 'improvements' / f'{token}.json'
        if not payload_path.exists():
            current_app.logger.warning('Improvement payload file not found for token %s', token)
            flash('Improvement data expired. Please re-run the analysis.', 'error')
            return redirect(url_for('main.improve_profile'))

        with open(payload_path, 'r', encoding='utf-8') as f:
            improvement_data = json.load(f)

        improved_profile = improvement_data.get('improved_profile')
        if not improved_profile:
            current_app.logger.warning('Improved profile missing in payload for token %s', token)
            flash('No improved profile found. Please analyze your profile first.', 'error')
            return redirect(url_for('main.improve_profile'))
        
        current_app.logger.info(f'Generating PDF for profile: {improved_profile.get("name", "Unknown")}')
        
        # Initialize LaTeX generator
        latex_generator = LaTeXResumeGenerator()
        
        # Generate PDF
        pdf_path = latex_generator.generate_resume_pdf(improved_profile)
        current_app.logger.info(f'PDF generated at: {pdf_path}')
        
        # Verify the PDF file exists
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Generated PDF file not found at {pdf_path}")
        
        current_app.logger.info('Sending PDF file for download')
        
        # Return the PDF file for download
        return send_from_directory(
            os.path.dirname(pdf_path),
            os.path.basename(pdf_path),
            as_attachment=True,
            download_name=f"improved_resume_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        
    except Exception as e:
        current_app.logger.error(f'Failed to generate PDF: {e}', exc_info=True)
        flash(f'Failed to generate PDF: {str(e)}', 'error')
        return redirect(url_for('main.improve_profile'))


@main_blueprint.route('/save_improved_profile', methods=['POST'])
def save_improved_profile():
    """Save the improved profile as a new profile"""
    try:
        # Get analysis from session
        improvement_data = session.get('improvement_analysis')
        if not improvement_data:
            flash('No improvement analysis found. Please analyze your profile first.', 'error')
            return redirect(url_for('main.improve_profile'))
        
        improved_profile = improvement_data.get('improved_profile')
        original_profile_id = improvement_data.get('profile_id')
        
        if not improved_profile:
            flash('No improved profile found.', 'error')
            return redirect(url_for('main.improve_profile'))
        
        # Get original profile for reference
        original_profile = Profile.query.get(original_profile_id)
        if not original_profile:
            flash('Original profile not found.', 'error')
            return redirect(url_for('main.improve_profile'))
        
        # Create new profile with improved data
        new_profile = Profile(
            user_id=original_profile.user_id,
            title=f"Improved - {original_profile.title or 'Profile'}",
            name=improved_profile.get('name'),
            email=improved_profile.get('email'),
            phone=improved_profile.get('phone'),
            headline=improved_profile.get('headline'),
            location=improved_profile.get('location'),
            summary=improved_profile.get('summary'),
            skills=improved_profile.get('skills'),
            work_experience=improved_profile.get('work_experience'),
            education=improved_profile.get('education'),
            projects=improved_profile.get('projects'),
            certifications=improved_profile.get('certifications'),
            languages=improved_profile.get('languages'),
            links=improved_profile.get('links'),
            extracted_keywords=improved_profile.get('extracted_keywords')
        )
        
        db.session.add(new_profile)
        db.session.commit()
        
        flash('Improved profile saved successfully as a new profile!', 'success')
        
        # Clear session data
        session.pop('improvement_analysis', None)
        
        return redirect(url_for('main.jobs'))
        
    except Exception as e:
        current_app.logger.error(f'Failed to save improved profile: {e}', exc_info=True)
        db.session.rollback()
        flash('Failed to save improved profile. Please try again.', 'error')
        return redirect(url_for('main.improve_profile'))


@main_blueprint.route('/api/analyze_profile', methods=['POST'])
def api_analyze_profile():
    """API endpoint for profile analysis (for AJAX requests)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        profile_id = data.get('profile_id')
        job_description = data.get('job_description', '').strip()
        
        if not profile_id or not job_description:
            return jsonify({'error': 'Profile ID and job description are required'}), 400
        
        # Get profile
        profile = Profile.query.get(profile_id)
        if not profile:
            return jsonify({'error': 'Profile not found'}), 404
        
        # Convert profile to dictionary
        profile_data = {
            'name': profile.name,
            'first_name': profile.first_name,
            'last_name': profile.last_name,
            'email': profile.email,
            'phone': profile.phone,
            'headline': profile.headline,
            'location': profile.location,
            'address': profile.address,
            'city': profile.city,
            'state': profile.state,
            'zip_code': profile.zip_code,
            'linkedin': profile.linkedin,
            'github': profile.github,
            'website': profile.website,
            'summary': profile.summary,
            'ethnicity': profile.ethnicity,
            'gender': profile.gender,
            'lgbtq': profile.lgbtq,
            'work_authorization': profile.work_authorization,
            'visa_sponsorship': profile.visa_sponsorship,
            'disability': profile.disability,
            'veteran': profile.veteran,
            'skills': profile.skills or [],
            'work_experience': profile.work_experience or [],
            'education': profile.education or [],
            'projects': profile.projects or [],
            'certifications': profile.certifications or [],
            'languages': profile.languages or [],
            'links': profile.links or [],
            'extracted_keywords': profile.extracted_keywords or []
        }
        
        # Analyze
        improver = ResumeImprover()
        analysis = improver.analyze_and_improve(profile_data, job_description)
        improvements = improver.get_improvement_priority_list(analysis)
        
        return jsonify({
            'success': True,
            'analysis': {
                'overall_match_score': analysis.overall_match_score,
                'missing_skills': analysis.missing_skills,
                'keyword_gaps': analysis.keyword_gaps,
                'industry_alignment': analysis.industry_alignment,
                'experience_level_match': analysis.experience_level_match,
                'summary': analysis.summary,
                'action_items': analysis.action_items
            },
            'improvements': improvements
        })
        
    except Exception as e:
        current_app.logger.error(f'API profile analysis failed: {e}', exc_info=True)
        return jsonify({'error': 'Analysis failed. Please try again.'}), 500


# BATCH JOB APPLICATION ROUTES


@main_blueprint.route('/batch_results')
@login_required
def batch_results():
    """Display batch processing results"""
    batch_id = session.get('current_batch_id')
    if not batch_id:
        flash('No batch results found', 'error')
        return redirect(url_for('main.jobs_list'))

    # Load batch results
    from app.services.batch_resume_improver import BatchResumeImprover
    batch_processor = BatchResumeImprover()
    results = batch_processor.get_batch_results(batch_id)

    if not results:
        flash('Batch results not found or expired', 'error')
        return redirect(url_for('main.jobs_list'))

    return render_template('batch_results.html', results=results)


@main_blueprint.route('/api/batch_results_data')
@login_required
def get_batch_results_data():
    """API endpoint to get batch results data for extension"""
    batch_id = session.get('current_batch_id')
    if not batch_id:
        return jsonify({'error': 'No batch results found'}), 404

    from app.services.batch_resume_improver import BatchResumeImprover
    batch_processor = BatchResumeImprover()
    results = batch_processor.get_batch_results(batch_id)

    if not results:
        return jsonify({'error': 'Batch results not found or expired'}), 404

    # Debug logging
    _logger.info(f"Found batch results with {len(results.get('job_results', []))} job results")
    for i, jr in enumerate(results.get('job_results', [])[:3]):  # Log first 3 for debugging
        _logger.info(f"Job {i}: status={jr.get('status')}, has_analysis={bool(jr.get('analysis'))}")

    # Format data for extension consumption
    extension_data = {
        'batch_id': results.get('batch_id'),
        'timestamp': results.get('timestamp', results.get('created_at')),
        'total_jobs': len(results.get('job_results', [])),
        'successful_jobs': len([jr for jr in results.get('job_results', []) if jr.get('status') == 'success']),
        'user_profile': _format_profile_for_autofill(results.get('user_profile', {})),  # Formatted user profile
        'jobs': []
    }

    # Extract relevant job data for autofill
    for job_result in results.get('job_results', []):
        if job_result.get('status') == 'success' and job_result.get('analysis'):
            # Read improved resume content if available
            resume_content = None
            improved_resume_path = job_result.get('improved_resume_path')
            if improved_resume_path and os.path.exists(improved_resume_path):
                try:
                    # For now, we'll store the path and a flag - we can enhance this later to extract text
                    resume_content = {
                        'pdf_path': improved_resume_path,
                        'file_size': os.path.getsize(improved_resume_path),
                        'available': True
                    }
                except Exception as e:
                    _logger.warning(f"Could not read resume file {improved_resume_path}: {e}")
                    resume_content = {'available': False, 'error': str(e)}
            
            job_data = {
                'job_id': job_result.get('job_id'),
                'job_title': job_result.get('job_title'),
                'company': job_result.get('company'),
                'job_url': job_result.get('job_url'),
                'match_score': job_result.get('analysis', {}).get('overall_match_score', 0),
                'missing_skills': job_result.get('analysis', {}).get('missing_skills', []),
                'keyword_gaps': job_result.get('analysis', {}).get('keyword_gaps', []),
                'improvements_applied': job_result.get('improvements_count', 0),
                'summary': job_result.get('analysis', {}).get('summary', ''),
                'action_items': job_result.get('analysis', {}).get('action_items', []),
                'has_improved_resume': bool(improved_resume_path),
                'improved_resume': resume_content,
                'improved_profile': _format_profile_for_autofill(job_result.get('improved_profile', {})),  # Formatted job-specific improved profile
                'industry_alignment': job_result.get('analysis', {}).get('industry_alignment', ''),
                'experience_level_match': job_result.get('analysis', {}).get('experience_level_match', '')
            }
            extension_data['jobs'].append(job_data)

    return jsonify(extension_data)


@main_blueprint.route('/api/batch_results_public/<batch_id>')
def get_batch_results_public(batch_id):
    """Public API endpoint for extension to get batch results data using batch_id"""
    try:
        from app.services.batch_resume_improver import BatchResumeImprover
        batch_processor = BatchResumeImprover()
        results = batch_processor.get_batch_results(batch_id)

        if not results:
            return jsonify({'error': 'Batch results not found or expired'}), 404

        # Debug logging
        _logger.info(f"Public API: Found batch results with {len(results.get('job_results', []))} job results")

        # Format data for extension consumption (reuse the same logic)
        extension_data = {
            'batch_id': results.get('batch_id'),
            'timestamp': results.get('timestamp', results.get('created_at')),
            'total_jobs': len(results.get('job_results', [])),
            'successful_jobs': len([jr for jr in results.get('job_results', []) if jr.get('status') == 'success']),
            'user_profile': _format_profile_for_autofill(results.get('user_profile', {})),
            'jobs': [],
            'status': 'success'
        }

        # Extract relevant job data for autofill
        for job_result in results.get('job_results', []):
            if job_result.get('status') == 'success' and job_result.get('analysis'):
                # Read improved resume content if available
                resume_content = None
                improved_resume_path = job_result.get('improved_resume_path')
                if improved_resume_path and os.path.exists(improved_resume_path):
                    try:
                        resume_content = {
                            'pdf_path': improved_resume_path,
                            'file_size': os.path.getsize(improved_resume_path),
                            'available': True
                        }
                    except Exception as e:
                        _logger.warning(f"Could not read resume file {improved_resume_path}: {e}")
                        resume_content = {'available': False, 'error': str(e)}
                
                job_data = {
                    'job_id': job_result.get('job_id'),
                    'job_title': job_result.get('job_title'),
                    'company': job_result.get('company'),
                    'job_url': job_result.get('job_url'),
                    'match_score': job_result.get('analysis', {}).get('overall_match_score', 0),
                    'missing_skills': job_result.get('analysis', {}).get('missing_skills', []),
                    'keyword_gaps': job_result.get('analysis', {}).get('keyword_gaps', []),
                    'improvements_applied': job_result.get('improvements_count', 0),
                    'summary': job_result.get('analysis', {}).get('summary', ''),
                    'has_improved_resume': bool(job_result.get('improved_resume_path')),
                    'improved_resume': resume_content,
                    'improved_profile': _format_profile_for_autofill(job_result.get('improved_profile', {})),
                    'industry_alignment': job_result.get('analysis', {}).get('industry_alignment', ''),
                    'experience_level_match': job_result.get('analysis', {}).get('experience_level_match', '')
                }
                extension_data['jobs'].append(job_data)

        return jsonify(extension_data)

    except Exception as e:
        _logger.error(f"Error in public batch results API: {e}")
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@main_blueprint.route('/api/current_batch_id')
def get_current_batch_id():
    """Public endpoint to get current batch ID for extension use"""
    try:
        # Get the most recent batch directory as a fallback
        import os
        from pathlib import Path
        
        batch_dirs = Path("instance/tmp/job_applications")
        if not batch_dirs.exists():
            return jsonify({'error': 'No batch directories found'}), 404
        
        # Get the most recent batch directory
        subdirs = [d for d in batch_dirs.iterdir() if d.is_dir()]
        if not subdirs:
            return jsonify({'error': 'No batch results found'}), 404
        
        latest_batch = max(subdirs, key=os.path.getmtime)
        batch_id = latest_batch.name
        
        return jsonify({
            'batch_id': batch_id,
            'public_api_url': f'/api/batch_results_public/{batch_id}',
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        _logger.error(f"Error getting current batch ID: {e}")
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


def _format_profile_for_autofill(profile_data):
    """Format profile data for easy autofill consumption - includes ALL available fields"""
    return {
        'personal': {
            'name': profile_data.get('name', ''),
            'email': profile_data.get('email', ''),
            'phone': profile_data.get('phone', ''),
            'location': profile_data.get('location', ''),
            'headline': profile_data.get('headline', ''),
            'summary': profile_data.get('summary', ''),
            'linkedin': profile_data.get('linkedin', ''),
            'github': profile_data.get('github', ''),
            'website': profile_data.get('website', ''),
            'portfolio': profile_data.get('portfolio', ''),
        },
        'skills': profile_data.get('skills', []),
        'work_experience': profile_data.get('work_experience', []),
        'education': profile_data.get('education', []),
        'projects': profile_data.get('projects', []),
        'certifications': profile_data.get('certifications', []),
        'languages': profile_data.get('languages', []),
        'links': profile_data.get('links', []),
        'keywords': profile_data.get('extracted_keywords', []),
        
        # Additional fields that extension might need
        'ethnicity': profile_data.get('ethnicity', ''),
        'race': profile_data.get('race', ''),
        'gender': profile_data.get('gender', ''),
        'lgbtq': profile_data.get('lgbtq', ''),
        'sexual_orientation': profile_data.get('sexual_orientation', ''),
        'work_authorization': profile_data.get('work_authorization', ''),
        'authorized_to_work': profile_data.get('authorized_to_work', ''),
        'visa_sponsorship': profile_data.get('visa_sponsorship', ''),
        'requires_sponsorship': profile_data.get('requires_sponsorship', ''),
        'disability': profile_data.get('disability', ''),
        'disability_status': profile_data.get('disability_status', ''),
        'veteran_status': profile_data.get('veteran_status', ''),
        'veteran': profile_data.get('veteran', ''),
        
        # Location components (in case they're separate)
        'address': profile_data.get('address', ''),
        'city': profile_data.get('city', ''),
        'state': profile_data.get('state', ''),
        'zip': profile_data.get('zip', ''),
        'country': profile_data.get('country', ''),
        
        # Additional personal info
        'first_name': profile_data.get('first_name', ''),
        'last_name': profile_data.get('last_name', ''),
        'middle_name': profile_data.get('middle_name', ''),
        'preferred_name': profile_data.get('preferred_name', ''),
        'date_of_birth': profile_data.get('date_of_birth', ''),
        'nationality': profile_data.get('nationality', ''),
        
        # Emergency/additional contacts
        'emergency_contact': profile_data.get('emergency_contact', ''),
        'references': profile_data.get('references', []),
        
        # Academic/Professional additional info
        'gpa': profile_data.get('gpa', ''),
        'publications': profile_data.get('publications', []),
        'awards': profile_data.get('awards', []),
        'volunteer_experience': profile_data.get('volunteer_experience', []),
        
        # Meta information
        'profile_completeness': profile_data.get('profile_completeness', 0),
        'last_updated': profile_data.get('last_updated', ''),
        'source': profile_data.get('source', 'website')
    }


@main_blueprint.route('/api/raw_batch_data')
@login_required
def get_raw_batch_data():
    """Debug endpoint to see raw batch data structure"""
    batch_id = session.get('current_batch_id')
    if not batch_id:
        return jsonify({'error': 'No batch results found'}), 404

    from app.services.batch_resume_improver import BatchResumeImprover
    batch_processor = BatchResumeImprover()
    results = batch_processor.get_batch_results(batch_id)

    if not results:
        return jsonify({'error': 'Batch results not found or expired'}), 404

    return jsonify({
        'batch_id': batch_id,
        'raw_results': results,
        'job_results_count': len(results.get('job_results', [])),
        'first_job_keys': list(results.get('job_results', [{}])[0].keys()) if results.get('job_results') else [],
        'successful_jobs': len([jr for jr in results.get('job_results', []) if jr.get('status') == 'success'])
    })


@main_blueprint.route('/debug/session_info')
@login_required
def debug_session_info():
    """Debug endpoint to check session information"""
    return jsonify({
        'current_batch_id': session.get('current_batch_id'),
        'session_keys': list(session.keys()),
        'user_authenticated': current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else False,
        'timestamp': datetime.utcnow().isoformat()
    })


@main_blueprint.route('/debug/use_latest_batch')
@login_required
def use_latest_batch():
    """Debug endpoint to set session to use the latest batch for testing"""
    import os
    from pathlib import Path
    
    batch_dirs = Path("instance/tmp/job_applications")
    if not batch_dirs.exists():
        return jsonify({'error': 'No batch directories found'})
    
    # Get the most recent batch directory
    batch_folders = [d for d in batch_dirs.iterdir() if d.is_dir()]
    if not batch_folders:
        return jsonify({'error': 'No batch folders found'})
    
    # Sort by modification time, get the most recent
    latest_batch = max(batch_folders, key=lambda x: x.stat().st_mtime)
    batch_id = latest_batch.name
    
    # Set session
    session['current_batch_id'] = batch_id
    
    return jsonify({
        'message': f'Session set to use batch: {batch_id}',
        'batch_id': batch_id,
        'batch_directory': str(latest_batch),
        'test_links': {
            'batch_results': url_for('main.batch_results'),
            'api_data': url_for('main.get_batch_results_data'),
            'raw_data': url_for('main.get_raw_batch_data')
        }
    })


@main_blueprint.route('/debug/batch_data')
@login_required
def debug_batch_data():
    """Debug page to view batch data that would be sent to extension"""
    batch_id = session.get('current_batch_id')
    if not batch_id:
        return render_template_string('''
            <h2>No Batch Data</h2>
            <p>No batch results found in current session.</p>
            <a href="{{ url_for('main.jobs_list') }}">← Back to Jobs</a>
        ''')

    from app.services.batch_resume_improver import BatchResumeImprover
    batch_processor = BatchResumeImprover()
    results = batch_processor.get_batch_results(batch_id)

    if not results:
        return render_template_string('''
            <h2>Batch Data Not Found</h2>
            <p>Batch results not found or expired.</p>
            <a href="{{ url_for('main.jobs_list') }}">← Back to Jobs</a>
        ''')

    # Format data for extension consumption (same as API)
    extension_data = {
        'batch_id': results.get('batch_id'),
        'timestamp': results.get('timestamp'),
        'total_jobs': len(results.get('job_results', [])),
        'successful_jobs': len([jr for jr in results.get('job_results', []) if jr.get('success')]),
        'jobs': []
    }

    for job_result in results.get('job_results', []):
        if job_result.get('success') and job_result.get('analysis'):
            job_data = {
                'job_id': job_result.get('job_id'),
                'job_title': job_result.get('job_title'),
                'company': job_result.get('company'),
                'job_url': job_result.get('job_url'),
                'match_score': job_result.get('analysis', {}).get('overall_match_score', 0),
                'missing_skills': job_result.get('analysis', {}).get('missing_skills', []),
                'keyword_gaps': job_result.get('analysis', {}).get('keyword_gaps', []),
                'improvements_applied': job_result.get('improvements_count', 0),
                'summary': job_result.get('analysis', {}).get('summary', ''),
                'has_improved_resume': bool(job_result.get('improved_resume_path'))
            }
            extension_data['jobs'].append(job_data)

    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>Batch Data Debug - CyberCrack</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { border-bottom: 2px solid #00b4d8; padding-bottom: 20px; margin-bottom: 30px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card { background: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center; }
        .card h3 { margin: 0; color: #00b4d8; font-size: 2em; }
        .card p { margin: 5px 0 0 0; color: #666; }
        .job-item { border: 1px solid #ddd; border-radius: 6px; padding: 20px; margin-bottom: 20px; }
        .job-title { font-size: 1.2em; font-weight: bold; color: #333; margin-bottom: 10px; }
        .job-company { color: #666; margin-bottom: 15px; }
        .match-score { display: inline-block; padding: 4px 12px; border-radius: 20px; font-weight: bold; color: white; }
        .score-high { background: #28a745; }
        .score-medium { background: #ffc107; color: #333; }
        .score-low { background: #dc3545; }
        .json-viewer { background: #f8f9fa; border: 1px solid #ddd; border-radius: 4px; padding: 15px; margin-top: 20px; font-family: monospace; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
        .skills-list { background: #e9ecef; padding: 10px; border-radius: 4px; margin: 10px 0; }
        .back-link { color: #00b4d8; text-decoration: none; font-weight: bold; }
        .back-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Batch Data Debug Viewer</h1>
            <p>This shows the exact data that would be sent to the CyberCrack extension.</p>
            <a href="{{ url_for('main.batch_results') }}" class="back-link">← Back to Batch Results</a>
        </div>
        
        <div class="summary">
            <div class="card">
                <h3>{{ extension_data.total_jobs }}</h3>
                <p>Total Jobs</p>
            </div>
            <div class="card">
                <h3>{{ extension_data.successful_jobs }}</h3>
                <p>Successful</p>
            </div>
            <div class="card">
                <h3>{{ extension_data.jobs|length }}</h3>
                <p>Available for Extension</p>
            </div>
        </div>
        
        <h2>Job Details</h2>
        {% for job in extension_data.jobs %}
        <div class="job-item">
            <div class="job-title">{{ job.job_title }}</div>
            <div class="job-company">{{ job.company }}</div>
            
            {% set score_pct = (job.match_score * 100)|round|int %}
            <span class="match-score {% if score_pct >= 80 %}score-high{% elif score_pct >= 60 %}score-medium{% else %}score-low{% endif %}">
                {{ score_pct }}% Match
            </span>
            
            <div style="margin-top: 15px;">
                <strong>Missing Skills ({{ job.missing_skills|length }}):</strong>
                {% if job.missing_skills %}
                <div class="skills-list">{{ job.missing_skills|join(', ') }}</div>
                {% else %}
                <span style="color: #28a745;">None identified</span>
                {% endif %}
                
                <strong>Keyword Gaps ({{ job.keyword_gaps|length }}):</strong>
                {% if job.keyword_gaps %}
                <div class="skills-list">{{ job.keyword_gaps|join(', ') }}</div>
                {% else %}
                <span style="color: #28a745;">None identified</span>
                {% endif %}
                
                {% if job.summary %}
                <strong>Analysis Summary:</strong>
                <p style="margin: 10px 0; padding: 10px; background: #f8f9fa; border-left: 4px solid #00b4d8;">{{ job.summary }}</p>
                {% endif %}
                
                <p><strong>Improvements Applied:</strong> {{ job.improvements_applied }}</p>
                <p><strong>Enhanced Resume Available:</strong> {{ "Yes" if job.has_improved_resume else "No" }}</p>
                {% if job.job_url %}
                <p><strong>Job URL:</strong> <a href="{{ job.job_url }}" target="_blank">{{ job.job_url }}</a></p>
                {% endif %}
            </div>
        </div>
        {% endfor %}
        
        <h2>Raw JSON Data</h2>
        <p>This is the exact JSON data structure sent to the extension:</p>
        <div class="json-viewer">{{ extension_data | tojson(indent=2) }}</div>
    </div>
</body>
</html>
    ''', extension_data=extension_data)


@main_blueprint.route('/download_improved_resume/<batch_id>/<job_id>')
@login_required
def download_improved_resume(batch_id, job_id):
    """Download improved resume for specific job"""
    try:
        # Validate batch_id format
        if not batch_id or not job_id:
            flash('Invalid download request', 'error')
            return redirect(url_for('main.batch_results'))

        from app.services.batch_resume_improver import BatchResumeImprover
        batch_processor = BatchResumeImprover()
        results = batch_processor.get_batch_results(batch_id)

        if not results:
            flash('Batch results not found or expired', 'error')
            return redirect(url_for('main.batch_results'))

        # Find the job result
        job_result = None
        for result in results.get('job_results', []):
            if result.get('job_id') == job_id and result.get('status') == 'success':
                job_result = result
                break

        if not job_result:
            flash('Resume not found or processing failed', 'error')
            return redirect(url_for('main.batch_results'))

        resume_path = job_result.get('improved_resume_path')
        if not resume_path:
            flash('Resume path not available', 'error')
            return redirect(url_for('main.batch_results'))

        if not os.path.exists(resume_path):
            flash('Resume file not found on disk. It may have been cleaned up.', 'error')
            return redirect(url_for('main.batch_results'))

        # Create safe filename
        company = job_result.get('company', 'Unknown').replace(' ', '_').replace('/', '_')[:20]
        title = job_result.get('job_title', 'Unknown').replace(' ', '_').replace('/', '_')[:20]
        
        # Clean filename of any potentially unsafe characters
        import re
        company = re.sub(r'[^\w\-_]', '', company)
        title = re.sub(r'[^\w\-_]', '', title)
        
        filename = f"improved_resume_{company}_{title}.pdf"

        # Return file for download
        from flask import send_file
        return send_file(
            resume_path, 
            as_attachment=True, 
            download_name=filename,
            mimetype='application/pdf'
        )

    except Exception as e:
        current_app.logger.error(f'Failed to download resume for batch {batch_id}, job {job_id}: {e}', exc_info=True)
        flash('Download failed. Please try again or contact support.', 'error')
        return redirect(url_for('main.batch_results'))


# API ENDPOINTS FOR CHROME EXTENSION

@main_blueprint.route('/api/auth/token', methods=['POST'])
def create_api_token():
    """Create API token for Chrome extension authentication"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400

        from app.models import User
        from werkzeug.security import check_password_hash

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'Invalid credentials'}), 401

        # Generate JWT token
        import jwt
        from datetime import datetime, timedelta

        payload = {
            'user_id': str(user.id),
            'username': user.username,
            'exp': datetime.utcnow() + timedelta(hours=24)  # 24 hour expiration
        }

        token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

        return jsonify({
            'token': token,
            'user_id': str(user.id),
            'username': user.username,
            'expires_in': 86400  # 24 hours in seconds
        })

    except Exception as e:
        current_app.logger.error(f'Token creation failed: {e}', exc_info=True)
        return jsonify({'error': 'Token creation failed'}), 500


@main_blueprint.route('/api/jobs/apply', methods=['POST'])
def api_apply_jobs():
    """API endpoint for Chrome extension to apply to jobs"""
    try:
        # Verify JWT token
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid authorization header'}), 401

        token = auth_header.split(' ')[1]

        import jwt
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = payload['user_id']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        # Get request data
        data = request.get_json()
        profile_id = data.get('profile_id')
        selected_jobs = data.get('selected_jobs', [])

        if not profile_id or not selected_jobs:
            return jsonify({'error': 'Profile ID and selected jobs required'}), 400

        # Verify profile ownership
        from app.models import Profile
        profile = Profile.query.get(profile_id)
        if not profile or str(profile.user_id) != user_id:
            return jsonify({'error': 'Profile not found or access denied'}), 403

        # Convert profile to dictionary
        profile_data = {
            'name': profile.name,
            'first_name': profile.first_name,
            'last_name': profile.last_name,
            'email': profile.email,
            'phone': profile.phone,
            'headline': profile.headline,
            'location': profile.location,
            'address': profile.address,
            'city': profile.city,
            'state': profile.state,
            'zip_code': profile.zip_code,
            'linkedin': profile.linkedin,
            'github': profile.github,
            'website': profile.website,
            'summary': profile.summary,
            'ethnicity': profile.ethnicity,
            'gender': profile.gender,
            'lgbtq': profile.lgbtq,
            'work_authorization': profile.work_authorization,
            'visa_sponsorship': profile.visa_sponsorship,
            'disability': profile.disability,
            'veteran': profile.veteran,
            'skills': profile.skills or [],
            'work_experience': profile.work_experience or [],
            'education': profile.education or [],
            'projects': profile.projects or [],
            'certifications': profile.certifications or [],
            'languages': profile.languages or [],
            'links': profile.links or [],
            'extracted_keywords': profile.extracted_keywords or []
        }

        # Initialize batch processor
        from app.services.batch_resume_improver import BatchResumeImprover
        batch_processor = BatchResumeImprover()

        try:
            # Process jobs
            results = batch_processor.process_jobs_batch(profile_data, selected_jobs)

            # Save results
            batch_processor.save_batch_results(results['batch_id'], results)

            return jsonify({
                'batch_id': results['batch_id'],
                'status': results['status'],
                'total_jobs': results['total_jobs'],
                'successful_jobs': results['successful_jobs'],
                'failed_jobs': results['failed_jobs'],
                'results_url': url_for('main.batch_results', _external=True),
                'message': f'Processed {results["total_jobs"]} jobs with {results["successful_jobs"]} successes'
            })
            
        except Exception as processing_error:
            current_app.logger.error(f'API batch processing failed: {processing_error}', exc_info=True)
            return jsonify({
                'error': 'Batch processing failed',
                'details': str(processing_error)
            }), 500

    except Exception as e:
        current_app.logger.error(f'API batch application failed: {e}', exc_info=True)
        return jsonify({'error': 'Batch processing failed'}), 500


@main_blueprint.route('/api/batch/status/<batch_id>', methods=['GET'])
def api_batch_status(batch_id):
    """Get batch processing status"""
    try:
        from app.services.batch_resume_improver import BatchResumeImprover
        batch_processor = BatchResumeImprover()
        results = batch_processor.get_batch_results(batch_id)

        if not results:
            return jsonify({'error': 'Batch not found'}), 404

        return jsonify({
            'batch_id': batch_id,
            'status': results['status'],
            'progress': (results['processed_jobs'] / results['total_jobs']) * 100 if results['total_jobs'] > 0 else 0,
            'total_jobs': results['total_jobs'],
            'processed_jobs': results['processed_jobs'],
            'successful_jobs': results['successful_jobs'],
            'failed_jobs': results['failed_jobs']
        })

    except Exception as e:
        current_app.logger.error(f'Failed to get batch status: {e}', exc_info=True)
        return jsonify({'error': 'Failed to get status'}), 500


def cleanup_temp_files():
    """Clean up temporary files and old cache entries"""
    try:
        from pathlib import Path
        import time
        
        current_time = time.time()
        cleanup_count = 0
        
        # Cleanup improvement token files older than 24 hours
        tmp_dir = Path(current_app.instance_path) / 'tmp' / 'improvements'
        if tmp_dir.exists():
            for file_path in tmp_dir.glob('*.json'):
                if current_time - file_path.stat().st_mtime > 86400:  # 24 hours
                    try:
                        file_path.unlink()
                        cleanup_count += 1
                    except Exception as e:
                        current_app.logger.warning(f'Failed to cleanup improvement file {file_path}: {e}')
        
        # Cleanup old batch results older than 7 days
        batch_dir = Path(current_app.instance_path) / 'tmp' / 'job_applications'
        if batch_dir.exists():
            for batch_folder in batch_dir.iterdir():
                if batch_folder.is_dir() and current_time - batch_folder.stat().st_mtime > 604800:  # 7 days
                    try:
                        import shutil
                        shutil.rmtree(batch_folder)
                        cleanup_count += 1
                    except Exception as e:
                        current_app.logger.warning(f'Failed to cleanup batch folder {batch_folder}: {e}')
        
        # Cleanup old parse cache files
        uploads_dir = Path(current_app.static_folder) / 'uploads' / 'profiles'
        if uploads_dir.exists():
            for cache_file in uploads_dir.glob('*.parsed.json'):
                if current_time - cache_file.stat().st_mtime > 86400:  # 24 hours
                    try:
                        cache_file.unlink()
                        cleanup_count += 1
                    except Exception as e:
                        current_app.logger.warning(f'Failed to cleanup parse cache {cache_file}: {e}')
        
        current_app.logger.info(f'Cleanup completed: removed {cleanup_count} old files')
        return cleanup_count
        
    except Exception as e:
        current_app.logger.error(f'Cleanup process failed: {e}', exc_info=True)
        return 0


# Schedule periodic cleanup (this could be enhanced with a proper task scheduler)
def init_cleanup_scheduler():
    """Initialize periodic cleanup of temporary files"""
    import threading
    import time
    
    def periodic_cleanup():
        while True:
            time.sleep(3600)  # Run every hour
            try:
                with current_app.app_context():
                    cleanup_temp_files()
            except Exception as e:
                print(f"Cleanup error: {e}")  # Use print since logger might not be available
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    current_app.logger.info('Periodic cleanup thread started')