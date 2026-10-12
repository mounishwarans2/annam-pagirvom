import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'foodbridge.db')

def get_db_connection(db_path=None):
    if db_path is None:
        db_path = DATABASE_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(db_path=None):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. Users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('donor', 'receiver', 'volunteer', 'driver', 'coordinator', 'admin')),
        organization_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT NOT NULL,
        location_area TEXT NOT NULL,
        capacity_description TEXT,
        organization_type TEXT,
        logo_filename TEXT,
        phone_public_consent INTEGER DEFAULT 0,
        is_demo INTEGER DEFAULT 0,
        verification_status TEXT DEFAULT 'verified',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Donations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER NOT NULL,
        food_name TEXT NOT NULL,
        description TEXT,
        category TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit TEXT NOT NULL DEFAULT 'portions',
        preparation_time TEXT NOT NULL,
        safe_use_deadline TEXT NOT NULL,
        pickup_address TEXT NOT NULL,
        location_area TEXT NOT NULL,
        earliest_pickup_time TEXT NOT NULL,
        storage_instructions TEXT,
        contact_name TEXT NOT NULL,
        contact_phone TEXT NOT NULL,
        image_filename TEXT,
        latitude REAL,
        longitude REAL,
        location_accuracy REAL,
        organization_type TEXT,
        additional_notes TEXT,
        maps_link TEXT,
        pickup_instructions TEXT,
        dietary_type TEXT DEFAULT 'veg',
        partial_allocation_allowed INTEGER DEFAULT 1,
        safety_verified_by_donor INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted', 'accepted', 'collected', 'delivered', 'cancelled', 'expired', 'disputed')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (donor_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 3. Receiver Requirements
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receiver_id INTEGER NOT NULL,
        preferred_category TEXT NOT NULL,
        quantity_needed REAL NOT NULL,
        unit TEXT NOT NULL DEFAULT 'portions',
        required_by_time TEXT NOT NULL,
        location_area TEXT NOT NULL,
        delivery_address TEXT NOT NULL,
        transport_arranged_by TEXT NOT NULL DEFAULT 'volunteer' CHECK(transport_arranged_by IN ('receiver', 'donor', 'volunteer', 'any')),
        serving_capacity REAL NOT NULL,
        contact_name TEXT NOT NULL,
        contact_phone TEXT NOT NULL,
        organization_name TEXT,
        organization_type TEXT,
        email TEXT,
        urgency_level TEXT DEFAULT 'Normal',
        preferred_time TEXT,
        dietary_restrictions TEXT,
        additional_info TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'fulfilled', 'cancelled', 'expired', 'disputed')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 4. Matches / Requests
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donation_id INTEGER NOT NULL,
        requirement_id INTEGER,
        receiver_id INTEGER NOT NULL,
        matched_quantity REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected', 'cancelled', 'completed', 'disputed')),
        match_explanation TEXT,
        safety_verified_by_receiver INTEGER DEFAULT 0,
        accepted_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (donation_id) REFERENCES donations(id) ON DELETE CASCADE,
        FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE SET NULL,
        FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 5. Pickup Tasks
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pickup_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donation_id INTEGER NOT NULL,
        match_id INTEGER,
        volunteer_id INTEGER,
        status TEXT NOT NULL DEFAULT 'assigned' CHECK(status IN ('assigned', 'accepted', 'en_route_pickup', 'collected', 'en_route_delivery', 'delivered', 'cancelled', 'disputed', 'needs_review')),
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        accepted_at TIMESTAMP,
        en_route_pickup_at TIMESTAMP,
        collected_at TIMESTAMP,
        en_route_delivery_at TIMESTAMP,
        delivered_at TIMESTAMP,
        handover_notes TEXT,
        driver_notes TEXT,
        donor_signature_name TEXT,
        receiver_signature_name TEXT,
        pickup_photo TEXT,
        delivery_photo TEXT,
        collected_quantity REAL,
        delivered_quantity REAL,
        pickup_latitude REAL,
        pickup_longitude REAL,
        delivery_latitude REAL,
        delivery_longitude REAL,
        discrepancy_notes TEXT,
        FOREIGN KEY (donation_id) REFERENCES donations(id) ON DELETE CASCADE,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL,
        FOREIGN KEY (volunteer_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    # 6. Status History / Audit Trail
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        previous_status TEXT,
        new_status TEXT NOT NULL,
        changed_by_user_id INTEGER,
        remarks TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (changed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    # 7. In-App Notifications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        link TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 8. Contact Access Audit Logs (Sensitive Donor/Receiver Phone Access)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contact_access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        contact_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        access_granted INTEGER NOT NULL,
        reason TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    # Safe Schema Migrations for existing DB instances
    user_cols = [c[1] for c in cursor.execute("PRAGMA table_info(users)").fetchall()]
    if 'logo_filename' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN logo_filename TEXT")
    if 'organization_type' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN organization_type TEXT")
    if 'phone_public_consent' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN phone_public_consent INTEGER DEFAULT 0")
    if 'is_demo' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN is_demo INTEGER DEFAULT 0")
    if 'verification_status' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN verification_status TEXT DEFAULT 'verified'")

    don_cols = [c[1] for c in cursor.execute("PRAGMA table_info(donations)").fetchall()]
    if 'maps_link' not in don_cols:
        cursor.execute("ALTER TABLE donations ADD COLUMN maps_link TEXT")
    if 'pickup_instructions' not in don_cols:
        cursor.execute("ALTER TABLE donations ADD COLUMN pickup_instructions TEXT")
    if 'dietary_type' not in don_cols:
        cursor.execute("ALTER TABLE donations ADD COLUMN dietary_type TEXT DEFAULT 'veg'")
    if 'partial_allocation_allowed' not in don_cols:
        cursor.execute("ALTER TABLE donations ADD COLUMN partial_allocation_allowed INTEGER DEFAULT 1")

    req_cols = [c[1] for c in cursor.execute("PRAGMA table_info(requirements)").fetchall()]
    if 'organization_name' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN organization_name TEXT")
    if 'organization_type' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN organization_type TEXT")
    if 'email' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN email TEXT")
    if 'urgency_level' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN urgency_level TEXT DEFAULT 'Normal'")
    if 'preferred_time' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN preferred_time TEXT")
    if 'dietary_restrictions' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN dietary_restrictions TEXT")
    if 'additional_info' not in req_cols:
        cursor.execute("ALTER TABLE requirements ADD COLUMN additional_info TEXT")

    task_cols = [c[1] for c in cursor.execute("PRAGMA table_info(pickup_tasks)").fetchall()]
    if 'accepted_at' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN accepted_at TIMESTAMP")
    if 'en_route_pickup_at' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN en_route_pickup_at TIMESTAMP")
    if 'en_route_delivery_at' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN en_route_delivery_at TIMESTAMP")
    if 'driver_notes' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN driver_notes TEXT")
    if 'pickup_photo' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN pickup_photo TEXT")
    if 'delivery_photo' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN delivery_photo TEXT")
    if 'collected_quantity' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN collected_quantity REAL")
    if 'delivered_quantity' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN delivered_quantity REAL")
    if 'pickup_latitude' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN pickup_latitude REAL")
    if 'pickup_longitude' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN pickup_longitude REAL")
    if 'delivery_latitude' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN delivery_latitude REAL")
    if 'delivery_longitude' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN delivery_longitude REAL")
    if 'discrepancy_notes' not in task_cols:
        cursor.execute("ALTER TABLE pickup_tasks ADD COLUMN discrepancy_notes TEXT")

    user_sql_row = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if user_sql_row and "'coordinator'" not in user_sql_row[0]:
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("""
        CREATE TABLE users_migrated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('donor', 'receiver', 'volunteer', 'driver', 'coordinator', 'admin')),
            organization_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            location_area TEXT NOT NULL,
            capacity_description TEXT,
            organization_type TEXT,
            logo_filename TEXT,
            phone_public_consent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("INSERT INTO users_migrated SELECT * FROM users")
        cursor.execute("DROP TABLE users")
        cursor.execute("ALTER TABLE users_migrated RENAME TO users")
        cursor.execute("PRAGMA foreign_keys = ON")

    seed_demo_network_profiles(conn)
    conn.commit()
    conn.close()

def log_status_change(conn, entity_type, entity_id, prev_status, new_status, user_id, remarks=None):
    conn.execute("""
        INSERT INTO status_history (entity_type, entity_id, previous_status, new_status, changed_by_user_id, remarks)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (entity_type, entity_id, prev_status, new_status, user_id, remarks))

def log_contact_access(conn, user_id, role, contact_type, entity_type, entity_id, access_granted, reason=None, ip_address=None):
    """Audit log for sensitive contact number views (administrators, drivers, recipients)."""
    try:
        conn.execute("""
            INSERT INTO contact_access_logs (user_id, role, contact_type, entity_type, entity_id, access_granted, reason, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, role, contact_type, entity_type, entity_id, 1 if access_granted else 0, reason, ip_address))
        conn.commit()
    except Exception as e:
        # Non-blocking audit log
        pass

def add_notification(conn, user_id, title, message, link=None):
    """Add in-app notification for coordinators, donors, receivers or drivers."""
    try:
        conn.execute("""
            INSERT INTO notifications (user_id, title, message, link)
            VALUES (?, ?, ?, ?)
        """, (user_id, title, message, link))
    except Exception as e:
        print(f"Error adding notification: {e}")

DEMO_NETWORK_PROFILES = [
    # 2 Volunteer Drivers
    {
        'username': 'demo_volunteer_01',
        'email': 'demo_volunteer_01@annampagirvom.invalid',
        'role': 'driver',
        'organization_name': 'Annam Demo Volunteer 01 (DEMO — NOT VERIFIED)',
        'phone': '555-0101-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Karur Central (Demo)',
        'organization_type': 'Volunteer Driver',
        'capacity_description': 'DEMO — NOT VERIFIED. Two-wheeler insulated carrier box.',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_volunteer_02',
        'email': 'demo_volunteer_02@annampagirvom.invalid',
        'role': 'driver',
        'organization_name': 'Annam Demo Volunteer 02 (DEMO — NOT VERIFIED)',
        'phone': '555-0102-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Vengamedu, Karur (Demo)',
        'organization_type': 'Volunteer Driver',
        'capacity_description': 'DEMO — NOT VERIFIED. Auto-rickshaw covered crates.',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    # 4 Food-Receiver Organizations
    {
        'username': 'demo_kakkum_karangal',
        'email': 'kakkum_karangal@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Kakkum Karangal Oldage Home (DEMO — NOT VERIFIED)',
        'phone': '555-0201-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Karur Area (Pending Verification)',
        'organization_type': 'Shelter/Orphanage',
        'capacity_description': 'DEMO — NOT VERIFIED. Elder care home (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_amaidhi_arakkattalai',
        'email': 'amaidhi_arakkattalai@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Amaidhi Illam Arakkattalai (DEMO — NOT VERIFIED)',
        'phone': '555-0202-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Karur Area (Pending Verification)',
        'organization_type': 'Shelter/Orphanage',
        'capacity_description': 'DEMO — NOT VERIFIED. Community care home (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_divine_power',
        'email': 'divine_power@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Divine Power Old Age Home (DEMO — NOT VERIFIED)',
        'phone': '555-0203-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Karur Area (Pending Verification)',
        'organization_type': 'Shelter/Orphanage',
        'capacity_description': 'DEMO — NOT VERIFIED. Senior living shelter (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_karthikeyan_home',
        'email': 'karthikeyan_home@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Karthikeyan Old Age Home (DEMO — NOT VERIFIED)',
        'phone': '555-0204-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Karur Area (Pending Verification)',
        'organization_type': 'Shelter/Orphanage',
        'capacity_description': 'DEMO — NOT VERIFIED. Elder care home (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    # 5 Children\'s-Home / Trust Profiles
    {
        'username': 'demo_happy_home_trust',
        'email': 'happy_home_trust@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Happy Home Trust (DEMO — NOT VERIFIED)',
        'phone': '555-0301-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Aravakurichi (Rajappuram Road hint)',
        'organization_type': 'Charitable Trust',
        'capacity_description': 'DEMO — NOT VERIFIED. Children’s home trust (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_psychology_trust',
        'email': 'psychology_trust@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Psychology Trust (DEMO — NOT VERIFIED)',
        'phone': '555-0302-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Vennamalai (Claret Nagar hint)',
        'organization_type': 'Charitable Trust',
        'capacity_description': 'DEMO — NOT VERIFIED. Welfare and youth trust (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_karur_anbukarangal',
        'email': 'karur_anbukarangal@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Karur Anbukarangal Society (DEMO — NOT VERIFIED)',
        'phone': '555-0303-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Vennamalai (Ganesh Nagar hint)',
        'organization_type': 'NGO',
        'capacity_description': 'DEMO — NOT VERIFIED. Children’s welfare society (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_csi_shanthinilayam',
        'email': 'csi_shanthinilayam@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'CSI Shanthinilayam (DEMO — NOT VERIFIED)',
        'phone': '555-0304-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Vengamedu, Karur',
        'organization_type': 'Charitable Trust',
        'capacity_description': 'DEMO — NOT VERIFIED. Children’s home hostel (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    },
    {
        'username': 'demo_amaidhi_illam_munnur',
        'email': 'amaidhi_illam_munnur@annampagirvom.invalid',
        'role': 'receiver',
        'organization_name': 'Amaidhi Illam — Arakkattalai, Munnur (DEMO — NOT VERIFIED)',
        'phone': '555-0305-DEMO',
        'address': 'Full address pending verification',
        'location_area': 'Munnur (Arakkattalai hint)',
        'organization_type': 'Charitable Trust',
        'capacity_description': 'DEMO — NOT VERIFIED. Care trust & shelter (capacity pending verification).',
        'is_demo': 1,
        'verification_status': 'DEMO — NOT VERIFIED'
    }
]

def seed_demo_network_profiles(conn=None, db_path=None):
    """Seed the 11 demo volunteer drivers, food receiver homes and charitable trusts idempotently."""
    close_at_end = False
    if conn is None:
        conn = get_db_connection(db_path)
        close_at_end = True

    demo_pw = generate_password_hash("DemoPass@123")
    cursor = conn.cursor()

    for p in DEMO_NETWORK_PROFILES:
        existing = cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (p['username'], p['email'])).fetchone()
        if not existing:
            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, role, organization_name,
                    phone, address, location_area, capacity_description,
                    organization_type, is_demo, verification_status, phone_public_consent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                p['username'], p['email'], demo_pw, p['role'], p['organization_name'],
                p['phone'], p['address'], p['location_area'], p['capacity_description'],
                p['organization_type'], p['is_demo'], p['verification_status']
            ))

    conn.commit()
    if close_at_end:
        conn.close()

def seed_demo_data(db_path=None):
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Clear old data for a clean demo state
    cursor.execute("DELETE FROM status_history")
    cursor.execute("DELETE FROM pickup_tasks")
    cursor.execute("DELETE FROM matches")
    cursor.execute("DELETE FROM requirements")
    cursor.execute("DELETE FROM donations")
    cursor.execute("DELETE FROM users")

    # Passwords hashed
    donor_pw = generate_password_hash("Donor@123")
    receiver_pw = generate_password_hash("Receiver@123")
    volunteer_pw = generate_password_hash("Volunteer@123")
    driver_pw = generate_password_hash("Driver@123")
    coordinator_pw = generate_password_hash("Coordinator@123")
    admin_pw = generate_password_hash("Admin@123")

    now = datetime.now()

    # 1. Seed Users (Karur District Partners)
    users = [
        (1, 'donor_hotel', 'donor@annampagirvom.org', donor_pw, 'donor', 'Hotel Archana Grand & Caterers', '9842412345', '45, Kovai Main Road, Vengamedu, Karur', 'Vengamedu', 'Daily restaurant & banquet catering surplus', 'Hotel', 'logo_archana.png', 0),
        (2, 'receiver_kitchen', 'receiver@annampagirvom.org', receiver_pw, 'receiver', 'Anbu Illam Karur Destitute Home', '9443156789', '12, Trichy Road, Gandhigramam, Karur', 'Gandhigramam', 'Serves 120 elderly and destitute individuals daily', 'Shelter/Orphanage', 'logo_anbu_illam.png', 1),
        (3, 'volunteer_saravanan', 'volunteer@annampagirvom.org', volunteer_pw, 'volunteer', 'Saravanan Karur Youth Food Rescue Team', '9789012345', '8, Jawahar Bazaar, Karur Town', 'Karur Town', '2 two-wheelers and insulated thermal food carrier boxes', 'Volunteer Group', None, 1),
        (4, 'admin_user', 'admin@annampagirvom.org', admin_pw, 'admin', 'Karur District Food Redistribution Center', '04324222333', 'Collectorate Road, Thanthonimalai, Karur', 'Thanthonimalai', 'District Operations & Quality Audits', 'District Authority', None, 1),
        (5, 'coordinator_karur', 'coordinator@annampagirvom.org', coordinator_pw, 'coordinator', 'Karur District Food Logistics Coordination Unit', '9443212345', 'Collectorate Complex, Thanthonimalai, Karur', 'Thanthonimalai', 'Central dispatching, matching & driver coordination', 'Coordination Desk', None, 1),
        (6, 'driver_muthu', 'driver@annampagirvom.org', driver_pw, 'driver', 'Muthu Rapid Express Delivery', '9894123456', '22, Bus Stand Road, Karur', 'Karur Town', 'Auto-rickshaw with covered crates & thermal insulation', 'Delivery Driver', None, 1)
    ]

    cursor.executemany("""
        INSERT INTO users (id, username, email, password_hash, role, organization_name, phone, address, location_area, capacity_description, organization_type, logo_filename, phone_public_consent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, users)

    # Seed the 11 demo volunteer drivers, food receivers and charitable trusts
    seed_demo_network_profiles(conn)

    donor_id = 1
    receiver_id = 2
    volunteer_id = 3
    admin_id = 4
    coordinator_id = 5
    driver_id = 6

    # Timestamps for active demo matching
    prep_time = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    earliest_pickup = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
    safe_deadline = (now + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
    required_by = (now + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")

    # Historical completed donation timestamps (for real metric display)
    past_prep = (now - timedelta(days=1, hours=4)).strftime("%Y-%m-%d %H:%M")
    past_safe = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    past_pickup = (now - timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M")

    # 2. Seed Donations in Karur (Karur coordinates ~ 10.9601° N, 78.0766° E)
    cursor.execute("""
        INSERT INTO donations (
            id, donor_id, food_name, description, category, quantity, unit,
            preparation_time, safe_use_deadline, pickup_address, location_area,
            earliest_pickup_time, storage_instructions, contact_name, contact_phone,
            image_filename, latitude, longitude, location_accuracy,
            organization_type, additional_notes, maps_link, pickup_instructions, dietary_type, partial_allocation_allowed,
            safety_verified_by_donor, status
        ) VALUES (
            1, ?, 'Fresh Vegetable Rice & Mild Sambar',
            'Freshly prepared excess batch from corporate conference lunch in Vengamedu. Hot-packed in insulated steel containers.',
            'Cooked Meals', 40, 'portions', ?, ?, '45, Kovai Main Road, Vengamedu, Karur', 'Vengamedu',
            ?, 'Keep covered in insulated container; consume before safe deadline.', 'Chef R. Kumar', '9842412345',
            'demo_veg_rice.jpg', 10.9680, 78.0720, 10.5,
            'Hotel', 'Loaded in two large thermal food transport canisters. Immediate pickup recommended.',
            'https://maps.google.com/?q=10.9680,78.0720',
            'Kitchen entrance behind Hotel Archana, Ground Floor. Security will guide to storage vessels.',
            'veg', 1, 1, 'posted'
        )
    """, (donor_id, prep_time, safe_deadline, earliest_pickup))

    # Completed historical donation for metrics
    cursor.execute("""
        INSERT INTO donations (
            id, donor_id, food_name, description, category, quantity, unit,
            preparation_time, safe_use_deadline, pickup_address, location_area,
            earliest_pickup_time, storage_instructions, contact_name, contact_phone,
            image_filename, latitude, longitude, location_accuracy,
            organization_type, additional_notes, maps_link, pickup_instructions, dietary_type, partial_allocation_allowed,
            safety_verified_by_donor, status
        ) VALUES (
            2, ?, 'Steamed Idli & Tiffin Sambar',
            'Morning breakfast surplus from wedding hall near Jawahar Bazaar. Inspected and verified safe.',
            'Breakfast', 60, 'portions', ?, ?, '45, Kovai Main Road, Vengamedu, Karur', 'Vengamedu',
            ?, 'Transport immediately; serve warm.', 'Chef R. Kumar', '9842412345',
            'demo_idli_sambar.jpg', 10.9605, 78.0772, 12.0,
            'Marriage Hall', 'Neatly stacked and covered in clean food-grade trays.',
            'https://maps.google.com/?q=10.9605,78.0772',
            'Main dining hall dispatch area.',
            'veg', 1, 1, 'delivered'
        )
    """, (donor_id, past_prep, past_safe, past_pickup))

    # Active Donation 3: Chapati & Mixed Veg Kurma (Thanthonimalai, Karur)
    urgent_deadline = (now + timedelta(hours=1, minutes=45)).strftime("%Y-%m-%d %H:%M")
    cursor.execute("""
        INSERT INTO donations (
            id, donor_id, food_name, description, category, quantity, unit,
            preparation_time, safe_use_deadline, pickup_address, location_area,
            earliest_pickup_time, storage_instructions, contact_name, contact_phone,
            image_filename, latitude, longitude, location_accuracy,
            organization_type, additional_notes, maps_link, pickup_instructions, dietary_type, partial_allocation_allowed,
            safety_verified_by_donor, status
        ) VALUES (
            3, ?, 'Hot Wheat Chapati & Vegetable Kurma',
            'Freshly made hot chapatis wrapped in food-grade foil packs with aromatic vegetable kurma.',
            'Cooked Meals', 50, 'portions', ?, ?, '78, Salem Main Road, Thanthonimalai, Karur', 'Thanthonimalai',
            ?, 'Food-grade foil packed; handle with clean gloves.', 'Supervisor S. Mani', '9842412345',
            'demo_veg_rice.jpg', 10.9320, 78.0840, 8.0,
            'Restaurant', 'Park in rear lot; kitchen dispatch door is open.',
            'https://maps.google.com/?q=10.9320,78.0840',
            'Rear service gate, near dispatch ramp.',
            'veg', 1, 1, 'posted'
        )
    """, (donor_id, prep_time, urgent_deadline, prep_time))

    # 3. Seed Requirements in Karur
    cursor.execute("""
        INSERT INTO requirements (
            id, receiver_id, preferred_category, quantity_needed, unit,
            required_by_time, location_area, delivery_address,
            transport_arranged_by, serving_capacity, contact_name, contact_phone,
            organization_name, organization_type, email, urgency_level, preferred_time, dietary_restrictions, additional_info,
            status
        ) VALUES (
            1, ?, 'Cooked Meals', 35, 'portions', ?, 'Gandhigramam',
            '12, Trichy Road, Gandhigramam, Karur', 'volunteer', 50,
            'Meenakshi Ammal', '9443156789',
            'Anbu Illam Karur Destitute Home', 'Shelter/Orphanage', 'receiver@annampagirvom.org', 'Urgent (today)', 'Afternoon', 'Vegetarian preferred', 'Meals needed for afternoon community dining',
            'active'
        )
    """, (receiver_id, required_by))

    cursor.execute("""
        INSERT INTO requirements (
            id, receiver_id, preferred_category, quantity_needed, unit,
            required_by_time, location_area, delivery_address,
            transport_arranged_by, serving_capacity, contact_name, contact_phone,
            organization_name, organization_type, email, urgency_level, preferred_time, dietary_restrictions, additional_info,
            status
        ) VALUES (
            2, ?, 'Breakfast', 60, 'portions', ?, 'Gandhigramam',
            '12, Trichy Road, Gandhigramam, Karur', 'volunteer', 80,
            'Meenakshi Ammal', '9443156789',
            'Anbu Illam Karur Destitute Home', 'Shelter/Orphanage', 'receiver@annampagirvom.org', 'Normal', 'Morning', 'Any clean tiffin', 'Breakfast fulfilled smoothly',
            'fulfilled'
        )
    """, (receiver_id, past_safe))

    # 4. Seed Matches (Historical completed match)
    cursor.execute("""
        INSERT INTO matches (
            id, donation_id, requirement_id, receiver_id, matched_quantity, status,
            match_explanation, safety_verified_by_receiver, accepted_at
        ) VALUES (
            1, 2, 2, ?, 60, 'completed',
            'Quantity suitable (60 portions) · Pickup before deadline · Receiver capacity confirmed (80 max)',
            1, ?
        )
    """, (receiver_id, (now - timedelta(days=1, hours=3)).strftime("%Y-%m-%d %H:%M:%S")))

    # 5. Seed Pickup Task (Historical completed task)
    cursor.execute("""
        INSERT INTO pickup_tasks (
            id, donation_id, match_id, volunteer_id, status,
            assigned_at, collected_at, delivered_at, handover_notes,
            donor_signature_name, receiver_signature_name,
            collected_quantity, delivered_quantity, pickup_photo, delivery_photo,
            pickup_latitude, pickup_longitude, delivery_latitude, delivery_longitude
        ) VALUES (
            1, 2, 1, ?, 'delivered',
            ?, ?, ?,
            'Smooth pickup and delivery using temperature-safe food carrier boxes.',
            'Chef R. Kumar (Donor)', 'Meenakshi Ammal (Receiver)',
            60, 60, 'demo_idli_sambar.jpg', 'demo_veg_rice.jpg',
            10.9605, 78.0772, 10.9520, 78.0840
        )
    """, (
        volunteer_id,
        (now - timedelta(days=1, hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        (now - timedelta(days=1, hours=2, minutes=20)).strftime("%Y-%m-%d %H:%M:%S"),
        (now - timedelta(days=1, hours=1, minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
    ))

    # 6. Seed Active Assigned Task for Volunteer / Driver
    cursor.execute("""
        INSERT INTO matches (
            id, donation_id, requirement_id, receiver_id, matched_quantity, status,
            match_explanation, safety_verified_by_receiver, accepted_at
        ) VALUES (
            2, 1, 1, ?, 35, 'accepted',
            'Proximity match (Vengamedu to Gandhigramam) · Category Cooked Meals · 35 portions requested',
            0, ?
        )
    """, (receiver_id, (now - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")))

    cursor.execute("""
        INSERT INTO pickup_tasks (
            id, donation_id, match_id, volunteer_id, status,
            assigned_at, accepted_at, handover_notes,
            pickup_latitude, pickup_longitude, delivery_latitude, delivery_longitude
        ) VALUES (
            2, 1, 2, ?, 'assigned',
            ?, ?, 'Hot containers ready at Hotel Archana kitchen. Deliver directly to Anbu Illam dining hall.',
            10.9680, 78.0720, 10.9520, 78.0840
        )
    """, (
        volunteer_id,
        (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
        (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    ))

    # 7. Audit Trail & In-App Notifications
    log_status_change(conn, 'donation', 2, None, 'posted', donor_id, 'Donation created')
    log_status_change(conn, 'donation', 2, 'posted', 'accepted', receiver_id, 'Receiver matched and accepted')
    log_status_change(conn, 'donation', 2, 'accepted', 'collected', volunteer_id, 'Volunteer Saravanan collected food')
    log_status_change(conn, 'donation', 2, 'collected', 'delivered', volunteer_id, 'Volunteer delivered to receiver, verified by Meenakshi Ammal')

    log_status_change(conn, 'donation', 1, None, 'posted', donor_id, 'Active demo donation ready for matching')
    log_status_change(conn, 'pickup_task', 2, None, 'assigned', admin_id, 'Delivery mission assigned to Saravanan Youth Food Rescue Team')

    add_notification(conn, volunteer_id, 'New Pickup Mission Assigned', 'You have been assigned to pick up 35 portions from Hotel Archana Grand.', '/driver/dashboard')
    add_notification(conn, receiver_id, 'Donation Matched', 'Hotel Archana Grand donation matched with your daily requirement.', '/receiver/dashboard')
    add_notification(conn, donor_id, 'Pickup Driver Assigned', 'Saravanan Youth Food Rescue Team assigned to collect surplus meals.', '/donor/dashboard')

    conn.commit()
    conn.close()
    print("Database initialized and sample demo data seeded successfully.")

if __name__ == '__main__':
    init_db()
    seed_demo_data()
