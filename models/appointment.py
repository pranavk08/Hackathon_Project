from . import appointments, users
from datetime import datetime, timedelta
from bson import ObjectId

class Appointment:
    @staticmethod
    def create(patient_id, doctor_id, date, time_slot, reason=None):
        """Create a new appointment."""
        # Convert string IDs to ObjectId if needed
        if isinstance(patient_id, str):
            patient_id = ObjectId(patient_id)
        if isinstance(doctor_id, str):
            doctor_id = ObjectId(doctor_id)
            
        # Get doctor info for department
        doctor = users.find_one({'_id': doctor_id})
        
        appointment = {
            'patient_id': patient_id,
            'doctor_id': doctor_id,
            'department': doctor.get('specialization', 'General'),
            'date': date,  # Store as YYYY-MM-DD
            'time_slot': time_slot,  # Store as HH:MM format
            'reason': reason,
            'status': 'scheduled',  # scheduled, checked-in, completed, cancelled
            'created_at': datetime.utcnow(),
            'priority': 0,  # 0=normal, 1=priority, 2=emergency
            'estimated_wait_time': None,
            'actual_start_time': None,
            'actual_end_time': None
        }
        
        result = appointments.insert_one(appointment)
        return result.inserted_id
    
    @staticmethod
    def get_by_patient(patient_id, status=None):
        """Get appointments for a patient."""
        query = {'patient_id': ObjectId(patient_id)}
        if status:
            query['status'] = status
        
        # Join with doctor information
        pipeline = [
            {'$match': query},
            {'$lookup': {
                'from': 'users',
                'localField': 'doctor_id',
                'foreignField': '_id',
                'as': 'doctor'
            }},
            {'$unwind': '$doctor'},
            {'$project': {
                'doctor_password': 0
            }}
        ]
        
        return list(appointments.aggregate(pipeline))
    
    @staticmethod
    def get_by_doctor(doctor_id, date=None, status=None, future_only=False):
        """Get appointments for a doctor.
        
        Args:
            doctor_id: The ID of the doctor
            date (str, optional): Filter appointments by date (YYYY-MM-DD)
            status (str or list, optional): Filter appointments by status
            future_only (bool, optional): If True, only return appointments with future dates
        
        Returns:
            list: A list of appointments matching the criteria
        """
        query = {'doctor_id': ObjectId(doctor_id)}
        
        # Filter by date if provided
        if date:
            query['date'] = date
        
        # Filter by status if provided
        if status:
            if isinstance(status, list):
                query['status'] = {'$in': status}
            else:
                query['status'] = status
        
        # Filter for future appointments if future_only is True
        if future_only:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            if 'date' in query:
                # If date is already specified, make sure it's in the future
                if query['date'] < today:
                    return []  # No need to query if the date is in the past
            else:
                query['date'] = {'$gte': today}
        
        # Join with patient information
        pipeline = [
            {'$match': query},
            {'$lookup': {
                'from': 'users',
                'localField': 'patient_id',
                'foreignField': '_id',
                'as': 'patient'
            }},
            {'$unwind': '$patient'},
            {'$project': {
                'patient_password': 0
            }}
        ]
        
        return list(appointments.aggregate(pipeline))
    
    @staticmethod
    def update_status(appointment_id, status, additional_data=None):
        """Update appointment status."""
        update_data = {'status': status}
        
        if status == 'checked-in':
            update_data['check_in_time'] = datetime.utcnow()
        elif status == 'in-progress':
            update_data['actual_start_time'] = datetime.utcnow()
        elif status == 'completed':
            update_data['actual_end_time'] = datetime.utcnow()
            
        if additional_data:
            update_data.update(additional_data)
            
        appointments.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': update_data}
        )
    
    @staticmethod
    def get_available_slots(doctor_id, date):
        """Get available time slots for a doctor on a specific date."""
        # Define default working hours (8 AM to 5 PM)
        work_start = 8  # 8 AM
        work_end = 17   # 5 PM
        slot_duration = 30  # 30 minutes
        
        # Generate all possible time slots
        all_slots = []
        current_time = work_start
        while current_time < work_end:
            hour = current_time
            minutes = (current_time - hour) * 60
            slot_time = f"{int(hour):02d}:{int(minutes):02d}"
            all_slots.append(slot_time)
            current_time += slot_duration/60
        
        # Get booked slots
        booked_appointments = appointments.find({
            'doctor_id': ObjectId(doctor_id),
            'date': date,
            'status': {'$nin': ['cancelled']}
        })
        
        booked_slots = [appointment['time_slot'] for appointment in booked_appointments]
        
        # Return available slots
        return [slot for slot in all_slots if slot not in booked_slots]
