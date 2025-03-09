from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from config import Config
from models import users
from models.user import User
from models.appointment import Appointment
from models.queue import QueueManager
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
import json
import os

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

mail = Mail(app)

# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    user = users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return None
    
    # Create a user-like object that Flask-Login can use
    class UserObject:
        def __init__(self, id, email, name, role):
            self.id = str(id)
            self.email = email
            self.name = name
            self.role = role
            self.is_authenticated = True
            self.is_active = True
            self.is_anonymous = False
        
        def get_id(self):
            return self.id
    
    return UserObject(
        user['_id'], 
        user['email'], 
        user['name'],
        user['role']
    )

# Scheduler for background tasks
scheduler = BackgroundScheduler()

# Scheduler job to send appointment reminders
def send_reminders():
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Find appointments for tomorrow
    upcoming_appointments = list(Appointment.find_by_date(tomorrow, status='scheduled'))
    
    for appt in upcoming_appointments:
        # Get patient info
        patient = users.find_one({'_id': appt['patient_id']})
        doctor = users.find_one({'_id': appt['doctor_id']})
        
        if patient and 'email' in patient:
            # Send email reminder
            msg = Message(
                subject="Appointment Reminder",
                recipients=[patient['email']],
                body=f"Dear {patient['name']},\n\nThis is a reminder for your appointment tomorrow at {appt['time_slot']} with Dr. {doctor['name']}.\n\nPlease arrive 15 minutes early for check-in.\n\nThank you,\nHealthcare Queue Management System"
            )
            mail.send(msg)
            
            # Update appointment with reminder sent status
            Appointment.update_status(
                appt['_id'], 
                'scheduled', 
                {'reminder_sent': True}
            )

# Start scheduler
scheduler.add_job(send_reminders, 'cron', hour=17)  # Send reminders at 5 PM every day
scheduler.start()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.get_by_email(email)
        
        if user and User.verify_password(user, password):
            # Create user object for flask-login
            user_obj = load_user(str(user['_id']))
            login_user(user_obj)
            
            if user['role'] == 'patient':
                return redirect(url_for('patient_dashboard'))
            elif user['role'] == 'doctor':
                return redirect(url_for('doctor_dashboard'))
            else:
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        role = request.form.get('role', 'patient')
        phone = request.form.get('phone')
        
        # Check if user already exists
        existing_user = User.get_by_email(email)
        if existing_user:
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        # Create new user
        user_id = User.create_user(email, password, name, role, phone)
        
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Patient routes
@app.route('/patient/dashboard')
@login_required
def patient_dashboard():
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Get upcoming appointments
    upcoming = Appointment.get_by_patient(current_user.id, status=['scheduled', 'checked-in'])
    
    # Get queue status for upcoming appointments
    queue_status = {}
    for appt in upcoming:
        if appt['status'] == 'checked-in':
            dept_status = QueueManager.get_department_status(appt['department'])
            if dept_status:
                queue_status[str(appt['_id'])] = {
                    'position': dept_status['checked_in_count'],
                    'wait_time': dept_status['estimated_wait']
                }
    
    return render_template(
        'patient/dashboard.html', 
        upcoming_appointments=upcoming,
        queue_status=queue_status
    )

@app.route('/patient/book_appointment')
@login_required
def book_appointment_page():
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Get all doctors
    doctors = User.get_doctors()
    
    return render_template('patient/book_appointment.html', doctors=doctors)

@app.route('/api/available_slots', methods=['GET'])
@login_required
def get_available_slots():
    doctor_id = request.args.get('doctor_id')
    date = request.args.get('date')
    
    if not doctor_id or not date:
        return jsonify({'error': 'Missing parameters'}), 400
    
    slots = Appointment.get_available_slots(doctor_id, date)
    return jsonify({'slots': slots})

@app.route('/patient/book_appointment', methods=['POST'])
@login_required
def book_appointment():
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    doctor_id = request.form.get('doctor_id')
    date = request.form.get('date')
    time_slot = request.form.get('time_slot')
    reason = request.form.get('reason')
    
    # Create appointment
    appointment_id = Appointment.create(
        current_user.id,
        doctor_id,
        date,
        time_slot,
        reason
    )
    
    flash('Appointment booked successfully', 'success')
    return redirect(url_for('patient_dashboard'))

