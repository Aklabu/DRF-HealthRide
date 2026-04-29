from django.core.mail import send_mail
from django.conf import settings


# Send OTP email to provider
def send_otp_email(email, otp_code, purpose):
    purpose_labels = {
        'signup': 'Sign Up',
        'login': 'Login',
        'forgot_password': 'Password Reset',
    }
    label = purpose_labels.get(purpose, 'Verification')

    subject = f'Health Ride — Your {label} OTP'
    message = (
        f'Your OTP for {label} is: {otp_code}\n\n'
        f'This code expires in 10 minutes.\n'
        f'Do not share this code with anyone.'
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


# Send welcome email after signup completion
def send_welcome_email(email, business_name):
    subject = 'Welcome to Health Ride NEMT'
    message = (
        f'Hello {business_name},\n\n'
        f'Your account has been successfully created.\n'
        f'You can now log in to your provider dashboard.\n\n'
        f'Thank you for choosing Health Ride NEMT.'
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )