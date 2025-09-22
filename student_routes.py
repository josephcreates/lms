from flask import Blueprint, current_app, render_template, abort, redirect, url_for, flash, jsonify, session, send_from_directory, send_file, make_response
import json, os
from flask import request
from flask_login import login_required, current_user, login_user
from sqlalchemy import func
from werkzeug.utils import safe_join, secure_filename
from models import db, User, Quiz, StudentQuizSubmission, Question, StudentProfile, QuizAttempt, Assignment, CourseMaterial, StudentCourseRegistration, Course,  TimetableEntry, AcademicCalendar, AcademicYear, AppointmentSlot, AppointmentBooking, StudentFeeBalance, ClassFeeStructure, StudentFeeTransaction, Exam, ExamSubmission, ExamQuestion, ExamAttempt, ExamSet, ExamSetQuestion, Notification, NotificationRecipient, Meeting, StudentAnswer
from datetime import datetime
from forms import CourseRegistrationForm, ChangePasswordForm, StudentLoginForm
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import io


student_bp = Blueprint('student', __name__, url_prefix='/student')

@student_bp.route('/login', methods=['GET', 'POST'])
def student_login():
    form = StudentLoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user_id = form.user_id.data.strip()
        password = form.password.data.strip()

        user = User.query.filter_by(user_id=user_id, role='student').first()
        if user and user.username.lower() == username.lower() and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.first_name}!", "success")
            return redirect(url_for('student.dashboard'))
        flash("Invalid student credentials.", "danger")

    return render_template('student/login.html', form=form)

@student_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'student':
        abort(403)
    return render_template('student/dashboard.html', user=current_user)


@student_bp.app_context_processor
def inject_notification_count():
    unread_count = 0
    if current_user.is_authenticated:
        from models import NotificationRecipient

        if hasattr(current_user, "user_id"):  
            # Regular User (student, teacher, parent)
            unread_count = NotificationRecipient.query.filter_by(
                user_id=current_user.user_id,
                is_read=False
            ).count()

        elif hasattr(current_user, "admin_id"):  
            # Admin → get all unread notifications
            unread_count = NotificationRecipient.query.filter_by(is_read=False).count()

    return dict(unread_count=unread_count)

from datetime import timedelta


@student_bp.route('/courses', methods=['GET', 'POST'])
@login_required
def register_courses():
    form = CourseRegistrationForm()
    student = current_user
    now = datetime.utcnow()
    start, registration_deadline = Course.get_registration_window()

    profile = StudentProfile.query.filter_by(user_id=student.user_id).first()
    if not profile:
        flash("Student profile not found.", "danger")
        return redirect(url_for("student.dashboard"))

    class_name = profile.current_class

    # Get all distinct academic years
    years = db.session.query(Course.academic_year).distinct().order_by(Course.academic_year).all()
    if not years:
        flash("No academic years available yet. Contact admin.", "warning")
        return redirect(url_for("student.dashboard"))

    form.academic_year.choices = [(y[0], y[0]) for y in years]

    # Determine current step
    step = request.form.get("step")
    selected_sem = request.form.get("semester") or form.semester.data or 'First'
    selected_year = request.form.get("academic_year") or form.academic_year.data or years[-1][0]

    form.semester.data = selected_sem
    form.academic_year.data = selected_year

    # Fetch relevant courses
    courses = Course.query.filter_by(
        assigned_class=class_name,
        semester=selected_sem,
        academic_year=selected_year
    ).all()

    mandatory_courses = [c for c in courses if c.is_mandatory]
    optional_courses = [c for c in courses if not c.is_mandatory]
    form.courses.choices = [(c.id, f"{c.code} - {c.name}") for c in optional_courses]

    registered = StudentCourseRegistration.query.filter_by(
        student_id=student.id,
        semester=selected_sem,
        academic_year=selected_year
    ).all()
    form.courses.data = [r.course_id for r in registered if not r.course.is_mandatory]

    # === Block registration if deadline passed ===
    deadline_passed = registration_deadline and now > registration_deadline

    # Handle final registration submission
    if request.method == "POST" and step == "register_courses" and form.validate_on_submit():
        if deadline_passed:
            flash("Registration deadline has passed. You cannot register or update courses.", "danger")
            return redirect(url_for("student.register_courses"))

        selected_ids = set(map(int, request.form.getlist('courses[]')))
        mandatory_ids = {c.id for c in mandatory_courses}
        final_course_ids = selected_ids | mandatory_ids

        StudentCourseRegistration.query.filter_by(
            student_id=student.id,
            semester=selected_sem,
            academic_year=selected_year
        ).delete()
        db.session.commit()

        for cid in final_course_ids:
            db.session.add(StudentCourseRegistration(
                student_id=student.id,
                course_id=cid,
                semester=selected_sem,
                academic_year=selected_year
            ))
        db.session.commit()

        flash("Courses registered successfully!", "success")
        return redirect(url_for("student.register_courses"))

    show_courses = (step == "select_semester") or len(registered) > 0

    return render_template(
        'student/courses.html',
        form=form,
        mandatory_courses=mandatory_courses,
        optional_courses=optional_courses,
        registered_courses=registered,
        show_courses=show_courses,
        registration_deadline=registration_deadline,
        deadline_passed=deadline_passed
    )

