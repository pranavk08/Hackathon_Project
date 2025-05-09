import datetime
import os
from datetime import datetime, timedelta
from collections import defaultdict
from flask import current_app

def get_log_path():
    return os.path.join(current_app.instance_path, 'admin.log')

def log_admin_event(event_type, message, user_email=None, ip=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {event_type.upper()}: {message}"
    if user_email:
        log_entry += f" | User: {user_email}"
    if ip:
        log_entry += f" | IP: {ip}"
    
    # Ensure the instance directory exists
    os.makedirs(os.path.dirname(get_log_path()), exist_ok=True)
    
    # Write to the log file in the instance directory
    with open(get_log_path(), 'a', encoding='utf-8') as f:
        f.write(log_entry + '\n')


def get_user_activity_data(days=7):
    """Extract login and registration activity from logs for the specified number of days.
    Returns data suitable for the admin dashboard chart.
    """
    # Initialize data structures
    login_data = defaultdict(int)
    registration_data = defaultdict(int)
    
    # Calculate the start date
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Generate date labels for the specified range
    date_labels = []
    current_date = start_date
    while current_date <= end_date:
        date_labels.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)
    
    # Initialize counters for each date
    for date in date_labels:
        login_data[date] = 0
        registration_data[date] = 0
    
    try:
        # Read the log file
        with open(get_log_path(), 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    # Extract timestamp
                    timestamp_str = line.split(']')[0].strip('[') if ']' in line else ''
                    if not timestamp_str:
                        continue
                        
                    # Parse the timestamp
                    log_date = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    log_date_str = log_date.strftime('%Y-%m-%d')
                    
                    # Skip if outside our date range
                    if log_date < start_date or log_date > end_date:
                        continue
                    
                    # Check event type
                    if 'LOGIN_SUCCESS' in line:
                        login_data[log_date_str] += 1
                    elif 'REGISTER_SUCCESS' in line:
                        registration_data[log_date_str] += 1
                except Exception:
                    # Skip lines that can't be parsed
                    continue
    except (FileNotFoundError, IOError):
        # If log file doesn't exist or can't be read
        pass
    
    # Format for chart.js
    if days <= 7:
        # For weekly view, use day names
        formatted_labels = []
        for date_str in date_labels:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            formatted_labels.append(date_obj.strftime('%a'))
    else:
        # For longer periods, use date format
        formatted_labels = [datetime.strptime(date, '%Y-%m-%d').strftime('%b %d') for date in date_labels]
    
    # Convert to lists in the same order as labels
    login_counts = [login_data[date] for date in date_labels]
    registration_counts = [registration_data[date] for date in date_labels]
    
    return {
        'labels': formatted_labels,
        'login_data': login_counts,
        'registration_data': registration_counts
    }
