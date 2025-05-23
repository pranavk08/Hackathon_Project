import os

from flask import Flask
from flask_mail import Mail

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        MONGO_URI='mongodb://localhost:27017/TodoApp',
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

    return app
