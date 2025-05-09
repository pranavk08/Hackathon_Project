import functools
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, jsonify
)
import datetime
from bson.objectid import ObjectId
from flaskr.db import get_db
from flaskr.auth import recruiter_required, verified_recruiter_required, student_required, login_required
from pymongo.errors import DuplicateKeyError

# Try to import notifications module
try:
    from flaskr.notifications import send_sms
except ImportError:
    # Define a dummy function if the notifications module is not available
    def send_sms(phone_number, message):
        print(f"Would send SMS to {phone_number}: {message}")
        return True

bp = Blueprint('interviews', __name__, url_prefix='/interviews')

@bp.route('/')
@login_required
def index():
    """Show all interviews based on user role"""
    db = get_db()
    
    if g.user.get('role') == 'student':
        # For students, show their interviews
        interviews_cursor = db['interviews'].find({
            'student_id': str(g.user['_id'])
        }).sort('interview_date', 1)
        
        interviews = []
        for interview in interviews_cursor:
            # Get job details
            try:
                job = db['jobs'].find_one({'_id': ObjectId(interview['job_id'])})
                if job:
                    interview['job'] = job
                    
                    # Get company details
                    company = db['users'].find_one({'_id': ObjectId(job['company_id'])})
                    interview['company_name'] = company.get('company_name', 'Unknown Company')
                    
                    interviews.append(interview)
            except:
                # Skip invalid interviews
                continue
        
        return render_template('interviews/student_index.html', interviews=interviews)
    
    elif g.user.get('role') == 'recruiter':
        # For recruiters, show interviews for their jobs
        interviews_cursor = db['interviews'].find({
            'company_id': str(g.user['_id'])
        }).sort('interview_date', 1)
        
        interviews = []
        for interview in interviews_cursor:
            # Get job details
            try:
                job = db['jobs'].find_one({'_id': ObjectId(interview['job_id'])})
                if job:
                    interview['job'] = job
                    
                    # Get student details
                    student = db['users'].find_one({'_id': ObjectId(interview['student_id'])})
                    if student:
                        interview['student'] = {
                            'username': student.get('username'),
                            'email': student.get('email'),
                            'phone': student.get('phone'),
                            'cgpa': student.get('cgpa'),
                            'branch': student.get('branch'),
                            'year': student.get('year')
                        }
                    
                    interviews.append(interview)
            except:
                # Skip invalid interviews
                continue
        
        return render_template('interviews/recruiter_index.html', interviews=interviews)
    
    else:
        # For admin, show all interviews
        flash('Admin view for interviews not implemented yet')
        return redirect(url_for('index'))

