from . import queue_status, appointments
from datetime import datetime, timedelta
from bson import ObjectId

class QueueManager:
    @staticmethod
    def update_department_status(department):
        """Update the queue status for a department."""
        # Get today's appointments for this department
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Find all checked-in appointments
        checked_in = appointments.find({
            'department': department,
            'date': today,
            'status': 'checked-in'
        }).count()
        
        # Find all in-progress appointments
        in_progress = appointments.find({
            'department': department,
            'date': today,
            'status': 'in-progress'
        }).count()
        
        # Calculate average wait time based on completed appointments today
        completed = list(appointments.find({
            'department': department,
            'date': today,
            'status': 'completed',
            'check_in_time': {'$exists': True},
            'actual_start_time': {'$exists': True}
        }))
        
        avg_wait_time = 0
        if completed:
            wait_times = [(app['actual_start_time'] - app['check_in_time']).total_seconds() / 60 for app in completed]
            avg_wait_time = sum(wait_times) / len(wait_times)
        
        # Calculate estimated wait time (simple approximation)
        estimated_wait = avg_wait_time * checked_in
        
        # Update queue status
        queue_status.update_one(
            {'department': department},
            {
                '$set': {
                    'checked_in_count': checked_in,
                    'in_progress_count': in_progress,
                    'avg_wait_time': avg_wait_time,
                    'estimated_wait': estimated_wait,
                    'last_updated': datetime.utcnow()
                }
            },
            upsert=True
        )
        
        return {
            'department': department,
            'checked_in_count': checked_in,
            'in_progress_count': in_progress,
            'avg_wait_time': avg_wait_time,
            'estimated_wait': estimated_wait
        }
    
    @staticmethod
    def get_department_status(department=None):
        """Get the current queue status for a department or all departments."""
        if department:
            return queue_status.find_one({'department': department})
        else:
            return list(queue_status.find())
    
    @staticmethod
    def check_in_patient(appointment_id):
        """Check in a patient for their appointment."""
        # Update appointment status
        appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {
                '$set': {
                    'status': 'checked-in',
                    'check_in_time': datetime.utcnow()
                }
            }
        )
        
        # Get appointment details
        appointment = appointments.find_one({'_id': ObjectId(appointment_id)})
        
        # Update queue status for this department
        QueueManager.update_department_status(appointment['department'])
        
        # Calculate and return estimated wait time
        queue = queue_status.find_one({'department': appointment['department']})
        if queue:
            return queue['estimated_wait']
        return 0
