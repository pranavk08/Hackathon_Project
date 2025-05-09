import os
import datetime
from flask import Flask
from flask_mail import Mail

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        MONGO_URI='mongodb://localhost:27017/StarterFlask',
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    from flask import g, render_template
    @app.route('/')
    def index():
        username = g.user['username'] if getattr(g, 'user', None) else None
        return render_template('index.html', username=username)

    from . import db
    db.init_app(app)

    from . import auth
    app.register_blueprint(auth.bp)

    # Initialize database indexes
    auth.init_db_indexes(app)

    # Register admin blueprint
    from . import admin
    app.register_blueprint(admin.bp)


    # Create first admin user if none exists
    with app.app_context():
        database = db.get_db()
        admin_exists = database['users'].find_one({'is_admin': True})
        if not admin_exists:
            # Check if any user exists that we can promote to admin
            first_user = database['users'].find_one({})
            if first_user:
                database['users'].update_one(
                    {'_id': first_user['_id']},
                    {'$set': {'is_admin': True}}
                )
                from flaskr.admin_log import log_admin_event
                log_admin_event('admin_creation', f'User {first_user.get("email")} automatically promoted to admin as first admin user')
    
    from .  import profile
    app.register_blueprint(profile.bp)

    return app
