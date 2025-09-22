from flask import Blueprint, current_app, render_template, abort, redirect, url_for, flash, jsonify, session, send_from_directory, send_file
import json, os
from flask import request
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import func
from werkzeug.utils import safe_join, secure_filename
from models import db, User, Quiz, StudentQuizSubmission, Question, StudentProfile, QuizAttempt, Assignment, CourseMaterial, StudentCourseRegistration, Course,  TimetableEntry, AcademicCalendar, AcademicYear, AppointmentSlot, AppointmentBooking, StudentFeeBalance, ClassFeeStructure, StudentFeeTransaction, Exam, ExamSubmission, ExamQuestion, ExamAttempt, ExamSet, ExamSetQuestion, Meeting, StudentAnswer, Recording, PasswordResetRequest, PasswordResetToken, AssignmentSubmission
from datetime import date, datetime, timedelta, time
from forms import StudentLoginForm, ForgotPasswordForm, ResetPasswordForm
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from utils.email_utils import send_password_reset_email


vclass_bp = Blueprint('vclass', __name__, url_prefix='/vclass')

ALLOWED_EXTENSIONS = {'.doc', '.docx', '.xls', '.xlsx', '.pdf', '.ppt', '.txt'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads", "assignments")

def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Utility to split multi-day events into single-day all-day events
def split_event_into_days(title, start, end, color, extended_props):
    """Split a multi-day event into separate all-day blocks, one per day."""
    events = []
    current = start.date()
    final = end.date()
    while current <= final:
        next_day = current + timedelta(days=1)
        events.append({
            'title': title,
            'start': current.isoformat(),   # Date only for all-day events
            'end': next_day.isoformat(),    # Next day (non-inclusive end)
            'color': color,
            'allDay': True,
            'extendedProps': extended_props
        })
        current = next_day
    return events


@vclass_bp.route('/login', methods=['GET', 'POST'])
def vclass_login():
    form = StudentLoginForm()
    next_page = request.args.get('next')

    if form.validate_on_submit():
        username = form.username.data.strip()
        user_id = form.user_id.data.strip()
        password = form.password.data.strip()

        user = User.query.filter_by(user_id=user_id, role='student').first()
        if user and user.username.lower() == username.lower() and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.first_name}!", 'success')
            return redirect(next_page or url_for('vclass.dashboard'))

        flash('Invalid login credentials.', 'danger')

    return render_template('vclass/vclass_login.html', form=form)


@vclass_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user_id = form.user_id.data.strip() or None

        query = User.query.filter(db.func.lower(User.email) == email)
        if user_id:
            query = query.filter_by(user_id=user_id)
        user = query.first()

        if not user:
            flash('If that account exists, a reset email will be sent.', 'info')
            return redirect(url_for('auth.forgot_password'))

        # Log request
        reset_request = PasswordResetRequest(user_id=user.user_id, role=user.role)
        db.session.add(reset_request)
        db.session.commit()

        # Generate token
        token = PasswordResetToken.generate_for_user(user, request_obj=reset_request)

        # Send email immediately
        try:
            send_password_reset_email(user, token)
            reset_request.status = 'emailed'
            reset_request.email_sent_at = datetime.utcnow()
        except Exception as e:
            reset_request.status = 'email_failed'
            current_app.logger.exception(f"Failed to send password reset email: {e}")

        db.session.commit()

        flash('If your email exists, you’ll get a reset link shortly.', 'info')
        return redirect(url_for('login'))

    return render_template('forgot_password.html', form=form)


@vclass_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    prt, status = PasswordResetToken.verify(token)
    if status != 'ok':
        messages = {
            'expired': 'Reset link expired.',
            'used': 'Reset link already used.',
            'invalid': 'Invalid reset link.'
        }
        flash(messages.get(status, 'danger'))
        return redirect(url_for('auth.forgot_password'))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = prt.user
        user.set_password(form.password.data)
        prt.used = True
        prt.used_at = datetime.utcnow()
        if prt.request:
            prt.request.status = 'completed'
            prt.request.completed_at = datetime.utcnow()
        db.session.commit()
        flash('Password updated. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', form=form)

@vclass_bp.route('/switch-to-vclass')
@login_required
def switch_to_vclass():
    logout_user()
    flash('You have been logged out. Please log in to access Virtual Class.', 'info')
    return redirect(url_for('vclass.vclass_login', next=url_for('vclass.dashboard')))


@vclass_bp.route('/switch-to-student-portal')
@login_required
def switch_to_student_portal():
    logout_user()
    flash('You have been logged out. Please log in to access the Student Portal.', 'info')
    return redirect(url_for('student.student_login', next=url_for('student.dashboard')))

@vclass_bp.route('/switch-to-student-courses')
@login_required
def switch_to_student_courses():
    logout_user()
    flash('You have been logged out. Please log in to access Course Registration.', 'info')
    return redirect(url_for('login', next=url_for('student.register_courses')))

# Virtual Classroom Dashboard
@vclass_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student':
        abort(403)

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not profile:
        flash("Student profile not found.", "danger")
        return redirect(url_for("vclass.vclass_dashboard"))

    student_class = profile.current_class
    now = datetime.utcnow()

    # --- Quizzes ---
    quizzes = Quiz.query.filter_by(assigned_class=student_class).all()
    quiz_list = []
    for q in quizzes:
        status = 'Upcoming'
        if q.start_datetime <= now <= q.end_datetime:
            status = 'Ongoing'
        elif now > q.end_datetime:
            status = 'Due'
        quiz_list.append({
            'id': q.id,
            'title': q.title,
            'course_name': q.subject,
            'due_date': q.end_datetime.isoformat(),
            'start_datetime': q.start_datetime.strftime("%H:%M"),
            'duration': q.duration_minutes,
            'is_active': status != 'Due'
        })

    # --- Assignments ---
    assignments = Assignment.query.filter_by(assigned_class=student_class).all()
    assignment_list = [{
        'id': a.id,
        'title': a.title,
        'course_name': a.course_name,
        'description': a.description,
        'instructions': a.instructions,
        'due_date': a.due_date.isoformat(),
        'filename': a.filename,
        'original_name': a.original_name
    } for a in assignments]

    # --- Course Materials ---
    materials = CourseMaterial.query.filter_by(assigned_class=student_class).all()
    material_list = [{
        'id': m.id,
        'title': m.title,
        'course_name': m.course_name,
        'filename': m.filename,
        'original_name': m.original_name,
        'file_type': m.file_type,
        'upload_date': m.upload_date.isoformat() if m.upload_date else None
    } for m in materials]

    # --- Combined Calendar Events ---
    events = []

    # Quizzes → Calendar
    for q in quizzes:
        status = 'Upcoming'
        color = '#0d6efd'
        if q.start_datetime <= now <= q.end_datetime:
            status = 'Ongoing'
            color = '#ffc107'
        elif now > q.end_datetime:
            status = 'Due'
            color = '#dc3545'

        events.append({
            'title': f"{q.title} [{status}]",
            'start': q.start_datetime.isoformat(),
            'end': q.end_datetime.isoformat(),
            'url': url_for('vclass.quiz_instructions', quiz_id=q.id),            'color': color,
            'extendedProps': {
                'type': 'Quiz',
                'status': status,
                'course': q.subject,
                'description': ''
            }
        })

    # Assignments → Calendar
    for a in assignments:
        events.append({
            'title': f"{a.title} [Due]",
            'start': a.due_date.isoformat(),
            'end': a.due_date.isoformat(),
            'url': url_for('vclass.download_assignment', filename=a.filename),
            'color': '#198754',
            'extendedProps': {
                'type': 'Assignment',
                'status': 'Due',
                'course': a.course_name,
                'description': a.instructions or ''
            }
        })

    # Course Registration Period
    registration_start, registration_end = Course.get_registration_window()
    if registration_start and registration_end:
        events += split_event_into_days(
            title='Course Registration Period',
            start=registration_start,
            end=registration_end,
            color='#dc3545',
            extended_props={
                'type': 'Deadline',
                'status': 'Open',
                'course': '',
                'description': 'Course registration is available during this window.'
            }
        )

    # --- Academic Calendar Events (vacations, holidays, etc.) ---
    ac_events = AcademicCalendar.query.order_by(AcademicCalendar.date).all()
    color_map = {
        'Vacation': '#e67e22',
        'Midterm': '#9b59b6',
        'Exam': '#2980b9',
        'Holiday': '#c0392b',
        'Other': '#95a5a6'
    }

    for ev in ac_events:
        events.append({
            'title': ev.label,
            'start': ev.date.isoformat(),
            'color': color_map.get(ev.break_type, '#7f8c8d'),
            'extendedProps': {
                'type': ev.break_type,
                'status': 'Academic',
                'course': '',
                'description': ''
            }
        })

    # Semester background (visual highlight)
    academic_year = AcademicYear.query.first()
    if academic_year:
        events.append({
            'start': academic_year.semester_1_start.isoformat(),
            'end': (academic_year.semester_1_end + timedelta(days=1)).isoformat(),
            'display': 'background',
            'color': '#d1e7dd',
            'title': 'Semester 1'
        })
        events.append({
            'start': academic_year.semester_2_start.isoformat(),
            'end': (academic_year.semester_2_end + timedelta(days=1)).isoformat(),
            'display': 'background',
            'color': '#f8d7da',
            'title': 'Semester 2'
        })

    return render_template(
        'vclass/dashboard.html',
        quizzes=quiz_list,
        assignments=assignment_list,
        materials=material_list,
        events=events
    )

