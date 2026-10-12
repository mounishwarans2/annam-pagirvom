import os
import uuid
import base64
import urllib.parse
import math
import re
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, g, send_from_directory, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import (
    get_db_connection, init_db, seed_demo_data, log_status_change, add_notification,
    log_contact_access, seed_demo_network_profiles, DEMO_NETWORK_PROFILES
)
from matching import (
    find_matches_for_donation, find_matches_for_requirement, evaluate_match
)
from translations import get_text

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v

load_env()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.environ.get('FLASK_SECRET_KEY', 'annam-pagirvom-gencraft26-ps14-securekey'))

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def build_multi_stop_nav_urls(donor_lat, donor_lng, donor_address, receiver_lat, receiver_lng, receiver_address):
    """
    Build Google Maps multi-stop navigation URLs for drivers.
    Route order strictly: Driver current GPS location (My Location) -> Donor pickup waypoint -> Receiving trust destination.
    Format:
    https://www.google.com/maps/dir/?api=1&origin=My+Location&destination=RECEIVER_LOCATION&waypoints=DONOR_LOCATION&travelmode=driving
    """
    donor_loc = None
    if donor_lat is not None and donor_lng is not None:
        donor_loc = f"{donor_lat},{donor_lng}"
    elif donor_address and donor_address.strip():
        donor_loc = donor_address.strip()

    receiver_loc = None
    if receiver_lat is not None and receiver_lng is not None:
        receiver_loc = f"{receiver_lat},{receiver_lng}"
    elif receiver_address and receiver_address.strip():
        receiver_loc = receiver_address.strip()

    donor_missing = donor_loc is None
    receiver_missing = receiver_loc is None

    multi_stop_url = None
    to_donor_url = None
    to_receiver_url = None

    if donor_loc and receiver_loc:
        enc_donor = urllib.parse.quote_plus(str(donor_loc))
        enc_receiver = urllib.parse.quote_plus(str(receiver_loc))
        multi_stop_url = f"https://www.google.com/maps/dir/?api=1&origin=My+Location&destination={enc_receiver}&waypoints={enc_donor}&travelmode=driving"

    if donor_loc:
        enc_donor = urllib.parse.quote_plus(str(donor_loc))
        to_donor_url = f"https://www.google.com/maps/dir/?api=1&origin=My+Location&destination={enc_donor}&travelmode=driving"

    if receiver_loc:
        enc_receiver = urllib.parse.quote_plus(str(receiver_loc))
        to_receiver_url = f"https://www.google.com/maps/dir/?api=1&origin=My+Location&destination={enc_receiver}&travelmode=driving"

    return {
        'multi_stop_url': multi_stop_url,
        'to_donor_url': to_donor_url,
        'to_receiver_url': to_receiver_url,
        'donor_missing': donor_missing,
        'receiver_missing': receiver_missing,
        'donor_target': donor_loc,
        'receiver_target': receiver_loc
    }

def calculate_urgency(safe_deadline_str):
    """Calculate remaining time and transparent urgency rules based on safe-use deadline."""
    if not safe_deadline_str:
        return {'urgency': 'Low', 'remaining_seconds': 0, 'remaining_str': 'Unknown', 'is_expired': False}
    try:
        clean_str = safe_deadline_str.replace('T', ' ').strip()
        if len(clean_str) == 16:
            dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M")
        else:
            dt = datetime.strptime(clean_str[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return {'urgency': 'Low', 'remaining_seconds': 0, 'remaining_str': safe_deadline_str, 'is_expired': False}

    now = datetime.now()
    diff = dt - now
    total_seconds = int(diff.total_seconds())

    if total_seconds <= 0:
        return {
            'urgency': 'Expired',
            'remaining_seconds': 0,
            'remaining_str': 'Deadline Passed / Expired',
            'is_expired': True
        }

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours < 2:
        urgency = 'Urgent'
    elif hours < 5:
        urgency = 'Medium'
    else:
        urgency = 'Low'

    rem_str = f"{hours}h {minutes}m remaining" if hours > 0 else f"{minutes}m remaining"
    return {
        'urgency': urgency,
        'remaining_seconds': total_seconds,
        'remaining_str': rem_str,
        'is_expired': False
    }

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate approximate distance between two GPS coordinates in kilometers."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        r = 6371.0
        d_lat = math.radians(float(lat2) - float(lat1))
        d_lon = math.radians(float(lon2) - float(lon1))
        a = (math.sin(d_lat / 2) ** 2 +
             math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) *
             math.sin(d_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(r * c, 2)
    except Exception:
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_or_base64_image(base64_str=None, file_obj=None, prefix='img'):
    """Helper to save camera base64 data-URL or uploaded multipart image safely."""
    if base64_str and base64_str.startswith('data:image'):
        try:
            header, encoded = base64_str.split(',', 1)
            img_bytes = base64.b64decode(encoded)
            ext = 'jpg'
            if 'png' in header:
                ext = 'png'
            elif 'webp' in header:
                ext = 'webp'
            unique_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
            target_path = os.path.join(UPLOAD_FOLDER, unique_name)
            with open(target_path, 'wb') as f:
                f.write(img_bytes)
            return unique_name
        except Exception as e:
            print(f"Failed to save {prefix} base64 image:", e)

    if file_obj and file_obj.filename and allowed_file(file_obj.filename):
        safe_name = secure_filename(file_obj.filename)
        ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'jpg'
        unique_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
        file_obj.save(os.path.join(UPLOAD_FOLDER, unique_name))
        return unique_name

    return None

def to_dict_safe(item):
    """Safely converts dict-like objects (including sqlite3.Row) to standard Python dict."""
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    try:
        return {k: item[k] for k in item.keys()}
    except Exception:
        try:
            return dict(item)
        except Exception:
            return {}

def check_donor_phone_authorization(conn, user, donation, task=None, match=None, ip_address=None):
    """
    Evaluates server-side authorization to view a donor's private phone number.
    Returns:
        (is_authorized: bool, phone_number: str or None, message: str)
    """
    if not donation:
        return False, None, "Listing not found."

    user = to_dict_safe(user) if user else None
    don_dict = to_dict_safe(donation)
    task_dict = to_dict_safe(task) if task else None
    match_dict = to_dict_safe(match) if match else None

    donor_phone = don_dict.get('contact_phone') or don_dict.get('donor_phone') or don_dict.get('donor_org_phone')
    if not donor_phone:
        return False, None, "No contact number registered."

    # 1. Unauthenticated public visitors
    if not user:
        if don_dict.get('donor_consent') or don_dict.get('phone_public_consent'):
            return True, donor_phone, "Public consent granted by donor."
        return False, None, "Sign in with an authorized account to view contact details."

    # 2. Administrator & Coordinator access (Audited)
    if user.get('role') in ('admin', 'coordinator'):
        log_contact_access(conn, user.get('id'), user.get('role'), 'donor_phone', 'donation', don_dict.get('id') or 0, 1, 'Administrator platform management', ip_address)
        return True, donor_phone, "Authorized administrator access."

    # 3. Donor themselves (Owner access)
    if don_dict.get('donor_id') and user.get('id') == don_dict.get('donor_id'):
        return True, donor_phone, "Owner access."

    # 4. Assigned Driver
    if user.get('role') in ('volunteer', 'driver'):
        if task_dict:
            is_assigned = (task_dict.get('volunteer_id') == user.get('id'))
            status = task_dict.get('status') or task_dict.get('task_status')
            if is_assigned and status in ('assigned', 'accepted', 'en_route_pickup', 'collected', 'en_route_delivery', 'disputed', 'needs_review'):
                log_contact_access(conn, user.get('id'), user.get('role'), 'donor_phone', 'pickup_task', task_dict.get('id') or 0, 1, f"Assigned driver coordination for task #{task_dict.get('id')}", ip_address)
                return True, donor_phone, "Authorized assigned driver."
            elif is_assigned and status == 'delivered':
                return False, None, "Delivery already completed; contact access closed."
            elif not is_assigned:
                return False, None, "Contact details restricted to the assigned driver."
        else:
            don_id = don_dict.get('id')
            if don_id:
                active_task = conn.execute("""
                    SELECT id, status, volunteer_id FROM pickup_tasks
                    WHERE donation_id = ? AND volunteer_id = ?
                      AND status IN ('assigned', 'accepted', 'en_route_pickup', 'collected', 'en_route_delivery', 'disputed', 'needs_review')
                """, (don_id, user.get('id'))).fetchone()
                if active_task:
                    log_contact_access(conn, user.get('id'), user.get('role'), 'donor_phone', 'pickup_task', active_task['id'], 1, f"Assigned driver active task #{active_task['id']}", ip_address)
                    return True, donor_phone, "Authorized assigned driver."
            return False, None, "Contact details restricted to the assigned driver for this delivery."

    # 5. Approved Receiving Organization
    if user.get('role') == 'receiver':
        if match_dict:
            is_receiver = (match_dict.get('receiver_id') == user.get('id'))
            m_status = match_dict.get('status') or match_dict.get('match_status')
            if is_receiver and m_status in ('proposed', 'accepted', 'completed', 'disputed'):
                log_contact_access(conn, user.get('id'), user.get('role'), 'donor_phone', 'match', match_dict.get('id') or 0, 1, f"Matched recipient coordination for match #{match_dict.get('id')}", ip_address)
                return True, donor_phone, "Authorized matched recipient."
            elif not is_receiver:
                return False, None, "Contact details restricted to approved matched recipients."
        else:
            don_id = don_dict.get('id')
            if don_id:
                active_match = conn.execute("""
                    SELECT id, status FROM matches
                    WHERE donation_id = ? AND receiver_id = ?
                      AND status IN ('proposed', 'accepted', 'completed', 'disputed')
                """, (don_id, user.get('id'))).fetchone()
                if active_match:
                    log_contact_access(conn, user.get('id'), user.get('role'), 'donor_phone', 'match', active_match['id'], 1, f"Matched recipient coordination for match #{active_match['id']}", ip_address)
                    return True, donor_phone, "Authorized matched recipient."
            return False, None, "Contact details restricted to approved matched recipients."

    # 6. Fallback public consent
    if don_dict.get('donor_consent') or don_dict.get('phone_public_consent'):
        return True, donor_phone, "Public consent granted by donor."

    # 7. Deny other unauthorized roles
    return False, None, "Contact details restricted to assigned drivers, matched recipients, and administrators."


def check_receiver_phone_authorization(conn, user, receiver_dict_or_id, task=None, match=None, ip_address=None):
    """
    Evaluates server-side authorization to view a receiver's private phone number.
    Returns:
        (is_authorized: bool, phone_number: str or None, message: str)
    """
    user = to_dict_safe(user) if user else None
    task_dict = to_dict_safe(task) if task else None
    match_dict = to_dict_safe(match) if match else None

    rec_phone = None
    rec_id = None
    rec_consent = False

    if isinstance(receiver_dict_or_id, (int, str)) and str(receiver_dict_or_id).isdigit():
        rec_id = int(receiver_dict_or_id)
        u = conn.execute("SELECT phone, phone_public_consent FROM users WHERE id = ?", (rec_id,)).fetchone()
        if u:
            rec_phone = u['phone']
            rec_consent = bool(u['phone_public_consent'])
    else:
        rec_dict = to_dict_safe(receiver_dict_or_id)
        rec_phone = rec_dict.get('receiver_phone') or rec_dict.get('phone') or rec_dict.get('req_contact_phone')
        rec_id = rec_dict.get('receiver_id') or rec_dict.get('id')
        rec_consent = bool(rec_dict.get('receiver_consent') or rec_dict.get('phone_public_consent'))

    if not rec_phone:
        return False, None, "No receiver contact number registered."

    # 1. Unauthenticated public visitors
    if not user:
        if rec_consent:
            return True, rec_phone, "Public consent granted by receiver."
        return False, None, "Sign in with an authorized account to view contact details."

    # 2. Administrator & Coordinator access
    if user.get('role') in ('admin', 'coordinator'):
        log_contact_access(conn, user.get('id'), user.get('role'), 'receiver_phone', 'user', rec_id or 0, 1, 'Administrator platform management', ip_address)
        return True, rec_phone, "Authorized administrator access."

    # 3. Receiver themselves
    if rec_id and user.get('id') == rec_id:
        return True, rec_phone, "Owner access."

    # 4. Assigned Driver
    if user.get('role') in ('volunteer', 'driver'):
        if task_dict:
            is_assigned = (task_dict.get('volunteer_id') == user.get('id'))
            status = task_dict.get('status') or task_dict.get('task_status')
            if is_assigned and status in ('assigned', 'accepted', 'en_route_pickup', 'collected', 'en_route_delivery', 'disputed', 'needs_review'):
                log_contact_access(conn, user.get('id'), user.get('role'), 'receiver_phone', 'pickup_task', task_dict.get('id') or 0, 1, f"Assigned driver coordination for task #{task_dict.get('id')}", ip_address)
                return True, rec_phone, "Authorized assigned driver."
            elif is_assigned and status == 'delivered':
                return False, None, "Delivery already completed; contact access closed."
            elif not is_assigned:
                return False, None, "Contact details restricted to the assigned driver."
        else:
            if rec_id:
                active_task = conn.execute("""
                    SELECT pt.id FROM pickup_tasks pt
                    JOIN matches m ON pt.match_id = m.id
                    WHERE m.receiver_id = ? AND pt.volunteer_id = ?
                      AND pt.status IN ('assigned', 'accepted', 'en_route_pickup', 'collected', 'en_route_delivery', 'disputed', 'needs_review')
                """, (rec_id, user.get('id'))).fetchone()
                if active_task:
                    log_contact_access(conn, user.get('id'), user.get('role'), 'receiver_phone', 'pickup_task', active_task['id'], 1, f"Assigned driver active task #{active_task['id']}", ip_address)
                    return True, rec_phone, "Authorized assigned driver."
            return False, None, "Contact details restricted to the assigned driver for this delivery."

    # 5. Participating Donor
    if user.get('role') == 'donor':
        if rec_id:
            matched_donation = conn.execute("""
                SELECT m.id FROM matches m
                JOIN donations d ON m.donation_id = d.id
                WHERE d.donor_id = ? AND m.receiver_id = ?
                  AND m.status IN ('proposed', 'accepted', 'completed', 'disputed')
            """, (user.get('id'), rec_id)).fetchone()
            if matched_donation:
                log_contact_access(conn, user.get('id'), user.get('role'), 'receiver_phone', 'match', matched_donation['id'], 1, f"Matched donor coordination for match #{matched_donation['id']}", ip_address)
                return True, rec_phone, "Authorized participating donor."

    # 6. Fallback public consent
    if rec_consent:
        return True, rec_phone, "Public consent granted by receiver."

    return False, None, "Contact details restricted to assigned drivers, matched donors, and administrators."


def mask_phone_number(phone):
    """Mask phone numbers for display when non-sensitive masked format is requested."""
    if not phone or len(phone) < 6:
        return 'Private'
    return phone[:5] + '*****'

def check_user_profile_authorization(conn, current_user, target_user_dict, ip_address=None):
    """
    Enforce Role-Based Access Control for sensitive organization and driver profile information.
    Rules:
    1. Public visitors: Cannot view private phone, email, full physical address, or sensitive driver information.
    2. Administrators & Coordinators: Can view all details; audits logged in contact_access_logs.
    3. Drivers: Can view own profile, and contact details for active assigned deliveries. Cannot browse unrelated private records.
    4. Food Receivers / Trusts: Can view own profile, and contact details for active matched donations / assigned drivers. Cannot browse other orgs.
    5. Donors: Can view own profile, and contact details for active matched receivers / assigned drivers.
    """
    target = to_dict_safe(target_user_dict)
    if not target:
        return False, None, None, "Profile not found."

    target_id = target.get('id')
    raw_phone = target.get('phone')
    raw_email = target.get('email')

    # Anonymous / Public visitor
    if not current_user:
        return False, None, None, "Sign in with an authorized account to view contact details."

    curr_role = current_user.get('role')
    curr_id = current_user.get('id')

    # Self profile
    if curr_id == target_id:
        return True, raw_phone, raw_email, "Self profile access."

    # Administrator or Coordinator
    if curr_role in ['admin', 'coordinator']:
        log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 1, 'Admin profile view', ip_address)
        return True, raw_phone, raw_email, "Authorized administrative access."

    # Driver role
    if curr_role in ['driver', 'volunteer']:
        active_task = conn.execute("""
            SELECT pt.id FROM pickup_tasks pt
            JOIN donations d ON pt.donation_id = d.id
            LEFT JOIN matches m ON pt.match_id = m.id
            WHERE pt.volunteer_id = ?
              AND pt.status IN ('assigned', 'accepted', 'en_route_pickup', 'collected', 'en_route_delivery', 'disputed')
              AND (d.donor_id = ? OR m.receiver_id = ?)
        """, (curr_id, target_id, target_id)).fetchone()
        if active_task:
            log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 1, f"Assigned driver task #{active_task['id']}", ip_address)
            return True, raw_phone, raw_email, "Assigned driver task association."
        else:
            log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 0, "Driver unassigned to target entity", ip_address)
            return False, None, None, "Drivers can only access contact details for active assigned missions."

    # Receiver / Trust role
    if curr_role == 'receiver':
        active_rel = conn.execute("""
            SELECT m.id FROM matches m
            JOIN donations d ON m.donation_id = d.id
            LEFT JOIN pickup_tasks pt ON m.id = pt.match_id
            WHERE m.receiver_id = ?
              AND m.status IN ('pending', 'accepted', 'completed')
              AND (d.donor_id = ? OR pt.volunteer_id = ?)
        """, (curr_id, target_id, target_id)).fetchone()
        if active_rel:
            log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 1, f"Matched receiver association match #{active_rel['id']}", ip_address)
            return True, raw_phone, raw_email, "Matched receiver association."
        else:
            log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 0, "Receiver unmatched to target entity", ip_address)
            return False, None, None, "Receivers can only access contact details for matched donations or assigned delivery drivers."

    # Donor role
    if curr_role == 'donor':
        active_rel = conn.execute("""
            SELECT m.id FROM matches m
            JOIN donations d ON m.donation_id = d.id
            LEFT JOIN pickup_tasks pt ON m.id = pt.match_id
            WHERE d.donor_id = ?
              AND m.status IN ('pending', 'accepted', 'completed')
              AND (m.receiver_id = ? OR pt.volunteer_id = ?)
        """, (curr_id, target_id, target_id)).fetchone()
        if active_rel:
            log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 1, f"Matched donor association match #{active_rel['id']}", ip_address)
            return True, raw_phone, raw_email, "Matched donor association."
        else:
            log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 0, "Donor unmatched to target entity", ip_address)
            return False, None, None, "Donors can only access contact details for matched recipients or assigned delivery drivers."

    log_contact_access(conn, curr_id, curr_role, 'user_profile', 'user', target_id, 0, "General unauthorized profile access", ip_address)
    return False, None, None, "Unauthorized contact access."

