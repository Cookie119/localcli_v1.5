import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'DATABASE_URL=postgresql://arc_l59c_user:SYExULIHnrFM5QGrQNMAWU1F6JrrEUT2@dpg-d69b1vv5r7bs73f52d6g-a.singapore-postgres.render.com/arc_l59c')
    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False