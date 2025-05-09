import functools
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, current_app, jsonify
)
from werkzeug.security import check_password_hash, generate_password_hash
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import os
from flaskr.db import get_db
from flaskr.auth import login_required
from flaskr.admin_log import log_admin_event, get_log_path, get_user_activity_data

bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(view):
    """View decorator that requires the user to be an administrator."""
    @functools.wraps(view)
    @login_required
    def wrapped_view(**kwargs):
        if not g.user.get('is_admin', False):
            log_admin_event('unauthorized_access', 'Non-admin user attempted to access admin area', 
                           user_email=g.user.get('email'), ip=request.remote_addr)
            flash('Administrator privileges required.', 'error')
            return redirect(url_for('index'))
        return view(**kwargs)
    return wrapped_view

@bp.route('/')
@admin_required
def index():
    """Admin dashboard home page."""
    db = get_db()
    
    # Get user statistics
    total_users = db['users'].count_documents({})
    admin_users = db['users'].count_documents({'is_admin': True})
    
    # Get recent registrations (last 7 days)
    one_week_ago = datetime.now() - timedelta(days=7)
    recent_users = db['users'].count_documents({
        'created_at': {'$gte': one_week_ago}
    })
    
    # Get recent login activity
    try:
        with open(get_log_path(), 'r') as f:
            log_lines = f.readlines()[-50:]  # Get last 50 lines
            login_activities = [line for line in log_lines if 'LOGIN_' in line]
    except (FileNotFoundError, IOError):
        login_activities = []
    
    # Get user activity data for the chart (default 7 days)
    user_activity = get_user_activity_data(days=7)
    
    log_admin_event('admin_dashboard_access', 'Admin accessed dashboard', 
                   user_email=g.user.get('email'), ip=request.remote_addr)
    
    return render_template('admin/index.html', 
                          total_users=total_users,
                          admin_users=admin_users,
                          recent_users=recent_users,
                          login_activities=login_activities,
                          user_activity=user_activity,
                          now=datetime.now())

@bp.route('/users')
@admin_required
def users():
    """List all users."""
    db = get_db()
    users_list = list(db['users'].find({}, {
        'username': 1, 
        'email': 1, 
        'phone': 1, 
        'is_admin': 1,
        'created_at': 1,
        'last_login': 1
    }).sort('created_at', -1))
    
    log_admin_event('admin_users_view', 'Admin viewed user list', 
                   user_email=g.user.get('email'), ip=request.remote_addr)
    
    return render_template('admin/users.html', users=users_list)

@bp.route('/users/<id>', methods=('GET', 'POST'))
@admin_required
def user_edit(id):
    """Edit a user."""
    db = get_db()
    user = db['users'].find_one({'_id': ObjectId(id)})
    
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        phone = request.form.get('phone')
        is_admin = 'is_admin' in request.form
        
        # Check if we're changing the password
        password = request.form.get('password')
        
        # Prepare update document
        update_doc = {
            'username': username,
            'email': email,
            'phone': phone,
            'is_admin': is_admin
        }
        
        if password:
            update_doc['password'] = generate_password_hash(password)
        
        try:
            db['users'].update_one(
                {'_id': ObjectId(id)},
                {'$set': update_doc}
            )
            log_admin_event('admin_user_edit', f'Admin edited user {email}', 
                           user_email=g.user.get('email'), ip=request.remote_addr)
            flash('User updated successfully.', 'success')
            return redirect(url_for('admin.users'))
        except Exception as e:
            flash(f'Error updating user: {str(e)}', 'error')
    
    return render_template('admin/user_edit.html', user=user)

@bp.route('/users/delete/<id>', methods=('POST',))
@admin_required
def user_delete(id):
    """Delete a user."""
    db = get_db()
    user = db['users'].find_one({'_id': ObjectId(id)})
    
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))
    
    # Don't allow deleting yourself
    if str(user['_id']) == session.get('user_id'):
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin.users'))
    
    try:
        db['users'].delete_one({'_id': ObjectId(id)})
        log_admin_event('admin_user_delete', f'Admin deleted user {user.get("email")}', 
                       user_email=g.user.get('email'), ip=request.remote_addr)
        flash('User deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')
    
    return redirect(url_for('admin.users'))

@bp.route('/logs')
@admin_required
def logs():
    """View admin logs."""
    try:
        with open(get_log_path(), 'r') as f:
            log_content = f.readlines()
    except (FileNotFoundError, IOError):
        log_content = []
    
    # Parse log entries for better display
    parsed_logs = []
    for line in log_content:
        try:
            # Extract timestamp, event type, and message
            parts = line.strip().split(']', 1)
            timestamp = parts[0].strip('[')
            
            # Extract event type
            event_parts = parts[1].split(':', 1)
            event_type = event_parts[0].strip()
            
            # Extract message and additional info
            message_parts = event_parts[1].split('|')
            message = message_parts[0].strip()
            
            # Extract user and IP if available
            user_email = None
            ip = None
            for part in message_parts[1:]:
                if 'User:' in part:
                    user_email = part.split('User:')[1].strip()
                elif 'IP:' in part:
                    ip = part.split('IP:')[1].strip()
            
            parsed_logs.append({
                'timestamp': timestamp,
                'event_type': event_type,
                'message': message,
                'user_email': user_email,
                'ip': ip
            })
        except Exception:
            # If parsing fails, just add the raw line
            parsed_logs.append({
                'timestamp': 'Unknown',
                'event_type': 'PARSE_ERROR',
                'message': line.strip(),
                'user_email': None,
                'ip': None
            })
    
    log_admin_event('admin_logs_view', 'Admin viewed logs', 
                   user_email=g.user.get('email'), ip=request.remote_addr)
    
    return render_template('admin/logs.html', logs=parsed_logs[::-1])  # Reverse to show newest first

@bp.route('/make-admin/<id>', methods=('POST',))
@admin_required
def make_admin(id):
    """Promote a user to admin status."""
    db = get_db()
    user = db['users'].find_one({'_id': ObjectId(id)})
    
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))
    
    try:
        db['users'].update_one(
            {'_id': ObjectId(id)},
            {'$set': {'is_admin': True}}
        )
        log_admin_event('admin_promotion', f'User {user.get("email")} promoted to admin', 
                       user_email=g.user.get('email'), ip=request.remote_addr)
        flash(f'User {user.get("username")} is now an administrator.', 'success')
    except Exception as e:
        flash(f'Error promoting user: {str(e)}', 'error')
    
    return redirect(url_for('admin.users'))

@bp.route('/revoke-admin/<id>', methods=('POST',))
@admin_required
def revoke_admin(id):
    """Revoke admin status from a user."""
    db = get_db()
    user = db['users'].find_one({'_id': ObjectId(id)})
    
    if user is None:
        flash('User not found.', 'error')
        return redirect(url_for('admin.users'))
    
    # Don't allow revoking your own admin status
    if str(user['_id']) == session.get('user_id'):
        flash('You cannot revoke your own admin privileges.', 'error')
        return redirect(url_for('admin.users'))
    
    try:
        db['users'].update_one(
            {'_id': ObjectId(id)},
            {'$set': {'is_admin': False}}
        )
        log_admin_event('admin_revocation', f'Admin status revoked from user {user.get("email")}', 
                       user_email=g.user.get('email'), ip=request.remote_addr)
        flash(f'Admin privileges revoked from {user.get("username")}.', 'success')
    except Exception as e:
        flash(f'Error revoking admin status: {str(e)}', 'error')
    
    return redirect(url_for('admin.users'))
