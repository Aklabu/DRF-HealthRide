# Health Ride NEMT

A backend API for Non-Emergency Medical Transportation (NEMT) providers — built with Django REST Framework.

## Tech Stack

- **Django 6.0.4** + **Django REST Framework**
- **PostgreSQL** — primary database
- **Redis** — cache backend
- **Simple JWT** — authentication
- **Pillow** — image handling

## Project Structure

```
HealthRide/
├── apps/
│   ├── accounts/       # Provider auth, settings, rate cards
│   ├── vehicles/       # Fleet management
│   ├── drivers/        # Driver management
│   ├── passengers/     # Passenger management
│   └── facilities/     # Facility management
├── config/             # Django settings, URLs
├── utils/              # Shared response, exception handler
├── media/
└── manage.py
```

## Apps

| App | Description |
|---|---|
| `accounts` | Provider signup/login (OTP-based), JWT auth, company profile, rate cards |
| `vehicles` | Vehicle fleet, insurance, maintenance, documents, driver assignment |
| `drivers` | Driver profiles, certifications, availability, work logs, payouts |
| `passengers` | Passenger records, medical info, insurance, emergency contacts |
| `facilities` | Facility contracts, pricing, billing contacts, documents |

## Quick Start

**1. Clone and set up environment**
```bash
git clone <repo-url>
cd HealthRide
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
```

**2. Install dependencies**
```bash
pip install django djangorestframework djangorestframework-simplejwt django-environ Pillow redis
```

**3. Configure environment**

Create a `.env` file in the root directory:
```env
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/1
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=noreply@healthride.com
```

**4. Run migrations**
```bash
python manage.py makemigrations
python manage.py migrate
```

**5. Create superuser**
```bash
python manage.py createsuperuser
```

**6. Start server**
```bash
python manage.py runserver
```

API is available at `http://localhost:8000`  
Admin panel at `http://localhost:8000/admin`

## API Overview

All endpoints are prefixed with `/api/`

```
/api/accounts/      Auth, profile, settings
/api/vehicles/      Fleet management
/api/drivers/       Driver management
/api/passengers/    Passenger management
/api/facilities/    Facility management
```

All responses follow a consistent format:
```json
{
    "success": true,
    "statusCode": 200,
    "message": "...",
    "timestamp": "...",
    "data": {},
    "errors": null
}
```

## Authentication

Provider authentication uses a two-step OTP flow:

```
POST /api/accounts/signin/             # Submit email + password → OTP sent
POST /api/accounts/signin/verify-otp/  # Submit OTP → receive JWT tokens
```

Include the access token in all authenticated requests:
```
Authorization: Bearer <access_token>
```

## License

Private — All rights reserved.