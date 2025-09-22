from flask import Blueprint, render_template, abort, flash, redirect, url_for, request, jsonify, current_app
from flask_login import login_required, current_user, login_user
from models import Meeting, db, TeacherProfile, Course, StudentCourseRegistration, TeacherCourseAssignment, AttendanceRecord, User, StudentProfile, AcademicCalendar, AcademicYear, AppointmentBooking, AppointmentSlot, Assignment, SchoolClass, Quiz, StudentQuizSubmission, Exam, ExamSubmission, AssignmentSubmission, GradingScale
from forms import AssignmentForm, ChangePasswordForm, TeacherLoginForm
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
from sqlalchemy import and_, desc, func
from sqlalchemy.orm import joinedload
from collections import defaultdict
from utils.notifications import create_assignment_notification
import os, uuid

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")

@teacher_bp.route('/login', methods=['GET', 'POST'])
def teacher_login():
    form = TeacherLoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user_id = form.user_id.data.strip()
        password = form.password.data.strip()

        user = User.query.filter_by(user_id=user_id, role='teacher').first()
        if user and user.username.lower() == username.lower() and user.check_password(password):
            login_user(user)
            flash(f"Welcome back, {user.first_name}!", "success")
            return redirect(url_for('teacher.dashboard'))  # adjust dashboard endpoint
        flash("Invalid teacher credentials.", "danger")

    return render_template('teacher/login.html', form=form)

@teacher_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'teacher':
        abort(403)
    return render_template('teacher/dashboard.html', user=current_user)


@teacher_bp.route('/classes', methods=['GET', 'POST'])
@login_required
def classes():
    if current_user.role != 'teacher':
        abort(403)

    # 1) Ensure the teacher has a profile
    profile = TeacherProfile.query.filter_by(user_id=current_user.user_id).first()
    if not profile:
        flash("Please complete your profile before registering courses.", "warning")
        return redirect(url_for('teacher.dashboard'))

    # 2) All courses in the system
    all_courses = Course.query.order_by(Course.assigned_class, Course.name).all()

    # 3) Which ones this teacher has already signed up for?
    assigned = { a.course_id for a in profile.assignments }

    # 4) Handle form submission (register / unregister)
    if request.method == 'POST':
        selected = set(map(int, request.form.getlist('courses')))
        
        # 4a) Remove any deselected assignments
        for a in profile.assignments[:]:
            if a.course_id not in selected:
                db.session.delete(a)
        
        # 4b) Add any newly selected ones
        for cid in selected - assigned:
            db.session.add(TeacherCourseAssignment(
                teacher_id=profile.id,
                course_id=cid
            ))

        db.session.commit()
        flash("Your course selections have been updated.", "success")
        return redirect(url_for('teacher.classes'))

    # 5) Build display data
    display = []
    for c in all_courses:
        display.append({
            'id':        c.id,
            'class':     c.assigned_class,
            'name':      c.name,
            'registered': (c.id in assigned)
        })

    return render_template('teacher/classes.html',
                           courses=display)

@teacher_bp.route('/class/<int:course_id>')
@login_required
def view_class(course_id):
    if current_user.role != 'teacher':
        abort(403)

    course = Course.query.get_or_404(course_id)
    registrations = StudentCourseRegistration.query.filter_by(course_id=course_id).all()

    return render_template('teacher/class_detail.html', course=course, registrations=registrations)

@teacher_bp.route('/manage-assignments')
@login_required
def manage_assignments():
    assignments = Assignment.query.order_by(Assignment.due_date.asc()).all()
    return render_template('teacher/manage_assignments.html', assignments=assignments)