@bp.route('/schedule/<application_id>', methods=('GET', 'POST'))
@recruiter_required
def schedule(application_id):
    """Schedule an interview for a job application"""
    db = get_db()
    
    try:
        application = db['applications'].find_one({'_id': ObjectId(application_id)})
    except:
        flash('Invalid application ID')
        return redirect(url_for('jobs.my_listings'))
    
    if not application:
        flash('Application not found')
        return redirect(url_for('jobs.my_listings'))
    
    # Check if the recruiter owns this application
    if application['company_id'] != str(g.user['_id']) and not g.user.get('is_admin'):
        flash('You do not have permission to schedule an interview for this application')
        return redirect(url_for('jobs.my_listings'))
    
    # Get job details
    try:
        job = db['jobs'].find_one({'_id': ObjectId(application['job_id'])})
    except:
        flash('Invalid job ID')
        return redirect(url_for('jobs.my_listings'))
    
    if not job:
        flash('Job not found')
        return redirect(url_for('jobs.my_listings'))
    
    # Get student details
    try:
        student = db['users'].find_one({'_id': ObjectId(application['student_id'])})
    except:
        flash('Invalid student ID')
        return redirect(url_for('jobs.job_applications', job_id=application['job_id']))
    
    if not student:
        flash('Student not found')
        return redirect(url_for('jobs.job_applications', job_id=application['job_id']))
    
    # Check if interview already exists
    existing_interview = db['interviews'].find_one({
        'job_id': application['job_id'],
        'student_id': application['student_id']
    })
    
    if request.method == 'POST':
        interview_date = request.form.get('interview_date', '')
        interview_time = request.form.get('interview_time', '')
        location = request.form.get('location', '')
        interview_type = request.form.get('interview_type', 'in-person')
        meeting_link = request.form.get('meeting_link', '') if interview_type == 'online' else ''
        notes = request.form.get('notes', '')
        
        error = None
        
        # Validate inputs
        if not interview_date:
            error = 'Interview date is required.'
        elif not interview_time:
            error = 'Interview time is required.'
        elif not location and interview_type == 'in-person':
            error = 'Location is required for in-person interviews.'
        elif not meeting_link and interview_type == 'online':
            error = 'Meeting link is required for online interviews.'
        
        # Parse date and time
        try:
            interview_datetime = datetime.datetime.strptime(
                f"{interview_date} {interview_time}", 
                '%Y-%m-%d %H:%M'
            )
            
            # Check if date is in the past
            if interview_datetime < datetime.datetime.now():
                error = 'Interview date and time cannot be in the past.'
        except ValueError:
            error = 'Invalid date or time format.'
        
        if error is None:
            # Create or update interview
            interview_data = {
                'job_id': application['job_id'],
                'student_id': application['student_id'],
                'company_id': application['company_id'],
                'application_id': str(application['_id']),
                'interview_date': interview_datetime,
                'location': location,
                'interview_type': interview_type,
                'meeting_link': meeting_link,
                'notes': notes,
                'status': 'scheduled',
                'result': None,
                'feedback': None,
                'created_at': datetime.datetime.now(),
                'updated_at': datetime.datetime.now()
            }
            
            if existing_interview:
                # Update existing interview
                db['interviews'].update_one(
                    {'_id': existing_interview['_id']},
                    {'$set': {
                        'interview_date': interview_datetime,
                        'location': location,
                        'interview_type': interview_type,
                        'meeting_link': meeting_link,
                        'notes': notes,
                        'status': 'rescheduled' if existing_interview.get('status') == 'scheduled' else 'scheduled',
                        'updated_at': datetime.datetime.now()
                    }}
                )
                
                message = 'Interview rescheduled successfully!'
            else:
                # Create new interview
                db['interviews'].insert_one(interview_data)
                
                # Update application status to 'interviewing'
                db['applications'].update_one(
                    {'_id': ObjectId(application_id)},
                    {'$set': {
                        'status': 'shortlisted',
                        'updated_at': datetime.datetime.now()
                    }}
                )
                
                message = 'Interview scheduled successfully!'
            
            # Notify student
            try:
                if student.get('phone') and student.get('notification_preferences', {}).get('sms', True):
                    interview_date_str = interview_datetime.strftime('%d %b %Y at %I:%M %p')
                    location_info = f"at {location}" if interview_type == 'in-person' else "online"
                    
                    notification = f"Interview {existing_interview and 'rescheduled' or 'scheduled'} for {job['title']} {location_info} on {interview_date_str}. {notes}"
                    send_sms(student['phone'], notification)
            except Exception as e:
                # Log error but continue
                print(f"Failed to send interview notification: {str(e)}")
            
            flash(message)
            return redirect(url_for('jobs.job_applications', job_id=application['job_id']))
        
        flash(error)
    
    # Format student info for the template
    student_info = {
        'username': student.get('username'),
        'email': student.get('email'),
        'phone': student.get('phone'),
        'cgpa': student.get('cgpa'),
        'branch': student.get('branch'),
        'year': student.get('year')
    }
    
    # Format job info for the template
    job_info = {
        'title': job.get('title'),
        'role': job.get('role'),
        'company_name': g.user.get('company_name')
    }
    
    # Format existing interview data for the form if it exists
    interview_data = {}
    if existing_interview:
        interview_data = {
            'interview_date': existing_interview.get('interview_date').strftime('%Y-%m-%d'),
            'interview_time': existing_interview.get('interview_date').strftime('%H:%M'),
            'location': existing_interview.get('location', ''),
            'interview_type': existing_interview.get('interview_type', 'in-person'),
            'meeting_link': existing_interview.get('meeting_link', ''),
            'notes': existing_interview.get('notes', '')
        }
    
    return render_template('interviews/schedule.html', 
                          application=application,
                          student=student_info,
                          job=job_info,
                          interview=interview_data,
                          is_rescheduling=existing_interview is not None)

@bp.route('/<interview_id>/update-result', methods=['POST'])
@recruiter_required
def update_result(interview_id):
    """Update the result of an interview"""
    db = get_db()
    
    try:
        interview = db['interviews'].find_one({'_id': ObjectId(interview_id)})
    except:
        flash('Invalid interview ID')
        return redirect(url_for('interviews.index'))
    
    if not interview:
        flash('Interview not found')
        return redirect(url_for('interviews.index'))
    
    # Check if the recruiter owns this interview
    if interview['company_id'] != str(g.user['_id']) and not g.user.get('is_admin'):
        flash('You do not have permission to update this interview')
        return redirect(url_for('interviews.index'))
    
    # Update result
    result = request.form.get('result')
    if result not in ['passed', 'failed', 'pending_next_round']:
        flash('Invalid result')
        return redirect(url_for('interviews.index'))
    
    feedback = request.form.get('feedback', '')
    
    db['interviews'].update_one(
        {'_id': ObjectId(interview_id)},
        {'$set': {
            'result': result,
            'feedback': feedback,
            'status': 'completed',
            'updated_at': datetime.datetime.now()
        }}
    )
    
    # Update application status based on result
    if result == 'passed':
        db['applications'].update_one(
            {'_id': ObjectId(interview['application_id'])},
            {'$set': {
                'status': 'hired',
                'updated_at': datetime.datetime.now()
            }}
        )
    elif result == 'failed':
        db['applications'].update_one(
            {'_id': ObjectId(interview['application_id'])},
            {'$set': {
                'status': 'rejected',
                'updated_at': datetime.datetime.now()
            }}
        )
    
    # Notify student
    try:
        student = db['users'].find_one({'_id': ObjectId(interview['student_id'])})
        job = db['jobs'].find_one({'_id': ObjectId(interview['job_id'])})
        
        if student and student.get('phone') and student.get('notification_preferences', {}).get('sms', True):
            result_messages = {
                'passed': 'Congratulations! You have passed the interview',
                'failed': 'We regret to inform you that you did not pass the interview',
                'pending_next_round': 'You have been selected for the next round of interviews'
            }
            
            notification = f"Interview result for {job['title']}: {result_messages.get(result)}. Check the placement portal for details."
            send_sms(student['phone'], notification)
    except Exception as e:
        # Log error but continue
        print(f"Failed to send interview result notification: {str(e)}")
    
    flash(f'Interview result updated to {result}')
    return redirect(url_for('interviews.index'))

