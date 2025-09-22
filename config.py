import os

class Config:
    SECRET_KEY = 'secret-key-goes-here'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///lms.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Existing
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads', 'assignments')
    MATERIALS_FOLDER = os.path.join(os.getcwd(), 'uploads', 'materials')
    PAYMENT_PROOF_FOLDER = os.path.join('static', 'uploads', 'payments')
    RECEIPT_FOLDER = os.path.join('static', 'uploads', 'receipts')
    
    # ✅ New for profile pictures
    PROFILE_PICS_FOLDER = os.path.join('static', 'uploads', 'profile_pictures')

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'zip', 'jpg', 'jpeg', 'png', 'gif', 'mp3', 'mp4', 'mov', 'avi',
                          'doc', 'docx', 'xls', 'xlsx', 'pdf', 'ppt', 'txt'}
