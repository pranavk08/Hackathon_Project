from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from config import Config
from models import users
from models.user import User
from models.appointment import Appointment
from models.queue import QueueManager
from pymongo import MongoClient
from datetime import datetime
from flask import jsonify
from flask_login import current_user, login_required
from bson import ObjectId  # Add this import

from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['hospital_management']  # Updated database name
from datetime import datetime, timedelta
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
import json
import os
from flask import make_response
from ai_predictor import AppointmentPredictor

app = Flask(__name__)
app.config.from_object(Config)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

mail = Mail(app)

@login_manager.user_loader
def load_user(user_id):
    user = users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return None

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

scheduler = BackgroundScheduler()

def send_reminders():
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')
    upcoming_appointments = list(Appointment.find_by_date(tomorrow, status='scheduled'))
    
    for appt in upcoming_appointments:
        patient = users.find_one({'_id': appt['patient_id']})
        doctor = users.find_one({'_id': appt['doctor_id']})
        
        if patient and 'email' in patient:
            msg = Message(
                subject="Appointment Reminder",
                recipients=[patient['email']],
                body=f"Dear {patient['name']},\n\nThis is a reminder for your appointment tomorrow at {appt['time_slot']} with Dr. {doctor['name']}.\n\nPlease arrive 15 minutes early for check-in.\n\nThank you,\nHealthcare Queue Management System"
            )
            mail.send(msg)
            Appointment.update_status(
                appt['_id'], 
                'scheduled', 
                {'reminder_sent': True}
            )
scheduler.add_job(send_reminders, 'cron', hour=17)  # Send reminders at 5 PM every day
scheduler.start()

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
        existing_user = User.get_by_email(email)
        if existing_user:
            flash('Email already registered', 'error')
            return render_template('register.html')
        user_id = User.create_user(email, password, name, role, phone)
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/patient/dashboard')
@login_required
def patient_dashboard():
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))

    try:
        today = datetime.now().strftime('%Y-%m-%d')
        upcoming = Appointment.get_by_patient(
            current_user.id,
            status=['scheduled', 'checked-in']
        )
        todays_appointments = [appt for appt in upcoming if appt['date'] == today]
        future_appointments = [appt for appt in upcoming if appt['date'] > today]

        for appt in todays_appointments:
            if appt['status'] == 'checked-in':
                dept_status = QueueManager.get_department_status(appt['department'])
                if dept_status:
                    appt['queue_info'] = {
                        'position': dept_status['checked_in_count'],
                        'wait_time': appt['estimated_wait_time'] or dept_status['estimated_wait']
                    }
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
    
    try:
        hospital_doc = db.Hospitals.find_one()
        
        if not hospital_doc:
            flash('No hospitals found in the database', 'error')
            return redirect(url_for('patient_dashboard'))
            
        hospitals = hospital_doc.get('hospitals', [])
        today = datetime.now().strftime('%Y-%m-%d')
        
        return render_template('patient/book_appointment.html', 
                             hospitals=hospitals,
                             today=today)
                             
    except Exception as e:
        print(f"Error loading hospitals: {str(e)}")  # For debugging
        flash('Error loading hospitals data: ' + str(e), 'error')
        return redirect(url_for('patient_dashboard'))

