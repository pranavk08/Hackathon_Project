from flask import Flask, render_template, Blueprint, flash, request
from flaskr.db import get_db

bp = Blueprint('profile', __name__, url_prefix='/profile')

@bp.route('/')
def index():
    return render_template('prof/profile.html')

@bp.route('/ex')
def ex():
    db = get_db()
    k = db['users'].find_one({
        "username": "admin"
    })

    if k == None:
        flash("No User")
        return render_template('prof/db_con.html', k = k)
    else:
        return render_template('prof/db_con.html', k = k)

@bp.route('/user', methods=['GET', 'POST'])
def user():
    if request.method =='POST':
        name = request.form.get('name', '').strip() 

        db = get_db()

        if not name:
            flash("Please Enter the details")
            return render_template('prof/user.html')
        else:
            new_user = {
                'name': name,
            }
            db['sample'].insert_one(new_user)
            flash("User Added Successful")
            return render_template('index.html')
    
    return render_template('prof/user.html')

