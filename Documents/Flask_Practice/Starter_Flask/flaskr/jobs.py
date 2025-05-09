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

bp = Blueprint('jobs', __name__, url_prefix='/jobs')

@bp.route('/')
@login_required
def index():
    """Show all jobs with filtering options"""
    db = get_db()
    
    # Get filter parameters
    min_salary = request.args.get('min_salary', type=float)
    max_salary = request.args.get('max_salary', type=float)
    role = request.args.get('role', '')
    company = request.args.get('company', '')
    location = request.args.get('location', '')
    
    # Build query
    query = {'status': 'active'}
    
    if min_salary:
        query['salary'] = query.get('salary', {})
        query['salary']['$gte'] = min_salary
    
    if max_salary:
        query['salary'] = query.get('salary', {})
        query['salary']['$lte'] = max_salary
    
    if role:
        query['role'] = {'$regex': role, '$options': 'i'}
    
    if company:
        # Find company IDs matching the name
        company_ids = [doc['_id'] for doc in db['users'].find(
            {'company_name': {'$regex': company, '$options': 'i'}, 'role': 'recruiter'},
            {'_id': 1}
        )]
        if company_ids:
            query['company_id'] = {'$in': company_ids}
        else:
            # No matching companies, return empty result
            return render_template('jobs/index.html', jobs=[], companies=[])
    
    if location:
        query['location'] = {'$regex': location, '$options': 'i'}
    
    # Check if student is eligible based on CGPA and branch
    if g.user and g.user.get('role') == 'student':
        student_cgpa = g.user.get('cgpa', 0)
        student_branch = g.user.get('branch', '')
        
        # Add eligibility indicators to jobs
        jobs_cursor = db['jobs'].find(query).sort('created_at', -1)
        jobs = []
        
        for job in jobs_cursor:
            # Check eligibility
            is_eligible = True
            eligibility_message = ""
            
            if job.get('min_cgpa') and student_cgpa < job.get('min_cgpa'):
                is_eligible = False
                eligibility_message = f"Required CGPA: {job.get('min_cgpa')}, Your CGPA: {student_cgpa}"
            
            if job.get('eligible_branches') and student_branch not in job.get('eligible_branches'):
                is_eligible = False
                if eligibility_message:
                    eligibility_message += " | "
                eligibility_message += f"Required branches: {', '.join(job.get('eligible_branches'))}"
            
            # Add company information
            company_info = db['users'].find_one(
                {'_id': ObjectId(job['company_id'])},
                {'company_name': 1, 'company_website': 1}
            )
            
            job['company_name'] = company_info.get('company_name', 'Unknown Company')
            job['company_website'] = company_info.get('company_website', '#')
            job['is_eligible'] = is_eligible
            job['eligibility_message'] = eligibility_message
            
            # Check if student has already applied
            job['has_applied'] = False
            if g.user:
                application = db['applications'].find_one({
                    'job_id': str(job['_id']),
                    'student_id': str(g.user['_id'])
                })
                if application:
                    job['has_applied'] = True
                    job['application_status'] = application.get('status', 'pending')
            
            jobs.append(job)
    else:
        # For recruiters or admin, just show all jobs
        jobs_cursor = db['jobs'].find(query).sort('created_at', -1)
        jobs = []
        
        for job in jobs_cursor:
            # Add company information
            company_info = db['users'].find_one(
                {'_id': ObjectId(job['company_id'])},
                {'company_name': 1, 'company_website': 1}
            )
            
            job['company_name'] = company_info.get('company_name', 'Unknown Company')
            job['company_website'] = company_info.get('company_website', '#')
            jobs.append(job)
    
    # Get all companies for filter dropdown
    companies = db['users'].find(
        {'role': 'recruiter', 'verification_status': 'approved'},
        {'company_name': 1}
    ).sort('company_name', 1)
    
    return render_template('jobs/index.html', jobs=jobs, companies=companies)