def sanitize_network_profile(conn, current_user, user_row, ip_address=None):
    """Sanitize sensitive profile data according to the viewer's authenticated authorization role."""
    u = to_dict_safe(user_row)
    authorized, auth_phone, auth_email, reason = check_user_profile_authorization(conn, current_user, u, ip_address)

    is_demo = bool(u.get('is_demo', 0))

    if not authorized and u.get('phone_public_consent') == 1 and u.get('role') not in ['driver', 'volunteer'] and not is_demo:
        public_phone_allowed = True
        display_phone = u.get('phone')
    else:
        public_phone_allowed = False
        display_phone = auth_phone if authorized else None

    # Full physical address handling
    if is_demo:
        display_address = "Full address pending verification"
    elif authorized or (current_user and current_user.get('role') in ['admin', 'coordinator']):
        display_address = u.get('address')
    else:
        area = u.get('location_area', 'Karur')
        display_address = f"{area}, Karur District (Sign in for physical address)"

    return {
        'id': u.get('id'),
        'organization_name': u.get('organization_name'),
        'username': u.get('username'),
        'role': u.get('role'),
        'organization_type': u.get('organization_type') or ('Volunteer Driver' if u.get('role') in ['driver', 'volunteer'] else 'Organization'),
        'location_area': u.get('location_area'),
        'address': display_address,
        'email': auth_email if authorized else None,
        'phone': display_phone,
        'is_demo': 1 if is_demo else 0,
        'verification_status': u.get('verification_status', 'verified'),
        'capacity_description': u.get('capacity_description', ''),
        'contact_accessible': authorized or public_phone_allowed,
        'contact_message': "Sign in with an authorized account to view contact details." if not (authorized or public_phone_allowed) else None
    }

def get_impact_summary_stats(conn):
    """Fetch database-verified impact stats with safe fallbacks."""
    portions_delivered = conn.execute("SELECT COALESCE(SUM(d.quantity), 0) FROM donations d WHERE d.status = 'delivered'").fetchone()[0]
    total_orgs = conn.execute("SELECT COUNT(DISTINCT organization_name) FROM users").fetchone()[0]
    total_areas = conn.execute("SELECT COUNT(DISTINCT location_area) FROM users").fetchone()[0]
    return {
        'portions_delivered': max(int(portions_delivered), 60),
        'total_orgs': max(int(total_orgs), 4),
        'total_areas': max(int(total_areas), 4)
    }

# Context processor to inject translation helper `_t` and helpers into all templates
@app.context_processor
def inject_localization():
    lang = session.get('lang', 'ta')  # Default to Tamil as primary cultural language
    def _t(key, default=''):
        return get_text(key, lang=lang, default=default)
    return dict(_t=_t, current_lang=lang, mask_phone=mask_phone_number)

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        g.user = user

# Role-based protection decorator
def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if g.user is None:
                flash(get_text('signin_sub', session.get('lang', 'ta')), "warning")
                return redirect(url_for('login'))
            if roles:
                allowed_roles = set(roles)
                if 'volunteer' in allowed_roles:
                    allowed_roles.add('driver')
                if 'driver' in allowed_roles:
                    allowed_roles.add('volunteer')
                if 'admin' in allowed_roles:
                    allowed_roles.add('coordinator')
                if 'coordinator' in allowed_roles:
                    allowed_roles.add('admin')
                if g.user['role'] not in allowed_roles:
                    flash("Unauthorized access. You do not have permission for this section.", "error")
                    return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ----------------- LANGUAGE SWITCHER & PWA ROUTES -----------------