@app.route('/patient/appointment/<appointment_id>')
@login_required
def view_appointment(appointment_id):
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Find the appointment
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['patient_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('patient_dashboard'))
    
    # Check queue status if checked in
    queue_info = None
    if appointment['status'] == 'checked-in':
        dept_status = QueueManager.get_department_status(appointment['department'])
        if dept_status:
            queue_info = {
                'position': dept_status['checked_in_count'],
                'wait_time': dept_status['estimated_wait']
            }
    
    return render_template(
        'patient/view_appointment.html',
        appointment=appointment,
        queue_info=queue_info
    )

@app.route('/patient/check_in/<appointment_id>', methods=['POST'])
@login_required
def check_in(appointment_id):
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Find the appointment
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['patient_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('patient_dashboard'))
    
    if appointment['status'] != 'scheduled':
        flash('Cannot check in - appointment is not in scheduled status', 'error')
        return redirect(url_for('view_appointment', appointment_id=appointment_id))
    
    # Check in
    estimated_wait = QueueManager.check_in_patient(appointment_id)
    
    flash(f'Check-in successful. Estimated wait time: {estimated_wait} minutes', 'success')
    return redirect(url_for('view_appointment', appointment_id=appointment_id))

@app.route('/patient/cancel_appointment/<appointment_id>', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Find the appointment
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['patient_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('patient_dashboard'))
    
    if appointment['status'] not in ['scheduled']:
        flash('Cannot cancel - appointment is already in progress or completed', 'error')
        return redirect(url_for('view_appointment', appointment_id=appointment_id))
    
    # Cancel the appointment
    Appointment.update_status(appointment_id, 'cancelled')
    
    flash('Appointment cancelled successfully', 'success')
    return redirect(url_for('patient_dashboard'))

# Doctor routes
@app.route('/doctor/dashboard')
@login_required
def doctor_dashboard():
    if current_user.role != 'doctor':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Get today's date
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    # Get today's appointments
    todays_appointments = Appointment.get_by_doctor(current_user.id, date=today)
    
    # Get checked-in patients
    checked_in = [a for a in todays_appointments if a['status'] == 'checked-in']
    
    # Get upcoming appointments (future dates)
    upcoming = Appointment.get_by_doctor(
        current_user.id, 
        status='scheduled',
        future_only=True  # Use the new future_only argument
    )
    
    return render_template(
        'doctor/dashboard.html',
        todays_appointments=todays_appointments,
        checked_in=checked_in,
        upcoming=upcoming
    )
# def doctor_dashboard():
#     if current_user.role != 'doctor':
#         flash('Unauthorized access', 'error')
#         return redirect(url_for('index'))
    
#     # Get today's date
#     today = datetime.utcnow().strftime('%Y-%m-%d')
    
#     # Get today's appointments
#     todays_appointments = Appointment.get_by_doctor(current_user.id, date=today)
    
#     # Get checked-in patients
#     checked_in = [a for a in todays_appointments if a['status'] == 'checked-in']
    
#     # Get upcoming appointments (future dates)
#     upcoming = Appointment.get_by_doctor(
#         current_user.id, 
#         status='scheduled',
#         future_only=True
#     )
    
#     return render_template(
#         'doctor/dashboard.html',
#         todays_appointments=todays_appointments,
#         checked_in=checked_in,
#         upcoming=upcoming
#     )

@app.route('/doctor/start_appointment/<appointment_id>', methods=['POST'])
@login_required
def start_appointment(appointment_id):
    if current_user.role != 'doctor':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Find the appointment
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['doctor_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('doctor_dashboard'))
    
    if appointment['status'] != 'checked-in':
        flash('Cannot start - patient is not checked in', 'error')
        return redirect(url_for('doctor_dashboard'))
    
    # Start the appointment
    Appointment.update_status(appointment_id, 'in-progress')
    
    # Update queue status
    QueueManager.update_department_status(appointment['department'])
    
    flash('Appointment started', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/complete_appointment/<appointment_id>', methods=['POST'])
@login_required
def complete_appointment(appointment_id):
    if current_user.role != 'doctor':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Find the appointment
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['doctor_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('doctor_dashboard'))
    
    if appointment['status'] != 'in-progress':
        flash('Cannot complete - appointment is not in progress', 'error')
        return redirect(url_for('doctor_dashboard'))
    
    # Complete the appointment
    Appointment.update_status(appointment_id, 'completed')
    
    # Update queue status
    QueueManager.update_department_status(appointment['department'])
    
    flash('Appointment completed', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/update_availability', methods=['GET', 'POST'])
@login_required
def update_availability():
    if current_user.role != 'doctor':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Process availability update
        # This would depend on how you structure availability data
        # For simplicity, we'll just show the concept
        flash('Availability updated', 'success')
        return redirect(url_for('doctor_dashboard'))
    
    return render_template('doctor/update_availability.html')

# Queue Status API
@app.route('/api/queue_status')
def get_queue_status():
    department = request.args.get('department')
    
    if department:
        status = QueueManager.get_department_status(department)
        if status:
            return jsonify(status)
        return jsonify({'error': 'Department not found'}), 404
    
    # Get all departments' status
    all_status = QueueManager.get_department_status()
    return jsonify(all_status)

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

# Cleanup function for the scheduler
@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    if not os.path.exists('instance'):
        os.makedirs('instance')
    app.run(debug=True)