@bp.route('/<interview_id>/cancel', methods=['POST'])
@recruiter_required
def cancel_interview(interview_id):
    """Cancel a scheduled interview"""
    db = get_db()
    
    try:
        interview = db['interviews'].find_one({'_id': ObjectId(interview_id)})
    except:
        flash('Invalid interview ID')
        return redirect(url_for('interviews.index'))
    
    if not interview:
        flash('Interview not found')
        return redirect(url_for('interviews.index'))
    
    # Check if the recruiter owns this interview
    if interview['company_id'] != str(g.user['_id']) and not g.user.get('is_admin'):
        flash('You do not have permission to cancel this interview')
        return redirect(url_for('interviews.index'))
    
    # Cancel interview
    db['interviews'].update_one(
        {'_id': ObjectId(interview_id)},
        {'$set': {
            'status': 'cancelled',
            'updated_at': datetime.datetime.now()
        }}
    )
    
    # Notify student
    try:
        student = db['users'].find_one({'_id': ObjectId(interview['student_id'])})
        job = db['jobs'].find_one({'_id': ObjectId(interview['job_id'])})
        
        if student and student.get('phone') and student.get('notification_preferences', {}).get('sms', True):
            interview_date_str = interview.get('interview_date').strftime('%d %b %Y at %I:%M %p')
            notification = f"Your interview for {job['title']} scheduled on {interview_date_str} has been cancelled. Check the placement portal for details."
            send_sms(student['phone'], notification)
    except Exception as e:
        # Log error but continue
        print(f"Failed to send interview cancellation notification: {str(e)}")
    
    flash('Interview cancelled successfully')
    return redirect(url_for('interviews.index'))

@bp.route('/my-interviews')
@student_required
def my_interviews():
    """View all interviews for the current student"""
    db = get_db()
    
    # Get upcoming interviews
    upcoming_interviews = db['interviews'].find({
        'student_id': str(g.user['_id']),
        'interview_date': {'$gte': datetime.datetime.now()},
        'status': {'$in': ['scheduled', 'rescheduled']}
    }).sort('interview_date', 1)
    
    # Get past interviews
    past_interviews = db['interviews'].find({
        'student_id': str(g.user['_id']),
        '$or': [
            {'interview_date': {'$lt': datetime.datetime.now()}},
            {'status': {'$in': ['completed', 'cancelled']}}
        ]
    }).sort('interview_date', -1)
    
    # Process interviews to add job and company info
    def process_interviews(interviews_cursor):
        result = []
        for interview in interviews_cursor:
            try:
                job = db['jobs'].find_one({'_id': ObjectId(interview['job_id'])})
                if job:
                    interview['job'] = job
                    
                    company = db['users'].find_one({'_id': ObjectId(job['company_id'])})
                    interview['company_name'] = company.get('company_name', 'Unknown Company')
                    
                    result.append(interview)
            except:
                continue
        return result
    
    upcoming = process_interviews(upcoming_interviews)
    past = process_interviews(past_interviews)
    
    return render_template('interviews/my_interviews.html', 
                          upcoming_interviews=upcoming, 
                          past_interviews=past)

@bp.route('/job/<job_id>')
@recruiter_required
def job_interviews(job_id):
    """View all interviews for a specific job"""
    db = get_db()
    
    try:
        job = db['jobs'].find_one({'_id': ObjectId(job_id)})
    except:
        flash('Invalid job ID')
        return redirect(url_for('jobs.my_listings'))
    
    if not job:
        flash('Job not found')
        return redirect(url_for('jobs.my_listings'))
    
    # Check if the recruiter owns this job
    if job['company_id'] != str(g.user['_id']) and not g.user.get('is_admin'):
        flash('You do not have permission to view interviews for this job')
        return redirect(url_for('jobs.my_listings'))
    
    # Get interviews
    interviews_cursor = db['interviews'].find({
        'job_id': job_id
    }).sort('interview_date', 1)
    
    interviews = []
    for interview in interviews_cursor:
        # Get student details
        student = db['users'].find_one({'_id': ObjectId(interview['student_id'])})
        if student:
            interview['student'] = {
                'username': student.get('username'),
                'email': student.get('email'),
                'phone': student.get('phone'),
                'cgpa': student.get('cgpa'),
                'branch': student.get('branch'),
                'year': student.get('year')
            }
            
            interviews.append(interview)
    
    return render_template('interviews/job_interviews.html', job=job, interviews=interviews)
