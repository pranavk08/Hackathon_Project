import functools
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)
import re
import time
import datetime
from flask import request as flask_request
from flaskr.admin_log import log_admin_event
from werkzeug.security import check_password_hash, generate_password_hash
from bson.objectid import ObjectId

from flaskr.db import get_db
from pymongo.errors import DuplicateKeyError

from flask import current_app

# Import notifications module if needed for SMS notifications
try:
    from flaskr.notifications import send_sms
except ImportError:
    # Define a dummy function if the notifications module is not available
    def send_sms(phone_number, message):
        print(f"Would send SMS to {phone_number}: {message}")
        return True

bp = Blueprint('auth', __name__)

def init_db_indexes(app):
    """Initialize database indexes for optimal performance"""
    with app.app_context():
        db = get_db()
        # Create compound unique index for email and username
        db['users'].create_index([('email', 1)], unique=True)
        db['users'].create_index([('username', 1)], unique=True)
        # Add sparse index for phone numbers (only indexes documents that have the field)
        db['users'].create_index([('phone', 1)], unique=True, sparse=True)
        # Add index for frequently queried fields
        db['users'].create_index([('email', 1), ('password', 1)])
        # Add index for user role
        db['users'].create_index([('role', 1)])
        # Add index for student fields
        db['users'].create_index([('cgpa', 1)])
        db['users'].create_index([('branch', 1)])
        # Add indexes for job listings
        db['jobs'].create_index([('company_id', 1)])
        db['jobs'].create_index([('status', 1)])
        db['jobs'].create_index([('min_cgpa', 1)])
        # Add indexes for applications
        db['applications'].create_index([('job_id', 1)])
        db['applications'].create_index([('student_id', 1)])
        db['applications'].create_index([('status', 1)])
        # Add indexes for interviews
        db['interviews'].create_index([('job_id', 1)])
        db['interviews'].create_index([('student_id', 1)])

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form.get('username', '')
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '')
        role = request.form.get('role', 'student')  # Default to student role
        
        # Student-specific fields
        branch = request.form.get('branch', '') if role == 'student' else ''
        cgpa = request.form.get('cgpa', '') if role == 'student' else ''
        year = request.form.get('year', '') if role == 'student' else ''
        
        # Recruiter-specific fields
        company_name = request.form.get('company_name', '') if role == 'recruiter' else ''
        company_website = request.form.get('company_website', '') if role == 'recruiter' else ''
        
        db = get_db()
        error = None

        # Email format validation
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        # Password strength: at least 8 chars, 1 uppercase, 1 lowercase, 1 digit
        password_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
        # Phone number validation: exactly 10 digits
        phone_regex = r"^\d{10}$"

        if not username:
            error = 'Username is required.'
        elif not email:
            error = 'Email is required.'
        elif not re.match(email_regex, email):
            error = 'Please enter a valid email address.'
        elif not phone:
            error = 'Phone number is required.'
        elif not re.match(phone_regex, phone):
            error = 'Please enter a valid 10-digit phone number.'
        elif not password:
            error = 'Password is required.'
        elif not confirm_password:
            error = 'Please confirm your password.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif not re.match(password_regex, password):
            error = 'Password must be at least 8 characters long, contain an uppercase letter, a lowercase letter, and a digit.'
        
        # Role-specific validations
        if role == 'student':
            if not branch:
                error = 'Branch is required for students.'
            elif not cgpa:
                error = 'CGPA is required for students.'
            elif not year:
                error = 'Year of study is required for students.'
            else:
                try:
                    cgpa_float = float(cgpa)
                    if cgpa_float < 0 or cgpa_float > 10:
                        error = 'CGPA must be between 0 and 10.'
                except ValueError:
                    error = 'CGPA must be a valid number.'
        elif role == 'recruiter':
            if not company_name:
                error = 'Company name is required for recruiters.'

        if error is None:
            try:
                # Prepare the user document based on role
                user_data = {
                    'username': username,
                    'email': email,
                    'phone': f"+91{phone}",  # Store phone number with country code
                    'password': generate_password_hash(password),
                    'role': role,
                    'is_admin': False,  # Default to non-admin
                    'created_at': datetime.datetime.now(),  # Add creation timestamp
                    'notification_preferences': {
                        'sms': True,  # Default to SMS notifications enabled
                        'email': True  # Default to email notifications enabled
                    }
                }
                
                # Add role-specific fields
                if role == 'student':
                    user_data.update({
                        'branch': branch,
                        'cgpa': float(cgpa),
                        'year': year,
                        'resume': None  # Placeholder for resume upload
                    })
                elif role == 'recruiter':
                    user_data.update({
                        'company_name': company_name,
                        'company_website': company_website,
                        'verification_status': 'pending'  # Recruiters need verification
                    })
                
                # Insert the user
                result = db['users'].insert_one(user_data)
                log_admin_event('register_success', f'{role.capitalize()} registered successfully.', user_email=email, ip=flask_request.remote_addr)
                
                # Send welcome SMS if notifications are enabled
                try:
                    phone_number = f"+91{phone}"
                    welcome_message = f"Welcome to College Placement Portal! Your {role} account has been created successfully."
                    send_sms(phone_number, welcome_message)
                except Exception as sms_error:
                    # Log the error but don't prevent registration
                    log_admin_event('sms_error', f'Failed to send welcome SMS: {str(sms_error)}', user_email=email)
                
                # Automatically log in the user after successful registration
                session.clear()
                session['user_id'] = str(result.inserted_id)
                flash(f'Registration successful! You are now logged in as a {role}.')
                return redirect(url_for('index'))
            except DuplicateKeyError as e:
                # Check which unique constraint was violated
                if 'email' in str(e):
                    error = "An account with this email already exists. Please use a different email."
                elif 'username' in str(e):
                    error = "This username is already taken. Please choose another."
                else:
                    error = "A user with these credentials already exists. Please try different ones."
                log_admin_event('register_fail', error, user_email=email, ip=flask_request.remote_addr)

        if error:
            log_admin_event('register_error', error, user_email=email, ip=flask_request.remote_addr)
            flash(error)
            # Store form data in session for form repopulation
            session['register_form_data'] = {
                'username': username,
                'email': email,
                'phone': phone,
                'role': role,
                'branch': branch,
                'cgpa': cgpa,
                'year': year,
                'company_name': company_name,
                'company_website': company_website
            }
            return redirect(url_for('auth.register'))

    # Get stored form data if it exists
    form_data = session.pop('register_form_data', {}) if request.method == 'GET' else {}
    
    return render_template('auth/register.html', form_data=form_data)



