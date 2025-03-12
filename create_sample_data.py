from pymongo import MongoClient
from datetime import datetime, timedelta
import random

# MongoDB connection
client = MongoClient('mongodb://localhost:27017/')
db = client['hospital_management']  # Changed database name to be more specific

def generate_time_slots(start_date, num_days=7):
    slots = []
    slot_id = 1
    
    for day in range(num_days):
        current_date = start_date + timedelta(days=day)
        # Generate slots from 9 AM to 5 PM
        for hour in [9, 10, 11, 12, 14, 15, 16, 17]:
            slots.append({
                "slot_id": slot_id,
                "date": current_date.strftime("%Y-%m-%d"),
                "time": f"{hour:02d}:00",
                "is_available": True
            })
            slot_id += 1
    return slots

def create_sample_data():
    # Start date from today
    start_date = datetime.now()
    
    hospital_data = {
        "hospitals": [
            {
                "hospital_id": 1,
                "hospital_name": "Apollo Hospitals",
                "location": "Jubilee Hills, Hyderabad",
                "contact": {
                    "phone": "+91-40-12345678",
                    "email": "apollo.jubilee@apollo.com"
                },
                "departments": [
                    {
                        "department_id": 101,
                        "department_name": "Cardiology",
                        "doctors": [
                            {
                                "doctor_id": 1001,
                                "doctor_name": "Dr. Rajesh Kumar",
                                "specialization": "Interventional Cardiology",
                                "experience": "15 years",
                                "qualification": "MD, DM Cardiology",
                                "available_slots": generate_time_slots(start_date)
                            },
                            {
                                "doctor_id": 1002,
                                "doctor_name": "Dr. Priya Sharma",
                                "specialization": "Cardiac Surgery",
                                "experience": "12 years",
                                "qualification": "MS, MCh Cardiac Surgery",
                                "available_slots": generate_time_slots(start_date)
                            }
                        ]
                    },
                    {
                        "department_id": 102,
                        "department_name": "Orthopedics",
                        "doctors": [
                            {
                                "doctor_id": 1003,
                                "doctor_name": "Dr. Suresh Reddy",
                                "specialization": "Joint Replacement",
                                "experience": "10 years",
                                "qualification": "MS Orthopedics",
                                "available_slots": generate_time_slots(start_date)
                            }
                        ]
                    }
                ]
            },
            {
                "hospital_id": 2,
                "hospital_name": "KIMS Hospital",
                "location": "Secunderabad, Telangana",
                "contact": {
                    "phone": "+91-40-87654321",
                    "email": "info@kimshospitals.com"
                },
                "departments": [
                    {
                        "department_id": 201,
                        "department_name": "Pediatrics",
                        "doctors": [
                            {
                                "doctor_id": 2001,
                                "doctor_name": "Dr. Meera Patel",
                                "specialization": "Pediatric Medicine",
                                "experience": "8 years",
                                "qualification": "MD Pediatrics",
                                "available_slots": generate_time_slots(start_date)
                            }
                        ]
                    },
                    {
                        "department_id": 202,
                        "department_name": "Neurology",
                        "doctors": [
                            {
                                "doctor_id": 2002,
                                "doctor_name": "Dr. Arun Singh",
                                "specialization": "Neurosurgery",
                                "experience": "14 years",
                                "qualification": "MCh Neurosurgery",
                                "available_slots": generate_time_slots(start_date)
                            }
                        ]
                    }
                ]
            }
        ]
    }

    try:
        # Drop existing collections
        db.Hospitals.drop()
        
        # Insert new data
        result = db.Hospitals.insert_one(hospital_data)
        
        print("Successfully created sample hospital database!")
        print("Created document with ID:", result.inserted_id)
        
        # Verify the data
        hospital_count = db.Hospitals.count_documents({})
        print(f"Number of hospital documents: {hospital_count}")
        
        # Print some sample data for verification
        hospital = db.Hospitals.find_one({})
        if hospital:
            print("\nSample Hospital Data:")
            print(f"First Hospital: {hospital['hospitals'][0]['hospital_name']}")
            print(f"Number of departments: {len(hospital['hospitals'][0]['departments'])}")
            print(f"First doctor: {hospital['hospitals'][0]['departments'][0]['doctors'][0]['doctor_name']}")
            
    except Exception as e:
        print(f"Error creating database: {str(e)}")

if __name__ == "__main__":
    create_sample_data()
