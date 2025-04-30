import datetime

LOG_FILE = 'admin.log'

def log_admin_event(event_type, message, user_email=None, ip=None):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {event_type.upper()}: {message}"
    if user_email:
        log_entry += f" | User: {user_email}"
    if ip:
        log_entry += f" | IP: {ip}"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_entry + '\n')
