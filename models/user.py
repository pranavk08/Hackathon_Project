from . import users
import bcrypt
from datetime import datetime

class User:
    @staticmethod
    def create_user(email, password, name, role='patient', phone=None, specialization=None):
        """Create a new user."""
        salt = bcrypt.gensalt()
        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt)
        
        user = {
            'email': email,
            'password': hashed_pw,
            'name': name,
            'role': role,  # 'patient', 'doctor', 'admin'
            'phone': phone,
            'created_at': datetime.utcnow(),
            'active': True
        }
        
        if role == 'doctor' and specialization:
            user['specialization'] = specialization
            
        result = users.insert_one(user)
        return result.inserted_id
    
    @staticmethod
    def get_by_email(email):
        """Get user by email."""
        return users.find_one({'email': email})
    
    @staticmethod
    def verify_password(user, password):
        """Verify password."""
        if not user or 'password' not in user:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), user['password'])
        
    @staticmethod
    def get_doctors(specialization=None):
        """Get doctors, optionally filtered by specialization."""
        query = {'role': 'doctor', 'active': True}
        if specialization:
            query['specialization'] = specialization
        return list(users.find(query, {'password': 0}))