@teacher_bp.route('/assignments/add', methods=['GET', 'POST'])
@login_required
def add_assignment():
    if not current_user.role == "teacher":
        abort(403)

    form = AssignmentForm()
    if form.validate_on_submit():
        # Save uploaded file
        file = form.file.data
        filename, original_name = None, None
        if file:
            original_name = file.filename
            filename = secure_filename(original_name)
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        # Create assignment
        assignment = Assignment(
            title=form.title.data,
            description=form.description.data,
            instructions=form.instructions.data,
            course_name=form.course_name.data,
            assigned_class=form.assigned_class.data,
            due_date=form.due_date.data,
            filename=filename,
            original_name=original_name,
            max_score=form.max_score.data
        )
        db.session.add(assignment)
        db.session.commit()

        # 🔔 Create notification (same as admin)
        create_assignment_notification(assignment)

        # Handle AJAX requests
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=True)

        flash('Assignment added successfully.', 'success')
        return redirect(url_for('teacher.manage_assignments'))

    # Return AJAX errors if form validation failed
    if request.method == "POST" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(success=False, errors=form.errors)

    return render_template("teacher/add_assignment.html", form=form)

@teacher_bp.route('/assignments/edit/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def edit_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    form = AssignmentForm(obj=assignment)

    if form.validate_on_submit():
        assignment.title = form.title.data
        assignment.description = form.description.data
        assignment.instructions = form.instructions.data
        assignment.course_name = form.course_name.data
        assignment.assigned_class = form.assigned_class.data
        assignment.due_date = form.due_date.data

        file = form.file.data
        if file:
            original_name = file.filename
            filename = secure_filename(original_name)
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            assignment.filename = filename
            assignment.original_name = original_name

        db.session.commit()
        flash('Assignment updated successfully.', 'success')
        return redirect(url_for('teacher.manage_assignments'))

    return render_template('teacher/edit_assignment.html', form=form, assignment=assignment)

@teacher_bp.route('/assignments/delete/<int:assignment_id>', methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)

    # Delete uploaded file if exists
    if assignment.filename:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], assignment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    db.session.delete(assignment)
    db.session.commit()
    flash('Assignment deleted successfully.', 'success')
    return redirect(url_for('teacher.manage_assignments'))

@teacher_bp.route('/submissions')
@login_required
def submissions_index():
    if current_user.role != 'teacher':
        abort(403)

    assignments = Assignment.query.order_by(Assignment.course_name, Assignment.due_date.desc()).all()
    grouped = defaultdict(list)
    for a in assignments:
        grouped[a.course_name or 'General'].append(a)
    grouped = dict(grouped)

    # force the teacher base template explicitly
    return render_template('teacher/submissions_index.html', grouped=grouped, layout='teacher/base_teacher.html')

@teacher_bp.route('/assignment/<int:assignment_id>/submissions')
@login_required
def view_submissions(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment_id).all()
    return render_template(
        "teacher/assignment_submissions.html",
        assignment=assignment,
        submissions=submissions
    )

@teacher_bp.route('/submission/<int:submission_id>/score', methods=['GET', 'POST'])
@login_required
def score_submission(submission_id):
    submission = AssignmentSubmission.query.get_or_404(submission_id)

    if request.method == 'POST':
        score = request.form.get("score")
        feedback = request.form.get("feedback")

        submission.score = float(score) if score else None
        submission.feedback = feedback
        submission.scored_at = datetime.utcnow()

        # Automatically assign grade if grading scale exists
        scales = GradingScale.query.order_by(GradingScale.min_score.desc()).all()
        for scale in scales:
            if submission.score is not None and scale.min_score <= submission.score <= scale.max_score:
                submission.grade_letter = scale.grade_letter
                submission.pass_fail = scale.pass_fail
                break

        db.session.commit()
        flash("Score saved successfully.", "success")
        return redirect(url_for('teacher.view_submissions', assignment_id=submission.assignment_id))

    return render_template("teacher/score_submission.html", submission=submission)

