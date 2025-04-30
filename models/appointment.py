from . import appointments, users
from datetime import datetime, timedelta
from bson import ObjectId
import re

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
        if not doctor:
            raise ValueError("Doctor not found")
            
        # Check if the time slot is already taken for this doctor
        existing_appointment = appointments.find_one({
            'doctor_id': doctor_id,
            'date': date,
            'time_slot': time_slot,
            'status': {'$ne': 'cancelled'}
        })
        
        if existing_appointment:
            raise ValueError("This time slot is already booked for the selected doctor")
        
        # Check if patient already has an appointment at this time
        patient_appointment = appointments.find_one({
            'patient_id': patient_id,
            'date': date,
            'time_slot': time_slot,
            'status': {'$ne': 'cancelled'}
        })
        
        if patient_appointment:
            raise ValueError("You already have an appointment scheduled at this time")
            
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
        
        try:
            result = appointments.insert_one(appointment)
            # Return both the appointment ID and the created appointment data
            return {
                'appointment_id': result.inserted_id,
                'appointment': appointment
            }
        except Exception as e:
            raise ValueError("Failed to create appointment. Please try again.")
    
    @staticmethod
    def get_by_patient(patient_id, status=None):
        """Get appointments for a patient."""
        # Convert string ID to ObjectId if needed
        if isinstance(patient_id, str):
            patient_id = ObjectId(patient_id)
            
        # Build the base query
        query = {'patient_id': patient_id}
        
        # Add status filter if provided
        if status:
            if isinstance(status, list):
                query['status'] = {'$in': status}
            else:
                query['status'] = status
        
        # Join with doctor information and format the output
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
                '_id': 1,
                'patient_id': 1,
                'doctor_id': 1,
                'department': 1,
                'date': 1,
                'time_slot': 1,
                'reason': 1,
                'status': 1,
                'created_at': 1,
                'priority': 1,
                'estimated_wait_time': 1,
                'actual_start_time': 1,
                'actual_end_time': 1,
                'doctor_name': '$doctor.name'
            }},
            {'$sort': {'date': 1, 'time_slot': 1}}
        ]
        
        try:
            appointments_list = list(appointments.aggregate(pipeline))
            
            # Format the dates and times for consistent output
            for appt in appointments_list:
                # Convert ObjectIds to strings
                appt['_id'] = str(appt['_id'])
                appt['patient_id'] = str(appt['patient_id'])
                appt['doctor_id'] = str(appt['doctor_id'])
                
                # Ensure date is in YYYY-MM-DD format
                if isinstance(appt['date'], datetime):
                    appt['date'] = appt['date'].strftime('%Y-%m-%d')
                    
                # Format timestamps if they exist
                if appt.get('created_at'):
                    appt['created_at'] = appt['created_at'].isoformat()
                if appt.get('actual_start_time'):
                    appt['actual_start_time'] = appt['actual_start_time'].isoformat()
                if appt.get('actual_end_time'):
                    appt['actual_end_time'] = appt['actual_end_time'].isoformat()
                    
                # Ensure priority is an integer
                appt['priority'] = int(appt.get('priority', 0))
                
                # Set default values for null fields
                appt['estimated_wait_time'] = appt.get('estimated_wait_time')
                appt['reason'] = appt.get('reason', '')
                
            return appointments_list
            
        except Exception as e:
            print(f"Error fetching appointments: {str(e)}")
            return []
    
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
        # Convert string ID to ObjectId if needed
        if isinstance(doctor_id, str):
            doctor_id = ObjectId(doctor_id)
            
        # Build the base query
        query = {'doctor_id': doctor_id}
        
        # Add date filter if provided
        if date:
            query['date'] = date
        elif future_only:
            today = datetime.now().strftime('%Y-%m-%d')
            query['date'] = {'$gte': today}
            
        # Add status filter if provided
        if status:
            if isinstance(status, list):
                query['status'] = {'$in': status}
            else:
                query['status'] = status
        
        # Join with patient information and format the output
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
                '_id': 1,
                'patient_id': 1,
                'doctor_id': 1,
                'department': 1,
                'date': 1,
                'time_slot': 1,
                'reason': 1,
                'status': 1,
                'created_at': 1,
                'priority': 1,
                'estimated_wait_time': 1,
                'actual_start_time': 1,
                'actual_end_time': 1,
                'patient_name': '$patient.name',
                'patient_phone': '$patient.phone'
            }},
            {'$sort': {'date': 1, 'time_slot': 1}}
        ]
        
        try:
            appointments_list = list(appointments.aggregate(pipeline))
            
            # Format the dates and times for consistent output
            for appt in appointments_list:
                # Convert ObjectIds to strings
                appt['_id'] = str(appt['_id'])
                appt['patient_id'] = str(appt['patient_id'])
                appt['doctor_id'] = str(appt['doctor_id'])
                
                # Ensure date is in YYYY-MM-DD format
                if isinstance(appt['date'], datetime):
                    appt['date'] = appt['date'].strftime('%Y-%m-%d')
                    
                # Format timestamps if they exist
                if appt.get('created_at'):
                    appt['created_at'] = appt['created_at'].isoformat()
                if appt.get('actual_start_time'):
                    appt['actual_start_time'] = appt['actual_start_time'].isoformat()
                if appt.get('actual_end_time'):
                    appt['actual_end_time'] = appt['actual_end_time'].isoformat()
                    
                # Ensure priority is an integer
                appt['priority'] = int(appt.get('priority', 0))
                
                # Set default values for null fields
                appt['estimated_wait_time'] = appt.get('estimated_wait_time')
                appt['reason'] = appt.get('reason', '')
                
            return appointments_list
            
        except Exception as e:
            print(f"Error fetching doctor appointments: {str(e)}")
            return []
    
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
    
    @staticmethod
    def get_by_id(appointment_id):
        """Get appointment by ID."""
        if isinstance(appointment_id, str):
            appointment_id = ObjectId(appointment_id)
            
        # Join with doctor information
        pipeline = [
            {'$match': {'_id': appointment_id}},
            {'$lookup': {
                'from': 'users',
                'localField': 'doctor_id',
                'foreignField': '_id',
                'as': 'doctor'
            }},
            {'$unwind': '$doctor'},
            {'$lookup': {
                'from': 'users',
                'localField': 'patient_id',
                'foreignField': '_id',
                'as': 'patient'
            }},
            {'$unwind': '$patient'},
            {'$project': {
                'doctor_password': 0,
                'patient_password': 0
            }}
        ]
        
        result = list(appointments.aggregate(pipeline))
        return result[0] if result else None
    
    @staticmethod
    def update_appointment(appointment_id, update_data):
        """Update an appointment with new data.
        
        Args:
            appointment_id: The ID of the appointment to update
            update_data: Dictionary containing the fields to update
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            # Convert string ID to ObjectId if needed
            if isinstance(appointment_id, str):
                appointment_id = ObjectId(appointment_id)
                
            # Ensure proper date format
            if 'date' in update_data and isinstance(update_data['date'], str):
                # Validate date format
                datetime.strptime(update_data['date'], '%Y-%m-%d')
                
            # Ensure proper time slot format
            if 'time_slot' in update_data:
                # Validate time slot format (HH:MM-HH:MM)
                if not re.match(r'^\d{2}:\d{2}-\d{2}:\d{2}$', update_data['time_slot']):
                    raise ValueError('Invalid time slot format. Must be HH:MM-HH:MM')
            
            # Update timestamps if present
            for field in ['created_at', 'actual_start_time', 'actual_end_time']:
                if field in update_data and update_data[field]:
                    if isinstance(update_data[field], str):
                        update_data[field] = datetime.fromisoformat(update_data[field].replace('Z', '+00:00'))
            
            # Ensure priority is an integer
            if 'priority' in update_data:
                update_data['priority'] = int(update_data['priority'])
            
            # Verify the appointment exists before updating
            existing = appointments.find_one({'_id': appointment_id})
            if not existing:
                raise ValueError('Appointment not found')
            
            # Perform the update
            result = appointments.update_one(
                {'_id': appointment_id},
                {'$set': update_data}
            )
            
            if result.matched_count == 0:
                raise ValueError('Appointment not found')
                
            return result.modified_count > 0
            
        except Exception as e:
            raise ValueError(f"Error updating appointment: {str(e)}")
    
    @staticmethod
    def is_time_slot_available(doctor_id, date, time_slot, exclude_appointment_id=None):
        """Check if a time slot is available for a doctor on a given date.
        
        Args:
            doctor_id: The ID of the doctor
            date: The date to check (YYYY-MM-DD format)
            time_slot: The time slot to check (HH:MM-HH:MM format)
            exclude_appointment_id: Optional appointment ID to exclude from the check
            
        Returns:
            bool: True if the time slot is available, False otherwise
        """
        try:
            # Convert string ID to ObjectId if needed
            if isinstance(doctor_id, str):
                doctor_id = ObjectId(doctor_id)
            
            # Build the query
            query = {
                'doctor_id': doctor_id,
                'date': date,
                'time_slot': time_slot,
                'status': {'$nin': ['cancelled', 'completed']}
            }
            
            # Exclude the current appointment if provided
            if exclude_appointment_id:
                if isinstance(exclude_appointment_id, str):
                    exclude_appointment_id = ObjectId(exclude_appointment_id)
                query['_id'] = {'$ne': exclude_appointment_id}
            
            # Check if any appointments exist in this time slot
            existing = appointments.find_one(query)
            return existing is None
            
        except Exception as e:
            print(f"Error checking time slot availability: {str(e)}")
            return False
