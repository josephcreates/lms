from datetime import datetime
import os
import sys, uuid, threading, webbrowser
from flask import Flask, current_app, render_template, redirect, url_for, flash, request, abort, jsonify, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flaskwebgui import FlaskUI
from datetime import datetime, timedelta
from utils.helpers import get_class_choices
from utils.extensions import db, mail
from config import Config
from models import PasswordResetToken, User, Admin, SchoolClass, StudentProfile, TeacherProfile, ParentProfile, Exam, Quiz, ExamSet, PasswordResetRequest

# Import blueprints after monkey patching and flask imports
from admin_routes import admin_bp
from teacher_routes import teacher_bp
from student_routes import student_bp
from parent_routes import parent_bp
from utils.auth_routes import auth_bp
from exam_routes import exam_bp
from vclass_routes import vclass_bp

app = Flask(__name__)
app.config.from_object(Config)

app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///lms.db"  # or your DB
#app.config['MAIL_BACKEND'] = "console" for local development testing
app.config['MAIL_SERVER'] = "smtp.gmail.com"
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = "lampteyjoseph860@gmail.com"
app.config['MAIL_PASSWORD'] = "injj jivj dnlq tlum"
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_DEFAULT_SENDER'] = ("LMS Admin", "lampteyjoseph860@gmail.com")

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['MATERIALS_FOLDER'], exist_ok=True)
os.makedirs(app.config['PAYMENT_PROOF_FOLDER'], exist_ok=True)
os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_PICS_FOLDER'], exist_ok=True)

db.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

@app.context_processor
def csrf_context():
    return dict(csrf_token=generate_csrf)

@app.after_request
def set_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response

login_manager = LoginManager(app)

@login_manager.unauthorized_handler
def unauthorized_callback():
    # If the request is for an admin route → send to admin login
    if request.path.startswith("/admin"):
        return redirect(url_for("admin.admin_login", next=request.path))
    # Otherwise → go to portal selection
    return redirect(url_for("select_portal", next=request.path))

# Register Blueprints with explicit names
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(teacher_bp, url_prefix="/teacher")
app.register_blueprint(student_bp, url_prefix="/student")
app.register_blueprint(parent_bp, url_prefix="/parent")
app.register_blueprint(auth_bp)  # no prefix
app.register_blueprint(exam_bp, url_prefix="/exam")
app.register_blueprint(vclass_bp, url_prefix="/vclass")

@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith("admin:"):
        return Admin.query.filter_by(admin_id=user_id.split(":", 1)[1]).first()
    elif user_id.startswith("user:"):
        return User.query.filter_by(user_id=user_id.split(":", 1)[1]).first()
    return None

@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def home():
    try:
        return render_template('home.html')
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"<h1>Template rendering error: {e}</h1>", 500

@app.route('/student/results-test')
def test_results():
    return "Results test route works!"

@app.route('/routes')
def show_routes():
    output = []
    for rule in app.url_map.iter_rules():
        output.append(f"{rule.endpoint:30s} {rule.rule}")
    return "<pre>" + "\n".join(sorted(output)) + "</pre>"

@app.route('/portal')
def select_portal():
    """Render the portal selection page."""
    return render_template('portal_selection.html')

@app.route('/portal/<portal>')
def redirect_to_portal(portal):
    """
    Map a clean portal slug to the actual login endpoint.
    Edit this mapping to match your app's blueprint endpoint names.
    """
    mapping = {
        'exams':        'exam.exam_login',          # example: exam blueprint
        'teachers':     'teacher.teacher_login',    # teacher blueprint
        'students':     'student.student_login',    # student blueprint
        'parents':      'parent.parent_login',      # parent blueprint
        'vclass':       'vclass.vclass_login'       # vclass blueprint
    }

    key = portal.lower()
    if key not in mapping:
        abort(404)

    # If the target endpoint exists, redirect there
    return redirect(url_for(mapping[key]))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('select_portal'))


@app.before_request
def initialize_database():
    db.create_all()

    super_admin = Admin.query.filter_by(username='SuperAdmin').first()
    if not super_admin:
        admin = Admin(username='SuperAdmin', admin_id='ADM001')
        admin.set_password('Password123')
        db.session.add(admin)
        db.session.commit()
        print("SuperAdmin created.")

    existing_classes = {cls.name for cls in SchoolClass.query.all()}
    default_classes = [name for name, _ in get_class_choices()]
    for class_name in default_classes:
        if class_name not in existing_classes:
            db.session.add(SchoolClass(name=class_name))
    db.session.commit()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
