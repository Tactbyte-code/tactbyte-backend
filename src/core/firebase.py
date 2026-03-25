import firebase_admin
from firebase_admin import credentials
from src.core.settings import settings
import json

def initialize_firebase():
    if not firebase_admin._apps:
        creds_json = settings.FIREBASE_CREDENTIALS
        cred = credentials.Certificate(json.loads(creds_json))
        firebase_admin.initialize_app(cred)