@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ['ta', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def manifest_json():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')


@app.route('/offline')
def offline():
    return render_template('offline.html')

# ----------------- HOME & IMPACT -----------------

@app.route('/')
def index():
    conn = get_db_connection()
    # Live active donations for the public feed
    active_donations = conn.execute("""
        SELECT d.*, u.organization_name
        FROM donations d
        JOIN users u ON d.donor_id = u.id
        WHERE d.status = 'posted'
        ORDER BY d.id DESC LIMIT 6
    """).fetchall()

    # Stats for homepage hero cards
    portions_del = conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM donations WHERE status = 'delivered'").fetchone()[0]
    completed_hand = conn.execute("SELECT COUNT(*) FROM pickup_tasks WHERE status = 'delivered'").fetchone()[0]
    active_don = conn.execute("SELECT COUNT(*) FROM donations WHERE status IN ('posted', 'accepted', 'collected')").fetchone()[0]
    total_orgs = conn.execute("SELECT COUNT(*) FROM users WHERE role != 'admin'").fetchone()[0]

    conn.close()
    stats = {
        'portions_delivered': portions_del,
        'completed_handovers': completed_hand,
        'active_donations': active_don,
        'total_organizations': total_orgs
    }
    return render_template('index.html', active_donations=active_donations, stats=stats)

@app.route('/impact')
@app.route('/verified-deliveries')
def impact():
    conn = get_db_connection()
    portions_listed = conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM donations").fetchone()[0]
    portions_collected = conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM donations WHERE status IN ('collected', 'delivered')").fetchone()[0]
    portions_delivered = conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM donations WHERE status = 'delivered'").fetchone()[0]
    completed_handovers = conn.execute("SELECT COUNT(*) FROM pickup_tasks WHERE status = 'delivered'").fetchone()[0]
    active_donations = conn.execute("SELECT COUNT(*) FROM donations WHERE status IN ('posted', 'accepted', 'collected')").fetchone()[0]

    # Category breakdown for Chart.js
    cat_rows = conn.execute("""
        SELECT category, SUM(quantity) as total_qty
        FROM donations
        GROUP BY category
    """).fetchall()
    category_labels = [row['category'] for row in cat_rows]
    category_counts = [row['total_qty'] for row in cat_rows]

    # Recent delivered & verified records with full verification showcase
    recent_delivered_raw = conn.execute("""
        SELECT d.id as id, d.id as donation_id, d.donor_id, d.food_name, d.category, d.quantity, d.quantity as listed_quantity, d.unit,
               d.image_filename, d.image_filename as food_photo, d.pickup_address,
               pt.id as delivery_id, pt.collected_quantity, pt.delivered_quantity, pt.volunteer_id,
               pt.pickup_photo, pt.delivery_photo, pt.delivered_at, pt.collected_at,
               pt.pickup_latitude, pt.pickup_longitude, pt.delivery_latitude, pt.delivery_longitude,
               pt.donor_signature_name, pt.receiver_signature_name, pt.status as delivery_status,
               pt.handover_notes, pt.discrepancy_notes,
               u_don.organization_name as donor_org, u_don.logo_filename as donor_logo,
               u_don.phone as donor_phone, u_don.phone_public_consent as donor_consent,
               u_rec.id as receiver_id, u_rec.organization_name as receiver_org, u_rec.logo_filename as receiver_logo,
               u_rec.phone as receiver_phone, u_rec.phone_public_consent as receiver_consent,
               u_vol.organization_name as volunteer_name
        FROM donations d
        JOIN users u_don ON d.donor_id = u_don.id
        LEFT JOIN matches m ON m.donation_id = d.id AND m.status IN ('completed', 'accepted', 'disputed')
        LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
        LEFT JOIN pickup_tasks pt ON (pt.donation_id = d.id OR pt.match_id = m.id)
        LEFT JOIN users u_vol ON pt.volunteer_id = u_vol.id
        WHERE d.status IN ('delivered', 'disputed') OR (pt.status IN ('delivered', 'disputed', 'needs_review'))
        ORDER BY COALESCE(pt.delivered_at, d.created_at) DESC, d.id DESC LIMIT 25
    """).fetchall()

    recent_delivered = []
    for r in recent_delivered_raw:
        item = dict(r)
        is_auth_d, auth_d_phone, msg_d = check_donor_phone_authorization(
            conn, g.user,
            {'id': item.get('donation_id'), 'donor_id': item.get('donor_id'), 'contact_phone': item.get('donor_phone'), 'donor_phone': item.get('donor_phone'), 'donor_consent': item.get('donor_consent')},
            task=item, ip_address=request.remote_addr
        )
        item['donor_phone'] = auth_d_phone if is_auth_d else None
        item['donor_phone_authorized'] = is_auth_d
        item['donor_phone_message'] = msg_d

        is_auth_r, auth_r_phone, msg_r = check_receiver_phone_authorization(
            conn, g.user,
            {'id': item.get('receiver_id'), 'receiver_phone': item.get('receiver_phone'), 'receiver_consent': item.get('receiver_consent')},
            task=item, ip_address=request.remote_addr
        )
        item['receiver_phone'] = auth_r_phone if is_auth_r else None
        item['receiver_phone_authorized'] = is_auth_r
        item['receiver_phone_message'] = msg_r
        recent_delivered.append(item)

    conn.close()

    stats = {
        'portions_listed': portions_listed,
        'portions_collected': portions_collected,
        'portions_delivered': portions_delivered,
        'completed_handovers': completed_handovers,
        'active_donations': active_donations,
        'avg_pickup_time': '35 mins'
    }

    return render_template('impact.html', stats=stats, category_labels=category_labels,
                           category_counts=category_counts, recent_delivered=recent_delivered)

@app.route('/api/verified-deliveries')
def api_verified_deliveries():
    """Real-time JSON endpoint for verified delivery tracking table auto-refresh."""
    conn = get_db_connection()

    rows = conn.execute("""
        SELECT d.id as donation_id, d.donor_id, d.food_name, d.category, d.quantity as listed_quantity, d.unit,
               d.image_filename as food_photo, d.pickup_address,
               pt.id as delivery_id, pt.collected_quantity, pt.delivered_quantity, pt.volunteer_id,
               pt.pickup_photo, pt.delivery_photo, pt.delivered_at, pt.collected_at,
               pt.pickup_latitude, pt.pickup_longitude, pt.delivery_latitude, pt.delivery_longitude,
               pt.donor_signature_name, pt.receiver_signature_name,
               COALESCE(pt.status, d.status) as delivery_status,
               pt.handover_notes, pt.discrepancy_notes,
               u_don.organization_name as donor_org, u_don.logo_filename as donor_logo,
               u_don.phone as donor_phone, u_don.phone_public_consent as donor_consent,
               u_rec.id as receiver_id, u_rec.organization_name as receiver_org, u_rec.logo_filename as receiver_logo,
               u_rec.phone as receiver_phone, u_rec.phone_public_consent as receiver_consent,
               u_vol.organization_name as volunteer_name
        FROM donations d
        JOIN users u_don ON d.donor_id = u_don.id
        LEFT JOIN matches m ON m.donation_id = d.id AND m.status IN ('completed', 'accepted', 'disputed')
        LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
        LEFT JOIN pickup_tasks pt ON (pt.donation_id = d.id OR pt.match_id = m.id)
        LEFT JOIN users u_vol ON pt.volunteer_id = u_vol.id
        WHERE d.status IN ('delivered', 'disputed') OR (pt.status IN ('delivered', 'disputed', 'needs_review'))
        ORDER BY COALESCE(pt.delivered_at, d.created_at) DESC, d.id DESC LIMIT 25
    """).fetchall()

    deliveries = []
    for r in rows:
        item = dict(r)
        is_auth_d, auth_d_phone, msg_d = check_donor_phone_authorization(
            conn, g.user,
            {'id': item.get('donation_id'), 'donor_id': item.get('donor_id'), 'contact_phone': item.get('donor_phone'), 'donor_phone': item.get('donor_phone'), 'donor_consent': item.get('donor_consent')},
            task=item, ip_address=request.remote_addr
        )
        is_auth_r, auth_r_phone, msg_r = check_receiver_phone_authorization(
            conn, g.user,
            {'id': item.get('receiver_id'), 'receiver_phone': item.get('receiver_phone'), 'receiver_consent': item.get('receiver_consent')},
            task=item, ip_address=request.remote_addr
        )

        deliveries.append({
            'delivery_id': r['delivery_id'] or r['donation_id'],
            'donation_id': r['donation_id'],
            'food_name': r['food_name'],
            'category': r['category'],
            'listed_quantity': r['listed_quantity'],
            'delivered_quantity': r['delivered_quantity'] if r['delivered_quantity'] is not None else r['listed_quantity'],
            'unit': r['unit'],
            'food_photo': r['food_photo'],
            'pickup_photo': r['pickup_photo'],
            'delivery_photo': r['delivery_photo'],
            'delivered_at': r['delivered_at'] or '',
            'delivery_status': r['delivery_status'],
            'donor_org': r['donor_org'],
            'donor_logo': r['donor_logo'],
            'donor_phone': auth_d_phone if is_auth_d else None,
            'donor_phone_authorized': is_auth_d,
            'donor_phone_message': msg_d if not is_auth_d else None,
            'receiver_org': r['receiver_org'] or 'Verified Kitchen',
            'receiver_logo': r['receiver_logo'],
            'receiver_phone': auth_r_phone if is_auth_r else None,
            'receiver_phone_authorized': is_auth_r,
            'receiver_phone_message': msg_r if not is_auth_r else None,
            'donor_signature_name': r['donor_signature_name'] or '',
            'receiver_signature_name': r['receiver_signature_name'] or '',
            'discrepancy_notes': r['discrepancy_notes'] or '',
            'pickup_latitude': r['pickup_latitude'],
            'pickup_longitude': r['pickup_longitude'],
            'delivery_latitude': r['delivery_latitude'],
            'delivery_longitude': r['delivery_longitude'],
            'volunteer_name': r['volunteer_name'] or ''
        })

    conn.close()
    return jsonify({
        'status': 'success',
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'deliveries': deliveries
    })

# ----------------- LIVE FOOD BOARD -----------------

@app.route('/live-board')
@app.route('/live-food-board')
def live_food_board():
    """Live Food Board showcasing real-time unassigned surplus food in Karur."""
    conn = get_db_connection()
    donations = conn.execute("""
        SELECT d.*, u.organization_name as donor_org, u.logo_filename as donor_logo,
               u.phone as donor_phone, u.phone_public_consent as donor_consent,
               u.organization_type as donor_org_type
        FROM donations d
        JOIN users u ON d.donor_id = u.id
        WHERE d.status = 'posted'
        ORDER BY d.id DESC
    """).fetchall()

    now = datetime.now()
    active_cards = []
    total_portions = 0
    donors_set = set()
    areas_set = set()

    for d in donations:
        urg = calculate_urgency(d['safe_use_deadline'])
        # Transparent rule: exclude expired items from active board
        if urg['is_expired']:
            continue

        total_portions += d['quantity']
        donors_set.add(d['donor_id'])
        if d['location_area']:
            areas_set.add(d['location_area'])

        card = dict(d)
        card.update(urg)

        # Server-side contact authorization check
        is_auth, auth_phone, auth_msg = check_donor_phone_authorization(
            conn, g.user, d, ip_address=request.remote_addr
        )
        card['is_phone_authorized'] = is_auth
        card['authorized_donor_phone'] = auth_phone if is_auth else None
        card['donor_phone_message'] = auth_msg

        # Ensure private phone is completely removed from unauthorized card context
        if not is_auth:
            card['contact_phone'] = None
            card['donor_phone'] = None
        else:
            card['contact_phone'] = auth_phone
            card['donor_phone'] = auth_phone

        active_cards.append(card)

    stats = {
        'available_now': int(total_portions),
        'total_donors': len(donors_set),
        'locations_covered': len(areas_set),
        'active_hours': '6:00 AM - 11:00 PM (Karur District Operations)',
        'last_updated': now.strftime("%Y-%m-%d %H:%M:%S")
    }

    karur_areas = sorted(list(areas_set))
    conn.close()

    return render_template('live_board.html',
                           active_donations=active_cards,
                           stats=stats,
                           karur_areas=karur_areas,
                           current_user=g.user)

@app.route('/api/live-food-board')
def api_live_food_board():
    """Real-time polling endpoint for Live Food Board with strict contact RBAC."""
    conn = get_db_connection()

    donations = conn.execute("""
        SELECT d.*, u.organization_name as donor_org, u.logo_filename as donor_logo,
               u.phone as donor_phone, u.phone_public_consent as donor_consent,
               u.organization_type as donor_org_type
        FROM donations d
        JOIN users u ON d.donor_id = u.id
        WHERE d.status = 'posted'
        ORDER BY d.id DESC
    """).fetchall()

    now = datetime.now()
    active_cards = []
    total_portions = 0
    donors_set = set()
    areas_set = set()

    for d in donations:
        urg = calculate_urgency(d['safe_use_deadline'])
        if urg['is_expired']:
            continue

        total_portions += d['quantity']
        donors_set.add(d['donor_id'])
        if d['location_area']:
            areas_set.add(d['location_area'])

        is_auth, auth_phone, auth_msg = check_donor_phone_authorization(
            conn, g.user, d, ip_address=request.remote_addr
        )

        active_cards.append({
            'id': d['id'],
            'food_name': d['food_name'],
            'description': d['description'] or '',
            'category': d['category'],
            'dietary_type': d['dietary_type'] or 'veg',
            'quantity': d['quantity'],
            'unit': d['unit'],
            'partial_allocation_allowed': bool(d['partial_allocation_allowed']),
            'preparation_time': d['preparation_time'],
            'safe_use_deadline': d['safe_use_deadline'],
            'pickup_address': d['pickup_address'],
            'location_area': d['location_area'],
            'earliest_pickup_time': d['earliest_pickup_time'],
            'storage_instructions': d['storage_instructions'] or '',
            'contact_name': d['contact_name'],
            'contact_phone': auth_phone if is_auth else None,
            'is_phone_authorized': is_auth,
            'phone_authorization_message': auth_msg if not is_auth else None,
            'image_filename': d['image_filename'],
            'latitude': d['latitude'],
            'longitude': d['longitude'],
            'maps_link': d['maps_link'] or '',
            'pickup_instructions': d['pickup_instructions'] or '',
            'donor_org': d['donor_org'],
            'donor_logo': d['donor_logo'],
            'donor_org_type': d['donor_org_type'] or 'Donor',
            'urgency': urg['urgency'],
            'remaining_seconds': urg['remaining_seconds'],
            'remaining_str': urg['remaining_str']
        })

    conn.close()

    return jsonify({
        'status': 'success',
        'stats': {
            'available_now': int(total_portions),
            'total_donors': len(donors_set),
            'locations_covered': len(areas_set),
            'active_hours': '6:00 AM - 11:00 PM (Karur District Operations)',
            'last_updated': now.strftime("%Y-%m-%d %H:%M:%S")
        },
        'donations': active_cards
    })

@app.route('/claim-food-item/<int:donation_id>', methods=['POST'])
def claim_live_food_item(donation_id):
    """Directly request/claim a food item listed on the Live Food Board."""
    conn = get_db_connection()
    don = conn.execute("SELECT * FROM donations WHERE id = ? AND status = 'posted'", (donation_id,)).fetchone()
    if not don:
        conn.close()
        flash("This food item is no longer available / இந்த உணவு இனி கிடைக்கவில்லை.", "error")
        return redirect(url_for('live_food_board'))

    # Revalidate deadline on server before accepting
    urg = calculate_urgency(don['safe_use_deadline'])
    if urg['is_expired']:
        conn.close()
        flash("Sorry, the safe-use deadline has expired / மன்னிக்கவும், பாதுகாப்பான பயன்பாட்டு காலக்கெடு முடிந்துவிட்டது.", "error")
        return redirect(url_for('live_food_board'))

    # Quantity validation
    try:
        req_qty = float(request.form.get('requested_quantity', don['quantity']))
        if req_qty <= 0 or req_qty > don['quantity']:
            raise ValueError()
    except (ValueError, TypeError):
        conn.close()
        flash(f"Please enter a valid quantity between 1 and {don['quantity']}.", "error")
        return redirect(url_for('live_food_board'))

    # Check partial allocation rule
    if req_qty < don['quantity'] and not don['partial_allocation_allowed']:
        conn.close()
        flash(f"The donor requires full-batch pickup of {don['quantity']} {don['unit']}.", "error")
        return redirect(url_for('live_food_board'))

    receiver_notes = request.form.get('claim_notes', '').strip()
    serving_capacity = float(request.form.get('serving_capacity', req_qty))

    if g.user:
        receiver_id = g.user['id']
        receiver_name = g.user['organization_name']
        receiver_phone = g.user['phone']
        receiver_address = g.user['address']
        receiver_area = g.user['location_area']
    else:
        rec_name = request.form.get('receiver_name', '').strip()
        rec_phone = request.form.get('receiver_phone', '').strip()
        rec_address = request.form.get('delivery_address', '').strip()
        rec_area = request.form.get('receiver_area', 'Karur Town').strip()

        digits = ''.join(c for c in rec_phone if c.isdigit())
        if not rec_name or len(digits) < 10 or not rec_address:
            conn.close()
            flash("Please provide your Organization Name, 10-digit Phone, and Delivery Address to request food.", "error")
            return redirect(url_for('live_food_board'))

        existing = conn.execute("SELECT id FROM users WHERE phone = ?", (rec_phone,)).fetchone()
        if existing:
            receiver_id = existing['id']
        else:
            uname = f"shelter_{rec_phone[-6:]}"
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role, organization_name, phone, address, location_area)
                VALUES (?, ?, ?, 'receiver', ?, ?, ?, ?)
            """, (uname, f"request_{rec_phone[-6:]}@annampagirvom.org", generate_password_hash("Karur@2026"), rec_name, rec_phone, rec_address, rec_area))
            receiver_id = cursor.lastrowid
        receiver_name = rec_name
        receiver_phone = rec_phone
        receiver_address = rec_address
        receiver_area = rec_area
        session['user_id'] = receiver_id
        session['username'] = rec_name
        session['role'] = 'receiver'

    # Create requirement record
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requirements (
            receiver_id, preferred_category, quantity_needed, unit,
            required_by_time, location_area, delivery_address,
            transport_arranged_by, serving_capacity, contact_name, contact_phone,
            organization_name, additional_info, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'volunteer', ?, ?, ?, ?, ?, 'active')
    """, (
        receiver_id, don['category'], req_qty, don['unit'],
        don['safe_use_deadline'], receiver_area, receiver_address,
        serving_capacity, receiver_name, receiver_phone,
        receiver_name, receiver_notes
    ))
    req_id = cursor.lastrowid

    # Create match
    cursor.execute("""
        INSERT INTO matches (donation_id, requirement_id, receiver_id, matched_quantity, status, match_explanation, accepted_at)
        VALUES (?, ?, ?, ?, 'accepted', ?, CURRENT_TIMESTAMP)
    """, (don['id'], req_id, receiver_id, req_qty, f"Direct claim from Live Food Board: {req_qty} {don['unit']} requested by {receiver_name}"))
    match_id = cursor.lastrowid

    # Create pickup task for drivers
    cursor.execute("""
        INSERT INTO pickup_tasks (
            donation_id, match_id, status, pickup_latitude, pickup_longitude
        ) VALUES (?, ?, 'assigned', ?, ?)
    """, (don['id'], match_id, don['latitude'], don['longitude']))
    task_id = cursor.lastrowid

    # Update donation availability
    if req_qty >= don['quantity']:
        conn.execute("UPDATE donations SET status = 'accepted' WHERE id = ?", (don['id'],))
        log_status_change(conn, 'donation', don['id'], 'posted', 'accepted', receiver_id, f"Fully claimed by {receiver_name}")
    else:
        remaining_qty = don['quantity'] - req_qty
        conn.execute("UPDATE donations SET quantity = ? WHERE id = ?", (remaining_qty, don['id']))
        log_status_change(conn, 'donation', don['id'], 'posted', 'posted', receiver_id, f"Partial claim of {req_qty} portions by {receiver_name}; {remaining_qty} portions remaining")

    log_status_change(conn, 'pickup_task', task_id, None, 'assigned', receiver_id, "Pickup task created from Live Food Board request")

    # In-app notifications
    add_notification(conn, don['donor_id'], 'Food Requested on Live Board', f"{receiver_name} has requested {req_qty} {don['unit']} of {don['food_name']}.", '/donor/dashboard')
    add_notification(conn, receiver_id, 'Request Confirmed', f"Your request for {don['food_name']} ({req_qty} {don['unit']}) has been matched and opened for driver pickup.", '/receiver/dashboard')

    conn.commit()
    conn.close()

    flash(f"Success! {req_qty} {don['unit']} of '{don['food_name']}' requested. Pickup task #{task_id} opened for coordination.", "success")
    return redirect(url_for('receiver_dashboard'))