@bp.route('/create', methods=('GET', 'POST'))
@verified_recruiter_required
def create():
    """Create a new job listing"""
    if request.method == 'POST':
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        role = request.form.get('role', '')
        location = request.form.get('location', '')
        salary = request.form.get('salary', '')
        min_cgpa = request.form.get('min_cgpa', '')
        eligible_branches = request.form.getlist('eligible_branches')
        application_deadline = request.form.get('application_deadline', '')
        
        error = None
        
        # Validate inputs
        if not title:
            error = 'Job title is required.'
        elif not description:
            error = 'Job description is required.'
        elif not role:
            error = 'Job role is required.'
        elif not location:
            error = 'Job location is required.'
        
        # Convert salary to float if provided
        try:
            salary = float(salary) if salary else None
        except ValueError:
            error = 'Salary must be a valid number.'
        
        # Convert min_cgpa to float if provided
        try:
            min_cgpa = float(min_cgpa) if min_cgpa else None
        except ValueError:
            error = 'Minimum CGPA must be a valid number.'
        
        # Parse deadline date
        try:
            if application_deadline:
                application_deadline = datetime.datetime.strptime(application_deadline, '%Y-%m-%d')
            else:
                # Default to 30 days from now
                application_deadline = datetime.datetime.now() + datetime.timedelta(days=30)
        except ValueError:
            error = 'Invalid application deadline date format. Use YYYY-MM-DD.'
        
        if error is None:
            db = get_db()
            
            # Create job listing
            job = {
                'title': title,
                'description': description,
                'role': role,
                'location': location,
                'salary': salary,
                'min_cgpa': min_cgpa,
                'eligible_branches': eligible_branches,
                'application_deadline': application_deadline,
                'company_id': str(g.user['_id']),
                'status': 'active',
                'created_at': datetime.datetime.now(),
                'updated_at': datetime.datetime.now()
            }
            
            result = db['jobs'].insert_one(job)
            
            # Notify eligible students about the new job posting
            if min_cgpa is not None and eligible_branches:
                # Find eligible students
                eligible_students = db['users'].find({
                    'role': 'student',
                    'cgpa': {'$gte': min_cgpa},
                    'branch': {'$in': eligible_branches},
                    'notification_preferences.sms': True
                })
                
                # Send notifications
                for student in eligible_students:
                    if student.get('phone'):
                        job_notification = f"New job alert! {title} at {g.user.get('company_name')} is available. Check the placement portal for details."
                        try:
                            send_sms(student['phone'], job_notification)
                        except Exception as e:
                            # Log error but continue
                            print(f"Failed to send job notification to {student.get('email')}: {str(e)}")
            
            flash('Job listing created successfully!')
            return redirect(url_for('jobs.view', job_id=result.inserted_id))
        
        flash(error)
    
    # Get all branches for the form
    branches = [
        'Computer Science', 'Information Technology', 'Electronics', 
        'Electrical', 'Mechanical', 'Civil', 'Chemical', 'Biotechnology'
    ]
    
    return render_template('jobs/create.html', branches=branches)