@app.route('/api/available_slots', methods=['GET'])
@login_required
def get_available_slots():
    doctor_id = request.args.get('doctor_id')
    date = request.args.get('date')
    
    if not doctor_id or not date:
        return jsonify({'error': 'Missing parameters'}), 400
    
    try:
        doctor_id = int(doctor_id)
        pipeline = [
            {"$unwind": "$hospitals"},
            {"$unwind": "$hospitals.departments"},
            {"$unwind": "$hospitals.departments.doctors"},
            {"$match": {"hospitals.departments.doctors.doctor_id": doctor_id}},
            {"$project": {
                "slots": {
                    "$filter": {
                        "input": "$hospitals.departments.doctors.available_slots",
                        "as": "slot",
                        "cond": {
                            "$and": [
                                {"$eq": ["$$slot.date", date]},
                                {"$eq": ["$$slot.is_available", True]}
                            ]
                        }
                    }
                }
            }}
        ]
        
        result = list(db.Hospitals.aggregate(pipeline))
        
        if not result or not result[0].get('slots'):
            return jsonify({'slots': []})
        
        slots = result[0]['slots']
        return jsonify({
            'slots': [{'slot_id': slot['slot_id'], 'time': slot['time']} for slot in slots]
        })
        
    except Exception as e:
        print(f"Error fetching slots: {str(e)}")  # For debugging
        return jsonify({'error': str(e)}), 500

@app.route('/patient/book_appointment', methods=['POST'])
@login_required
def book_appointment():
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    doctor_id = request.form.get('doctor_id', '')
    slot_id = request.form.get('slot_id', '')
    reason = request.form.get('reason', '')
    
    if not all([doctor_id, slot_id, reason]):
        flash('Please fill in all required fields', 'error')
        return redirect(url_for('book_appointment_page'))

    try:
        doctor_id = int(doctor_id)
        slot_id = int(slot_id)
    except (ValueError, TypeError):
        flash('Invalid doctor or slot selected', 'error')
        return redirect(url_for('book_appointment_page'))
    
    try:
        result = db.Hospitals.aggregate([
            {"$unwind": "$hospitals"},
            {"$unwind": "$hospitals.departments"},
            {"$unwind": "$hospitals.departments.doctors"},
            {"$match": {"hospitals.departments.doctors.doctor_id": doctor_id}},
            {"$project": {
                "hospital_name": "$hospitals.hospital_name",
                "department_name": "$hospitals.departments.department_name",
                "doctor_name": "$hospitals.departments.doctors.doctor_name",
                "slot": {
                    "$filter": {
                        "input": "$hospitals.departments.doctors.available_slots",
                        "as": "slot",
                        "cond": {"$eq": ["$$slot.slot_id", slot_id]}
                    }
                }
            }}
        ])
        
        result = list(result)
        if not result or not result[0].get('slot'):
            flash('Selected slot is not available', 'error')
            return redirect(url_for('book_appointment_page'))
            
        appointment_info = result[0]
        slot = appointment_info['slot'][0]
        appointment = {
            'patient_id': current_user.id,
            'doctor_id': doctor_id,
            'slot_id': slot_id,
            'date': slot['date'],
            'time': slot['time'],
            'reason': reason,
            'status': 'scheduled',
            'hospital_name': appointment_info['hospital_name'],
            'department_name': appointment_info['department_name'],
            'doctor_name': appointment_info['doctor_name'],
            'created_at': datetime.now()
        }
        db.Appointments.insert_one(appointment)
        db.Hospitals.update_one(
            {"hospitals.departments.doctors.doctor_id": doctor_id},
            {"$pull": {"hospitals.$[].departments.$[].doctors.$[].available_slots": {"slot_id": slot_id}}}
        )
        flash('Appointment booked successfully', 'success')
        return redirect(url_for('patient_dashboard'))  
    except Exception as e:
        flash('Error booking appointment: ' + str(e), 'error')
        return redirect(url_for('book_appointment_page'))

