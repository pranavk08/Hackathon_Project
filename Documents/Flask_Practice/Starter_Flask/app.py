from flask import Flask
from dotenv import load_dotenv; load_dotenv()
from flask_pymongo import PyMongo

from flaskr import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
