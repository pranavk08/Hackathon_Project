from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from config import Config
from models import users
from models.user import User
from models.appointment import Appointment
from models.queue import QueueManager
from bson import ObjectId
from datetime import datetime
from flask import jsonify
from flask_login import current_user, login_required

# Make sure your MongoDB connection is properly initialized
# Add this near the top of your app.py
from pymongo import MongoClient

# MongoDB connection
client = MongoClient('mongodb://localhost:27017/')
db = client['healthcare_queue']
from datetime import datetime, timedelta
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
import json
import os
from flask import make_response

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

    try:
        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get upcoming appointments (scheduled and checked-in)
        upcoming = Appointment.get_by_patient(
            current_user.id,
            status=['scheduled', 'checked-in']
        )
        
        # Separate today's appointments from future appointments
        todays_appointments = [appt for appt in upcoming if appt['date'] == today]
        future_appointments = [appt for appt in upcoming if appt['date'] > today]
        
        # Get queue status for checked-in appointments
        for appt in todays_appointments:
            if appt['status'] == 'checked-in':
                dept_status = QueueManager.get_department_status(appt['department'])
                if dept_status:
                    appt['queue_info'] = {
                        'position': dept_status['checked_in_count'],
                        'wait_time': appt['estimated_wait_time'] or dept_status['estimated_wait']
                    }
        
        # Get past appointments
        past_appointments = Appointment.get_by_patient(
            current_user.id,
            status='completed'
        )

        return render_template(
            'patient/dashboard.html',
            today_appointments=todays_appointments,
            upcoming_appointments=future_appointments,
            past_appointments=past_appointments
        )
        
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/patient/book_appointment')
@login_required
def book_appointment_page():
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    # Get all doctors
    doctors = User.get_doctors()
    
    # Get hospitals data and convert ObjectId to string
    try:
        hospitals = list(db.Hospitals.find())
        # Convert ObjectId to string for JSON serialization
        for hospital in hospitals:
            hospital['_id'] = str(hospital['_id'])
            for h in hospital.get('hospitals', []):
                if '_id' in h:
                    h['_id'] = str(h['_id'])
                for dept in h.get('departments', []):
                    if '_id' in dept:
                        dept['_id'] = str(dept['_id'])
                    for doc in dept.get('doctors', []):
                        if '_id' in doc:
                            doc['_id'] = str(doc['_id'])
    except Exception as e:
        hospitals = []
        flash('Error loading hospitals data', 'error')
    
    return render_template('patient/book_appointment.html', 
                         doctors=doctors,
                         hospitals=hospitals)

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
    
    try:
        result = Appointment.create(
            current_user.id,
            doctor_id,
            date,
            time_slot,
            reason
        )
        
        flash('Appointment booked successfully', 'success')
        return redirect(url_for('view_appointment', appointment_id=result['appointment_id']))
        
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('book_appointment_page'))

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
                'wait_time': appointment['estimated_wait_time'] or dept_status['estimated_wait']
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
# Add this new API endpoint for doctor appointments
@app.route('/api/patient/appointments')
@login_required
def get_patient_appointments():
    if current_user.role != 'patient':
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get all non-completed appointments
        appointments = Appointment.get_by_patient(
            current_user.id,
            status=['scheduled', 'checked-in', 'in-progress']
        )
        
        # Separate today's and upcoming appointments
        today_appts = []
        upcoming_appts = []
        
        for appt in appointments:
            # Add queue information for checked-in appointments
            if appt['status'] == 'checked-in':
                dept_status = QueueManager.get_department_status(appt['department'])
                if dept_status:
                    appt['queue_info'] = {
                        'position': dept_status['checked_in_count'],
                        'wait_time': appt['estimated_wait_time'] or dept_status['estimated_wait']
                    }
            
            # Separate appointments by date
            if appt['date'] == today:
                today_appts.append(appt)
            elif appt['date'] > today:
                upcoming_appts.append(appt)
        
        return jsonify({
            'today': today_appts,
            'upcoming': upcoming_appts,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

@app.route('/api/doctor/appointments')
@login_required
def get_doctor_appointments():
    if current_user.role != 'doctor':
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get all appointments for today
        todays_appointments = Appointment.get_by_doctor(
            current_user.id,
            date=today,
            status=['scheduled', 'checked-in', 'in-progress', 'completed']
        )
        
        # Get upcoming appointments
        upcoming_appointments = Appointment.get_by_doctor(
            current_user.id,
            status=['scheduled'],
            future_only=True
        )
        # Filter out today's appointments from upcoming
        upcoming_appointments = [appt for appt in upcoming_appointments if appt['date'] > today]
        
        # Get department queue status
        doctor = db.users.find_one({'_id': ObjectId(current_user.id)})
        department = doctor.get('department', 'General')
        dept_status = QueueManager.get_department_status(department)
        
        # Update queue information for checked-in appointments
        for appt in todays_appointments:
            if appt['status'] == 'checked-in' and dept_status:
                appt['queue_info'] = {
                    'position': dept_status['checked_in_count'],
                    'wait_time': appt['estimated_wait_time'] or dept_status['estimated_wait']
                }
        
        # Calculate queue metrics
        queue_metrics = {
            'waiting': len([a for a in todays_appointments if a['status'] == 'checked-in']),
            'completed': len([a for a in todays_appointments if a['status'] == 'completed']),
            'scheduled': len([a for a in todays_appointments if a['status'] == 'scheduled']),
            'in_progress': len([a for a in todays_appointments if a['status'] == 'in-progress'])
        }
        
        return jsonify({
            'today': todays_appointments,
            'upcoming': upcoming_appointments,
            'queue_metrics': queue_metrics,
            'department': department,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

@app.route('/doctor/dashboard')
@login_required
def doctor_dashboard():
    if current_user.role != 'doctor':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
        
    try:
        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get today's appointments
        todays_appointments = Appointment.get_by_doctor(
            current_user.id,
            date=today,
            status=['scheduled', 'checked-in', 'in-progress']
        )
        
        # Get upcoming appointments (excluding today)
        upcoming_appointments = Appointment.get_by_doctor(
            current_user.id,
            status=['scheduled'],
            future_only=True
        )
        # Filter out today's appointments from upcoming
        upcoming_appointments = [appt for appt in upcoming_appointments if appt['date'] > today]
        
        # Get completed appointments for today
        completed_today = Appointment.get_by_doctor(
            current_user.id,
            date=today,
            status='completed'
        )
        
        # Calculate queue metrics
        queue_metrics = {
            'waiting': len([a for a in todays_appointments if a['status'] == 'checked-in']),
            'completed': len(completed_today),
            'scheduled': len([a for a in todays_appointments if a['status'] == 'scheduled']),
            'in_progress': len([a for a in todays_appointments if a['status'] == 'in-progress'])
        }
        
        # Get department queue status
        doctor = db.users.find_one({'_id': ObjectId(current_user.id)})
        department = doctor.get('department', 'General')
        dept_status = QueueManager.get_department_status(department)
        
        # Update wait times for checked-in appointments
        for appt in todays_appointments:
            if appt['status'] == 'checked-in' and dept_status:
                appt['queue_info'] = {
                    'position': dept_status['checked_in_count'],
                    'wait_time': appt['estimated_wait_time'] or dept_status['estimated_wait']
                }
        
        return render_template(
            'doctor/dashboard.html',
            today_appointments=todays_appointments,
            upcoming_appointments=upcoming_appointments,
            completed_today=completed_today,
            queue_metrics=queue_metrics,
            department=department,
            current_date=today
        )
        
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return redirect(url_for('index'))

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

@app.route('/appointment/<appointment_id>/reschedule', methods=['GET', 'POST'])
@login_required
def appointment_reschedule(appointment_id):
    try:
        # Get the appointment
        appointment = Appointment.get_by_id(appointment_id)
        if not appointment:
            flash('Appointment not found', 'error')
            return redirect(url_for('index'))
            
        # Check authorization
        if current_user.role == 'patient' and str(appointment['patient_id']) != str(current_user.id):
            flash('Unauthorized access', 'error')
            return redirect(url_for('index'))
        elif current_user.role == 'doctor' and str(appointment['doctor_id']) != str(current_user.id):
            flash('Unauthorized access', 'error')
            return redirect(url_for('index'))
            
        if request.method == 'POST':
            new_date = request.form.get('date')
            new_time = request.form.get('time_slot')
            
            if not new_date or not new_time:
                flash('Please select both date and time', 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
            
            # Check if the selected time slot is available
            if not Appointment.is_time_slot_available(
                appointment['doctor_id'], 
                new_date, 
                new_time, 
                exclude_appointment_id=appointment_id
            ):
                flash('This time slot is not available. Please select another time.', 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
                
            # Update the appointment
            update_data = {
                'date': new_date,
                'time_slot': new_time,
                'status': 'scheduled'  # Reset status to scheduled
            }
            
            try:
                Appointment.update_appointment(appointment_id, update_data)
                flash('Appointment rescheduled successfully', 'success')
                if current_user.role == 'doctor':
                    return redirect(url_for('doctor_dashboard'))
                else:
                    return redirect(url_for('patient_dashboard'))
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
            except Exception as e:
                flash('An unexpected error occurred. Please try again.', 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
        
        # GET request - show reschedule form
        return render_template(
            'reschedule_appointment.html',
            appointment=appointment,
            current_date=datetime.now().strftime('%Y-%m-%d')
        )
    except Exception as e:
        flash('An unexpected error occurred. Please try again.', 'error')
        return redirect(url_for('index'))

@app.route('/api/check_time_slots', methods=['GET'])
@login_required
def check_time_slots():
    try:
        doctor_id = request.args.get('doctor_id')
        date = request.args.get('date')
        appointment_id = request.args.get('appointment_id')
        
        if not doctor_id or not date:
            return jsonify({
                'error': 'Missing required parameters',
                'success': False
            }), 400
            
        # Get all time slots
        all_slots = [
            "09:00-09:30", "09:30-10:00", "10:00-10:30", "10:30-11:00",
            "11:00-11:30", "11:30-12:00", "14:00-14:30", "14:30-15:00",
            "15:00-15:30", "15:30-16:00", "16:00-16:30", "16:30-17:00"
        ]
        
        # Check availability for each slot
        available_slots = []
        for slot in all_slots:
            if Appointment.is_time_slot_available(doctor_id, date, slot, appointment_id):
                available_slots.append(slot)
                
        return jsonify({
            'available_slots': available_slots,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

@app.route('/api/peak_hours')
def get_peak_hours():
    try:
        # Get all appointments for the next 7 days
        start_date = datetime.now()
        end_date = start_date + timedelta(days=7)
        
        # Aggregate appointments by hour
        pipeline = [
            {
                '$match': {
                    'date': {
                        '$gte': start_date.strftime('%Y-%m-%d'),
                        '$lte': end_date.strftime('%Y-%m-%d')
                    },
                    'status': {'$in': ['scheduled', 'checked-in']}
                }
            },
            {
                '$group': {
                    '_id': {'$substr': ['$time_slot', 0, 5]},  # Group by start time
                    'count': {'$sum': 1}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        peak_hours = list(db.appointments.aggregate(pipeline))
        
        # Categorize hours as high, medium, or low traffic
        max_count = max([p['count'] for p in peak_hours]) if peak_hours else 0
        
        for hour in peak_hours:
            if hour['count'] >= max_count * 0.7:
                hour['traffic'] = 'high'
            elif hour['count'] >= max_count * 0.3:
                hour['traffic'] = 'medium'
            else:
                hour['traffic'] = 'low'
        
        return jsonify({
            'peak_hours': peak_hours,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

if __name__ == '__main__':
    if not os.path.exists('instance'):
        os.makedirs('instance')
    app.run(debug=True)