# Utility functions
def is_quiz_active(quiz):
    now = datetime.utcnow()
    return quiz.start_datetime <= now <= quiz.end_datetime

def is_quiz_submission_allowed(quiz):
    now = datetime.now()
    quiz_start = datetime.combine(quiz.date, quiz.start_time)
    quiz_end = quiz_start + timedelta(minutes=quiz.duration_minutes)
    # Allow submission only if current time <= quiz_end
    return now <= quiz_end

# Quiz Instructions Page
@vclass_bp.route('/quiz-instructions/<int:quiz_id>')
@login_required
def quiz_instructions(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    now = datetime.utcnow()

    if now < quiz.start_datetime:
        flash("This quiz is not yet available.", "warning")
        return redirect(url_for('student.virtual_class'))

    if now > quiz.end_datetime:
        flash("This quiz is past its due date and can no longer be taken.", "danger")
        return redirect(url_for('student.virtual_class'))

    if current_user.role != 'student':
        abort(403)

    attempts_made = QuizAttempt.query.filter_by(
        quiz_id=quiz.id,
        student_id=current_user.id
    ).count()

    can_attempt = attempts_made < quiz.attempts_allowed

    return render_template(
        'vclass/quiz_instructions.html',
        quiz=quiz,
        attempts_made=attempts_made,
        can_attempt=can_attempt
    )

from sqlalchemy.orm import joinedload

from flask_wtf.csrf import generate_csrf

@vclass_bp.route('/take-quiz/<int:quiz_id>')
@login_required
def take_quiz(quiz_id):
    if current_user.role != 'student':
        abort(403)

    quiz = Quiz.query.options(
        joinedload(Quiz.questions).joinedload(Question.options)
    ).get_or_404(quiz_id)

    now = datetime.utcnow()

    if now < quiz.start_datetime:
        flash("This quiz is not yet available.", "warning")
        return redirect(url_for('vclass.virtual_class'))

    if now > quiz.end_datetime:
        flash("This quiz is past its due date and can no longer be taken.", "danger")
        return redirect(url_for('vclass.virtual_class'))

    attempts_made = QuizAttempt.query.filter_by(
        quiz_id=quiz.id,
        student_id=current_user.id
    ).count()

    if attempts_made >= quiz.attempts_allowed:
        flash("You have reached the maximum number of attempts for this quiz.", "danger")
        return redirect(url_for('vclass.quiz_instructions', quiz_id=quiz.id))

    quiz_data = {
        "id": quiz.id,
        "title": quiz.title,
        "duration_minutes": quiz.duration_minutes,
        "questions": [
            {
                "id": q.id,
                "question_text": q.text,
                "options": [
                    {"id": opt.id, "text": opt.text}
                    for opt in q.options
                ]
            }
            for q in quiz.questions
        ]
    }

    # ✅ generate csrf token for the template
    return render_template('vclass/take_quiz.html', quiz_json=quiz_data, session=session)


@vclass_bp.route('/start-quiz-timer/<int:quiz_id>', methods=['POST'], endpoint='start_quiz_timer')
@login_required
def start_quiz_timer(quiz_id):
    key = f'quiz_{quiz_id}_start_time'
    if key not in session:
        session[key] = datetime.utcnow().isoformat()
        session.modified = True
    return jsonify({'status': 'started'})

@vclass_bp.route("/vclass/autosave_answer", methods=["POST"])
def autosave_answer():
    data = request.get_json()
    quiz_id = data["quiz_id"]
    qid = data["question_id"]
    oid = data["selected_option_id"]

    ans = StudentAnswer.query.filter_by(
        student_id=current_user.id,
        quiz_id=quiz_id,
        question_id=qid
    ).first()

    if ans:
        ans.selected_option_id = oid
        ans.saved_at = datetime.utcnow()
    else:
        ans = StudentAnswer(
            student_id=current_user.id,
            quiz_id=quiz_id,
            question_id=qid,
            selected_option_id=oid
        )
        db.session.add(ans)

    db.session.commit()
    return jsonify(success=True)

@vclass_bp.route("/vclass/get_saved_answers/<int:quiz_id>")
@login_required
def get_saved_answers(quiz_id):
    answers = (
        StudentAnswer.query
        .join(QuizAttempt)
        .filter(
            QuizAttempt.student_id == current_user.id,
            QuizAttempt.quiz_id == quiz_id
        )
        .all()
    )
    return jsonify({str(a.question_id): a.answer_text for a in answers})

@vclass_bp.route('/submit_quiz/<int:quiz_id>', methods=['POST'])
@login_required
def submit_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    # 🧠 Use current_user.id (numeric PK)
    autosaved_key = f'autosaved_quiz_{quiz.id}_{current_user.id}'
    autosaved_answers = session.get(autosaved_key, {})

    score = 0
    for q in quiz.questions:
        submitted_option_id = request.form.get(f"answers[{q.id}]")

        if not submitted_option_id:
            submitted_option_id = autosaved_answers.get(str(q.id))

        if submitted_option_id:
            try:
                submitted_option_id = int(submitted_option_id)
                correct_option = next((opt for opt in q.options if opt.is_correct), None)
                if correct_option and submitted_option_id == correct_option.id:
                    score += 1
            except (ValueError, TypeError):
                continue

    # 🧾 Save Submission
    submission = StudentQuizSubmission(
        student_id=current_user.id,  # ✅ integer ID
        quiz_id=quiz.id,
        score=score,
        submitted_at=datetime.utcnow()
    )
    db.session.add(submission)

    # 📘 Save Attempt
    attempt = QuizAttempt(
        student_id=current_user.id,  # ✅ integer ID
        quiz_id=quiz.id,
        score=score,
        submitted_at=datetime.utcnow()
    )
    db.session.add(attempt)

    # Clean up session
    session.pop(autosaved_key, None)
    session.pop(f'quiz_{quiz.id}_start_time', None)

    db.session.commit()

    return redirect(url_for('vclass.quiz_result', submission_id=submission.id))

@vclass_bp.route('/has-submitted/<int:quiz_id>')
@login_required
def has_submitted(quiz_id):
    exists = StudentQuizSubmission.query.filter_by(
        student_id=current_user.id,
        quiz_id=quiz_id
    ).first()
    return jsonify({"submitted": bool(exists)})

@vclass_bp.route('/quiz_result/<int:submission_id>')
@login_required
def quiz_result(submission_id):
    submission = StudentQuizSubmission.query.get_or_404(submission_id)
    quiz = submission.quiz

    return render_template('vclass/quiz_result.html', quiz=quiz, submission=submission)


@vclass_bp.route('/download/assignments/<filename>')
@login_required
def download_assignment(filename):
    filepath = safe_join(current_app.config['UPLOAD_FOLDER'], filename)
    print(f"Looking for file: {filepath}")  # 🔍 DEBUG LINE
    if not os.path.exists(filepath):
        abort(404)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@vclass_bp.route('/assignment/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
def submit_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash("No file selected.", "danger")
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash("Invalid file type. Allowed: doc, docx, xls, xlsx, pdf, ppt, txt", "danger")
            return redirect(request.url)

        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        submission = AssignmentSubmission(
            assignment_id=assignment.id,
            student_id=current_user.id,
            filename=filename,
            original_name=file.filename
        )
        db.session.add(submission)
        db.session.commit()

        flash("Assignment submitted successfully!", "success")
        return redirect(url_for('vclass.my_results'))

    return render_template("vclass/submit_assignment.html", assignment=assignment)

# Download course materials
@vclass_bp.route('/download/materials/<filename>')
@login_required
def download_material(filename):
    materials_dir = current_app.config.get("MATERIALS_FOLDER") or os.path.join(os.getcwd(), "uploads", "materials")
    filepath = os.path.join(materials_dir, filename)
    print(f"Looking for material: {filepath}")  # 🔍 DEBUG
    if not os.path.exists(filepath):
        abort(404)
    return send_from_directory(materials_dir, filename, as_attachment=True)

@vclass_bp.route('/assignments')
@login_required
def assignments():
    assignments = Assignment.query.all()

    # Convert now to date
    now = datetime.utcnow().date()

    # Convert due_date to date for each assignment
    for a in assignments:
        a.due = a.due_date.date()  # new attribute for template comparisons

    return render_template(
        'vclass/assignments.html',
        assignments=assignments,
        now=now
    )

@vclass_bp.route('/material/video/<filename>')
@login_required
def play_video(filename):
    material = CourseMaterial.query.filter_by(filename=filename).first_or_404()

    if material.file_type.lower() not in ['mp4', 'webm', 'ogg']:
        flash('Unsupported video format.', 'warning')
        return redirect(url_for('vclass.virtual_class'))

    # Fetch related videos
    related_videos = CourseMaterial.query.filter(
        CourseMaterial.id != material.id,
        CourseMaterial.file_type.in_(['mp4', 'webm', 'ogg'])
    ).order_by(CourseMaterial.upload_date.desc()).limit(10).all()

    return render_template('vclass/play_video.html', material=material, related_videos=related_videos)

@vclass_bp.route('/stream/materials/<filename>')
@login_required
def stream_material_video(filename):
    video_path = os.path.join(current_app.root_path, 'uploads', 'materials', filename)
    if not os.path.isfile(video_path):
        abort(404)
    mime_type = f'video/{filename.rsplit(".", 1)[-1]}'

    # send_file with headers forcing inline content (stream)
    response = send_file(video_path, mimetype=mime_type, conditional=True)
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response

# Profile Page
@vclass_bp.route('/profile')
@login_required
def profile():
    if current_user.role != 'student':  # or 'teacher', depending
        abort(403)

    # Assuming you have a Profile model related to your User
    profile = getattr(current_user, 'profile', None)

    return render_template(
        'vclass/profile.html',
        user=current_user,  # pass current_user as 'user'
        profile=profile     # pass profile
    )

@vclass_bp.route('/participants')
@login_required
def participants():
    if current_user.role != 'student':
        abort(403)
    
    # Example: fetch participants of the current class
    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not profile:
        flash("Profile not found.", "danger")
        return redirect(url_for("vclass.dashboard"))

    student_class = profile.current_class
    participants_list = StudentProfile.query.filter_by(current_class=student_class).all()

    return render_template('vclass/participants.html', participants=participants_list)

@vclass_bp.route('/join-room')
@login_required
def join_room():
    if current_user.role != 'student':
        abort(403)
    
    # Use the correct column
    meetings = Meeting.query.order_by(Meeting.scheduled_start.desc()).all()
    
    return render_template('vclass/join_room.html', meetings=meetings)

@vclass_bp.route('/schedule')
@login_required
def schedule():
    return render_template('vclass/schedule.html')

@vclass_bp.route('/recordings')
@login_required
def recordings():
    if current_user.role != 'student':
        abort(403)

    # Example: fetch recordings
    recordings = Recording.query.order_by(Recording.created_at.desc()).all()

    return render_template('vclass/recordings.html', recordings=recordings)

@vclass_bp.route('/book-appointment', methods=['GET', 'POST'])
@login_required
def book_appointment():
    # Only fetch unbooked slots
    available_slots = AppointmentSlot.query.filter_by(is_booked=False).all()

    # Pass slots directly to template
    slots = []
    for slot in available_slots:
        teacher_user = slot.teacher.user  # Get the related User
        slots.append({
            'id': slot.id,
            'date': slot.date,
            'start_time': slot.start_time,
            'end_time': slot.end_time,
            'teacher_name': f"{teacher_user.first_name} {teacher_user.last_name}"
        })

    if request.method == 'POST':
        slot_id = request.form['slot_id']
        note = request.form.get('note', '')
        slot = AppointmentSlot.query.get_or_404(slot_id)

        if slot.is_booked:
            flash('Slot already booked.', 'danger')
            return redirect(url_for('vclass.book_appointment'))

        student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
        if not student_profile:
            flash('Student profile not found.', 'danger')
            return redirect(url_for('vclass.book_appointment'))

        booking = AppointmentBooking(
            student_id=student_profile.id,
            slot_id=slot.id,
            note=note
        )
        slot.is_booked = True
        db.session.add(booking)
        db.session.add(booking)
        db.session.commit()

        flash('Appointment booked successfully.', 'success')
        return redirect(url_for('vclass.my_appointments'))

    return render_template('vclass/book_appointment.html', slots=slots)

@vclass_bp.route('/my_results')
@login_required
def my_results():
    user_id = current_user.id

    # -----------------------
    # QUIZZES (student submissions) - unchanged
    # -----------------------
    quiz_subs = StudentQuizSubmission.query.filter_by(student_id=user_id).all()
    quiz_results = []
    for sub in quiz_subs:
        quiz = getattr(sub, 'quiz', None)
        max_score = None
        if getattr(sub, 'max_score', None) is not None:
            max_score = float(sub.max_score)
        elif quiz is not None:
            if getattr(quiz, 'total_marks', None) is not None:
                max_score = float(quiz.total_marks)
            elif getattr(quiz, 'total_questions', None) is not None:
                points_each = float(getattr(quiz, 'points_per_question', 1) or 1)
                max_score = float(quiz.total_questions) * points_each

        obtained = float(sub.score) if getattr(sub, 'score', None) is not None else None
        percent = None
        if obtained is not None and max_score and max_score > 0:
            percent = (obtained / max_score) * 100.0

        quiz_results.append({
            'quiz': quiz,
            'score': obtained,
            'max_score': max_score,
            'percent': percent,
            'submitted_at': getattr(sub, 'submitted_at', None),
            'raw_submission': sub
        })

    # -----------------------
    # ASSIGNMENTS
    # -----------------------
    # 1) get student's submissions (map by assignment_id)
    assignment_subs = {}
    try:
        subs = AssignmentSubmission.query.filter_by(student_id=user_id).all()
        for s in subs:
            # ensure int key
            assignment_subs[int(getattr(s, 'assignment_id'))] = s
    except Exception as ex:
        # log if you want; keep map empty but don't break
        current_app.logger.debug("AssignmentSubmission fetch failed: %s", ex)
        assignment_subs = {}

    # 2) build list of assignments to show:
    #    - assignments for student's classes AND
    #    - any assignment ids that appear in student's submissions
    assignment_ids = set()
    try:
        student_classes = StudentCourseRegistration.query.filter_by(student_id=user_id).all()
        class_names = [sc.course.name for sc in student_classes if getattr(sc, 'course', None)]
        if class_names:
            assignments_by_class = Assignment.query.filter(Assignment.assigned_class.in_(class_names)).all()
            assignment_ids.update([a.id for a in assignments_by_class])
    except Exception as ex:
        current_app.logger.debug("Student class lookup failed: %s", ex)

    # include assignments that student submitted (guarantees they appear)
    assignment_ids.update(list(assignment_subs.keys()))

    # final fetch
    assignments = []
    if assignment_ids:
        assignments = Assignment.query.filter(Assignment.id.in_(list(assignment_ids))).all()

    # 3) build assignment_results (attach submission if exists)
    assignment_results = []
    for a in assignments:
        sub = assignment_subs.get(getattr(a, 'id'))

        # determine max_score from assignment fields (fallbacks if you use different fields)
        max_score = None
        if getattr(a, 'max_score', None) is not None:
            max_score = float(a.max_score)
        elif getattr(a, 'marks_allocated', None) is not None:
            max_score = float(a.marks_allocated)
        elif getattr(a, 'total_marks', None) is not None:
            max_score = float(a.total_marks)
        elif getattr(a, 'total_questions', None) is not None:
            points_each = float(getattr(a, 'points_per_question', 1) or 1)
            max_score = float(a.total_questions) * points_each

        obtained = None
        submitted_at = None
        grade_letter = None
        pass_fail = None
        if sub:
            obtained = float(getattr(sub, 'score')) if getattr(sub, 'score', None) is not None else None
            submitted_at = getattr(sub, 'submitted_at', None)
            grade_letter = getattr(sub, 'grade_letter', None)
            pass_fail = getattr(sub, 'pass_fail', None)

        percent = None
        if obtained is not None and max_score and max_score > 0:
            percent = (obtained / max_score) * 100.0

        assignment_results.append({
            'assignment': a,
            'score': obtained,
            'max_score': max_score,
            'percent': percent,
            'submitted_at': submitted_at,
            'submission': sub,
            'grade_letter': grade_letter,
            'pass_fail': pass_fail
        })

    # -----------------------
    # EXAMS (unchanged)
    # -----------------------
    exam_submissions = ExamSubmission.query.filter_by(student_id=user_id).all()
    exam_results = []
    for sub in exam_submissions:
        exam = getattr(sub, 'exam', None)
        max_score = None
        if getattr(sub, 'max_score', None) is not None:
            max_score = float(sub.max_score)
        elif getattr(sub, 'max_possible', None) is not None:
            max_score = float(sub.max_possible)
        elif exam is not None:
            if getattr(exam, 'total_marks', None) is not None:
                max_score = float(exam.total_marks)
            elif getattr(exam, 'total_questions', None) is not None:
                points_each = float(getattr(exam, 'points_per_question', 1) or 1)
                max_score = float(exam.total_questions) * points_each

        obtained = float(sub.score) if getattr(sub, 'score', None) is not None else None
        percent = None
        if obtained is not None and max_score and max_score > 0:
            percent = (obtained / max_score) * 100.0

        exam_results.append({
            'exam': exam,
            'score': obtained,
            'max_score': max_score,
            'percent': percent,
            'set_name': getattr(getattr(sub, 'exam_set', None), 'name', None),
            'submitted_at': getattr(sub, 'submitted_at', None),
            'raw_submission': sub
        })

    return render_template(
        "vclass/results.html",       # or the template file you actually use for student results
        quiz_results=quiz_results,
        assignment_results=assignment_results,
        exam_results=exam_results
    )

@vclass_bp.route('/calculator')
@login_required
def calculator():
    # vclass is for students only — still check role if you want:
    if getattr(current_user, "role", None) != "student":
        abort(403)
    return render_template('vclass/calculator.html')
