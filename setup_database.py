from pymongo import MongoClient
import json
from datetime import datetime

def connect_to_mongodb():
    # Connect to MongoDB (make sure MongoDB is running locally)
    client = MongoClient('mongodb://localhost:27017/')
    db = client['hospital_management']
    return db

def create_collections(db):
    # Create collections if they don't exist
    collections = ['hospitals', 'doctors', 'patients', 'appointments']
    for collection in collections:
        if collection not in db.list_collection_names():
            db.create_collection(collection)

def load_sample_data(db):
    # Load sample data from JSON file
    with open('sample_data.json', 'r') as file:
        data = json.load(file)
    
    # Insert data into collections
    for collection_name in ['hospitals', 'doctors', 'patients', 'appointments']:
        if data.get(collection_name):
            db[collection_name].insert_many(data[collection_name])

def main():
    try:
        # Connect to MongoDB
        db = connect_to_mongodb()
        print("Connected to MongoDB successfully!")

        # Create collections
        create_collections(db)
        print("Collections created successfully!")

        # Load sample data
        load_sample_data(db)
        print("Sample data loaded successfully!")

    except Exception as e:
        print(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()
