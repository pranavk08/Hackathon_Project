from pymongo import MongoClient
from config import Config

# Connect to MongoDB
client = MongoClient(Config.MONGO_URI)
db = client.get_database()

# Define collections
users = db.users
appointments = db.appointments
queue_status = db.queue_status
departments = db.departments