@bp.route('/<job_id>')
@login_required
def view(job_id):
    """View a specific job listing"""
    db = get_db()
    
    try:
        job = db['jobs'].find_one({'_id': ObjectId(job_id)})
    except:
        flash('Invalid job ID')
        return redirect(url_for('jobs.index'))
    
    if not job:
        flash('Job not found')
        return redirect(url_for('jobs.index'))
    
    # Get company information
    company = db['users'].find_one({'_id': ObjectId(job['company_id'])})
    job['company_name'] = company.get('company_name', 'Unknown Company')
    job['company_website'] = company.get('company_website', '#')
    
    # Check eligibility for students
    is_eligible = True
    eligibility_message = ""
    has_applied = False
    application_status = None
    
    if g.user and g.user.get('role') == 'student':
        student_cgpa = g.user.get('cgpa', 0)
        student_branch = g.user.get('branch', '')
        
        if job.get('min_cgpa') and student_cgpa < job.get('min_cgpa'):
            is_eligible = False
            eligibility_message = f"Required CGPA: {job.get('min_cgpa')}, Your CGPA: {student_cgpa}"
        
        if job.get('eligible_branches') and student_branch not in job.get('eligible_branches'):
            is_eligible = False
            if eligibility_message:
                eligibility_message += " | "
            eligibility_message += f"Required branches: {', '.join(job.get('eligible_branches'))}"
        
        # Check if student has already applied
        application = db['applications'].find_one({
            'job_id': job_id,
            'student_id': str(g.user['_id'])
        })
        
        if application:
            has_applied = True
            application_status = application.get('status', 'pending')
    
    # Get application statistics for recruiters
    application_stats = None
    if g.user and (g.user.get('role') == 'recruiter' or g.user.get('is_admin')):
        if g.user.get('role') == 'recruiter' and job['company_id'] != str(g.user['_id']):
            # Recruiters can only see stats for their own jobs
            pass
        else:
            # Count applications by status
            pipeline = [
                {'$match': {'job_id': job_id}},
                {'$group': {
                    '_id': '$status',
                    'count': {'$sum': 1}
                }}
            ]
            
            application_counts = list(db['applications'].aggregate(pipeline))
            
            application_stats = {
                'total': sum(item['count'] for item in application_counts),
                'pending': next((item['count'] for item in application_counts if item['_id'] == 'pending'), 0),
                'shortlisted': next((item['count'] for item in application_counts if item['_id'] == 'shortlisted'), 0),
                'rejected': next((item['count'] for item in application_counts if item['_id'] == 'rejected'), 0),
                'hired': next((item['count'] for item in application_counts if item['_id'] == 'hired'), 0)
            }
    
    return render_template('jobs/view.html', 
                          job=job, 
                          is_eligible=is_eligible, 
                          eligibility_message=eligibility_message,
                          has_applied=has_applied,
                          application_status=application_status,
                          application_stats=application_stats)

@bp.route('/<job_id>/edit', methods=('GET', 'POST'))
@verified_recruiter_required
def edit(job_id):
    """Edit a job listing"""
    db = get_db()
    
    try:
        job = db['jobs'].find_one({'_id': ObjectId(job_id)})
    except:
        flash('Invalid job ID')
        return redirect(url_for('jobs.index'))
    
    if not job:
        flash('Job not found')
        return redirect(url_for('jobs.index'))
    
    # Check if the recruiter owns this job
    if job['company_id'] != str(g.user['_id']) and not g.user.get('is_admin'):
        flash('You do not have permission to edit this job')
        return redirect(url_for('jobs.view', job_id=job_id))
    
    if request.method == 'POST':
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        role = request.form.get('role', '')
        location = request.form.get('location', '')
        salary = request.form.get('salary', '')
        min_cgpa = request.form.get('min_cgpa', '')
        eligible_branches = request.form.getlist('eligible_branches')
        application_deadline = request.form.get('application_deadline', '')
        status = request.form.get('status', 'active')
        
        error = None
        
        # Validate inputs
        if not title:
            error = 'Job title is required.'
        elif not description:
            error = 'Job description is required.'
        elif not role:
            error = 'Job role is required.'
        elif not location:
            error = 'Job location is required.'
        
        # Convert salary to float if provided
        try:
            salary = float(salary) if salary else None
        except ValueError:
            error = 'Salary must be a valid number.'
        
        # Convert min_cgpa to float if provided
        try:
            min_cgpa = float(min_cgpa) if min_cgpa else None
        except ValueError:
            error = 'Minimum CGPA must be a valid number.'
        
        # Parse deadline date
        try:
            if application_deadline:
                application_deadline = datetime.datetime.strptime(application_deadline, '%Y-%m-%d')
            else:
                # Keep existing deadline
                application_deadline = job.get('application_deadline')
        except ValueError:
            error = 'Invalid application deadline date format. Use YYYY-MM-DD.'
        
        if error is None:
            # Update job listing
            db['jobs'].update_one(
                {'_id': ObjectId(job_id)},
                {'$set': {
                    'title': title,
                    'description': description,
                    'role': role,
                    'location': location,
                    'salary': salary,
                    'min_cgpa': min_cgpa,
                    'eligible_branches': eligible_branches,
                    'application_deadline': application_deadline,
                    'status': status,
                    'updated_at': datetime.datetime.now()
                }}
            )
            
            flash('Job listing updated successfully!')
            return redirect(url_for('jobs.view', job_id=job_id))
        
        flash(error)
    
    # Format date for the form
    if job.get('application_deadline'):
        job['application_deadline_str'] = job['application_deadline'].strftime('%Y-%m-%d')
    
    # Get all branches for the form
    branches = [
        'Computer Science', 'Information Technology', 'Electronics', 
        'Electrical', 'Mechanical', 'Civil', 'Chemical', 'Biotechnology'
    ]
    
    return render_template('jobs/edit.html', job=job, branches=branches)