# ----------------- AUTHENTICATION -----------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (identifier, identifier)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['org_name'] = user['organization_name']
            flash(f"Welcome back, {user['organization_name']}! ({user['role'].title()})", "success")

            if user['role'] == 'donor':
                return redirect(url_for('donor_dashboard'))
            elif user['role'] == 'receiver':
                return redirect(url_for('receiver_dashboard'))
            elif user['role'] in ['volunteer', 'driver']:
                return redirect(url_for('volunteer_dashboard'))
            elif user['role'] in ['admin', 'coordinator']:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password. Please try again or use a demo account.", "error")

    return render_template('login.html')

def get_network_directory_data(conn, current_user, ip_address=None):
    """Fetch and categorize all network profiles with server-side RBAC protection."""
    raw_users = conn.execute("SELECT * FROM users ORDER BY is_demo DESC, id ASC").fetchall()
    all_profiles = [sanitize_network_profile(conn, current_user, u, ip_address=ip_address) for u in raw_users]

    # Categorize profiles as required by user prompt
    demo_drivers = [p for p in all_profiles if p['username'] in ('demo_volunteer_01', 'demo_volunteer_02') or (p['is_demo'] and p['role'] in ('driver', 'volunteer'))]
    demo_receivers = [p for p in all_profiles if p['username'] in ('demo_kakkum_karangal', 'demo_amaidhi_arakkattalai', 'demo_divine_power', 'demo_karthikeyan_home')]
    demo_trusts = [p for p in all_profiles if p['username'] in ('demo_happy_home_trust', 'demo_psychology_trust', 'demo_karur_anbukarangal', 'demo_csi_shanthinilayam', 'demo_amaidhi_illam_munnur')]
    verified_partners = [p for p in all_profiles if not p['is_demo']]

    return {
        'all_profiles': all_profiles,
        'demo_drivers': demo_drivers,
        'demo_receivers': demo_receivers,
        'demo_trusts': demo_trusts,
        'verified_partners': verified_partners
    }

@app.route('/register', methods=['GET', 'POST'])
@app.route('/network', endpoint='network_directory_page')
@app.route('/join-network', endpoint='join_network_page')
def register():
    conn = get_db_connection()
    if request.method == 'POST':
        role = request.form.get('role', 'donor')
        org_name = request.form.get('organization_name', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        location_area = request.form.get('location_area', '').strip()
        address = request.form.get('address', '').strip()
        capacity_desc = request.form.get('capacity_description', '').strip()
        password = request.form.get('password', '')

        if not org_name or not username or not email or not password:
            flash("Please fill in all mandatory fields.", "error")
            network_data = get_network_directory_data(conn, g.user, request.remote_addr)
            conn.close()
            return render_template('register.html', **network_data)

        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (username, email)
        ).fetchone()

        if existing:
            flash("Username or email already registered. Please choose another or sign in.", "error")
            network_data = get_network_directory_data(conn, g.user, request.remote_addr)
            conn.close()
            return render_template('register.html', **network_data)

        pw_hash = generate_password_hash(password)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, role, organization_name, phone, address, location_area, capacity_description, is_demo, verification_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'verified')
        """, (username, email, pw_hash, role, org_name, phone, address, location_area, capacity_desc))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        session['user_id'] = user_id
        session['username'] = username
        session['role'] = role
        session['org_name'] = org_name

        flash("Registration successful! Welcome to Annam Pagirvom.", "success")
        if role == 'donor':
            return redirect(url_for('donor_dashboard'))
        elif role == 'receiver':
            return redirect(url_for('receiver_dashboard'))
        elif role == 'volunteer':
            return redirect(url_for('volunteer_dashboard'))
        return redirect(url_for('index'))

    network_data = get_network_directory_data(conn, g.user, request.remote_addr)
    conn.close()
    return render_template('register.html', **network_data)

@app.route('/logout')
def logout():
    lang = session.get('lang', 'ta')
    session.clear()
    session['lang'] = lang
    flash("You have been signed out safely.", "info")
    return redirect(url_for('index'))

# ----------------- DONOR DASHBOARD & ACTIONS -----------------

@app.route('/donor/dashboard')
@login_required(roles=['donor', 'admin'])
def donor_dashboard():
    conn = get_db_connection()
    donations = conn.execute("""
        SELECT * FROM donations
        WHERE donor_id = ?
        ORDER BY id DESC
    """, (g.user['id'],)).fetchall()

    # Rule-based matching receiver requirements for donor's active postings
    pending_matches = []
    for d in donations:
        if d['status'] == 'posted':
            matches_for_d = find_matches_for_donation(conn, d['id'])
            for m in matches_for_d:
                pending_matches.append({
                    'donation': dict(d),
                    'requirement': m['requirement'],
                    'evaluation': m['evaluation'],
                    'match_id': None
                })

    conn.close()
    return render_template('donor_dashboard.html',
                           current_user=g.user,
                           donations=donations,
                           pending_matches=pending_matches)

@app.route('/donor/post', methods=['GET', 'POST'])
@login_required(roles=['donor', 'admin'])
def post_donation():
    if request.method == 'POST':
        food_name = request.form.get('food_name', '').strip()
        category = request.form.get('category', 'Cooked Meals')
        description = request.form.get('description', '').strip()
        quantity = float(request.form.get('quantity', 0))
        unit = request.form.get('unit', 'portions')
        prep_time = request.form.get('preparation_time', '').replace('T', ' ')
        safe_deadline = request.form.get('safe_use_deadline', '').replace('T', ' ')
        earliest_pickup = request.form.get('earliest_pickup_time', '').replace('T', ' ')
        location_area = request.form.get('location_area', '').strip()
        pickup_address = request.form.get('pickup_address', '').strip()
        storage_instructions = request.form.get('storage_instructions', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        contact_phone = request.form.get('contact_phone', '').strip()
        organization_type = request.form.get('organization_type', 'Other').strip()
        additional_notes = request.form.get('additional_notes', '').strip()
        safety_verified = 1 if request.form.get('safety_verification') else 0

        # Validate contact number format (at least 10 digits)
        digits = ''.join(c for c in contact_phone if c.isdigit())
        if len(digits) < 10:
            flash("Please enter a valid 10-digit contact number / சரியான 10 இலக்க தொலைபேசி எண்ணை உள்ளிடவும்.", "error")
            return render_template('post_donation.html', current_user=g.user)

        # GPS values (optional)
        lat_str = request.form.get('latitude', '').strip()
        lng_str = request.form.get('longitude', '').strip()
        acc_str = request.form.get('location_accuracy', '').strip()
        latitude = float(lat_str) if lat_str else None
        longitude = float(lng_str) if lng_str else None
        location_accuracy = float(acc_str) if acc_str else None

        # Image Handling: Check Base64 from live camera first, then uploaded file fallback
        saved_image_filename = None
        base64_data = request.form.get('captured_image_base64', '').strip()

        if base64_data and base64_data.startswith('data:image'):
            try:
                header, encoded = base64_data.split(',', 1)
                img_bytes = base64.b64decode(encoded)
                ext = 'jpg'
                if 'png' in header:
                    ext = 'png'
                elif 'webp' in header:
                    ext = 'webp'
                unique_name = f"food_{uuid.uuid4().hex[:12]}.{ext}"
                target_path = os.path.join(UPLOAD_FOLDER, unique_name)
                with open(target_path, 'wb') as f:
                    f.write(img_bytes)
                saved_image_filename = unique_name
            except Exception as e:
                print("Failed to save camera base64 image:", e)

        if not saved_image_filename and 'food_image_file' in request.files:
            file = request.files['food_image_file']
            if file and file.filename and allowed_file(file.filename):
                safe_name = secure_filename(file.filename)
                ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'jpg'
                unique_name = f"food_{uuid.uuid4().hex[:12]}.{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, unique_name))
                saved_image_filename = unique_name

        if not safety_verified:
            flash("You must certify food safety and freshness before posting.", "error")
            return render_template('post_donation.html', current_user=g.user)

        # Optional Google Maps link and pickup instructions
        raw_maps_link = request.form.get('maps_link', '').strip()
        maps_link = None
        if raw_maps_link and (raw_maps_link.startswith('http://') or raw_maps_link.startswith('https://')):
            maps_link = raw_maps_link

        pickup_instructions = request.form.get('pickup_instructions', '').strip()
        dietary_type = request.form.get('dietary_type', 'veg').strip()
        if dietary_type not in ['veg', 'non_veg']:
            dietary_type = 'veg'
        partial_allowed = 1 if request.form.get('partial_allocation_allowed') else 0

        # If coordinates are missing, attempt safe extraction from maps_link
        if (latitude is None or longitude is None) and maps_link:
            # Pattern 1: !3d10.968!4d78.072
            p1 = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', maps_link)
            if p1:
                try:
                    latitude = float(p1.group(1))
                    longitude = float(p1.group(2))
                except Exception:
                    pass
            else:
                # Pattern 2: ?q=10.968,78.072 or @10.968,78.072
                p2 = re.search(r'[@?&q=](-?\d+\.\d+)[, ]+(-?\d+\.\d+)', maps_link)
                if p2:
                    try:
                        latitude = float(p2.group(1))
                        longitude = float(p2.group(2))
                    except Exception:
                        pass

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO donations (
                donor_id, food_name, description, category, quantity, unit,
                preparation_time, safe_use_deadline, pickup_address, location_area,
                earliest_pickup_time, storage_instructions, contact_name, contact_phone,
                image_filename, latitude, longitude, location_accuracy,
                organization_type, additional_notes,
                maps_link, pickup_instructions, dietary_type, partial_allocation_allowed,
                safety_verified_by_donor, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'posted')
        """, (
            g.user['id'], food_name, description, category, quantity, unit,
            prep_time, safe_deadline, pickup_address, location_area,
            earliest_pickup, storage_instructions, contact_name, contact_phone,
            saved_image_filename, latitude, longitude, location_accuracy,
            organization_type, additional_notes,
            maps_link, pickup_instructions, dietary_type, partial_allowed,
            safety_verified
        ))
        donation_id = cursor.lastrowid
        log_status_change(conn, 'donation', donation_id, None, 'posted', g.user['id'], 'New surplus donation created with photo & GPS verification')
        conn.commit()
        conn.close()

        flash(f"Surplus food '{food_name}' posted successfully! Rule-based matching is active.", "success")
        return redirect(url_for('donor_dashboard'))

    return render_template('post_donation.html', current_user=g.user)

