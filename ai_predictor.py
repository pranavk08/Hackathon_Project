from prophet import Prophet
import pandas as pd
from datetime import datetime, timedelta
from sklearn.preprocessing import MinMaxScaler
import numpy as np

class AppointmentPredictor:
    def __init__(self, db):
        self.db = db
        self.model = None
        self.scaler = MinMaxScaler()
        
    def prepare_data(self, days_history=30):
        # Get historical appointment data
        start_date = (datetime.now() - timedelta(days=days_history)).strftime('%Y-%m-%d')
        
        pipeline = [
            {
                '$match': {
                    'date': {'$gte': start_date},
                    'status': {'$in': ['completed', 'scheduled', 'checked-in']}
                }
            },
            {
                '$group': {
                    '_id': {
                        'date': '$date',
                        'hour': {'$substr': ['$time_slot', 0, 2]}
                    },
                    'count': {'$sum': 1}
                }
            }
        ]
        
        appointments = list(self.db.appointments.aggregate(pipeline))
        
        # Convert to DataFrame format required by Prophet
        df = pd.DataFrame([
            {
                'ds': datetime.strptime(f"{a['_id']['date']} {a['_id']['hour']}:00", '%Y-%m-%d %H:%M'),
                'y': a['count']
            }
            for a in appointments
        ])
        
        return df
    
    def train_model(self):
        df = self.prepare_data()
        if len(df) < 10:  # Need minimum data points
            return False
            
        self.model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
            interval_width=0.95
        )
        self.model.fit(df)
        return True
        
    def predict_peak_hours(self, days_ahead=7):
        if not self.model:
            if not self.train_model():
                return None
                
        # Create future dates dataframe
        future_dates = self.model.make_future_dataframe(
            periods=days_ahead * 24,
            freq='H'
        )
        
        # Make predictions
        forecast = self.model.predict(future_dates)
        
        # Process predictions
        predictions = []
        for _, row in forecast.tail(days_ahead * 24).iterrows():
            hour = row['ds'].strftime('%H:00')
            predictions.append({
                'date': row['ds'].strftime('%Y-%m-%d'),
                'hour': hour,
                'predicted_load': float(row['yhat']),
                'lower_bound': float(row['yhat_lower']),
                'upper_bound': float(row['yhat_upper'])
            })
        
        return predictions
    
    def suggest_appointment_slots(self, date, existing_appointments):
        predictions = self.predict_peak_hours()
        if not predictions:
            return None
            
        # Get predictions for requested date
        date_predictions = [p for p in predictions if p['date'] == date]
        
        # Calculate optimal slots based on predicted load
        slots = []
        for pred in date_predictions:
            hour = int(pred['hour'].split(':')[0])
            if 9 <= hour < 17:  # Within business hours
                load_score = (pred['predicted_load'] - pred['lower_bound']) / (pred['upper_bound'] - pred['lower_bound'])
                
                # Convert load score to recommendation
                if load_score < 0.3:
                    recommendation = 'Highly Recommended'
                elif load_score < 0.6:
                    recommendation = 'Recommended'
                else:
                    recommendation = 'Busy Hour'
                
                slots.append({
                    'hour': f"{hour:02d}:00",
                    'load_score': load_score,
                    'recommendation': recommendation
                })
        
        return sorted(slots, key=lambda x: x['load_score'])