@teacher_bp.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    if current_user.role != 'teacher':
        abort(403)

    # 1️⃣ Teacher & their classes
    teacher = TeacherProfile.query.filter_by(user_id=current_user.user_id).first_or_404()
    classes = sorted({a.course.assigned_class for a in teacher.assignments})

    # 2️⃣ Pull filters
    selected_class = request.values.get('classSelect', '')
    date_str       = request.values.get('date', '')
    today          = datetime.utcnow().date()
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else today
    except ValueError:
        selected_date = today

    # 3️⃣ Students in that class
    students = []
    if selected_class:
        students = (
            User.query
                .join(StudentProfile, StudentProfile.user_id == User.user_id)
                .filter(StudentProfile.current_class == selected_class)
                .order_by(User.last_name)
                .all()
        )

    # 4️⃣ Already‐recorded student IDs on that date
    existing_records = {
        r.student_id
        for r in AttendanceRecord.query.filter(
            and_(
                AttendanceRecord.teacher_id == teacher.id,
                AttendanceRecord.date == selected_date
            )
        )
    }

    # 5️⃣ AcademicCalendar: fetch all break entries
    #    assume AcademicCalendar has `date` (Date) and `break_type` (str)
    cal_entries = AcademicCalendar.query.with_entities(
        AcademicCalendar.date, AcademicCalendar.break_type
    ).all()
    # build dict: "YYYY-MM-DD" -> break_type
    disabled_dates = {
        entry.date.isoformat(): entry.break_type
        for entry in cal_entries
    }

    # 6️⃣ Handle form POST
    if request.method == 'POST' and request.form.get('action') == 'submit_attendance':
        inserted = duplicates = 0
        for student in students:
            if student.id in existing_records:
                duplicates += 1
                continue
            present = bool(request.form.get(f'attend_{student.id}'))
            db.session.add(AttendanceRecord(
                student_id=student.id,
                teacher_id=teacher.id,
                date=selected_date,
                is_present=present
            ))
            inserted += 1
        db.session.commit()

        if inserted:
            flash(f"{inserted} new record(s) saved.", "success")
        if duplicates:
            flash(f"{duplicates} student(s) already marked and skipped.", "warning")

        return redirect(url_for('teacher.attendance',
                                classSelect=selected_class,
                                date=selected_date.isoformat()))

    return render_template(
        'teacher/attendance.html',
        classes=classes,
        students=students,
        existing_records=existing_records,
        selected_class=selected_class,
        selected_date=selected_date,
        disabled_dates=disabled_dates
    )

from flask import render_template, request, abort
from flask_login import login_required, current_user
from collections import defaultdict
from models import db, User, StudentProfile, TeacherProfile, AttendanceRecord

@teacher_bp.route('/view-attendance')
@login_required
def view_attendance():
    if current_user.role != 'teacher':
        abort(403)

    teacher = TeacherProfile.query.filter_by(user_id=current_user.user_id).first_or_404()
    selected_class = request.args.get('classSelect', '', type=str)
    selected_date_str = request.args.get('date', '', type=str)
    selected_date = None
    if selected_date_str:
        try:
            selected_date = datetime.fromisoformat(selected_date_str).date()
        except ValueError:
            selected_date = None

    # 1. Get all distinct dates for the selected class
    date_query = db.session.query(AttendanceRecord.date).filter(AttendanceRecord.teacher_id == teacher.id)
    if selected_class:
        date_query = date_query.join(User, User.id == AttendanceRecord.student_id) \
                               .join(StudentProfile, StudentProfile.user_id == User.user_id) \
                               .filter(StudentProfile.current_class == selected_class)
    date_list = [d[0] for d in date_query.distinct().order_by(AttendanceRecord.date).all()]

    # 2. Get students for the selected class
    student_query = db.session.query(User.id, User.first_name, User.middle_name, User.last_name, StudentProfile.current_class) \
        .join(StudentProfile, StudentProfile.user_id == User.user_id) \
        .join(AttendanceRecord, AttendanceRecord.student_id == User.id) \
        .filter(AttendanceRecord.teacher_id == teacher.id)
    if selected_class:
        student_query = student_query.filter(StudentProfile.current_class == selected_class)
    students = student_query.distinct().order_by(User.last_name, User.first_name).all()

    # 3. Get attendance records filtered by date and/or class
    attendance_query = db.session.query(AttendanceRecord.student_id, AttendanceRecord.date, AttendanceRecord.is_present) \
        .filter(AttendanceRecord.teacher_id == teacher.id)
    if selected_class:
        attendance_query = attendance_query.join(User, User.id == AttendanceRecord.student_id) \
                                           .join(StudentProfile, StudentProfile.user_id == User.user_id) \
                                           .filter(StudentProfile.current_class == selected_class)
    if selected_date:
        attendance_query = attendance_query.filter(AttendanceRecord.date == selected_date)
    attendance_records = attendance_query.all()

    # 4. Attendance map for Excel-style table
    attendance_map = defaultdict(lambda: 0)
    for student_id, date, is_present in attendance_records:
        attendance_map[(student_id, date)] = 1 if is_present else 0

    # 5. Records list for standard table
    records_query = db.session.query(AttendanceRecord.date, StudentProfile.current_class, 
                                     User.first_name, User.middle_name, User.last_name, AttendanceRecord.is_present) \
        .join(User, User.id == AttendanceRecord.student_id) \
        .join(StudentProfile, StudentProfile.user_id == User.user_id) \
        .filter(AttendanceRecord.teacher_id == teacher.id)
    if selected_class:
        records_query = records_query.filter(StudentProfile.current_class == selected_class)
    if selected_date:
        records_query = records_query.filter(AttendanceRecord.date == selected_date)
    records_query = records_query.order_by(AttendanceRecord.date)
    formatted_records = [{
        'date': r.date,
        'current_class': r.current_class,
        'full_name': " ".join(filter(None, [r.first_name, r.middle_name, r.last_name])),
        'is_present': r.is_present
    } for r in records_query.all()]

    # 6. Class list for filter
    class_options = db.session.query(StudentProfile.current_class) \
        .join(User, User.user_id == StudentProfile.user_id) \
        .join(AttendanceRecord, AttendanceRecord.student_id == User.id) \
        .filter(AttendanceRecord.teacher_id == teacher.id) \
        .distinct().order_by(StudentProfile.current_class).all()
    class_list = [c[0] for c in class_options]

    # 7. Student list for Excel view
    student_list = [{
        'id': s.id,
        'full_name': " ".join(filter(None, [s.first_name, s.middle_name, s.last_name])),
        'current_class': s.current_class
    } for s in students]

    return render_template(
        'teacher/view_attendance.html',
        students=student_list,
        dates=date_list,
        attendance_map=attendance_map,
        classes=class_list,
        selected_class=selected_class,
        selected_date=selected_date,
        records=formatted_records
    )

@teacher_bp.route('/calendar')
@login_required
def calendar():
    if current_user.role != 'teacher':
        abort(403)

    # Academic Events
    events = AcademicCalendar.query.order_by(AcademicCalendar.date).all()
    color_map = {
        'Vacation': '#e67e22',
        'Midterm': '#9b59b6',
        'Exam': '#2980b9',
        'Holiday': '#c0392b',
        'Other': '#95a5a6'
    }

    cal_events = [
        {
            'id': e.id,
            'title': e.label,
            'start': e.date.isoformat(),
            'color': color_map.get(e.break_type, '#7f8c8d'),
            'backgroundColor': '#28a745' if e.is_workday else '#dc3545',
            'display': 'auto'
        }
        for e in events
    ]

    # Semester background ranges (visual highlight)
    academic_year = AcademicYear.query.first()
    if academic_year:
        cal_events.append({
            'start': academic_year.semester_1_start.isoformat(),
            'end': (academic_year.semester_1_end + timedelta(days=1)).isoformat(),
            'display': 'background',
            'color': '#d1e7dd',
            'title': 'Semester 1'
        })
        cal_events.append({
            'start': academic_year.semester_2_start.isoformat(),
            'end': (academic_year.semester_2_end + timedelta(days=1)).isoformat(),
            'display': 'background',
            'color': '#f8d7da',
            'title': 'Semester 2'
        })

    return render_template('teacher/calendar.html', cal_events=cal_events)

# Appointments Management
@teacher_bp.route('/appointment-slots', methods=['GET', 'POST'])
@login_required
def manage_slots():
    teacher = TeacherProfile.query.filter_by(user_id=current_user.user_id).first_or_404()

    # Delete expired slots (where end datetime is in the past)
    now = datetime.now()
    expired_slots = AppointmentSlot.query.filter(
        AppointmentSlot.teacher_id == teacher.id,
        db.func.datetime(AppointmentSlot.date, AppointmentSlot.end_time) < now,
        AppointmentSlot.is_booked == False  # Optional: only delete unbooked
    ).all()

    for slot in expired_slots:
        db.session.delete(slot)
    db.session.commit()

    if request.method == 'POST':
        date = request.form['date']
        start = request.form['start_time']
        end = request.form['end_time']
        slot = AppointmentSlot(
            teacher_id=teacher.id,
            date=datetime.strptime(date, '%Y-%m-%d').date(),
            start_time=datetime.strptime(start, '%H:%M').time(),
            end_time=datetime.strptime(end, '%H:%M').time()
        )
        db.session.add(slot)
        db.session.commit()
        flash('Slot added.')
        return redirect(url_for('teacher.manage_slots'))

    slots = AppointmentSlot.query.filter_by(teacher_id=teacher.id).all()
    return render_template('teacher/appointment_slots.html', slots=slots)

@teacher_bp.route('/appointment-requests')
@login_required
def appointment_requests():
    teacher = TeacherProfile.query.filter_by(user_id=current_user.user_id).first_or_404()
    slots = AppointmentSlot.query.filter_by(teacher_id=teacher.id).all()
    bookings = AppointmentBooking.query \
        .filter(AppointmentBooking.slot_id.in_([s.id for s in slots])) \
        .options(joinedload(AppointmentBooking.student).joinedload(StudentProfile.user)) \
        .all()
    return render_template('teacher/appointment_requests.html', bookings=bookings)


@teacher_bp.route('/appointment/update-status/<int:booking_id>/<string:status>')
@login_required
def update_booking_status(booking_id, status):
    booking = AppointmentBooking.query.get_or_404(booking_id)
    booking.status = status
    db.session.commit()
    flash(f'Booking marked as {status}')
    return redirect(url_for('teacher.appointment_requests'))

@teacher_bp.route("/slots/delete/<int:slot_id>", methods=["POST"])
@login_required
def delete_slot(slot_id):
    slot = AppointmentSlot.query.get_or_404(slot_id)

    if slot.is_booked:
        flash("Cannot delete a booked slot.", "danger")
    else:
        db.session.delete(slot)
        db.session.commit()
        flash("Slot deleted successfully.", "success")

    return redirect(url_for("teacher.manage_slots"))

# Reports
@teacher_bp.route('/reports')
@login_required
def reports():
    # Fetch classes and academic years
    classes = SchoolClass.query.all()
    years = AcademicYear.query.all()
    
    return render_template('teacher/reports.html', classes=classes, years=years)


# Profile
@teacher_bp.route('/profile')
@login_required
def profile():
    if not current_user.is_teacher:
        abort(403)

    profile = TeacherProfile.query.filter_by(user_id=current_user.user_id).first()
    return render_template('teacher/profile.html', profile=profile)

@teacher_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        # Verify current password
        if current_user.check_password(form.current_password.data):
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash('Password updated successfully!', 'success')
            return redirect(url_for('teacher.profile'))
        else:
            flash('Current password is incorrect.', 'danger')
    return render_template('teacher/change_password.html', form=form)

