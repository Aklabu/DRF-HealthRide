import random
import string
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.conf import settings


# Generate readable 8-char password — exclude ambiguous chars 0, O, 1, l, I
def generate_driver_password():
    safe_chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(safe_chars, k=8))


# Hash the plain password before storing
def hash_password(plain_password):
    return make_password(plain_password)


# Send welcome email to driver with login credentials
def send_driver_welcome_email(email, full_name, plain_password, login_url=''):
    subject = 'Welcome to Health Ride NEMT — Your Driver Account'
    message = (
        f'Hello {full_name},\n\n'
        f'Your driver account has been created.\n\n'
        f'Login credentials:\n'
        f'  Email:    {email}\n'
        f'  Password: {plain_password}\n\n'
        f'Please log in and change your password after your first login.\n'
        f'Login URL: {login_url or "Contact your provider for the login link."}\n\n'
        f'Thank you,\n'
        f'Health Ride NEMT Team'
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )