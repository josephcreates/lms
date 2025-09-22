import uuid
from flask import url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property
import secrets, hashlib

from utils.extensions import db
class Admin(db.Model, UserMixin):
    __tablename__ = 'admin'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Flask-Login requires a unique ID; by default UserMixin uses `id`.
    # Since you're using `admin_id`, override get_id:
    def get_id(self):
        return f"admin:{self.admin_id}"

    @property
    def role(self):
        return 'admin'

    @property
    def is_admin(self):
        # Since this class is specifically Admin, return True
        return True

class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), unique=True, nullable=False)  # e.g. STD001, TCH001, PAR001
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)  # email used for password reset
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    # ✅ New column for profile picture (stores filename/path)
    profile_picture = db.Column(db.String(255), nullable=True, default="default.png")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"user:{self.user_id}"
    
    @property
    def is_student(self):
        return self.role == 'student'

    @property
    def is_teacher(self):
        return self.role == 'teacher'
    
    @property
    def full_name(self):
        names = [self.first_name]
        if self.middle_name:
            names.append(self.middle_name)
        names.append(self.last_name)
        return ' '.join(names)
    
    @property
    def profile_picture_url(self):
        """Return the URL for the user's profile picture (fallback to default)."""
        if self.profile_picture:
            return url_for("static", filename=f"uploads/profile_pictures/{self.profile_picture}")
        return url_for("static", filename="uploads/profile_pictures/default.png")
    

class PasswordResetRequest(db.Model):
    __tablename__ = 'password_reset_request'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), default='emailed')  
    # statuses: emailed, email_failed, completed, expired
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    email_sent_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    user = db.relationship('User', backref='reset_requests')


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_token'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)
    token_hash = db.Column(db.String(128), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    used_at = db.Column(db.DateTime)
    request_id = db.Column(db.Integer, db.ForeignKey('password_reset_request.id'))
    
    user = db.relationship('User', backref=db.backref('reset_tokens', cascade='all, delete-orphan'))
    request = db.relationship('PasswordResetRequest', backref=db.backref('tokens', cascade='all, delete-orphan'))

    @staticmethod
    def generate_for_user(user, request_obj=None, expires_in_minutes=60):
        import secrets, hashlib
        raw = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        now = datetime.utcnow()
        token = PasswordResetToken(
            user_id=user.user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + timedelta(minutes=expires_in_minutes),
            request=request_obj
        )
        db.session.add(token)
        db.session.commit()
        return raw

    @staticmethod
    def verify(raw_token):
        import hashlib
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
        if not token:
            return None, 'invalid'
        if token.used:
            return None, 'used'
        if token.expires_at < datetime.utcnow():
            return None, 'expired'
        return token, 'ok'
        
class SchoolClass(db.Model):
    __tablename__ = 'school_class'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def __repr__(self):
        return f"<SchoolClass {self.name}>"

class StudentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), unique=True)
    graduated_level = db.Column(db.String(10))  # e.g., 'Primary', 'JHS', 'SHS'
    is_graduated = db.Column(db.Boolean, default=False)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10))
    nationality = db.Column(db.String(50))
    religion = db.Column(db.String(50))
    address = db.Column(db.Text)
    city = db.Column(db.String(50))
    state = db.Column(db.String(50))
    postal_code = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    guardian_name = db.Column(db.String(100))
    guardian_relation = db.Column(db.String(50))
    guardian_contact = db.Column(db.String(20))
    previous_school = db.Column(db.String(150))
    last_class_completed = db.Column(db.String(50))
    academic_performance = db.Column(db.String(100))
    current_class = db.Column(db.String(50))  # e.g., 'SHS 3'
    academic_year = db.Column(db.String(20))
    preferred_second_language = db.Column(db.String(50))
    sibling_name = db.Column(db.String(100))
    sibling_class = db.Column(db.String(50))
    blood_group = db.Column(db.String(10))
    medical_conditions = db.Column(db.Text)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_number = db.Column(db.String(20))

    user = db.relationship('User', backref=db.backref('student_profile', uselist=False), foreign_keys=[user_id])
    bookings = db.relationship('AppointmentBooking', back_populates='student', cascade='all, delete-orphan')

class TeacherProfile(db.Model):
    __tablename__ = 'teacher_profile'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), unique=True)

    # Identification & Personal Details
    employee_id = db.Column(db.String(20), unique=True, nullable=False)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    nationality = db.Column(db.String(50), nullable=True)

    # Professional Background
    qualification = db.Column(db.String(100), nullable=True)
    specialization = db.Column(db.String(100), nullable=True)
    years_of_experience = db.Column(db.Integer, nullable=True)
    subjects_taught = db.Column(db.String(255), nullable=True)
    employment_type = db.Column(db.String(20), nullable=True)  # e.g., Full-Time, Part-Time

    # Institutional Placement
    department = db.Column(db.String(100), nullable=True)
    date_of_hire = db.Column(db.Date, nullable=True)
    office_location = db.Column(db.String(100), nullable=True)

    # Metadata
    date_joined = db.Column(db.Date, default=datetime.utcnow)

    # Relationships
    user = relationship('User', backref=backref('teacher_profile', uselist=False), foreign_keys=[user_id])
    slots = db.relationship('AppointmentSlot', back_populates='teacher', cascade='all, delete-orphan')

class ParentChildLink(db.Model):
    __tablename__ = 'parent_child_link'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('parent_profile.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)

    parent = db.relationship('ParentProfile', backref='children_links')
    student = db.relationship('StudentProfile', backref='parent_links')

class ParentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.user_id'), unique=True, nullable=False)

    # Personal Details
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20))
    nationality = db.Column(db.String(100))
    occupation = db.Column(db.String(100))
    education_level = db.Column(db.String(150))

    # Contact Info
    phone_number = db.Column(db.String(20))
    email = db.Column(db.String(120))  # Optional: can differ from login email
    address = db.Column(db.String(255))

    # Guardian/Child-Related Info
    relationship_to_student = db.Column(db.String(50))  # e.g., Mother, Father, Guardian
    number_of_children = db.Column(db.Integer)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))

    # Misc
    preferred_contact_method = db.Column(db.String(50))  # e.g., Phone, Email, SMS

    user = db.relationship("User", backref="parent_profile", uselist=False)

# Class-wide fee assignment per semester/year
class ClassFeeStructure(db.Model):
    __tablename__ = 'class_fee_structure'
    id = db.Column(db.Integer, primary_key=True)
    class_level = db.Column(db.String(50), nullable=False)  # e.g. 'JHS 1'
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('class_level', 'academic_year', 'semester', 'description', name='uq_class_fee_unique'),
    )

# Tracks all payment transactions
class StudentFeeTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ New fields
    proof_filename = db.Column(db.String(255))  # uploaded file
    is_approved = db.Column(db.Boolean, default=False)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'))

    # Optional: relationships
    student = db.relationship('User', backref='fee_transactions')
    reviewer = db.relationship('Admin', backref='approved_payments', foreign_keys=[reviewed_by_admin_id])
        
# Stores cumulative balance per student
class StudentFeeBalance(db.Model):
    __tablename__ = 'student_fee_balance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0.0)
    updated_on = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = db.relationship('User', backref='fee_balances')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'academic_year', 'semester', name='uq_student_fee_balance'),
    )

class Quiz(db.Model):
    __tablename__ = 'quiz'

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    assigned_class = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    attempts_allowed = db.Column(db.Integer, nullable=False, default=1)
    content_file = db.Column(db.String(255), nullable=True)

    # ✅ cascade so deleting a quiz deletes its questions (and their options)
    questions = db.relationship(
        'Question',
        backref='quiz',
        lazy=True,
        cascade="all, delete-orphan"
    )

    @property
    def max_score(self):
        return sum(q.points for q in self.questions)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    points = db.Column(db.Float, default=1.0, nullable=False)

    options = db.relationship('Option', backref='question', cascade="all, delete-orphan")

    @property
    def max_score(self):
        # For a single question where the question has a points value:
        return float(self.points or 0.0)
    
class Option(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

class StudentAnswer(db.Model):
    __tablename__ = 'student_answers'
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('quiz_attempt.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    answer_text = db.Column(db.Text, nullable=True)
    is_correct = db.Column(db.Boolean, default=False)

    attempt = db.relationship('QuizAttempt', backref='answers')
    question = db.relationship('Question', backref='student_answers')

class StudentQuizSubmission(db.Model):
    __tablename__ = 'student_quiz_submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # assuming user table
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    score = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    student = db.relationship('User', backref='quiz_submissions')
    quiz = db.relationship('Quiz', backref='submissions')
    
class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

class Assignment(db.Model):
    __tablename__ = 'assignments'
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    instructions = db.Column(db.Text)
    assigned_class = db.Column(db.String(50), nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    filename = db.Column(db.String(200))
    original_name = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    max_score = db.Column(db.Float, nullable=False)

class AssignmentSubmission(db.Model):
    __tablename__ = 'assignment_submissions'
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Teacher scoring
    score = db.Column(db.Float, nullable=True)
    feedback = db.Column(db.Text, nullable=True)
    scored_at = db.Column(db.DateTime)

    # Automatically computed grade
    grade_letter = db.Column(db.String(5))   # e.g. A, B+, C, etc.
    pass_fail = db.Column(db.String(10))     # e.g. Pass, Fail

    # Relationships
    student = db.relationship("User", backref="assignment_submissions")
    assignment = db.relationship("Assignment", backref="submissions")

class GradingScale(db.Model):
    __tablename__ = 'grading_scales'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    min_score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False)
    grade_letter = db.Column(db.String(5), nullable=False)
    pass_fail = db.Column(db.String(10), nullable=False)
    created_by_admin = db.Column(db.Boolean, default=True)

class CourseMaterial(db.Model):
    __tablename__ = 'course_material'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    assigned_class = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_name = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

from sqlalchemy.sql import func

class Course(db.Model):
    __tablename__ = 'course'
    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(100), nullable=False)
    code                = db.Column(db.String(20), unique=True, nullable=False)
    assigned_class      = db.Column(db.String(50), nullable=False)
    semester            = db.Column(db.String(10), nullable=False)
    academic_year       = db.Column(db.String(20), nullable=False)
    is_mandatory        = db.Column(db.Boolean, default=False)

    # New columns for global registration window
    registration_start  = db.Column(db.DateTime, nullable=True)
    registration_end    = db.Column(db.DateTime, nullable=True)

    @classmethod
    def get_registration_window(cls):
        """Return a tuple (start, end) of the global registration window."""
        result = db.session.query(
            func.min(cls.registration_start),
            func.max(cls.registration_end)
        ).one()
        return result  # (start_datetime, end_datetime)

    @classmethod
    def set_registration_window(cls, start_dt, end_dt):
        """Apply the same window to every course."""
        db.session.query(cls).update({
            cls.registration_start: start_dt,
            cls.registration_end:   end_dt
        })
        db.session.commit()

class CourseLimit(db.Model):
    __tablename__ = 'course_limit'
    id               = db.Column(db.Integer, primary_key=True)
    class_level      = db.Column(db.String(50), nullable=False)  # e.g. 'JHS 1'
    semester         = db.Column(db.String(10), nullable=False)
    academic_year    = db.Column(db.String(20), nullable=False)
    mandatory_limit  = db.Column(db.Integer, nullable=False)
    optional_limit   = db.Column(db.Integer, nullable=False)

class StudentCourseRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.String(10), nullable=False)

    course = db.relationship('Course', backref='registrations')
    student = db.relationship('User', backref='registered_courses')

class TimetableEntry(db.Model):
    __tablename__ = 'timetable_entry'
    id = db.Column(db.Integer, primary_key=True)
    assigned_class = db.Column(db.String(50), nullable=False)  # e.g., "JSS1"
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    day_of_week = db.Column(db.String(10), nullable=False)  # e.g., "Monday"
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    course = db.relationship('Course', backref='timetable_entries')


class TeacherCourseAssignment(db.Model):
    __tablename__ = 'teacher_course_assignment'
    id         = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer,
                           db.ForeignKey('teacher_profile.id'),
                           nullable=False)
    course_id  = db.Column(db.Integer,
                           db.ForeignKey('course.id'),
                           nullable=False)

    teacher = db.relationship("TeacherProfile", backref="assignments")
    course  = db.relationship("Course")

class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_record'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_profile.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    is_present = db.Column(db.Boolean, default=False)

    student = db.relationship('User')
    teacher = db.relationship('TeacherProfile')
    course = db.relationship('Course')

class AcademicCalendar(db.Model):
    __tablename__ = 'academic_calendar'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    label = db.Column(db.String(100), nullable=False)
    break_type = db.Column(db.String(50), nullable=False)  # e.g. Holiday, Exam, Midterm
    is_workday = db.Column(db.Boolean, default=False)

class AcademicYear(db.Model):
    __tablename__ = 'academic_year'
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    semester_1_start = db.Column(db.Date, nullable=False)
    semester_1_end = db.Column(db.Date, nullable=False)
    semester_2_start = db.Column(db.Date, nullable=False)
    semester_2_end = db.Column(db.Date, nullable=False)

class AppointmentSlot(db.Model):
    __tablename__ = 'appointment_slot'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher_profile.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_booked = db.Column(db.Boolean, default=False, nullable=False)

    teacher = db.relationship('TeacherProfile', back_populates='slots')
    booking = db.relationship('AppointmentBooking', back_populates='slot', uselist=False)

class AppointmentBooking(db.Model):
    __tablename__ = 'appointment_booking'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('appointment_slot.id'), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, approved, declined, rescheduled
    note = db.Column(db.Text)
    requested_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship('StudentProfile', back_populates='bookings')
    slot = db.relationship('AppointmentSlot', back_populates='booking')


# ============================
# Exam-related models
# ============================

class Exam(db.Model):
    __tablename__ = 'exams'
    id = db.Column(db.Integer, primary_key=True)

    subject = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    assigned_class = db.Column(db.String(50), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=True)

    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # NEW COLUMNS
    assignment_mode = db.Column(db.String(20), default='random', nullable=False)
    assignment_seed = db.Column(db.String(255), nullable=True)

    # Relationships
    questions = db.relationship('ExamQuestion', backref='exam', cascade="all, delete-orphan")
    sets = db.relationship("ExamSet", backref="exam", cascade="all, delete-orphan")
    submissions = db.relationship('ExamSubmission', backref='exam', cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Exam {self.title}>"
    @hybrid_property
    def max_score(self):
        return sum(q.marks for q in self.questions)

class ExamSet(db.Model):
    __tablename__ = "exam_sets"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    max_score = db.Column(db.Float, nullable=True)

    # actual column
    access_password = db.Column(db.String(128), nullable=True)

    # relationship
    set_questions = db.relationship("ExamSetQuestion", backref="set", cascade="all, delete-orphan")

    @property
    def password(self):
        return self.access_password

    def __repr__(self):
        return f"<ExamSet {self.name} of Exam {self.exam_id}>"

    @property
    def computed_max_score(self):
        return sum(q.question.marks or 0 for q in self.set_questions)

class ExamQuestion(db.Model):
    __tablename__ = "exam_questions"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)

    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # 'mcq', 'true_false', 'subjective'
    marks = db.Column(db.Integer, nullable=False, default=1)

    options = db.relationship("ExamOption", backref="question", cascade="all, delete-orphan")

    in_sets = db.relationship("ExamSetQuestion", backref="question", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ExamQuestion {self.question_text[:30]}...>"

class ExamSetQuestion(db.Model):
    __tablename__ = 'exam_set_questions'
    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(db.Integer, db.ForeignKey("exam_sets.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("exam_questions.id"), nullable=False)
    order = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("set_id", "question_id", name="uix_set_question"),
    )

class ExamOption(db.Model):
    __tablename__ = 'exam_options'
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('exam_questions.id'), nullable=False)
    text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<ExamOption {self.text}>"

# ============================
# Attempts / Submissions
# ============================

class ExamAttempt(db.Model):
    __tablename__ = 'exam_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    set_id = db.Column(db.Integer, db.ForeignKey('exam_sets.id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)

    submitted = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, nullable=True)   # exact submission time
    
    score = db.Column(db.Float, nullable=True)

    exam = db.relationship("Exam", backref="attempts")
    exam_set = db.relationship("ExamSet", backref="attempts")

    def __repr__(self):
        return f"<ExamAttempt exam={self.exam_id} student={self.student_id} submitted={self.submitted}>"

class ExamSubmission(db.Model):
    __tablename__ = 'exam_submissions'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    set_id = db.Column(db.Integer, db.ForeignKey('exam_sets.id'), nullable=True)

    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Float, nullable=True)

    answers = db.relationship('ExamAnswer', backref='submission', cascade="all, delete-orphan")
    exam_set = db.relationship("ExamSet", backref="submissions")

    __table_args__ = (
        db.UniqueConstraint('exam_id', 'student_id', name='uix_exam_student'),
    )

    def __repr__(self):
        return f"<ExamSubmission exam={self.exam_id} student={self.student_id}>"

    @property
    def max_score(self):
        if self.exam_set:  # ✅ always prioritize the set
            return self.exam_set.computed_max_score or 0
        return 0  # if no set was assigned, don't fall back to exam pool

class ExamAnswer(db.Model):
    __tablename__ = 'exam_answers'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('exam_submissions.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('exam_questions.id'), nullable=False)
    selected_option_id = db.Column(db.Integer, db.ForeignKey('exam_options.id'), nullable=True)
    answer_text = db.Column(db.Text, nullable=True)  # for subjective answers

    def __repr__(self):
        return f"<ExamAnswer Q{self.question_id} -> Option {self.selected_option_id or 'text'}>"

class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # e.g. 'assignment', 'quiz', 'exam', 'event', 'fee', 'general'
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=True)

    related_type = db.Column(db.String(50), nullable=True)  # link target type
    related_id = db.Column(db.Integer, nullable=True)        # target object id

    sender = db.relationship('User', foreign_keys=[sender_id])

    recipients = db.relationship(
        "NotificationRecipient",
        back_populates="notification",
        cascade="all, delete-orphan"
    )


class NotificationRecipient(db.Model):
    __tablename__ = 'notification_recipients'

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id'), nullable=False)
    user_id = db.Column(db.String(20), db.ForeignKey('user.user_id'), nullable=False)

    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)

    notification = db.relationship('Notification', back_populates='recipients')
    user = db.relationship('User', backref='notifications_received')


# -----------------------
# DB Model (simple)
# -----------------------
class Meeting(db.Model):
    __tablename__ = 'meetings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    host_id = db.Column(db.String(60), nullable=False)
    meeting_code = db.Column(db.String(80), unique=True, index=True, nullable=False)
    scheduled_start = db.Column(db.DateTime, nullable=True)
    scheduled_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Recording(db.Model):
    __tablename__ = 'recordings'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Fixed table name
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))

    teacher = db.relationship('User', backref='recordings')
    course = db.relationship('Course', backref='recordings')
