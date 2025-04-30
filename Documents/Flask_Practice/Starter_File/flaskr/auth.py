import functools
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)
import re
import time
from flask import request as flask_request
from flaskr.admin_log import log_admin_event
from werkzeug.security import check_password_hash, generate_password_hash
from bson.objectid import ObjectId

from flaskr.db import get_db
from pymongo.errors import DuplicateKeyError

from flask import current_app

bp = Blueprint('auth', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        db = get_db()
        error = None

        # Email format validation
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        # Password strength: at least 8 chars, 1 uppercase, 1 lowercase, 1 digit
        password_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"

        if not username:
            error = 'Username is required.'
        elif not email:
            error = 'Email is required.'
        elif not re.match(email_regex, email):
            error = 'Please enter a valid email address.'
        elif not password:
            error = 'Password is required.'
        elif not re.match(password_regex, password):
            error = 'Password must be at least 8 characters long, contain an uppercase letter, a lowercase letter, and a digit.'

        if error is None:
            users = db['users']
            # Ensure a unique index exists on 'email' in the MongoDB shell with:
            # db.users.createIndex({email: 1}, {unique: true})
            if users.find_one({'email': email}):
                error = f"An account with this email already exists. Please use a different email."
                log_admin_event('register_fail', 'Attempt to register with duplicate email.', user_email=email, ip=flask_request.remote_addr)
            elif users.find_one({'username': username}):
                error = f"This username is already taken. Please choose another."
                log_admin_event('register_fail', 'Attempt to register with duplicate username.', user_email=email, ip=flask_request.remote_addr)
            else:
                try:
                    users.insert_one({
                        'username': username,
                        'email': email,
                        'password': generate_password_hash(password)
                    })
                    log_admin_event('register_success', 'User registered successfully.', user_email=email, ip=flask_request.remote_addr)
                    flash('Registration successful! Please log in.')
                    return redirect(url_for('auth.login'))
                except DuplicateKeyError:
                    error = f"A user with this email or username already exists. Please try again with different credentials."
                    log_admin_event('register_fail', 'DuplicateKeyError on registration.', user_email=email, ip=flask_request.remote_addr)

        if error:
            log_admin_event('register_error', error, user_email=email, ip=flask_request.remote_addr)
        flash(error)

    return render_template('auth/register.html')



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

        user = db['users'].find_one({'email': email}) if error is None else None

        if error is None:
            if user is None:
                error = 'No account found with this email.'
            elif not check_password_hash(user['password'], password):
                error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = str(user['_id'])
            log_admin_event('login_success', 'User logged in successfully.', user_email=email, ip=flask_request.remote_addr)
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