@app.route('/patient/appointment/<appointment_id>')
@login_required
def view_appointment(appointment_id):
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['patient_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('patient_dashboard'))
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
    appointment = Appointment.get_by_id(appointment_id)
    if not appointment or str(appointment['patient_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('patient_dashboard'))
    
    if appointment['status'] != 'scheduled':
        flash('Cannot check in - appointment is not in scheduled status', 'error')
        return redirect(url_for('view_appointment', appointment_id=appointment_id))
    
    estimated_wait = QueueManager.check_in_patient(appointment_id)
    flash(f'Check-in successful. Estimated wait time: {estimated_wait} minutes', 'success')
    return redirect(url_for('view_appointment', appointment_id=appointment_id))

@app.route('/patient/cancel_appointment/<appointment_id>', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))

    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['patient_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('patient_dashboard'))
    
    if appointment['status'] not in ['scheduled']:
        flash('Cannot cancel - appointment is already in progress or completed', 'error')
        return redirect(url_for('view_appointment', appointment_id=appointment_id))

    Appointment.update_status(appointment_id, 'cancelled')
    
    flash('Appointment cancelled successfully', 'success')
    return redirect(url_for('patient_dashboard'))

@app.route('/api/patient/appointments')
@login_required
def get_patient_appointments():
    if current_user.role != 'patient':
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        appointments = Appointment.get_by_patient(
            current_user.id,
            status=['scheduled', 'checked-in', 'in-progress']
        )
        today_appts = []
        upcoming_appts = []
        
        for appt in appointments:
            if appt['status'] == 'checked-in':
                dept_status = QueueManager.get_department_status(appt['department'])
                if dept_status:
                    appt['queue_info'] = {
                        'position': dept_status['checked_in_count'],
                        'wait_time': appt['estimated_wait_time'] or dept_status['estimated_wait']
                    }
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
        today = datetime.now().strftime('%Y-%m-%d')
        
        todays_appts = list(db.Appointments.find({
            'doctor_id': current_user.id,
            'date': today,
            'status': {'$in': ['scheduled', 'checked-in', 'in-progress']}
        }))
        
        upcoming_appts = list(db.Appointments.find({
            'doctor_id': current_user.id,
            'status': 'scheduled',
            'date': {'$gt': today}
        }))
        
        return jsonify({
            'today': todays_appts,
            'upcoming': upcoming_appts,
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
        today = datetime.now().strftime('%Y-%m-%d')
        todays_appointments = Appointment.get_by_doctor(
            current_user.id,
            date=today,
            status=['scheduled', 'checked-in', 'in-progress']
        )
        upcoming_appointments = Appointment.get_by_doctor(
            current_user.id,
            status=['scheduled'],
            future_only=True
        )
        upcoming_appointments = [appt for appt in upcoming_appointments if appt['date'] > today]
        completed_today = Appointment.get_by_doctor(
            current_user.id,
            date=today,
            status='completed'
        )
        queue_metrics = {
            'waiting': len([a for a in todays_appointments if a['status'] == 'checked-in']),
            'completed': len(completed_today),
            'scheduled': len([a for a in todays_appointments if a['status'] == 'scheduled']),
            'in_progress': len([a for a in todays_appointments if a['status'] == 'in-progress'])
        }
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
    
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['doctor_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('doctor_dashboard'))
    
    if appointment['status'] != 'checked-in':
        flash('Cannot start - patient is not checked in', 'error')
        return redirect(url_for('doctor_dashboard'))

    Appointment.update_status(appointment_id, 'in-progress')

    QueueManager.update_department_status(appointment['department'])
    
    flash('Appointment started', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/complete_appointment/<appointment_id>', methods=['POST'])
@login_required
def complete_appointment(appointment_id):
    if current_user.role != 'doctor':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    appointment = Appointment.get_by_id(appointment_id)
    
    if not appointment or str(appointment['doctor_id']) != current_user.id:
        flash('Appointment not found', 'error')
        return redirect(url_for('doctor_dashboard'))
    
    if appointment['status'] != 'in-progress':
        flash('Cannot complete - appointment is not in progress', 'error')
        return redirect(url_for('doctor_dashboard'))
    Appointment.update_status(appointment_id, 'completed')
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
        flash('Availability updated', 'success')
        return redirect(url_for('doctor_dashboard'))

    return render_template('doctor/update_availability.html')

@app.route('/api/queue_status')
def get_queue_status():
    department = request.args.get('department')
    
    if department:
        status = QueueManager.get_department_status(department)
        if status:
            return jsonify(status)
        return jsonify({'error': 'Department not found'}), 404
    all_status = QueueManager.get_department_status()
    return jsonify(all_status)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.route('/appointment/<appointment_id>/reschedule', methods=['GET', 'POST'])
@login_required
def appointment_reschedule(appointment_id):
    if current_user.role != 'patient':
        flash('Unauthorized access', 'error')
        return redirect(url_for('index'))
    
    try:
        appointment = db.Appointments.find_one({'_id': ObjectId(appointment_id)})
        
        if not appointment or str(appointment['patient_id']) != current_user.id:
            flash('Appointment not found', 'error')
            return redirect(url_for('patient_dashboard'))
        
        if request.method == 'POST':
            new_date = request.form.get('date')
            new_time = request.form.get('time')
            doctor_id = request.form.get('doctor_id')
            
            if not all([new_date, new_time, doctor_id]):
                flash('Please fill in all required fields', 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
            
            slot_available = check_slot_availability(doctor_id, new_date, new_time)
            if not slot_available:
                flash('This time slot is not available. Please select another time.', 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
            
            update_data = {
                'date': new_date,
                'time_slot': new_time,
                'doctor_id': int(doctor_id)
            }
            
            try:
                db.Appointments.update_one(
                    {'_id': ObjectId(appointment_id)},
                    {'$set': update_data}
                )
                flash('Appointment rescheduled successfully', 'success')
                return redirect(url_for('patient_dashboard'))
            except Exception as e:
                flash('An unexpected error occurred. Please try again.', 'error')
                return redirect(url_for('appointment_reschedule', appointment_id=appointment_id))
        
        return render_template(
            'reschedule_appointment.html',
            appointment=appointment,
            doctors=get_available_doctors()
        )
        
    except Exception as e:
        flash('An error occurred while processing your request', 'error')
        return redirect(url_for('patient_dashboard'))

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

        all_slots = [
            "09:00-09:30", "09:30-10:00", "10:00-10:30", "10:30-11:00",
            "11:00-11:30", "11:30-12:00", "14:00-14:30", "14:30-15:00",
            "15:00-15:30", "15:30-16:00", "16:00-16:30", "16:30-17:00"
        ]
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

from ai_predictor import AppointmentPredictor
predictor = AppointmentPredictor(db)
@app.route('/api/peak_hours')
def get_peak_hours():
    try:
        predictions = predictor.predict_peak_hours()
        start_date = datetime.now()
        end_date = start_date + timedelta(days=7)
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
                    '_id': {'$substr': ['$time_slot', 0, 5]},
                    'count': {'$sum': 1}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        peak_hours = list(db.appointments.aggregate(pipeline))
        if peak_hours:
            max_count = max([p['count'] for p in peak_hours])
            for hour in peak_hours:
                if hour['count'] >= max_count * 0.7:
                    hour['traffic'] = 'high'
                elif hour['count'] >= max_count * 0.3:
                    hour['traffic'] = 'medium'
                else:
                    hour['traffic'] = 'low'
        
        return jsonify({
            'historical_data': peak_hours,
            'ai_predictions': predictions if predictions else None,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        }), 500
@app.route('/api/suggest_slots')
@login_required
def suggest_appointment_slots():
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({
                'error': 'Date parameter is required',
                'success': False
            }), 400
        existing_appointments = list(db.appointments.find({
            'date': date,
            'status': {'$in': ['scheduled', 'checked-in']}
        }))
        
        suggestions = predictor.suggest_appointment_slots(date, existing_appointments)
        if not suggestions:
            return jsonify({
                'error': 'Could not generate suggestions',
                'success': False
            }), 400
            
        return jsonify({
            'suggestions': suggestions,
            'success': True
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

@app.teardown_appcontext
def shutdown_scheduler(exception=None):
    if scheduler.running:
        scheduler.shutdown()

if __name__ == '__main__':
    if not os.path.exists('instance'):
        os.makedirs('instance')
    app.run(debug=True)