@student_bp.route('/courses/reset', methods=['POST'])
@login_required
def reset_registration():
    student = current_user

    semester = request.form.get("semester")
    year = request.form.get("academic_year")

    if not semester or not year:
        flash("Semester or Academic Year missing for reset.", "danger")
        return redirect(url_for("student.register_courses"))

    # Delete the current registration
    StudentCourseRegistration.query.filter_by(
        student_id=student.id,
        semester=semester,
        academic_year=year
    ).delete()
    db.session.commit()

    flash("Course registration has been reset. You may register again.", "info")
    return redirect(url_for("student.register_courses"))

@student_bp.route('/my_results')
@login_required
def my_results():
    user_id = current_user.id

    # --- QUIZ RESULTS ---
    quiz_results = StudentQuizSubmission.query.filter_by(student_id=user_id).order_by(StudentQuizSubmission.submitted_at.asc()).all()

    # Build chart data: label = date (short), score = numeric (assume percent)
    quiz_chart_data = []
    quiz_subjects = set()
    for q in quiz_results:
        label = q.submitted_at.strftime('%d %b %Y') if q.submitted_at else 'Unknown'
        # ensure numeric score if possible, else None
        try:
            score = float(q.score) if q.score is not None else None
        except Exception:
            score = None
        quiz_chart_data.append({'label': label, 'score': score if score is not None else 0})
        if getattr(q.quiz, 'subject', None):
            quiz_subjects.add(q.quiz.subject)

    # aggregates
    numeric_scores = [float(q.score) for q in quiz_results if q.score is not None]
    avg_quiz_score = round(sum(numeric_scores) / len(numeric_scores), 2) if numeric_scores else 0
    quizzes_taken = len(quiz_results)
    highest_quiz = None
    lowest_quiz = None
    last_quiz_date = None
    if numeric_scores:
        highest_idx = max(range(len(quiz_results)), key=lambda i: (quiz_results[i].score or 0))
        lowest_idx = min(range(len(quiz_results)), key=lambda i: (quiz_results[i].score or 0))
        highest_quiz = f"{quiz_results[highest_idx].quiz.title} ({quiz_results[highest_idx].score}%)"
        lowest_quiz = f"{quiz_results[lowest_idx].quiz.title} ({quiz_results[lowest_idx].score}%)"
        last_quiz_date = quiz_results[-1].submitted_at.strftime('%d %b %Y') if quiz_results[-1].submitted_at else None

    # --- ASSIGNMENTS ---
    # Determine student's classes
    registrations = StudentCourseRegistration.query.filter_by(student_id=user_id).all()
    class_names = [reg.course.name for reg in registrations if getattr(reg, 'course', None)]
    # load assignments for those classes
    assignments = Assignment.query.filter(Assignment.assigned_class.in_(class_names)).order_by(Assignment.due_date.asc()).all() if class_names else []

    # assignments pending count
    today = datetime.utcnow().date()
    assignments_pending = sum(1 for a in assignments if a.due_date and a.due_date.date() >= today)

    # --- EXAMS ---
    exam_submissions = ExamSubmission.query.filter_by(student_id=user_id).order_by(ExamSubmission.submitted_at.desc()).all()
    exams_total = len(exam_submissions)
    exams_graded = sum(1 for e in exam_submissions if e.score is not None)
    exams_passed = sum(1 for e in exam_submissions if (e.score is not None and e.max_score and e.score >= (e.max_score * 0.5)))

    # Build exam_results list of dicts (template expects e.exam, set_name, score, max_score, submitted_at)
    exam_results = []
    for sub in exam_submissions:
        exam_obj = getattr(sub, 'exam', None)
        set_name = getattr(sub, 'exam_set', None)
        exam_results.append({
            "exam": exam_obj,
            "score": sub.score,
            "max_score": float(sub.max_score or 0),
            "set_name": set_name.name if set_name else None,
            "submitted_at": sub.submitted_at
        })

    return render_template(
        "student/results.html",
        quiz_results=quiz_results,
        quiz_chart_data=quiz_chart_data,
        quiz_subjects=sorted(quiz_subjects),
        avg_quiz_score=avg_quiz_score,
        quizzes_taken=quizzes_taken,
        highest_quiz=highest_quiz,
        lowest_quiz=lowest_quiz,
        last_quiz_date=last_quiz_date,
        assignments=assignments,
        assignments_pending=assignments_pending,
        exam_results=exam_results,
        exams_total=exams_total,
        exams_graded=exams_graded,
        exams_passed=exams_passed,
        now=today
    )

@student_bp.route('/download_registered_courses_pdf')
@login_required
def download_registered_courses_pdf():
    student = current_user
    semester = request.args.get('semester')
    academic_year = request.args.get('academic_year')

    if not semester or not academic_year:
        abort(400, "Missing semester or academic year")

    # Fetch all registrations for student for that semester and year
    registrations = StudentCourseRegistration.query \
        .filter_by(
            student_id=student.id,
            semester=semester,
            academic_year=academic_year
        ) \
        .options(joinedload(StudentCourseRegistration.course)) \
        .all()

    if not registrations:
        abort(404, description="No registered courses found.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=60, bottomMargin=40)
    elements = []

    styles = getSampleStyleSheet()
    styleH = styles['Heading1']
    styleN = styles['Normal']

    # Title
    elements.append(Paragraph("Course Registration Summary", styleH))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Student Name: {student.full_name}", styleN))
    elements.append(Paragraph(f"Academic Year: {academic_year}", styleN))
    elements.append(Paragraph(f"Semester: {semester}", styleN))
    elements.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", styleN))
    elements.append(Spacer(1, 24))

    # Table content
    data = [["Course Code", "Course Name", "Type"]]

    for reg in registrations:
        course = reg.course
        course_type = "Mandatory" if course.is_mandatory else "Optional"
        data.append([course.code, course.name, course_type])

    table = Table(data, colWidths=[100, 300, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#004085")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ]))

    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Course_Registration_{academic_year}_{semester}.pdf'
    return response

from time import time as current_time  # rename to avoid collision with datetime.time

@student_bp.route('/timetable')
@login_required
def view_timetable():
    if current_user.role != 'student':
        abort(403)

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    entries = (
        TimetableEntry.query
        .filter_by(assigned_class=profile.current_class)
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time)
        .all()
    )

    return render_template(
        'vclass/timetable.html',
        timetable_entries=entries,
        student_class=profile.current_class,
        download_ts=current_time()  # 👈 pass timestamp here
    )

@student_bp.route('/download_timetable')
@login_required
def download_timetable():
    student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not student_profile:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('student.view_timetable'))

    student_class = student_profile.current_class

    timetable_entries = TimetableEntry.query \
        .filter_by(assigned_class=student_class) \
        .join(Course, TimetableEntry.course_id == Course.id) \
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time) \
        .all()

    if not timetable_entries:
        flash('No timetable available to download.', 'warning')
        return redirect(url_for('student.view_timetable'))

    # Prepare time slots and structure
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    slots = sorted(set(entry.start_time for entry in timetable_entries))

    # Create a 2D matrix: rows=days, columns=time slots
    timetable_matrix = []
    header = ['Day / Time']
    for time in slots:
        # Find one matching end time (should be the same for same start_time)
        end_time = next(
            (entry.end_time for entry in timetable_entries if entry.start_time == time),
            None
        )
        time_range = f"{time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}" if end_time else "Unknown"
        header.append(time_range)

    for day in days:
        row = [day]
        for slot in slots:
            match = next((e for e in timetable_entries if e.day_of_week == day and e.start_time == slot), None)
            if match:
                row.append(f"{match.course.name}")
            else:
                row.append("—")
        timetable_matrix.append(row)

    data = [header] + timetable_matrix

    # PDF Generation
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2.0, height - 40, f"Class Timetable: {student_class}")

    table = Table(data, repeatRows=1, colWidths=None)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)
    ]))

    table_width, table_height = table.wrap(0, 0)
    table.drawOn(c, inch / 2, height - 80 - table_height)

    c.showPage()
    c.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{student_class}_timetable.pdf",
        mimetype='application/pdf'
    )

# Appointment Booking System
from collections import defaultdict

@student_bp.route('/book-appointment', methods=['GET', 'POST'])
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
            return redirect(url_for('student.book_appointment'))

        student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
        if not student_profile:
            flash('Student profile not found.', 'danger')
            return redirect(url_for('student.book_appointment'))

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
        return redirect(url_for('student.my_appointments'))

    return render_template('student/book_appointment.html', slots=slots)

from sqlalchemy.orm import joinedload