@bp.route('/<job_id>/apply', methods=['POST'])
@student_required
def apply(job_id):
    """Apply for a job"""
    db = get_db()
    
    try:
        job = db['jobs'].find_one({'_id': ObjectId(job_id)})
    except:
        flash('Invalid job ID')
        return redirect(url_for('jobs.index'))
    
    if not job:
        flash('Job not found')
        return redirect(url_for('jobs.index'))
    
    # Check if job is still active
    if job.get('status') != 'active':
        flash('This job is no longer accepting applications')
        return redirect(url_for('jobs.view', job_id=job_id))
    
    # Check if application deadline has passed
    if job.get('application_deadline') and job['application_deadline'] < datetime.datetime.now():
        flash('The application deadline for this job has passed')
        return redirect(url_for('jobs.view', job_id=job_id))
    
    # Check eligibility
    is_eligible = True
    eligibility_message = ""
    
    student_cgpa = g.user.get('cgpa', 0)
    student_branch = g.user.get('branch', '')
    
    if job.get('min_cgpa') and student_cgpa < job.get('min_cgpa'):
        is_eligible = False
        eligibility_message = f"Required CGPA: {job.get('min_cgpa')}, Your CGPA: {student_cgpa}"
    
    if job.get('eligible_branches') and student_branch not in job.get('eligible_branches'):
        is_eligible = False
        if eligibility_message:
            eligibility_message += " | "
        eligibility_message += f"Required branches: {', '.join(job.get('eligible_branches'))}"
    
    if not is_eligible:
        flash(f'You are not eligible for this job. {eligibility_message}')
        return redirect(url_for('jobs.view', job_id=job_id))
    
    # Check if already applied
    existing_application = db['applications'].find_one({
        'job_id': job_id,
        'student_id': str(g.user['_id'])
    })
    
    if existing_application:
        flash('You have already applied for this job')
        return redirect(url_for('jobs.view', job_id=job_id))
    
    # Create application
    cover_letter = request.form.get('cover_letter', '')
    
    application = {
        'job_id': job_id,
        'student_id': str(g.user['_id']),
        'company_id': job['company_id'],
        'cover_letter': cover_letter,
        'status': 'pending',
        'created_at': datetime.datetime.now(),
        'updated_at': datetime.datetime.now()
    }
    
    db['applications'].insert_one(application)
    
    # Notify recruiter
    try:
        recruiter = db['users'].find_one({'_id': ObjectId(job['company_id'])})
        if recruiter and recruiter.get('phone') and recruiter.get('notification_preferences', {}).get('sms', True):
            notification = f"New application received for {job['title']} from {g.user.get('username')}. Check the placement portal for details."
            send_sms(recruiter['phone'], notification)
    except Exception as e:
        # Log error but continue
        print(f"Failed to send application notification: {str(e)}")
    
    flash('Application submitted successfully!')
    return redirect(url_for('jobs.view', job_id=job_id))

@bp.route('/my-applications')
@student_required
def my_applications():
    """View all applications made by the current student"""
    db = get_db()
    
    # Get all applications
    applications_cursor = db['applications'].find({
        'student_id': str(g.user['_id'])
    }).sort('created_at', -1)
    
    applications = []
    for app in applications_cursor:
        # Get job details
        try:
            job = db['jobs'].find_one({'_id': ObjectId(app['job_id'])})
            if job:
                app['job'] = job
                
                # Get company details
                company = db['users'].find_one({'_id': ObjectId(job['company_id'])})
                app['company_name'] = company.get('company_name', 'Unknown Company')
                
                # Get interview details if any
                interview = db['interviews'].find_one({
                    'job_id': app['job_id'],
                    'student_id': app['student_id']
                })
                app['interview'] = interview
                
                applications.append(app)
        except:
            # Skip invalid applications
            continue
    
    return render_template('jobs/my_applications.html', applications=applications)