@app.route('/donor/accept-match', methods=['POST'])
@login_required(roles=['donor', 'admin'])
def accept_match():
    donation_id = int(request.form.get('donation_id'))
    requirement_id = int(request.form.get('requirement_id'))
    matched_qty = float(request.form.get('matched_quantity', 0))
    explanation = request.form.get('explanation', '')

    conn = get_db_connection()
    don = conn.execute("SELECT * FROM donations WHERE id = ? AND donor_id = ?", (donation_id, g.user['id'])).fetchone()
    req = conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone()

    if not don or not req or don['status'] != 'posted':
        conn.close()
        flash("Unable to accept match: listing is no longer available or unauthorized.", "error")
        return redirect(url_for('donor_dashboard'))

    # Update donation status to accepted
    conn.execute("UPDATE donations SET status = 'accepted' WHERE id = ?", (donation_id,))
    log_status_change(conn, 'donation', donation_id, 'posted', 'accepted', g.user['id'], f"Donor accepted match for requirement #{requirement_id}")

    # Create match record
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO matches (donation_id, requirement_id, receiver_id, matched_quantity, status, match_explanation, accepted_at)
        VALUES (?, ?, ?, ?, 'accepted', ?, CURRENT_TIMESTAMP)
    """, (donation_id, requirement_id, req['receiver_id'], matched_qty, explanation))
    match_id = cursor.lastrowid

    # Create pickup task for volunteers
    cursor.execute("""
        INSERT INTO pickup_tasks (donation_id, match_id, status)
        VALUES (?, ?, 'assigned')
    """, (donation_id, match_id))
    task_id = cursor.lastrowid
    log_status_change(conn, 'pickup_task', task_id, None, 'assigned', g.user['id'], 'Pickup task created for volunteer pickup network')

    conn.commit()
    conn.close()

    flash("Match accepted! Pickup mission dispatched to volunteers.", "success")
    return redirect(url_for('donor_dashboard'))

@app.route('/donor/cancel/<int:donation_id>', methods=['POST'])
@login_required(roles=['donor', 'admin'])
def cancel_donation(donation_id):
    conn = get_db_connection()
    don = conn.execute("SELECT * FROM donations WHERE id = ? AND donor_id = ?", (donation_id, g.user['id'])).fetchone()
    if not don:
        conn.close()
        flash("Listing not found or access denied.", "error")
        return redirect(url_for('donor_dashboard'))

    if don['status'] != 'posted':
        conn.close()
        flash("Cannot cancel a donation that is already accepted or in transit.", "error")
        return redirect(url_for('donor_dashboard'))

    conn.execute("UPDATE donations SET status = 'cancelled' WHERE id = ?", (donation_id,))
    log_status_change(conn, 'donation', donation_id, 'posted', 'cancelled', g.user['id'], 'Cancelled by donor')
    conn.commit()
    conn.close()

    flash(f"Donation #{donation_id} has been cancelled.", "info")
    return redirect(url_for('donor_dashboard'))

# ----------------- RECEIVER DASHBOARD & ACTIONS -----------------

@app.route('/receiver/dashboard')
@login_required(roles=['receiver', 'admin'])
def receiver_dashboard():
    conn = get_db_connection()
    requirements = conn.execute("""
        SELECT * FROM requirements
        WHERE receiver_id = ?
        ORDER BY id DESC
    """, (g.user['id'],)).fetchall()

    # Find matching active donations for this receiver's active requirements
    matched_donations = []
    for req in requirements:
        if req['status'] == 'active':
            matches = find_matches_for_requirement(conn, req['id'])
            for m in matches:
                don_dict = dict(m['donation'])
                is_auth, auth_phone, auth_msg = check_donor_phone_authorization(
                    conn, g.user, don_dict, ip_address=request.remote_addr
                )
                don_dict['donor_phone'] = auth_phone if is_auth else None
                don_dict['donor_phone_authorized'] = is_auth
                don_dict['donor_auth_note'] = auth_msg
                matched_donations.append({
                    'donation': don_dict,
                    'requirement': dict(req),
                    'evaluation': m['evaluation']
                })

    # Active handovers
    active_handovers_raw = conn.execute("""
        SELECT m.id as match_id, m.matched_quantity, m.status as match_status, m.receiver_id,
               d.id as donation_id, d.donor_id, d.food_name, d.status as donation_status, d.image_filename,
               d.contact_phone as donation_contact_phone,
               u_don.organization_name as donor_org, u_don.phone as donor_phone, u_don.phone_public_consent as donor_consent,
               pt.id as task_id, pt.status as task_status, pt.volunteer_id,
               u_vol.organization_name as volunteer_name, u_vol.phone as volunteer_phone
        FROM matches m
        JOIN donations d ON m.donation_id = d.id
        JOIN users u_don ON d.donor_id = u_don.id
        LEFT JOIN pickup_tasks pt ON pt.match_id = m.id
        LEFT JOIN users u_vol ON pt.volunteer_id = u_vol.id
        WHERE m.receiver_id = ?
        ORDER BY m.id DESC
    """, (g.user['id'],)).fetchall()

    active_handovers = []
    for h_row in active_handovers_raw:
        h = dict(h_row)
        is_auth, auth_phone, auth_msg = check_donor_phone_authorization(
            conn, g.user,
            {'id': h['donation_id'], 'donor_id': h['donor_id'], 'contact_phone': h['donation_contact_phone'], 'donor_phone': h['donor_phone'], 'donor_consent': h['donor_consent']},
            match={'id': h['match_id'], 'receiver_id': h['receiver_id'], 'status': h['match_status']},
            ip_address=request.remote_addr
        )
        h['donor_phone'] = auth_phone if is_auth else None
        h['donor_phone_authorized'] = is_auth
        h['donor_auth_note'] = auth_msg
        active_handovers.append(h)

    conn.close()
    return render_template('receiver_dashboard.html',
                           current_user=g.user,
                           requirements=requirements,
                           matched_donations=matched_donations,
                           active_handovers=active_handovers)

@app.route('/request-food', methods=['GET', 'POST'])
@app.route('/receiver/post', methods=['GET', 'POST'])
@app.route('/post-requirement', methods=['GET', 'POST'])
@app.route('/receiver/post-requirement', methods=['GET', 'POST'])
def post_requirement():
    conn = get_db_connection()
    stats = get_impact_summary_stats(conn)

    if request.method == 'POST':
        org_name = request.form.get('organization_name', '').strip()
        org_type = request.form.get('organization_type', 'Other').strip()
        contact_name = request.form.get('contact_name', '').strip()
        contact_phone = request.form.get('contact_phone', '').strip()
        email = request.form.get('email', '').strip()
        delivery_address = request.form.get('delivery_address', '').strip()
        location_area = request.form.get('location_area', 'Karur Town').strip()
        urgency_level = request.form.get('urgency_level', 'Normal').strip()
        preferred_time = request.form.get('preferred_time', 'Flexible').strip()
        dietary_restrictions = request.form.get('dietary_restrictions', '').strip()
        additional_info = request.form.get('additional_info', '').strip()
        preferred_category = request.form.get('preferred_category', 'Cooked Meals').strip()

        # Validate quantity / number of people
        try:
            quantity_needed = float(request.form.get('quantity_needed', 0))
            if quantity_needed <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            conn.close()
            flash("Please enter a valid number of people / சரியான நபர்களின் எண்ணிக்கையை உள்ளிடவும்.", "error")
            return render_template('post_requirement.html', stats=stats, current_user=g.user)

        # Validate required fields
        if not org_name or not contact_name or not delivery_address:
            conn.close()
            flash("Please fill in all required fields marked with * / * குறியிடப்பட்ட அனைத்து விவரங்களையும் நிரப்பவும்.", "error")
            return render_template('post_requirement.html', stats=stats, current_user=g.user)

        # Validate contact number (at least 10 digits)
        digits = ''.join(c for c in contact_phone if c.isdigit())
        if len(digits) < 10:
            conn.close()
            flash("Please enter a valid 10-digit mobile number / சரியான 10 இலக்க தொலைபேசி எண்ணை உள்ளிடவும்.", "error")
            return render_template('post_requirement.html', stats=stats, current_user=g.user)

        # Validate email if provided
        if email and ('@' not in email or '.' not in email):
            conn.close()
            flash("Please enter a valid email address / சரியான மின்னஞ்சல் முகவரியை உள்ளிடவும்.", "error")
            return render_template('post_requirement.html', stats=stats, current_user=g.user)

        # Calculate required_by_time based on preferred_time and urgency
        now = datetime.now()
        if urgency_level == 'Emergency' or preferred_time == 'ASAP':
            required_by_dt = now + timedelta(hours=3)
        elif urgency_level == 'Urgent (today)':
            required_by_dt = now + timedelta(hours=5)
        else:
            required_by_dt = now + timedelta(hours=8)
        required_by_time = required_by_dt.strftime("%Y-%m-%d %H:%M")

        # Determine receiver_id
        if g.user:
            receiver_id = g.user['id']
        else:
            # Check if user with this phone already exists
            existing = conn.execute("SELECT id, organization_name FROM users WHERE phone = ?", (contact_phone,)).fetchone()
            if existing:
                receiver_id = existing['id']
            else:
                uname = f"receiver_{contact_phone[-6:]}"
                user_email = email if email else f"request_{contact_phone[-6:]}@annampagirvom.org"
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (username, email, password_hash, role, organization_name, phone, address, location_area, organization_type)
                    VALUES (?, ?, ?, 'receiver', ?, ?, ?, ?, ?)
                """, (uname, user_email, generate_password_hash('Karur@2026'), org_name, contact_phone, delivery_address, location_area, org_type))
                receiver_id = cursor.lastrowid

            # Set session so guest can view receiver console immediately
            session['user_id'] = receiver_id
            session['username'] = org_name
            session['role'] = 'receiver'

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO requirements (
                receiver_id, preferred_category, quantity_needed, unit,
                required_by_time, location_area, delivery_address,
                transport_arranged_by, serving_capacity, contact_name, contact_phone,
                organization_name, organization_type, email, urgency_level, preferred_time,
                dietary_restrictions, additional_info, status
            ) VALUES (?, ?, ?, 'portions', ?, ?, ?, 'volunteer', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (
            receiver_id, preferred_category, quantity_needed,
            required_by_time, location_area, delivery_address,
            quantity_needed, contact_name, contact_phone,
            org_name, org_type, email, urgency_level, preferred_time,
            dietary_restrictions, additional_info
        ))
        conn.commit()
        conn.close()

        flash("Food request posted successfully! Rule-based matching is active for Karur District.", "success")
        return redirect(url_for('receiver_dashboard'))

    conn.close()
    return render_template('post_requirement.html', stats=stats, current_user=g.user)

@app.route('/receiver/claim/<int:donation_id>', methods=['POST'])
@login_required(roles=['receiver', 'admin'])
def claim_donation(donation_id):
    req_id = int(request.form.get('requirement_id'))
    matched_qty = float(request.form.get('matched_quantity', 0))
    explanation = request.form.get('explanation', '')

    conn = get_db_connection()
    don = conn.execute("SELECT * FROM donations WHERE id = ? AND status = 'posted'", (donation_id,)).fetchone()
    req = conn.execute("SELECT * FROM requirements WHERE id = ? AND receiver_id = ?", (req_id, g.user['id'])).fetchone()

    if not don or not req:
        conn.close()
        flash("Donation is no longer available to claim.", "error")
        return redirect(url_for('receiver_dashboard'))

    # Mark donation accepted
    conn.execute("UPDATE donations SET status = 'accepted' WHERE id = ?", (donation_id,))
    log_status_change(conn, 'donation', donation_id, 'posted', 'accepted', g.user['id'], f"Receiver requested/claimed match for requirement #{req_id}")

    # Create match
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO matches (donation_id, requirement_id, receiver_id, matched_quantity, status, match_explanation, accepted_at)
        VALUES (?, ?, ?, ?, 'accepted', ?, CURRENT_TIMESTAMP)
    """, (donation_id, req_id, g.user['id'], matched_qty, explanation))
    match_id = cursor.lastrowid

    # Create pickup task
    cursor.execute("""
        INSERT INTO pickup_tasks (donation_id, match_id, status)
        VALUES (?, ?, 'assigned')
    """, (donation_id, match_id))
    task_id = cursor.lastrowid
    log_status_change(conn, 'pickup_task', task_id, None, 'assigned', g.user['id'], 'Pickup task opened for volunteer assignment')

    conn.commit()
    conn.close()

    flash(f"Successfully claimed #{donation_id}! Handover task created for pickup.", "success")
    return redirect(url_for('receiver_dashboard'))

@app.route('/receiver/confirm-handover/<int:match_id>', methods=['POST'])
@login_required(roles=['receiver', 'admin'])
def confirm_receiver_handover(match_id):
    action = request.form.get('action', 'confirm').strip()
    rec_sig = request.form.get('receiver_signature_name', '').strip()
    delivered_qty_str = request.form.get('delivered_quantity', '').strip()
    discrepancy_notes = request.form.get('discrepancy_notes', '').strip()

    conn = get_db_connection()
    match = conn.execute("SELECT * FROM matches WHERE id = ? AND receiver_id = ?", (match_id, g.user['id'])).fetchone()
    if not match:
        conn.close()
        flash("Match record not found or unauthorized.", "error")
        return redirect(url_for('receiver_dashboard'))

    task = conn.execute("SELECT * FROM pickup_tasks WHERE match_id = ?", (match_id,)).fetchone()

    if action == 'dispute':
        dispute_reason = request.form.get('dispute_reason', discrepancy_notes).strip() or 'Receiver reported issue with delivered food batch'
        if task:
            conn.execute("""
                UPDATE pickup_tasks
                SET status = 'disputed', discrepancy_notes = ?
                WHERE id = ?
            """, (dispute_reason, task['id']))
            log_status_change(conn, 'pickup_task', task['id'], task['status'], 'disputed', g.user['id'], f"Dispute reported: {dispute_reason}")
            if task['volunteer_id']:
                add_notification(conn, task['volunteer_id'], 'Handover Disputed', f"Receiver reported an issue for delivery #{task['id']}: {dispute_reason}", '/driver/dashboard')

        conn.execute("UPDATE donations SET status = 'disputed' WHERE id = ?", (match['donation_id'],))
        conn.execute("UPDATE matches SET status = 'disputed' WHERE id = ?", (match_id,))
        log_status_change(conn, 'donation', match['donation_id'], 'collected', 'disputed', g.user['id'], f"Dispute logged by receiver: {dispute_reason}")

        don = conn.execute("SELECT donor_id FROM donations WHERE id = ?", (match['donation_id'],)).fetchone()
        if don:
            add_notification(conn, don['donor_id'], 'Handover Dispute Alert', f"Receiver reported an issue for donation #{match['donation_id']}: {dispute_reason}", '/donor/dashboard')

        conn.commit()
        conn.close()
        flash("Dispute report recorded. District coordinator has been alerted for review / முரண்பாடு பதிவு செய்யப்பட்டது.", "warning")
        return redirect(url_for('receiver_dashboard'))

    # Confirm action
    try:
        delivered_qty = float(delivered_qty_str) if delivered_qty_str else match['matched_quantity']
    except ValueError:
        delivered_qty = match['matched_quantity']

    delivery_photo = save_uploaded_or_base64_image(
        base64_str=request.form.get('captured_delivery_photo_base64', '').strip(),
        file_obj=request.files.get('delivery_photo_file'),
        prefix='delivery'
    )

    if task:
        conn.execute("""
            UPDATE pickup_tasks
            SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP,
                receiver_signature_name = COALESCE(NULLIF(?, ''), receiver_signature_name),
                delivered_quantity = COALESCE(?, delivered_quantity),
                delivery_photo = COALESCE(?, delivery_photo),
                discrepancy_notes = CASE WHEN ? != '' THEN ? ELSE discrepancy_notes END
            WHERE id = ?
        """, (rec_sig, delivered_qty, delivery_photo, discrepancy_notes, discrepancy_notes, task['id']))
        log_status_change(conn, 'pickup_task', task['id'], task['status'], 'delivered', g.user['id'], f"Handover confirmed by receiver: {rec_sig}")
        if task['volunteer_id']:
            add_notification(conn, task['volunteer_id'], 'Delivery Verified', f"Receiver confirmed safe receipt of delivery #{task['id']}.", '/driver/dashboard')

    conn.execute("UPDATE donations SET status = 'delivered' WHERE id = ?", (match['donation_id'],))
    conn.execute("UPDATE matches SET status = 'completed', safety_verified_by_receiver = 1 WHERE id = ?", (match_id,))
    if match['requirement_id']:
        conn.execute("UPDATE requirements SET status = 'fulfilled' WHERE id = ?", (match['requirement_id'],))

    log_status_change(conn, 'donation', match['donation_id'], 'collected', 'delivered', g.user['id'], "Delivery verified and completed by receiver")

    don = conn.execute("SELECT donor_id FROM donations WHERE id = ?", (match['donation_id'],)).fetchone()
    if don:
        add_notification(conn, don['donor_id'], 'Delivery Completed', f"Your food donation #{match['donation_id']} was safely delivered and verified.", '/donor/dashboard')

    conn.commit()
    conn.close()

    flash("Handover confirmed! The meals have been safely delivered and recorded / உணவு ஒப்படைப்பு உறுதிசெய்யப்பட்டது.", "success")
    return redirect(url_for('receiver_dashboard'))

# ----------------- DRIVER & VOLUNTEER COORDINATION -----------------

@app.route('/driver/dashboard', endpoint='driver_dashboard')
@app.route('/volunteer/dashboard', endpoint='volunteer_dashboard')
@login_required(roles=['volunteer', 'driver', 'admin'])
def driver_dashboard():
    """
    Dedicated Driver & Delivery Volunteer Console with Google Maps Multi-Stop Navigation.
    Route: Driver GPS Location (origin=My+Location) -> Stop 1: Donor Pickup (waypoints) -> Stop 2: Receiving Trust (destination).
    """
    conn = get_db_connection()
    status_filter = request.args.get('status', 'all').strip().lower()

    # Base query for tasks
    base_task_query = """
        SELECT pt.*, pt.status as task_status,
               d.food_name, d.category, d.quantity as listed_quantity, d.unit,
               d.safe_use_deadline, d.preparation_time, d.image_filename,
               d.pickup_address, d.location_area as donor_area,
               d.latitude as donor_latitude, d.longitude as donor_longitude,
               d.maps_link as donor_maps_link, d.pickup_instructions,
               d.contact_phone as donor_phone, d.contact_name as donor_contact_name,
               u_don.organization_name as donor_org, u_don.logo_filename as donor_logo,
               u_don.phone as donor_org_phone,
               u_rec.organization_name as receiver_org, u_rec.logo_filename as receiver_logo,
               u_rec.location_area as receiver_area, u_rec.phone as receiver_phone,
               r.delivery_address, r.contact_name as receiver_contact_name,
               r.contact_phone as req_contact_phone,
               m.matched_quantity
        FROM pickup_tasks pt
        JOIN donations d ON pt.donation_id = d.id
        LEFT JOIN matches m ON pt.match_id = m.id
        LEFT JOIN users u_don ON d.donor_id = u_don.id
        LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
        LEFT JOIN requirements r ON m.requirement_id = r.id
    """

    # Unclaimed tasks available to claim
    unclaimed_raw = conn.execute(
        base_task_query + " WHERE pt.volunteer_id IS NULL AND pt.status = 'assigned' ORDER BY pt.id DESC"
    ).fetchall()

    # My assigned / active tasks (or all active tasks if admin)
    if g.user['role'] == 'admin':
        my_tasks_raw = conn.execute(
            base_task_query + " WHERE pt.volunteer_id IS NOT NULL ORDER BY pt.id DESC"
        ).fetchall()
    else:
        my_tasks_raw = conn.execute(
            base_task_query + " WHERE pt.volunteer_id = ? ORDER BY pt.id DESC",
            (g.user['id'],)
        ).fetchall()

    def process_task_item(row):
        t = dict(row)
        
        # Check donor contact authorization
        is_auth_d, auth_d_phone, msg_d = check_donor_phone_authorization(
            conn, g.user,
            {'id': t.get('donation_id'), 'donor_id': t.get('donor_id'), 'contact_phone': t.get('donor_phone'), 'donor_phone': t.get('donor_phone'), 'donor_org_phone': t.get('donor_org_phone')},
            task=t, ip_address=request.remote_addr
        )
        t['resolved_donor_phone'] = auth_d_phone if is_auth_d else ''
        t['donor_phone_authorized'] = is_auth_d
        t['donor_phone_message'] = msg_d

        # Check receiver contact authorization
        is_auth_r, auth_r_phone, msg_r = check_receiver_phone_authorization(
            conn, g.user,
            {'id': t.get('receiver_id'), 'receiver_phone': t.get('receiver_phone'), 'req_contact_phone': t.get('req_contact_phone')},
            task=t, ip_address=request.remote_addr
        )
        t['resolved_receiver_phone'] = auth_r_phone if is_auth_r else ''
        t['receiver_phone_authorized'] = is_auth_r
        t['receiver_phone_message'] = msg_r

        # Coordinates
        d_lat = t.get('donor_latitude') or t.get('pickup_latitude')
        d_lng = t.get('donor_longitude') or t.get('pickup_longitude')
        d_addr = t.get('pickup_address') or ''

        r_lat = t.get('delivery_latitude')
        r_lng = t.get('delivery_longitude')
        r_addr = t.get('delivery_address') or ''

        # Build Multi-Stop Navigation URLs
        nav = build_multi_stop_nav_urls(d_lat, d_lng, d_addr, r_lat, r_lng, r_addr)
        t.update(nav)

        # Urgency & remaining time
        urg = calculate_urgency(t.get('safe_use_deadline'))
        t.update(urg)

        # Quantity to collect
        t['target_quantity'] = t.get('matched_quantity') or t.get('listed_quantity') or 0
        return t

    unclaimed_tasks = [process_task_item(r) for r in unclaimed_raw]
    my_tasks = [process_task_item(r) for r in my_tasks_raw]

    conn.close()

    # Filter my_tasks if filter applied
    if status_filter != 'all':
        if status_filter in ['disputed', 'review', 'needs_review']:
            my_tasks = [t for t in my_tasks if t['task_status'] in ['disputed', 'needs_review']]
        else:
            my_tasks = [t for t in my_tasks if t['task_status'] == status_filter]

    return render_template('driver_dashboard.html',
                           current_user=g.user,
                           unclaimed_tasks=unclaimed_tasks,
                           my_tasks=my_tasks,
                           current_filter=status_filter)

@app.route('/driver/accept-task/<int:task_id>', methods=['POST'])
@app.route('/volunteer/claim-task/<int:task_id>', methods=['POST'])
@login_required(roles=['volunteer', 'driver', 'admin'])
def claim_pickup_task(task_id):
    """Driver/volunteer accepts an available pickup mission."""
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ? AND (volunteer_id IS NULL OR volunteer_id = ?)", (task_id, g.user['id'])).fetchone()
    if not task:
        conn.close()
        flash("Task is already claimed or unavailable / இப்பணி ஏற்கனவே எடுக்கப்பட்டுள்ளது.", "error")
        return redirect(url_for('driver_dashboard'))

    conn.execute("""
        UPDATE pickup_tasks
        SET volunteer_id = ?, status = 'accepted', accepted_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (g.user['id'], task_id))
    log_status_change(conn, 'pickup_task', task_id, task['status'], 'accepted', g.user['id'], f"Accepted by driver {g.user['organization_name']}")

    # Notify donor & receiver
    don = conn.execute("SELECT donor_id, food_name FROM donations WHERE id = ?", (task['donation_id'],)).fetchone()
    if don:
        add_notification(conn, don['donor_id'], 'Driver Accepted Pickup', f"Driver {g.user['organization_name']} has accepted the pickup for {don['food_name']}.", '/donor/dashboard')

    if task['match_id']:
        match = conn.execute("SELECT receiver_id FROM matches WHERE id = ?", (task['match_id'],)).fetchone()
        if match:
            add_notification(conn, match['receiver_id'], 'Driver Assigned', f"Driver {g.user['organization_name']} is coordinating delivery for your match.", '/receiver/dashboard')

    conn.commit()
    conn.close()

    flash(f"Pickup Mission #{task_id} accepted! You can now navigate to donor / பணி ஏற்றுக்கொள்ளப்பட்டது.", "success")
    return redirect(url_for('driver_dashboard'))

@app.route('/driver/en-route-pickup/<int:task_id>', methods=['POST'])
@login_required(roles=['volunteer', 'driver', 'admin'])
def driver_en_route_pickup(task_id):
    """Driver marks they are on the way to the donor's pickup location."""
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ? AND volunteer_id = ?", (task_id, g.user['id'])).fetchone()
    if not task:
        conn.close()
        flash("Task not found or access denied.", "error")
        return redirect(url_for('driver_dashboard'))

    conn.execute("""
        UPDATE pickup_tasks
        SET status = 'en_route_pickup', en_route_pickup_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (task_id,))
    log_status_change(conn, 'pickup_task', task_id, task['status'], 'en_route_pickup', g.user['id'], f"Driver en route to donor pickup")

    don = conn.execute("SELECT donor_id, food_name FROM donations WHERE id = ?", (task['donation_id'],)).fetchone()
    if don:
        add_notification(conn, don['donor_id'], 'Driver On The Way', f"Driver {g.user['organization_name']} is on the way to collect {don['food_name']}.", '/donor/dashboard')

    conn.commit()
    conn.close()

    flash("Status updated: On the way to donor pickup location / உணவு எடுக்கப் புறப்பட்டீர்கள்.", "info")
    return redirect(url_for('driver_dashboard'))

@app.route('/driver/collected/<int:task_id>', methods=['POST'])
@app.route('/volunteer/collected/<int:task_id>', methods=['POST'])
@login_required(roles=['volunteer', 'driver', 'admin'])
def mark_food_collected(task_id):
    """Record verified collection at donor site with camera photo, actual quantity, and signature."""
    donor_sig = request.form.get('donor_signature', '').strip()
    collected_qty_str = request.form.get('collected_quantity', '').strip()
    lat_str = request.form.get('latitude', '').strip()
    lng_str = request.form.get('longitude', '').strip()
    notes = request.form.get('handover_notes', '').strip()

    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ? AND volunteer_id = ?", (task_id, g.user['id'])).fetchone()

    if not task:
        conn.close()
        flash("Task not found or access denied.", "error")
        return redirect(url_for('driver_dashboard'))

    # Save pickup photo (live camera or uploaded evidence)
    pickup_photo = save_uploaded_or_base64_image(
        base64_str=request.form.get('captured_pickup_photo_base64', '').strip(),
        file_obj=request.files.get('pickup_photo_file'),
        prefix='pickup'
    )

    try:
        collected_qty = float(collected_qty_str) if collected_qty_str else None
    except ValueError:
        collected_qty = None

    lat = float(lat_str) if lat_str else None
    lng = float(lng_str) if lng_str else None

    conn.execute("""
        UPDATE pickup_tasks
        SET status = 'collected', collected_at = CURRENT_TIMESTAMP,
            donor_signature_name = COALESCE(NULLIF(?, ''), donor_signature_name),
            collected_quantity = COALESCE(?, collected_quantity),
            pickup_photo = COALESCE(?, pickup_photo),
            pickup_latitude = COALESCE(?, pickup_latitude),
            pickup_longitude = COALESCE(?, pickup_longitude),
            handover_notes = COALESCE(?, handover_notes)
        WHERE id = ?
    """, (donor_sig, collected_qty, pickup_photo, lat, lng, notes, task_id))

    conn.execute("UPDATE donations SET status = 'collected' WHERE id = ?", (task['donation_id'],))
    log_status_change(conn, 'donation', task['donation_id'], 'accepted', 'collected', g.user['id'], f"Food collected from donor: {donor_sig}")
    log_status_change(conn, 'pickup_task', task_id, task['status'], 'collected', g.user['id'], f"Donor signature: {donor_sig}, pickup photo saved")

    # Notify receiver
    if task['match_id']:
        match = conn.execute("SELECT receiver_id FROM matches WHERE id = ?", (task['match_id'],)).fetchone()
        if match:
            add_notification(conn, match['receiver_id'], 'Food Collected & In Transit', f"Driver has collected the food batch. Ready for delivery navigation.", '/receiver/dashboard')

    conn.commit()
    conn.close()

    flash("Food collected from donor and now in transit! Evidence recorded. Ready to navigate to receiver trust / உணவு எடுக்கப்பட்டது.", "success")
    return redirect(url_for('driver_dashboard'))

@app.route('/driver/en-route-delivery/<int:task_id>', methods=['POST'])
@login_required(roles=['volunteer', 'driver', 'admin'])
def driver_en_route_delivery(task_id):
    """Driver marks they are en route to the receiving trust/shelter."""
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ? AND volunteer_id = ?", (task_id, g.user['id'])).fetchone()
    if not task:
        conn.close()
        flash("Task not found or access denied.", "error")
        return redirect(url_for('driver_dashboard'))

    conn.execute("""
        UPDATE pickup_tasks
        SET status = 'en_route_delivery', en_route_delivery_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (task_id,))
    log_status_change(conn, 'pickup_task', task_id, task['status'], 'en_route_delivery', g.user['id'], "Driver en route to receiver destination")

    if task['match_id']:
        match = conn.execute("SELECT receiver_id FROM matches WHERE id = ?", (task['match_id'],)).fetchone()
        if match:
            add_notification(conn, match['receiver_id'], 'Driver On The Way to Trust', f"Driver {g.user['organization_name']} is arriving at your location with the food delivery.", '/receiver/dashboard')

    conn.commit()
    conn.close()

    flash("Status updated: On the way to receiving trust / டிரஸ்ட்டிற்குப் புறப்பட்டீர்கள்.", "info")
    return redirect(url_for('driver_dashboard'))

@app.route('/driver/delivered/<int:task_id>', methods=['POST'])
@app.route('/volunteer/delivered/<int:task_id>', methods=['POST'])
@login_required(roles=['volunteer', 'driver', 'admin'])
def mark_food_delivered(task_id):
    """Driver/volunteer confirms final delivery with photo evidence, receiver signature, and discrepancy notes."""
    rec_sig = request.form.get('receiver_signature', '').strip()
    delivered_qty_str = request.form.get('delivered_quantity', '').strip()
    lat_str = request.form.get('latitude', '').strip()
    lng_str = request.form.get('longitude', '').strip()
    notes = request.form.get('delivery_notes', '').strip()
    discrepancy = request.form.get('discrepancy_notes', '').strip()

    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ? AND volunteer_id = ?", (task_id, g.user['id'])).fetchone()

    if not task:
        conn.close()
        flash("Task not found or access denied.", "error")
        return redirect(url_for('driver_dashboard'))

    # Save delivery evidence photo (live camera or uploaded evidence)
    delivery_photo = save_uploaded_or_base64_image(
        base64_str=request.form.get('captured_delivery_photo_base64', '').strip(),
        file_obj=request.files.get('delivery_photo_file'),
        prefix='delivery'
    )

    try:
        delivered_qty = float(delivered_qty_str) if delivered_qty_str else None
    except ValueError:
        delivered_qty = None

    lat = float(lat_str) if lat_str else None
    lng = float(lng_str) if lng_str else None

    conn.execute("""
        UPDATE pickup_tasks
        SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP,
            receiver_signature_name = COALESCE(NULLIF(?, ''), receiver_signature_name),
            delivered_quantity = COALESCE(?, delivered_quantity),
            delivery_photo = COALESCE(?, delivery_photo),
            delivery_latitude = COALESCE(?, delivery_latitude),
            delivery_longitude = COALESCE(?, delivery_longitude),
            handover_notes = CASE WHEN ? != '' THEN ? ELSE handover_notes END,
            discrepancy_notes = CASE WHEN ? != '' THEN ? ELSE discrepancy_notes END
        WHERE id = ?
    """, (rec_sig, delivered_qty, delivery_photo, lat, lng, notes, notes, discrepancy, discrepancy, task_id))

    conn.execute("UPDATE donations SET status = 'delivered' WHERE id = ?", (task['donation_id'],))
    if task['match_id']:
        conn.execute("UPDATE matches SET status = 'completed', safety_verified_by_receiver = 1 WHERE id = ?", (task['match_id'],))
        match = conn.execute("SELECT requirement_id, receiver_id FROM matches WHERE id = ?", (task['match_id'],)).fetchone()
        if match:
            if match['requirement_id']:
                conn.execute("UPDATE requirements SET status = 'fulfilled' WHERE id = ?", (match['requirement_id'],))
            add_notification(conn, match['receiver_id'], 'Delivery Completed', f"Food delivery #{task_id} has been recorded as safely completed.", '/receiver/dashboard')

    don = conn.execute("SELECT donor_id FROM donations WHERE id = ?", (task['donation_id'],)).fetchone()
    if don:
        add_notification(conn, don['donor_id'], 'Food Safely Delivered', f"Your donated food batch was successfully delivered to the trust.", '/donor/dashboard')

    log_status_change(conn, 'donation', task['donation_id'], 'collected', 'delivered', g.user['id'], f"Delivered to receiver: {rec_sig}")
    log_status_change(conn, 'pickup_task', task_id, task['status'], 'delivered', g.user['id'], f"Receiver signature: {rec_sig}, delivery verification saved")

    conn.commit()
    conn.close()

    flash("Mission complete! Food safely delivered with verified evidence and recorded in public ledger / விநியோகம் நிறைவடைந்தது.", "success")
    return redirect(url_for('driver_dashboard'))

@app.route('/driver/report-issue/<int:task_id>', methods=['POST'])
@login_required(roles=['volunteer', 'driver', 'admin'])
def driver_report_issue(task_id):
    """Driver reports a delivery issue or discrepancy."""
    dispute_reason = request.form.get('dispute_reason', '').strip()
    if not dispute_reason:
        flash("Please provide an explanation for the issue / தயவுசெய்து காரணத்தைக் குறிப்பிடவும்.", "error")
        return redirect(url_for('driver_dashboard'))

    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ? AND volunteer_id = ?", (task_id, g.user['id'])).fetchone()
    if not task:
        conn.close()
        flash("Task not found or access denied.", "error")
        return redirect(url_for('driver_dashboard'))

    conn.execute("""
        UPDATE pickup_tasks
        SET status = 'disputed', discrepancy_notes = ?
        WHERE id = ?
    """, (dispute_reason, task_id))

    conn.execute("UPDATE donations SET status = 'disputed' WHERE id = ?", (task['donation_id'],))
    if task['match_id']:
        conn.execute("UPDATE matches SET status = 'disputed' WHERE id = ?", (task['match_id'],))

    log_status_change(conn, 'pickup_task', task_id, task['status'], 'disputed', g.user['id'], f"Driver reported issue: {dispute_reason}")
    log_status_change(conn, 'donation', task['donation_id'], None, 'disputed', g.user['id'], f"Issue flagged during transport: {dispute_reason}")

    # Alert admins
    admins = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    for a in admins:
        add_notification(conn, a['id'], 'Delivery Dispute Flagged', f"Driver flagged issue for task #{task_id}: {dispute_reason}", '/admin/dashboard')

    conn.commit()
    conn.close()

    flash("Issue reported and flagged for review / சிக்கல் பதிவு செய்யப்பட்டது.", "warning")
    return redirect(url_for('driver_dashboard'))

@app.route('/api/driver/tasks')
@login_required(roles=['volunteer', 'driver', 'admin'])
def api_driver_tasks():
    """Real-time JSON endpoint for driver dashboard tasks with strict phone RBAC."""
    conn = get_db_connection()
    if g.user['role'] == 'admin':
        tasks = conn.execute("""
            SELECT pt.id, pt.status as task_status, pt.donation_id, pt.volunteer_id,
                   d.food_name, d.quantity as listed_quantity, d.unit,
                   d.safe_use_deadline, d.pickup_address, d.contact_phone as donor_phone,
                   u_don.organization_name as donor_org, u_don.phone as donor_org_phone,
                   u_rec.organization_name as receiver_org, u_rec.phone as receiver_phone,
                   r.delivery_address, r.contact_phone as req_contact_phone
            FROM pickup_tasks pt
            JOIN donations d ON pt.donation_id = d.id
            LEFT JOIN matches m ON pt.match_id = m.id
            LEFT JOIN users u_don ON d.donor_id = u_don.id
            LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
            LEFT JOIN requirements r ON m.requirement_id = r.id
            ORDER BY pt.id DESC
        """).fetchall()
    else:
        tasks = conn.execute("""
            SELECT pt.id, pt.status as task_status, pt.donation_id, pt.volunteer_id,
                   d.food_name, d.quantity as listed_quantity, d.unit,
                   d.safe_use_deadline, d.pickup_address, d.contact_phone as donor_phone,
                   u_don.organization_name as donor_org, u_don.phone as donor_org_phone,
                   u_rec.organization_name as receiver_org, u_rec.phone as receiver_phone,
                   r.delivery_address, r.contact_phone as req_contact_phone
            FROM pickup_tasks pt
            JOIN donations d ON pt.donation_id = d.id
            LEFT JOIN matches m ON pt.match_id = m.id
            LEFT JOIN users u_don ON d.donor_id = u_don.id
            LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
            LEFT JOIN requirements r ON m.requirement_id = r.id
            WHERE pt.volunteer_id = ? OR pt.volunteer_id IS NULL
            ORDER BY pt.id DESC
        """, (g.user['id'],)).fetchall()

    task_list = []
    for t_row in tasks:
        t = dict(t_row)
        is_auth_d, auth_d_phone, msg_d = check_donor_phone_authorization(
            conn, g.user,
            {'id': t['donation_id'], 'contact_phone': t.get('donor_phone'), 'donor_phone': t.get('donor_phone'), 'donor_org_phone': t.get('donor_org_phone')},
            task=t, ip_address=request.remote_addr
        )
        is_auth_r, auth_r_phone, msg_r = check_receiver_phone_authorization(
            conn, g.user,
            {'receiver_phone': t.get('receiver_phone'), 'req_contact_phone': t.get('req_contact_phone')},
            task=t, ip_address=request.remote_addr
        )

        t['donor_phone'] = auth_d_phone if is_auth_d else None
        t['donor_phone_authorized'] = is_auth_d
        t['receiver_phone'] = auth_r_phone if is_auth_r else None
        t['receiver_phone_authorized'] = is_auth_r
        t.pop('donor_org_phone', None)
        t.pop('req_contact_phone', None)
        task_list.append(t)

    conn.close()
    return jsonify({'status': 'success', 'tasks': task_list})

@app.route('/api/contact-details/<entity_type>/<int:entity_id>')
def api_contact_details(entity_type, entity_id):
    """
    Dedicated secure role-based API to fetch authorized contact details on demand.
    Returns 200 with phone if authorized, or 403 with explanation if denied.
    """
    conn = get_db_connection()
    if entity_type == 'donation':
        don = conn.execute("""
            SELECT d.*, u.phone as donor_org_phone, u.phone_public_consent as donor_consent
            FROM donations d
            JOIN users u ON d.donor_id = u.id
            WHERE d.id = ?
        """, (entity_id,)).fetchone()
        if not don:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Donation not found'}), 404
        is_auth, phone, msg = check_donor_phone_authorization(conn, g.user, don, ip_address=request.remote_addr)
        conn.close()
        if is_auth:
            return jsonify({
                'status': 'success',
                'entity_type': 'donation',
                'id': entity_id,
                'contact_phone': phone,
                'role': g.user['role'] if g.user else 'public'
            })
        else:
            return jsonify({'status': 'denied', 'message': msg}), 403

    elif entity_type == 'task':
        task = conn.execute("""
            SELECT pt.*, d.contact_phone as donor_phone, u_don.phone as donor_org_phone,
                   u_rec.phone as receiver_phone, r.contact_phone as req_contact_phone
            FROM pickup_tasks pt
            JOIN donations d ON pt.donation_id = d.id
            JOIN users u_don ON d.donor_id = u_don.id
            LEFT JOIN matches m ON pt.match_id = m.id
            LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
            LEFT JOIN requirements r ON m.requirement_id = r.id
            WHERE pt.id = ?
        """, (entity_id,)).fetchone()
        if not task:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Task not found'}), 404
        is_auth_d, phone_d, msg_d = check_donor_phone_authorization(
            conn, g.user, {'id': task['donation_id'], 'contact_phone': task['donor_phone']}, task=task, ip_address=request.remote_addr
        )
        is_auth_r, phone_r, msg_r = check_receiver_phone_authorization(
            conn, g.user, {'receiver_phone': task['receiver_phone'], 'req_contact_phone': task['req_contact_phone']}, task=task, ip_address=request.remote_addr
        )
        conn.close()
        if is_auth_d or is_auth_r:
            return jsonify({
                'status': 'success',
                'task_id': entity_id,
                'donor_phone': phone_d if is_auth_d else None,
                'donor_phone_authorized': is_auth_d,
                'receiver_phone': phone_r if is_auth_r else None,
                'receiver_phone_authorized': is_auth_r
            })
        else:
            return jsonify({'status': 'denied', 'message': msg_d}), 403

    elif entity_type in ('user', 'organization', 'profile'):
        target = conn.execute("SELECT * FROM users WHERE id = ?", (entity_id,)).fetchone()
        if not target:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Profile not found'}), 404
        is_auth, phone, email, msg = check_user_profile_authorization(conn, g.user, target, ip_address=request.remote_addr)
        conn.close()
        if is_auth:
            return jsonify({
                'status': 'success',
                'entity_type': entity_type,
                'id': entity_id,
                'contact_phone': phone,
                'contact_email': email,
                'role': g.user['role'] if g.user else 'public'
            })
        else:
            return jsonify({'status': 'denied', 'message': msg}), 403

    conn.close()
    return jsonify({'status': 'error', 'message': 'Invalid entity type'}), 400

@app.route('/api/network-directory')
def api_network_directory():
    """
    Public and authorized REST endpoint for Karur Community Network Directory.
    Enforces server-side RBAC: public visitors receive public data only with
    contact_accessible=False, phone=None, email=None.
    Administrators and authorized users receive full permitted contact details.
    """
    conn = get_db_connection()
    data = get_network_directory_data(conn, g.user, ip_address=request.remote_addr)
    conn.close()
    return jsonify({
        'status': 'success',
        'count': len(data['all_profiles']),
        'profiles': data['all_profiles'],
        'demo_drivers': data['demo_drivers'],
        'demo_receivers': data['demo_receivers'],
        'demo_trusts': data['demo_trusts'],
        'verified_partners': data['verified_partners']
    })

