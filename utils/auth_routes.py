from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from datetime import datetime, timedelta
from utils.extensions import db
from models import User, PasswordResetRequest, PasswordResetToken
from forms import ForgotPasswordForm, ResetPasswordForm
from utils.email_utils import send_password_reset_email

auth_bp = Blueprint('auth', __name__)


def can_request_password_reset(user, limit=3, period_minutes=60):
    cutoff = datetime.utcnow() - timedelta(minutes=period_minutes)
    recent_requests = PasswordResetRequest.query.filter(
        PasswordResetRequest.user_id == user.user_id,
        PasswordResetRequest.requested_at >= cutoff
    ).count()
    return recent_requests < limit


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
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


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
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
