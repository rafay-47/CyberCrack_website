from flask import Blueprint, render_template, send_from_directory, redirect, url_for, request, flash, current_app, jsonify, Response, session
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
import logging
from app.services.resume_parser import parse_resume, _read_text_from_file
from app.services.ai_resume_parser import parse_text as ai_parse_text
from app.services.normalize_parser import normalize
from app.models import db, User, Profile
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
    
_JOB_ANALYZER = get_job_analyzer()

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
            # Get job site from dropdown
            job_site = request.form.get('job_site')
            search_term = form.search_term.data
            location = form.location.data
            results_wanted = form.results_wanted.data

            if not job_site:
                flash('Please select a job site.', 'error')
                return render_template('jobs.html', form=form)

            jobs = None
            sites = []
            if job_site == 'all':
                # Use jobspy for all platforms via service
                jobs = fetch_jobs_from_jobspy(
                    site_names=['indeed', 'linkedin', 'glassdoor'],
                    search_term=search_term,
                    location=location,
                    results_wanted=results_wanted
                )
                sites = ['Indeed', 'LinkedIn', 'Glassdoor']
            else:
                # For now, do not scrape for individual platforms
                jobs = None
                sites = [job_site.capitalize()]
                flash('Scraping for individual platforms is not implemented yet.', 'warning')

            jobs_data = jobs.to_dict('records') if jobs is not None and not jobs.empty else []
            # Run job analyzer to extract skills for each job (if jobs present)
            if jobs_data:
                analyzer = _JOB_ANALYZER
                if analyzer is not None:
                    try:
                        for i, job_rec in enumerate(jobs_data):
                            # Build text to analyze from available fields
                            title = job_rec.get('title') or ''
                            company = job_rec.get('company') or ''
                            description = job_rec.get('description') or ''
                            text_to_analyze = f"{title} {company} {description}".strip()

                            try:
                                analysis = analyzer.analyze_job_posting(text_to_analyze, job_id=job_rec.get('job_url') or f"job_{i}")
                                # Attach a lightweight skills list for the template
                                job_rec['extracted_skills'] = [
                                    {
                                        'name': s.name,
                                        'surface_form': s.surface_form,
                                        'confidence': round(s.confidence, 2),
                                        'type': s.skill_type,
                                        'source': s.source
                                    } for s in (analysis.skills or [])
                                ]
                            except Exception:
                                job_rec['extracted_skills'] = []
                    except Exception as e:
                        # If analyzer fails during processing, continue without skills
                        _logger.warning(f"JobAnalyzer processing failed: {e}")
                else:
                    _logger.warning('JobAnalyzer is not available; skipping skills extraction for scraped jobs')
            search_info = {
                'sites': sites,
                'search_term': search_term,
                'location': location,
                'results_count': len(jobs_data),
                'results_wanted': results_wanted,
                'hours_old': None
            }
            if jobs is not None:
                flash(f'Successfully scraped {len(jobs_data)} jobs!', 'success')
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

    return render_template('jobs.html', form=form, jobs_data=jobs_data, search_info=search_info, profiles=profiles)


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

        # Job skills from extracted_skills or empty
        job_skill_objs = job.get('extracted_skills') or []
        job_skill_set = make_string_set(job_skill_objs)

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

        # Fallback: try to pull some tokens from job.description if no extracted skills
        if not job_skill_set:
            desc = job.get('description') or ''
            # simple tokenization: split by non-word, take most common words >3 letters
            import re, collections
            tokens = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", desc)]
            freq = collections.Counter(tokens)
            common = [w for w, _ in freq.most_common(20)]
            job_skill_set = set(common)

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
        profile_name = request.form.get('profile_name') or None
        email = request.form.get('email') or None
        phone = request.form.get('phone') or None
        summary = request.form.get('summary') or None
        headline = request.form.get('headline') or None
        location = request.form.get('location') or None

        # Handle file upload
        resume = request.files.get('resume')
        upload_folder = Path(current_app.static_folder) / 'uploads' / 'profiles'
        upload_folder.mkdir(parents=True, exist_ok=True)

        saved_filename = None
        if resume:
            filename = secure_filename(resume.filename)
            if filename:
                saved_path = upload_folder / filename
                resume.save(saved_path)
                saved_filename = str(saved_path.relative_to(Path(current_app.static_folder)))

        # If a resume file was uploaded, attempt to reuse a cached parse or parse once and cache result
        extracted_keywords = None
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
                            extracted_keywords = parsed_cached.get('extracted_keywords')
                    except Exception:
                        extracted_keywords = None

                # If no cache, perform a single parse here (AI first, then local fallback) and write cache
                if not extracted_keywords and not cache_path.exists():
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
        starts = request.form.getlist('work_start[]')
        ends = request.form.getlist('work_end[]')
        descriptions = request.form.getlist('work_description[]')
        work_items = []
        max_work = max(len(titles), len(companies), len(starts), len(ends), len(descriptions)) if any([titles, companies, starts, ends, descriptions]) else 0
        for i in range(max_work):
            item = {
                'title': (titles[i] if i < len(titles) else '') or '',
                'company': (companies[i] if i < len(companies) else '') or '',
                'start': (starts[i] if i < len(starts) else '') or '',
                'end': (ends[i] if i < len(ends) else '') or '',
                'description': ((descriptions[i] if i < len(descriptions) else '') or '').strip()
            }
            if any(item.values()):
                work_items.append(item)

        # Education
        schools = request.form.getlist('edu_school[]')
        degrees = request.form.getlist('edu_degree[]')
        edu_starts = request.form.getlist('edu_start[]')
        edu_ends = request.form.getlist('edu_end[]')
        edu_descs = request.form.getlist('edu_description[]')
        edu_items = []
        max_edu = max(len(schools), len(degrees), len(edu_starts), len(edu_ends), len(edu_descs)) if any([schools, degrees, edu_starts, edu_ends, edu_descs]) else 0
        for i in range(max_edu):
            item = {
                'school': (schools[i] if i < len(schools) else '') or '',
                'degree': (degrees[i] if i < len(degrees) else '') or '',
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

        # Persist to DB
        try:
            user_id = None
            if current_user and getattr(current_user, 'is_authenticated', False):
                user_id = current_user.get_id()

            profile = Profile(
                user_id=user_id,
                resume_filename=saved_filename,
                name=profile_name,
                email=email,
                phone=phone,
                headline=headline,
                location=location,
                summary=summary,
                skills=skills or None,
                work_experience=work_items or None,
                education=edu_items or None,
                projects=project_items or None,
                certifications=certifications or None,
                languages=languages or None,
                links=links or None
                ,extracted_keywords=extracted_keywords or None
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