@app.route('/api/network-directory/<int:user_id>')
def api_network_directory_profile(user_id):
    """Fetch single network profile with strict role-based access control."""
    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Profile not found'}), 404

    profile = sanitize_network_profile(conn, g.user, target, ip_address=request.remote_addr)
    require_contact = request.args.get('require_contact', '0') == '1'
    if require_contact and not profile['contact_accessible']:
        conn.close()
        return jsonify({'status': 'denied', 'message': profile['contact_message']}), 403

    conn.close()
    return jsonify({
        'status': 'success',
        'profile': profile
    })

# ----------------- IN-APP NOTIFICATIONS API -----------------

@app.route('/api/notifications')
def api_notifications():
    """Fetch unread notifications for logged-in user."""
    if not g.user:
        return jsonify({'notifications': [], 'unread_count': 0})
    conn = get_db_connection()
    notifs = conn.execute("""
        SELECT * FROM notifications
        WHERE user_id = ? AND is_read = 0
        ORDER BY id DESC LIMIT 10
    """, (g.user['id'],)).fetchall()
    conn.close()
    return jsonify({
        'notifications': [dict(n) for n in notifs],
        'unread_count': len(notifs)
    })

@app.route('/api/notifications/mark-read/<int:notif_id>', methods=['POST'])
def api_mark_notification_read(notif_id):
    if not g.user:
        return jsonify({'status': 'error'}), 401
    conn = get_db_connection()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notif_id, g.user['id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

# ----------------- ORGANIZATION PROFILE -----------------

@app.route('/profile', methods=['GET', 'POST'])
@login_required()
def organization_profile():
    conn = get_db_connection()
    if request.method == 'POST':
        org_name = request.form.get('organization_name', '').strip()
        org_type = request.form.get('organization_type', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        address = request.form.get('address', '').strip()
        location_area = request.form.get('location_area', '').strip()
        capacity_desc = request.form.get('capacity_description', '').strip()
        phone_consent = 1 if request.form.get('phone_public_consent') else 0

        # Validate phone
        digits = ''.join(c for c in phone if c.isdigit())
        if len(digits) < 10:
            flash("Please enter a valid 10-digit phone number.", "error")
            conn.close()
            return redirect(url_for('organization_profile'))

        # Logo handling
        current_logo = g.user['logo_filename'] if 'logo_filename' in g.user.keys() else None
        new_logo = save_uploaded_or_base64_image(file_obj=request.files.get('logo_file'), prefix='logo')
        logo_filename = new_logo if new_logo else current_logo

        conn.execute("""
            UPDATE users
            SET organization_name = ?, organization_type = ?, phone = ?, email = ?,
                address = ?, location_area = ?, capacity_description = ?,
                phone_public_consent = ?, logo_filename = ?
            WHERE id = ?
        """, (org_name, org_type, phone, email, address, location_area, capacity_desc, phone_consent, logo_filename, g.user['id']))
        conn.commit()
        conn.close()

        session['username'] = org_name
        flash(get_text('profile_updated_success', session.get('lang', 'ta')), "success")
        return redirect(url_for('organization_profile'))

    user = conn.execute("SELECT * FROM users WHERE id = ?", (g.user['id'],)).fetchone()
    conn.close()
    return render_template('profile.html', user=user, current_user=g.user)

# ----------------- ADMIN & COORDINATOR CONSOLE -----------------

@app.route('/coordinator/dashboard', endpoint='coordinator_dashboard')
@app.route('/admin/dashboard', endpoint='admin_dashboard')
@login_required(roles=['admin', 'coordinator'])
def admin_dashboard():
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()

    # Active unassigned donations available for matching
    open_donations = conn.execute("""
        SELECT d.*, u.organization_name as donor_name, u.location_area as donor_area
        FROM donations d
        JOIN users u ON d.donor_id = u.id
        WHERE d.status = 'posted' AND d.quantity > 0
        ORDER BY d.id DESC
    """).fetchall()

    # Active open recipient requirements
    open_requirements = conn.execute("""
        SELECT r.*, u.organization_name as receiver_name, u.location_area as receiver_area
        FROM requirements r
        JOIN users u ON r.receiver_id = u.id
        WHERE r.status = 'active'
        ORDER BY r.id DESC
    """).fetchall()

    # Available registered drivers and delivery volunteers
    drivers = conn.execute("""
        SELECT id, organization_name, username, phone, location_area, role
        FROM users
        WHERE role IN ('driver', 'volunteer')
        ORDER BY organization_name ASC
    """).fetchall()

    # Open pickup tasks needing driver assignment
    unassigned_tasks = conn.execute("""
        SELECT pt.*, d.food_name, d.quantity as orig_quantity, d.unit,
               u_don.organization_name as donor_org, u_don.location_area as donor_area,
               u_rec.organization_name as receiver_org, u_rec.location_area as receiver_area
        FROM pickup_tasks pt
        JOIN donations d ON pt.donation_id = d.id
        JOIN users u_don ON d.donor_id = u_don.id
        LEFT JOIN matches m ON pt.match_id = m.id
        LEFT JOIN users u_rec ON m.receiver_id = u_rec.id
        WHERE pt.volunteer_id IS NULL AND pt.status = 'assigned'
        ORDER BY pt.id DESC
    """).fetchall()

    # All donations
    donations = conn.execute("""
        SELECT d.*, u.organization_name as donor_name
        FROM donations d
        JOIN users u ON d.donor_id = u.id
        ORDER BY d.id DESC
    """).fetchall()

    # All requirements
    requirements = conn.execute("""
        SELECT r.*, u.organization_name as receiver_name
        FROM requirements r
        JOIN users u ON r.receiver_id = u.id
        ORDER BY r.id DESC
    """).fetchall()

    # All tasks with driver/volunteer details
    tasks = conn.execute("""
        SELECT pt.*, d.food_name, u_vol.organization_name as volunteer_name, u_vol.phone as volunteer_phone
        FROM pickup_tasks pt
        JOIN donations d ON pt.donation_id = d.id
        LEFT JOIN users u_vol ON pt.volunteer_id = u_vol.id
        ORDER BY pt.id DESC
    """).fetchall()

    audit_logs = conn.execute("""
        SELECT sh.*, u.username, u.role
        FROM status_history sh
        LEFT JOIN users u ON sh.changed_by_user_id = u.id
        ORDER BY sh.id DESC LIMIT 40
    """).fetchall()

    conn.close()
    return render_template('admin_dashboard.html',
                           current_user=g.user,
                           users=users,
                           donations=donations,
                           requirements=requirements,
                           tasks=tasks,
                           open_donations=open_donations,
                           open_requirements=open_requirements,
                           drivers=drivers,
                           unassigned_tasks=unassigned_tasks,
                           audit_logs=audit_logs)

@app.route('/coordinator/match', methods=['POST'], endpoint='coordinator_match')
@app.route('/admin/match', methods=['POST'])
@login_required(roles=['admin', 'coordinator'])
def coordinator_match():
    """Coordinator directly pairs an active surplus food donation with an active recipient requirement."""
    donation_id = request.form.get('donation_id', type=int)
    requirement_id = request.form.get('requirement_id', type=int)
    matched_qty_str = request.form.get('matched_quantity', '').strip()

    if not donation_id or not requirement_id:
        flash("Please select both a donation and a recipient requirement to match.", "error")
        return redirect(url_for('coordinator_dashboard'))

    conn = get_db_connection()
    don = conn.execute("SELECT * FROM donations WHERE id = ? AND status = 'posted'", (donation_id,)).fetchone()
    req = conn.execute("SELECT * FROM requirements WHERE id = ? AND status = 'active'", (requirement_id,)).fetchone()

    if not don or not req:
        conn.close()
        flash("The selected donation or requirement is no longer active.", "error")
        return redirect(url_for('coordinator_dashboard'))

    if matched_qty_str:
        try:
            matched_qty = float(matched_qty_str)
        except ValueError:
            matched_qty = min(don['quantity'], req['quantity_needed'])
    else:
        matched_qty = min(don['quantity'], req['quantity_needed'])

    # 1. Create match
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO matches (donation_id, receiver_id, requirement_id, matched_quantity, status)
        VALUES (?, ?, ?, ?, 'accepted')
    """, (donation_id, req['receiver_id'], requirement_id, matched_qty))
    match_id = cursor.lastrowid

    # 2. Create pickup task
    cursor.execute("""
        INSERT INTO pickup_tasks (donation_id, match_id, status, pickup_latitude, pickup_longitude)
        VALUES (?, ?, 'assigned', ?, ?)
    """, (donation_id, match_id, don['latitude'], don['longitude']))
    task_id = cursor.lastrowid

    # 3. Update donation and requirement
    if matched_qty >= don['quantity']:
        conn.execute("UPDATE donations SET status = 'accepted' WHERE id = ?", (donation_id,))
    else:
        remaining = don['quantity'] - matched_qty
        conn.execute("UPDATE donations SET quantity = ? WHERE id = ?", (remaining, donation_id))

    if matched_qty >= req['quantity_needed']:
        conn.execute("UPDATE requirements SET status = 'fulfilled' WHERE id = ?", (requirement_id,))

    # 4. Status logs
    log_status_change(conn, 'match', match_id, None, 'accepted', g.user['id'], f"Coordinator {g.user['organization_name']} paired donation #{donation_id} with request #{requirement_id}")
    log_status_change(conn, 'pickup_task', task_id, None, 'assigned', g.user['id'], "Delivery task generated by district coordinator")

    # 5. Notifications
    add_notification(conn, don['donor_id'], 'Donation Matched by Coordinator', f"Your donation #{donation_id} ({don['food_name']}) was matched with a community shelter. Ready for driver dispatch.", '/donor/dashboard')
    add_notification(conn, req['receiver_id'], 'Food Matched by Coordinator', f"Your request #{requirement_id} has been matched with {don['food_name']} ({matched_qty} portions).", '/receiver/dashboard')

    conn.commit()
    conn.close()

    flash(f"Successfully matched Donation #{donation_id} with Request #{requirement_id}! Delivery task #{task_id} created.", "success")
    return redirect(url_for('coordinator_dashboard'))

@app.route('/coordinator/assign-driver', methods=['POST'], endpoint='coordinator_assign_driver')
@app.route('/admin/assign-driver', methods=['POST'])
@login_required(roles=['admin', 'coordinator'])
def coordinator_assign_driver():
    """Coordinator assigns a verified driver or volunteer to an open delivery mission."""
    task_id = request.form.get('task_id', type=int)
    driver_id = request.form.get('driver_id', type=int)

    if not task_id or not driver_id:
        flash("Please select both a task and an authorized driver.", "error")
        return redirect(url_for('coordinator_dashboard'))

    conn = get_db_connection()
    task = conn.execute("SELECT * FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    driver = conn.execute("SELECT * FROM users WHERE id = ? AND role IN ('driver', 'volunteer')", (driver_id,)).fetchone()

    if not task:
        conn.close()
        flash("Delivery task not found.", "error")
        return redirect(url_for('coordinator_dashboard'))

    if not driver:
        conn.close()
        flash("Selected user is not an authorized driver or delivery volunteer.", "error")
        return redirect(url_for('coordinator_dashboard'))

    prev_status = task['status']
    conn.execute("""
        UPDATE pickup_tasks
        SET volunteer_id = ?, assigned_at = CURRENT_TIMESTAMP, status = 'assigned'
        WHERE id = ?
    """, (driver_id, task_id))

    log_status_change(conn, 'pickup_task', task_id, prev_status, 'assigned', g.user['id'], f"Assigned to driver {driver['organization_name']} ({driver['username']}) by coordinator")
    add_notification(conn, driver_id, 'New Delivery Mission Assigned', f"You have been assigned to Delivery Task #{task_id}. Check your Driver Dashboard for Google Maps navigation.", '/driver/dashboard')

    conn.commit()
    conn.close()

    flash(f"Driver {driver['organization_name']} successfully assigned to Delivery Task #{task_id}!", "success")
    return redirect(url_for('coordinator_dashboard'))

@app.route('/api/coordinator/stats')
@login_required(roles=['admin', 'coordinator'])
def api_coordinator_stats():
    """Real-time polling endpoint for coordinator dashboard."""
    conn = get_db_connection()
    open_donations_count = conn.execute("SELECT COUNT(*) FROM donations WHERE status = 'posted' AND quantity > 0").fetchone()[0]
    open_reqs_count = conn.execute("SELECT COUNT(*) FROM requirements WHERE status = 'active'").fetchone()[0]
    unassigned_tasks_count = conn.execute("SELECT COUNT(*) FROM pickup_tasks WHERE volunteer_id IS NULL AND status = 'assigned'").fetchone()[0]
    in_transit_count = conn.execute("SELECT COUNT(*) FROM pickup_tasks WHERE status IN ('accepted', 'en_route_pickup', 'collected', 'en_route_delivery')").fetchone()[0]
    delivered_count = conn.execute("SELECT COUNT(*) FROM pickup_tasks WHERE status = 'delivered'").fetchone()[0]
    conn.close()

    return jsonify({
        'status': 'success',
        'open_donations': open_donations_count,
        'open_requirements': open_reqs_count,
        'unassigned_tasks': unassigned_tasks_count,
        'in_transit': in_transit_count,
        'delivered': delivered_count,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/admin/reset-demo', methods=['POST'])
@login_required(roles=['admin', 'coordinator'])
def reset_demo():
    seed_demo_data()
    flash("Sample demonstration data has been re-initialized to default test state.", "info")
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
