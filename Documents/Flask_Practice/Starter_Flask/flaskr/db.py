import click
from flask import current_app, g
from pymongo import MongoClient

def get_db():
    if 'db' not in g:
        mongo_uri = current_app.config.get('MONGO_URI', 'mongodb://localhost:27017/StarterFlask')
        client = MongoClient(mongo_uri)
        g.db = client.get_default_database()
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.client.close()

# No init_db needed for MongoDB. Collections are created automatically when data is inserted.

# No CLI init-db command needed for MongoDB.

def init_app(app):
    app.teardown_appcontext(close_db)

