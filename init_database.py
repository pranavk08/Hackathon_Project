from pymongo import MongoClient
import json
from datetime import datetime

# MongoDB connection
client = MongoClient('mongodb://localhost:27017/')
db = client['healthcare_queue']

# Sample hospital data
hospital_data = {
    "hospitals": [
        {
            "hospital_id": 1,
            "hospital_name": "City General Hospital",
            "location": "123 Main St, Cityville",
            "departments": [
                {
                    "department_id": 101,
                    "department_name": "Cardiology",
                    "doctors": [
                        {
                            "doctor_id": 1001,
                            "doctor_name": "Dr. John Smith",
                            "available_slots": [
                                {
                                    "slot_id": 1,
                                    "date": "2023-10-15",
                                    "time": "09:00 AM"
                                },
                                {
                                    "slot_id": 2,
                                    "date": "2023-10-15",
                                    "time": "10:00 AM"
                                }
                            ]
                        },
                        {
                            "doctor_id": 1002,
                            "doctor_name": "Dr. Emily White",
                            "available_slots": [
                                {
                                    "slot_id": 3,
                                    "date": "2023-10-16",
                                    "time": "11:00 AM"
                                },
                                {
                                    "slot_id": 4,
                                    "date": "2023-10-16",
                                    "time": "01:00 PM"
                                }
                            ]
                        }
                    ]
                },
                {
                    "department_id": 102,
                    "department_name": "Orthopedics",
                    "doctors": [
                        {
                            "doctor_id": 1003,
                            "doctor_name": "Dr. Alice Johnson",
                            "available_slots": [
                                {
                                    "slot_id": 5,
                                    "date": "2023-10-17",
                                    "time": "08:00 AM"
                                },
                                {
                                    "slot_id": 6,
                                    "date": "2023-10-17",
                                    "time": "12:00 PM"
                                }
                            ]
                        },
                        {
                            "doctor_id": 1004,
                            "doctor_name": "Dr. Michael Brown",
                            "available_slots": [
                                {
                                    "slot_id": 7,
                                    "date": "2023-10-18",
                                    "time": "10:00 AM"
                                },
                                {
                                    "slot_id": 8,
                                    "date": "2023-10-18",
                                    "time": "02:00 PM"
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        {
            "hospital_id": 2,
            "hospital_name": "Green Valley Hospital",
            "location": "456 Elm St, Greenvalley",
            "departments": [
                {
                    "department_id": 103,
                    "department_name": "Pediatrics",
                    "doctors": [
                        {
                            "doctor_id": 1005,
                            "doctor_name": "Dr. Sarah Lee",
                            "available_slots": [
                                {
                                    "slot_id": 9,
                                    "date": "2023-10-19",
                                    "time": "09:00 AM"
                                },
                                {
                                    "slot_id": 10,
                                    "date": "2023-10-19",
                                    "time": "11:00 AM"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    ]
}

def init_database():
    try:
        # Drop existing collections to start fresh
        db.Hospitals.drop()
        
        # Insert hospital data
        db.Hospitals.insert_one(hospital_data)
        print("Successfully initialized the database with hospital data!")
        
        # Verify the data
        hospitals = list(db.Hospitals.find())
        print(f"Number of hospital documents: {len(hospitals)}")
        
    except Exception as e:
        print(f"Error initializing database: {str(e)}")

if __name__ == "__main__":
    init_database()