# Simple in-memory rate limiting (per session)
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW = 60  # seconds

@bp.route('/login', methods=('GET', 'POST'))
def login():
    if 'login_attempts' not in session:
        session['login_attempts'] = []

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        db = get_db()
        error = None

        # Email format validation
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not email:
            error = 'Email is required.'
        elif not re.match(email_regex, email):
            error = 'Please enter a valid email address.'
        elif not password:
            error = 'Password is required.'

        # Rate limiting logic
        now = time.time()
        attempts = [t for t in session['login_attempts'] if now - t < LOGIN_ATTEMPT_WINDOW]
        if len(attempts) >= LOGIN_ATTEMPT_LIMIT:
            error = f'Too many login attempts. Please try again in {int(LOGIN_ATTEMPT_WINDOW - (now - attempts[0]))} seconds.'
        else:
            session['login_attempts'] = attempts

        if error is None:
            # Use projection to fetch required fields including role
            user = db['users'].find_one(
                {'email': email},
                {'_id': 1, 'password': 1, 'role': 1, 'phone': 1, 'verification_status': 1}
            )
            
            if user is None:
                error = 'No account found with this email.'
            elif not check_password_hash(user['password'], password):
                error = 'Incorrect password.'
            # Check if recruiter is verified
            elif user.get('role') == 'recruiter' and user.get('verification_status') == 'rejected':
                error = 'Your recruiter account has been rejected. Please contact the administrator.'

        if error is None:
            session.clear()
            session['user_id'] = str(user['_id'])
            
            # Send login notification via SMS if applicable
            try:
                if user.get('phone'):
                    login_message = f"You've successfully logged in to College Placement Portal as a {user.get('role', 'user')}."
                    send_sms(user['phone'], login_message)
            except Exception as sms_error:
                # Log the error but don't prevent login
                log_admin_event('sms_error', f'Failed to send login SMS: {str(sms_error)}', user_email=email)
            
            # Redirect based on role and verification status
            if user.get('role') == 'recruiter' and user.get('verification_status') == 'pending':
                flash('Your recruiter account is pending verification. Some features may be limited until verification is complete.')
            
            log_admin_event('login_success', f'{user.get("role", "User")} logged in successfully.', user_email=email, ip=flask_request.remote_addr)
            return redirect(url_for('index'))
        else:
            # Record failed attempt
            session['login_attempts'].append(now)
            session.modified = True
            log_admin_event('login_fail', error, user_email=email, ip=flask_request.remote_addr)
            flash(error)

    return render_template('auth/login.html')

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        db = get_db()
        # Convert string back to ObjectId when querying
        g.user = db['users'].find_one({'_id': ObjectId(user_id)})
    

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))

        return view(**kwargs)

    return wrapped_view


def student_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        
        if g.user.get('role') != 'student':
            flash('Access denied. This page is only available to students.')
            return redirect(url_for('index'))

        return view(**kwargs)

    return wrapped_view


def recruiter_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        
        if g.user.get('role') != 'recruiter':
            flash('Access denied. This page is only available to recruiters.')
            return redirect(url_for('index'))
        
        # Check if the recruiter is verified
        if g.user.get('verification_status') == 'rejected':
            flash('Your recruiter account has been rejected. Please contact the administrator.')
            return redirect(url_for('index'))

        return view(**kwargs)

    return wrapped_view


def verified_recruiter_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        
        if g.user.get('role') != 'recruiter':
            flash('Access denied. This page is only available to recruiters.')
            return redirect(url_for('index'))
        
        # Check if the recruiter is verified
        if g.user.get('verification_status') != 'approved':
            flash('This action requires a verified recruiter account. Your account is currently pending verification.')
            return redirect(url_for('index'))

        return view(**kwargs)

    return wrapped_view