@student_bp.route('/my-appointments')
@login_required
def my_appointments():
    student_profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    if not student_profile:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('student.book_appointment'))

    bookings = AppointmentBooking.query \
        .filter_by(student_id=student_profile.id) \
        .options(joinedload(AppointmentBooking.slot).joinedload(AppointmentSlot.teacher)) \
        .all()

    return render_template('student/my_appointments.html', bookings=bookings)

# Fees Management
@student_bp.route('/fees')
@login_required
def student_fees():
    # Restrict to students
    if current_user.role != 'student':
        abort(403)

    fees = StudentFeeBalance.query.filter_by(
        student_id=current_user.id
    ).order_by(StudentFeeBalance.id.desc()).all()

    transactions = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id
    ).order_by(StudentFeeTransaction.timestamp.desc()).all()

    return render_template(
        'student/fees.html',
        fees=fees,
        transactions=transactions
    )

@student_bp.route('/pay-fees')
@login_required
def pay_fees():
    if current_user.role != 'student':
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.index'))

    # Get selected year and semester from query parameters
    year = request.args.get('year')
    semester = request.args.get('semester')

    # Render empty view if filters are missing
    if not year or not semester:
        flash("Please select an academic year and semester.", "warning")
        return render_template(
            'student/pay_fees.html',
            assigned_fees=[],
            total_fee=0,
            current_balance=0,
            pending_balance=0,
            transactions=[],
            year=year,
            semester=semester
        )

    student_class = current_user.student_profile.current_class

    # Fetch assigned fees for class/year/semester
    assigned_fees = ClassFeeStructure.query.filter_by(
        class_level=student_class,
        academic_year=year,
        semester=semester
    ).all()
    total_fee = sum(fee.amount for fee in assigned_fees)

    # Approved payments
    approved_txns = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id,
        academic_year=year,
        semester=semester,
        is_approved=True
    ).all()
    current_balance = sum(txn.amount for txn in approved_txns)

    # Pending payments
    pending_txns = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id,
        academic_year=year,
        semester=semester,
        is_approved=False
    ).all()
    pending_balance = sum(txn.amount for txn in pending_txns)

    # All transactions
    transactions = StudentFeeTransaction.query.filter_by(
        student_id=current_user.id,
        academic_year=year,
        semester=semester
    ).order_by(StudentFeeTransaction.timestamp.desc()).all()

    return render_template(
        'student/pay_fees.html',
        assigned_fees=assigned_fees,
        total_fee=total_fee,
        current_balance=current_balance,
        pending_balance=pending_balance,
        transactions=transactions,
        year=year,
        semester=semester
    )

@student_bp.route('/download-receipt/<int:txn_id>')
@login_required
def download_receipt(txn_id):
    txn = StudentFeeTransaction.query.get_or_404(txn_id)
    if txn.student_id != current_user.id or not txn.is_approved:
        abort(403)

    filename = f"receipt_{txn.id}.pdf"
    filepath = os.path.join(current_app.config['RECEIPT_FOLDER'], filename)

    if not os.path.exists(filepath):
        flash("Receipt not found. Please contact admin.", "danger")
        return redirect(url_for('student.pay_fees', year=txn.academic_year, semester=txn.semester))

    return send_file(filepath, as_attachment=True)


@student_bp.route('/profile')
@login_required
def profile():
    if not current_user.is_student:
        abort(403)

    profile = StudentProfile.query.filter_by(user_id=current_user.user_id).first()
    return render_template('student/profile.html', profile=profile, user=current_user)

@student_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if current_user.check_password(form.current_password.data):
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash('Password updated successfully!', 'success')
            return redirect(url_for('student.profile'))
        else:
            flash('Current password is incorrect.', 'danger')
    return render_template('student/change_password.html', form=form)

@student_bp.route('/notifications')
@login_required
def student_notifications():
    """
    Show the user's NotificationRecipient rows, joined to Notification.
    Order by Notification.created_at descending.
    """
    notifications = (
        NotificationRecipient.query
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .filter(NotificationRecipient.user_id == current_user.user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template('student/notifications.html', notifications=notifications)


@student_bp.route('/notifications/view/<int:recipient_id>')
@login_required
def view_notification(recipient_id):
    recipient = NotificationRecipient.query.filter_by(
        id=recipient_id, user_id=current_user.user_id
    ).join(Notification, Notification.id == NotificationRecipient.notification_id).first_or_404()

    # automatically mark as read if not already
    if not recipient.is_read:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()
        db.session.commit()

    return render_template('student/notification_detail.html', recipient=recipient)


@student_bp.route('/notifications/mark_read/<int:recipient_id>', methods=['POST'])
@login_required
def mark_notification_read(recipient_id):
    recipient = NotificationRecipient.query.filter_by(
        id=recipient_id, user_id=current_user.user_id
    ).first_or_404()

    if not recipient.is_read:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify({"success": True, "id": recipient_id})