@bp.route('/my-listings')
@recruiter_required
def my_listings():
    """View all job listings created by the current recruiter"""
    db = get_db()
    
    # Get all jobs
    jobs_cursor = db['jobs'].find({
        'company_id': str(g.user['_id'])
    }).sort('created_at', -1)
    
    jobs = list(jobs_cursor)
    
    # Get application counts for each job
    for job in jobs:
        job['application_count'] = db['applications'].count_documents({
            'job_id': str(job['_id'])
        })
    
    return render_template('jobs/my_listings.html', jobs=jobs)

@bp.route('/<job_id>/applications')
@recruiter_required
def job_applications(job_id):
    """View all applications for a specific job"""
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
        flash('You do not have permission to view applications for this job')
        return redirect(url_for('jobs.my_listings'))
    
    # Get filter parameters
    status = request.args.get('status', '')
    
    # Build query
    query = {'job_id': job_id}
    if status:
        query['status'] = status
    
    # Get applications
    applications_cursor = db['applications'].find(query).sort('created_at', -1)
    
    applications = []
    for app in applications_cursor:
        # Get student details
        student = db['users'].find_one({'_id': ObjectId(app['student_id'])})
        if student:
            app['student'] = {
                'username': student.get('username'),
                'email': student.get('email'),
                'phone': student.get('phone'),
                'cgpa': student.get('cgpa'),
                'branch': student.get('branch'),
                'year': student.get('year'),
                'resume': student.get('resume')
            }
            
            # Get interview details if any
            interview = db['interviews'].find_one({
                'job_id': job_id,
                'student_id': app['student_id']
            })
            app['interview'] = interview
            
            applications.append(app)
    
    return render_template('jobs/applications.html', job=job, applications=applications)

@bp.route('/<job_id>/application/<application_id>/update-status', methods=['POST'])
@recruiter_required
def update_application_status(job_id, application_id):
    """Update the status of a job application"""
    db = get_db()
    
    try:
        job = db['jobs'].find_one({'_id': ObjectId(job_id)})
        application = db['applications'].find_one({'_id': ObjectId(application_id)})
    except:
        flash('Invalid job or application ID')
        return redirect(url_for('jobs.my_listings'))
    
    if not job or not application:
        flash('Job or application not found')
        return redirect(url_for('jobs.my_listings'))
    
    # Check if the recruiter owns this job
    if job['company_id'] != str(g.user['_id']) and not g.user.get('is_admin'):
        flash('You do not have permission to update this application')
        return redirect(url_for('jobs.my_listings'))
    
    # Update status
    new_status = request.form.get('status')
    if new_status not in ['pending', 'shortlisted', 'rejected', 'hired']:
        flash('Invalid status')
        return redirect(url_for('jobs.job_applications', job_id=job_id))
    
    db['applications'].update_one(
        {'_id': ObjectId(application_id)},
        {'$set': {
            'status': new_status,
            'updated_at': datetime.datetime.now()
        }}
    )
    
    # Notify student
    try:
        student = db['users'].find_one({'_id': ObjectId(application['student_id'])})
        if student and student.get('phone') and student.get('notification_preferences', {}).get('sms', True):
            status_messages = {
                'pending': 'Your application is under review',
                'shortlisted': 'Congratulations! You have been shortlisted',
                'rejected': 'We regret to inform you that your application was not selected',
                'hired': 'Congratulations! You have been hired'
            }
            
            notification = f"Application update for {job['title']}: {status_messages.get(new_status)}. Check the placement portal for details."
            send_sms(student['phone'], notification)
    except Exception as e:
        # Log error but continue
        print(f"Failed to send status update notification: {str(e)}")
    
    flash(f'Application status updated to {new_status}')
    return redirect(url_for('jobs.job_applications', job_id=job_id))
