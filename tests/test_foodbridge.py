import os
import pytest
import sqlite3
import base64
from app import app
from database import init_db, seed_demo_data, get_db_connection
from matching import evaluate_match

TEST_DB = os.path.join(os.path.dirname(__file__), 'instance', 'test_foodbridge.py.db')

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret'
    
    # Initialize fresh test db
    init_db(TEST_DB)
    seed_demo_data(TEST_DB)

    # Monkeypatch db path during test
    import database
    database.DATABASE_PATH = TEST_DB

    with app.test_client() as client:
        yield client

    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
        except Exception:
            pass

def test_home_page_branding_tamil_and_english(client):
    """Test that homepage loads with both Tamil and English language options."""
    # Default is Tamil
    res_ta = client.get('/')
    assert res_ta.status_code == 200
    assert "அன்னம் பகிர்வோம்".encode('utf-8') in res_ta.data
    assert "உணவு பகிர்வோம்".encode('utf-8') in res_ta.data

    # Switch to English
    res_switch = client.get('/set-language/en', follow_redirects=True)
    assert res_switch.status_code == 200
    assert b"Share Food, Spread Hope" in res_switch.data
    assert b"Annam Pagirvom" in res_switch.data

def test_matching_rules():
    """Test rule-based matching engine logic."""
    donation = {
        'category': 'Cooked Meals',
        'quantity': 40,
        'unit': 'portions',
        'safe_use_deadline': '2030-01-01 20:00:00',
        'earliest_pickup_time': '2030-01-01 12:00:00',
        'location_area': 'Guindy'
    }
    requirement = {
        'preferred_category': 'Cooked Meals',
        'quantity_needed': 35,
        'unit': 'portions',
        'serving_capacity': 50,
        'required_by_time': '2030-01-01 18:00:00',
        'location_area': 'Saidapet',
        'transport_arranged_by': 'volunteer'
    }

    result = evaluate_match(donation, requirement)
    assert result['is_match'] is True
    assert result['matched_quantity'] == 35
    assert result['match_score'] >= 60

    # Test expired food rule failure
    expired_donation = dict(donation)
    expired_donation['safe_use_deadline'] = '2020-01-01 12:00:00'
    fail_result = evaluate_match(expired_donation, requirement)
    assert fail_result['is_match'] is False
    assert any("safe-use deadline" in d for d in fail_result['disqualifiers'])

    # Test capacity rule failure
    low_cap_req = dict(requirement)
    low_cap_req['serving_capacity'] = 10
    cap_fail = evaluate_match(donation, low_cap_req)
    assert cap_fail['is_match'] is False
    assert any("serving capacity" in d for d in cap_fail['disqualifiers'])

def test_camera_upload_and_gps_capture(client):
    """Test posting a donation with base64 camera image and GPS coordinates."""
    # Login as donor
    client.get('/set-language/en')
    client.post('/login', data={
        'username': 'donor_hotel',
        'password': 'Donor@123'
    }, follow_redirects=True)

    # Fake 1x1 png base64 image
    fake_png_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    res = client.post('/donor/post', data={
        'food_name': 'Camera Captured Meals',
        'category': 'Cooked Meals',
        'description': 'Packed safely in clean containers',
        'quantity': 25,
        'unit': 'portions',
        'preparation_time': '2026-10-09 10:00',
        'safe_use_deadline': '2026-10-09 18:00',
        'earliest_pickup_time': '2026-10-09 11:00',
        'location_area': 'Guindy',
        'pickup_address': 'Back Kitchen Entrance, 14 Anna Salai',
        'contact_name': 'Chef Kumar',
        'contact_phone': '9842412345',
        'organization_type': 'Hotel',
        'additional_notes': 'Clean hot transport boxes ready for pickup',
        'safety_verification': '1',
        'latitude': '13.0067',
        'longitude': '80.2036',
        'location_accuracy': '10.5',
        'captured_image_base64': fake_png_base64
    }, follow_redirects=True)

    assert res.status_code == 200

    conn = get_db_connection(TEST_DB)
    row = conn.execute("SELECT * FROM donations WHERE food_name = 'Camera Captured Meals'").fetchone()
    conn.close()

    assert row is not None
    assert row['image_filename'] is not None
    assert row['latitude'] == 13.0067
    assert row['longitude'] == 80.2036
    # Verify file saved on disk
    img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'uploads', row['image_filename'])
    assert os.path.exists(img_path)

def test_donor_receiver_handover_flow(client):
    """Test full cycle: login -> accept -> volunteer pickup -> deliver -> metrics check."""
    # Set to English for English assertion
    client.get('/set-language/en')

    # 1. Login as Donor
    login_res = client.post('/login', data={
        'username': 'donor_hotel',
        'password': 'Donor@123'
    }, follow_redirects=True)
    assert login_res.status_code == 200
    assert b"Donor Management Console" in login_res.data

    # 2. Donor accepts match #1
    accept_res = client.post('/donor/accept-match', data={
        'donation_id': 1,
        'requirement_id': 1,
        'matched_quantity': 35,
        'explanation': 'Quantity suitable · Receiver capacity confirmed'
    }, follow_redirects=True)
    assert accept_res.status_code == 200

    # 3. Login as Volunteer
    client.post('/login', data={
        'username': 'volunteer_saravanan',
        'password': 'Volunteer@123'
    }, follow_redirects=True)

    # 4. Volunteer claims the created pickup task
    conn = get_db_connection(TEST_DB)
    task = conn.execute("SELECT id FROM pickup_tasks WHERE donation_id = 1").fetchone()
    task_id = task['id']
    conn.close()

    claim_res = client.post(f'/volunteer/claim-task/{task_id}', follow_redirects=True)
    assert claim_res.status_code == 200

    # 5. Volunteer collects food
    coll_res = client.post(f'/volunteer/collected/{task_id}', data={
        'donor_signature': 'Chef Kumar'
    }, follow_redirects=True)
    assert coll_res.status_code == 200
    assert b"Food collected from donor and now in transit" in coll_res.data

    # 6. Volunteer delivers food
    del_res = client.post(f'/volunteer/delivered/{task_id}', data={
        'receiver_signature': 'Sister Mary'
    }, follow_redirects=True)
    assert del_res.status_code == 200
    assert b"Mission complete" in del_res.data

    # 7. Check impact metrics page reflects true delivery without false inflation
    imp_res = client.get('/impact')
    assert imp_res.status_code == 200
    # Donation 1 (40) + Donation 2 (60) = 100 delivered portions
    assert b"100" in imp_res.data

def test_pwa_routes(client):
    """Test PWA manifest and service worker availability."""
    sw_res = client.get('/sw.js')
    assert sw_res.status_code == 200
    assert b"annampagirvom" in sw_res.data

    manifest_res = client.get('/static/manifest.json')
    assert manifest_res.status_code == 200
    assert b"Annam Pagirvom" in manifest_res.data

    offline_res = client.get('/offline')
    assert offline_res.status_code == 200

def test_request_food_page_and_submission(client):
    """Test Request Food page display, validation, emergency helpline, and persistence."""
    # 1. GET /request-food
    res = client.get('/request-food')
    assert res.status_code == 200
    assert "உணவைக் கோருங்கள்".encode('utf-8') in res.data
    assert b"8098016330" in res.data
    assert b"Meals Delivered" in res.data or "வழங்கப்பட்ட உணவுகள்".encode('utf-8') in res.data

    # 2. POST with invalid contact phone (less than 10 digits)
    bad_res = client.post('/request-food', data={
        'organization_name': 'Karur Children Trust',
        'organization_type': 'NGO',
        'contact_name': 'K. Raman',
        'contact_phone': '12345',  # Invalid!
        'delivery_address': 'Thanthonimalai, Karur',
        'quantity_needed': '30'
    }, follow_redirects=True)
    assert b"10" in bad_res.data  # Validation message about 10 digits

    # 3. POST valid request as guest
    valid_res = client.post('/request-food', data={
        'organization_name': 'Karur Grace Community Kitchen',
        'organization_type': 'Community Kitchen',
        'contact_name': 'S. Murugan',
        'contact_phone': '9842499999',
        'email': 'murugan@karurkitchen.org',
        'delivery_address': '15, Jawahar Bazaar, Karur Town',
        'quantity_needed': '45',
        'urgency_level': 'Urgent (today)',
        'preferred_time': 'Afternoon',
        'preferred_category': 'Cooked Meals',
        'location_area': 'Karur Town',
        'dietary_restrictions': 'Vegetarian preferred',
        'additional_info': 'Gate 2 entry'
    }, follow_redirects=True)
    assert valid_res.status_code == 200
    assert b"Karur Grace Community Kitchen" in valid_res.data

    # Check persistence in database
    conn = get_db_connection(TEST_DB)
    req = conn.execute("SELECT * FROM requirements WHERE contact_phone = '9842499999'").fetchone()
    assert req is not None
    assert req['quantity_needed'] == 45
    assert req['urgency_level'] == 'Urgent (today)'
    assert req['dietary_restrictions'] == 'Vegetarian preferred'
    conn.close()

def test_organization_profile_management(client):
    """Test viewing and updating organization profile and privacy consent."""
    # Login as receiver
    client.post('/login', data={
        'username': 'receiver_kitchen',
        'password': 'Receiver@123'
    }, follow_redirects=True)

    # GET profile
    prof_res = client.get('/profile')
    assert prof_res.status_code == 200
    assert b"Anbu Illam Karur Destitute Home" in prof_res.data

    # POST profile update with privacy consent
    update_res = client.post('/profile', data={
        'organization_name': 'Anbu Illam Karur Senior Care',
        'organization_type': 'Shelter/Orphanage',
        'phone': '9443156789',
        'email': 'care@anbuillam.org',
        'location_area': 'Gandhigramam',
        'address': '12, Trichy Road, Gandhigramam, Karur',
        'capacity_description': '140 beds and dining facility',
        'phone_public_consent': '1'
    }, follow_redirects=True)
    assert update_res.status_code == 200

    conn = get_db_connection(TEST_DB)
    user = conn.execute("SELECT * FROM users WHERE id = 2").fetchone()
    assert user['organization_name'] == 'Anbu Illam Karur Senior Care'
    assert user['phone_public_consent'] == 1
    conn.close()

def test_delivery_showcase_phone_privacy(client):
    """Test that public anonymous visitors cannot see private phone numbers on recent deliveries."""
    # Anonymous visit
    res = client.get('/impact')
    assert res.status_code == 200
    # Private donor phone must NOT be in response data
    assert b"9842412345" not in res.data
    # Must display login prompt or login link for contact details
    assert "தொடர்பைக் காண உள்நுழைக".encode('utf-8') in res.data or b"/login?next=/impact" in res.data

def test_volunteer_evidence_persistence(client):
    """Test recording collected/delivered quantities and evidence during handover."""
    # 1. Login as donor & accept match
    client.post('/login', data={'username': 'donor_hotel', 'password': 'Donor@123'})
    client.post('/donor/accept-match', data={
        'donation_id': 1,
        'requirement_id': 1,
        'matched_quantity': 35,
        'explanation': 'Match verified'
    })

    # 2. Login as volunteer
    client.post('/login', data={'username': 'volunteer_saravanan', 'password': 'Volunteer@123'})
    conn = get_db_connection(TEST_DB)
    task = conn.execute("SELECT id FROM pickup_tasks WHERE donation_id = 1").fetchone()
    task_id = task['id']
    conn.close()

    # Claim
    client.post(f'/volunteer/claim-task/{task_id}')

    # Collect with quantity
    client.post(f'/volunteer/collected/{task_id}', data={
        'donor_signature': 'Chef Kumar',
        'collected_quantity': '35',
        'handover_notes': 'Hot sealed containers'
    })

    conn = get_db_connection(TEST_DB)
    t_after_coll = conn.execute("SELECT * FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t_after_coll['status'] == 'collected'
    assert t_after_coll['collected_quantity'] == 35.0
    conn.close()

    # Deliver with quantity
    client.post(f'/volunteer/delivered/{task_id}', data={
        'receiver_signature': 'Meenakshi Ammal',
        'delivered_quantity': '35'
    })

    conn = get_db_connection(TEST_DB)
    t_after_del = conn.execute("SELECT * FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t_after_del['status'] == 'delivered'
    assert t_after_del['delivered_quantity'] == 35.0
    assert t_after_del['receiver_signature_name'] == 'Meenakshi Ammal'

    don = conn.execute("SELECT status FROM donations WHERE id = 1").fetchone()
    assert don['status'] == 'delivered'
    conn.close()

def test_bilingual_language_persistence(client):
    """Test bilingual language switcher and session persistence."""
    # Set to Tamil
    res_ta = client.get('/set-language/ta', follow_redirects=True)
    assert res_ta.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get('lang') == 'ta'

    # Set to English
    res_en = client.get('/set-language/en', follow_redirects=True)
    assert res_en.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get('lang') == 'en'

def test_live_food_board_page_and_api(client):
    """Test Live Food Board page rendering, real metrics, and JSON polling endpoint."""
    # 1. Page GET
    res = client.get('/live-board')
    assert res.status_code == 200
    assert "Live Food Board".encode('utf-8') in res.data
    assert "நேரடி உணவு".encode('utf-8') in res.data
    assert b"statAvailableNow" in res.data
    assert b"statTotalDonors" in res.data

    # 2. JSON API GET
    api_res = client.get('/api/live-food-board')
    assert api_res.status_code == 200
    json_data = api_res.get_json()
    assert json_data['status'] == 'success'
    assert 'stats' in json_data
    assert json_data['stats']['available_now'] >= 40
    assert json_data['stats']['total_donors'] >= 1
    assert 'donations' in json_data
    assert len(json_data['donations']) >= 1

    # Check donation attributes
    don0 = json_data['donations'][0]
    assert 'food_name' in don0
    assert 'category' in don0
    assert 'urgency' in don0
    assert 'remaining_seconds' in don0
    assert 'remaining_str' in don0
    # Public anonymous user must not see private phone number
    assert don0['contact_phone'] is None
    assert don0['is_phone_authorized'] is False
    assert "Sign in with an authorized account" in don0['phone_authorization_message']

def test_claim_live_food_item_and_partial_allocation(client):
    """Test requesting food directly from Live Food Board with partial allocation."""
    # Claim 20 portions out of 40 available
    res = client.post('/claim-food-item/1', data={
        'requested_quantity': '20',
        'receiver_name': 'Karur Anbu Karangal Trust',
        'receiver_phone': '9876543210',
        'receiver_area': 'Thanthonimalai',
        'delivery_address': '55, Main Road, Thanthonimalai, Karur',
        'serving_capacity': '30',
        'claim_notes': 'Hot lunch needed for elders'
    }, follow_redirects=True)
    assert res.status_code == 200

    conn = get_db_connection(TEST_DB)
    # Donation remaining quantity should be 40 - 20 = 20
    don = conn.execute("SELECT quantity, status FROM donations WHERE id = 1").fetchone()
    assert don['quantity'] == 20.0
    assert don['status'] == 'posted'

    # Requirement and match should be created
    req = conn.execute("SELECT * FROM requirements WHERE contact_phone = '9876543210'").fetchone()
    assert req is not None
    assert req['quantity_needed'] == 20.0

    match = conn.execute("SELECT * FROM matches WHERE donation_id = 1 AND requirement_id = ?", (req['id'],)).fetchone()
    assert match is not None
    assert match['matched_quantity'] == 20.0

    # In-app notifications created
    notifs = conn.execute("SELECT * FROM notifications WHERE user_id = 1").fetchall()
    assert len(notifs) >= 1
    conn.close()

def test_driver_dashboard_and_multi_stop_navigation(client):
    """Test Driver Dashboard and Google Maps Multi-Stop Navigation URL construction."""
    # Login as volunteer / driver
    client.post('/login', data={'username': 'volunteer_saravanan', 'password': 'Volunteer@123'})
    res = client.get('/driver/dashboard')
    assert res.status_code == 200
    assert b"Navigate: Donor" in res.data
    assert b"google.com/maps/dir" in res.data

    # Check multi-stop route format: Driver -> Donor -> Trust
    # URL format must have: origin=My+Location, destination=RECEIVER_LOCATION, waypoints=DONOR_LOCATION
    assert b"origin=My+Location" in res.data
    assert b"waypoints=" in res.data
    assert b"destination=" in res.data
    assert b"travelmode=driving" in res.data

    # Check call buttons
    assert b"tel:" in res.data

def test_driver_status_transitions_and_workflow(client):
    """Test driver step-by-step lifecycle: assigned -> accepted -> en_route_pickup -> collected -> en_route_delivery -> delivered."""
    client.post('/login', data={'username': 'volunteer_saravanan', 'password': 'Volunteer@123'})

    conn = get_db_connection(TEST_DB)
    task = conn.execute("SELECT id FROM pickup_tasks WHERE donation_id = 1").fetchone()
    task_id = task['id']
    conn.close()

    # 1. Accept task
    res1 = client.post(f'/driver/accept-task/{task_id}', follow_redirects=True)
    assert res1.status_code == 200
    conn = get_db_connection(TEST_DB)
    t1 = conn.execute("SELECT status, accepted_at FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t1['status'] == 'accepted'
    assert t1['accepted_at'] is not None
    conn.close()

    # 2. En route to pickup
    res2 = client.post(f'/driver/en-route-pickup/{task_id}', follow_redirects=True)
    assert res2.status_code == 200
    conn = get_db_connection(TEST_DB)
    t2 = conn.execute("SELECT status, en_route_pickup_at FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t2['status'] == 'en_route_pickup'
    assert t2['en_route_pickup_at'] is not None
    conn.close()

    # 3. Collected with photo & donor signature
    res3 = client.post(f'/driver/collected/{task_id}', data={
        'donor_signature': 'Chef Kumar',
        'collected_quantity': '35',
        'latitude': '10.9680',
        'longitude': '78.0720',
        'handover_notes': 'Loaded into temperature carrier box'
    }, follow_redirects=True)
    assert res3.status_code == 200
    conn = get_db_connection(TEST_DB)
    t3 = conn.execute("SELECT status, collected_quantity, donor_signature_name FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t3['status'] == 'collected'
    assert t3['collected_quantity'] == 35.0
    assert t3['donor_signature_name'] == 'Chef Kumar'
    conn.close()

    # 4. En route to delivery (trust)
    res4 = client.post(f'/driver/en-route-delivery/{task_id}', follow_redirects=True)
    assert res4.status_code == 200
    conn = get_db_connection(TEST_DB)
    t4 = conn.execute("SELECT status, en_route_delivery_at FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t4['status'] == 'en_route_delivery'
    assert t4['en_route_delivery_at'] is not None
    conn.close()

    # 5. Delivered with recipient signature and notes
    res5 = client.post(f'/driver/delivered/{task_id}', data={
        'receiver_signature': 'Sister Meenakshi',
        'delivered_quantity': '35',
        'latitude': '10.9520',
        'longitude': '78.0840',
        'delivery_notes': 'All containers unloaded safely in dining hall',
        'discrepancy_notes': ''
    }, follow_redirects=True)
    assert res5.status_code == 200
    conn = get_db_connection(TEST_DB)
    t5 = conn.execute("SELECT status, delivered_quantity, receiver_signature_name FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t5['status'] == 'delivered'
    assert t5['delivered_quantity'] == 35.0
    assert t5['receiver_signature_name'] == 'Sister Meenakshi'

    # Donation marked delivered
    don = conn.execute("SELECT status FROM donations WHERE id = 1").fetchone()
    assert don['status'] == 'delivered'
    conn.close()

def test_driver_report_issue_dispute(client):
    """Test reporting an issue or dispute during transit."""
    client.post('/login', data={'username': 'volunteer_saravanan', 'password': 'Volunteer@123'})

    conn = get_db_connection(TEST_DB)
    task = conn.execute("SELECT id FROM pickup_tasks WHERE donation_id = 1").fetchone()
    task_id = task['id']
    conn.close()

    res = client.post(f'/driver/report-issue/{task_id}', data={
        'dispute_reason': 'Donor kitchen was unexpectedly closed upon arrival'
    }, follow_redirects=True)
    assert res.status_code == 200

    conn = get_db_connection(TEST_DB)
    t = conn.execute("SELECT status, discrepancy_notes FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert t['status'] == 'disputed'
    assert 'unexpectedly closed' in t['discrepancy_notes']
    conn.close()

def test_api_verified_deliveries_and_11_columns(client):
    """Test /api/verified-deliveries endpoint returning 11 explicit delivery tracking fields."""
    res = client.get('/api/verified-deliveries')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'success'
    assert 'deliveries' in data
    assert len(data['deliveries']) >= 1

    deliv = data['deliveries'][0]
    # Check all 11 required fields
    assert 'delivery_id' in deliv
    assert 'food_photo' in deliv
    assert 'food_name' in deliv
    assert 'category' in deliv
    assert 'delivered_quantity' in deliv
    assert 'donor_org' in deliv
    assert 'donor_phone' in deliv
    assert 'receiver_org' in deliv
    assert 'receiver_phone' in deliv
    assert 'delivery_status' in deliv
    assert 'delivered_at' in deliv
    assert 'donor_signature_name' in deliv
    assert 'receiver_signature_name' in deliv

def test_coordinator_dashboard_and_live_stats(client):
    """Test coordinator dashboard access and real-time polling API."""
    # Login as district coordinator
    login_res = client.post('/login', data={'username': 'coordinator_karur', 'password': 'Coordinator@123'}, follow_redirects=True)
    assert login_res.status_code == 200

    dash_res = client.get('/coordinator/dashboard')
    assert dash_res.status_code == 200
    assert b"Coordinator Console" in dash_res.data or "ஒருங்கிணைப்பாளர்".encode('utf-8') in dash_res.data

    stats_res = client.get('/api/coordinator/stats')
    assert stats_res.status_code == 200
    sdata = stats_res.get_json()
    assert sdata['status'] == 'success'
    assert 'open_donations' in sdata
    assert 'open_requirements' in sdata
    assert 'unassigned_tasks' in sdata
    assert 'delivered' in sdata

def test_coordinator_matching_and_driver_assignment_workflow(client):
    """Test complete end-to-end workflow: Donor -> Receiver -> Coordinator Match -> Assign Driver -> Deliver."""
    # 1. Donor posts food
    client.post('/login', data={'username': 'donor_hotel', 'password': 'Donor@123'})
    client.post('/donor/post', data={
        'food_name': 'Fresh Karur Veg Meals',
        'category': 'Cooked Meals',
        'dietary_type': 'veg',
        'quantity': '40',
        'unit': 'portions',
        'preparation_time': '2026-10-09 12:00',
        'safe_use_deadline': '2026-10-09 18:00',
        'pickup_address': '45, Kovai Main Road, Vengamedu, Karur',
        'location_area': 'Vengamedu',
        'earliest_pickup_time': '2026-10-09 12:30',
        'storage_instructions': 'Hot container',
        'contact_name': 'Manager Kumar',
        'contact_phone': '9842412345',
        'safety_verification': '1'
    }, follow_redirects=True)
    client.get('/logout')

    # Get created donation id
    conn = get_db_connection(TEST_DB)
    don = conn.execute("SELECT id FROM donations WHERE food_name = 'Fresh Karur Veg Meals' ORDER BY id DESC LIMIT 1").fetchone()
    don_id = don['id']

    # 2. Receiver posts food request
    client.post('/login', data={'username': 'receiver_kitchen', 'password': 'Receiver@123'})
    client.post('/receiver/post-requirement', data={
        'organization_name': 'Anbu Illam Karur Destitute Home',
        'organization_type': 'Shelter/Orphanage',
        'contact_name': 'Meenakshi Ammal',
        'contact_phone': '9443156789',
        'preferred_category': 'Cooked Meals',
        'dietary_restrictions': 'Vegetarian preferred',
        'quantity_needed': '40',
        'urgency_level': 'Urgent (today)',
        'preferred_time': 'Afternoon',
        'location_area': 'Gandhigramam',
        'delivery_address': '12, Trichy Road, Gandhigramam, Karur',
        'additional_info': 'Urgent lunch requirement'
    }, follow_redirects=True)
    client.get('/logout')

    conn = get_db_connection(TEST_DB)
    req = conn.execute("SELECT * FROM requirements WHERE receiver_id = 2 ORDER BY id DESC LIMIT 1").fetchone()
    req_id = req['id']
    conn.close()

    # 3. Coordinator matches donation and request
    client.post('/login', data={'username': 'coordinator_karur', 'password': 'Coordinator@123'})
    match_res = client.post('/coordinator/match', data={
        'donation_id': don_id,
        'requirement_id': req_id,
        'matched_quantity': '40'
    }, follow_redirects=True)
    assert match_res.status_code == 200

    conn = get_db_connection(TEST_DB)
    task = conn.execute("SELECT id, status, volunteer_id FROM pickup_tasks WHERE donation_id = ? ORDER BY id DESC LIMIT 1", (don_id,)).fetchone()
    assert task is not None
    assert task['status'] == 'assigned'
    task_id = task['id']

    # 4. Coordinator assigns driver (driver_muthu, id=6)
    assign_res = client.post('/coordinator/assign-driver', data={
        'task_id': task_id,
        'driver_id': 6
    }, follow_redirects=True)
    assert assign_res.status_code == 200

    task_after = conn.execute("SELECT volunteer_id FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert task_after['volunteer_id'] == 6
    conn.close()
    client.get('/logout')

    # 5. Driver logs in and fulfills the delivery
    client.post('/login', data={'username': 'driver_muthu', 'password': 'Driver@123'})
    d_dash = client.get('/driver/dashboard')
    assert d_dash.status_code == 200
    assert b"Fresh Karur Veg Meals" in d_dash.data

    # Accept & start pickup
    client.post(f'/driver/accept-task/{task_id}')
    client.post(f'/driver/en-route-pickup/{task_id}')

    # Collect with donor signature
    coll = client.post(f'/driver/collected/{task_id}', data={
        'donor_signature': 'Chef Arumugam',
        'collected_quantity': '40'
    }, follow_redirects=True)
    assert coll.status_code == 200

    # Deliver with receiver signature
    deliv = client.post(f'/driver/delivered/{task_id}', data={
        'receiver_signature': 'Warden Selvi',
        'delivered_quantity': '40'
    }, follow_redirects=True)
    assert deliv.status_code == 200
    client.get('/logout')

    # 6. Verify verified delivery record in database and public APIs
    conn = get_db_connection(TEST_DB)
    final_task = conn.execute("SELECT status, delivered_quantity, receiver_signature_name FROM pickup_tasks WHERE id = ?", (task_id,)).fetchone()
    assert final_task['status'] == 'delivered'
    assert final_task['delivered_quantity'] == 40.0
    assert final_task['receiver_signature_name'] == 'Warden Selvi'
    conn.close()

    imp_res = client.get('/impact')
    assert imp_res.status_code == 200
    assert b"Fresh Karur Veg Meals" in imp_res.data

def test_role_based_access_controls(client):
    """Test RBAC: Donors cannot access coordinator routes; drivers cannot assign tasks."""
    # Donor tries to access coordinator dashboard
    client.post('/login', data={'username': 'donor_hotel', 'password': 'Donor@123'})
    res = client.get('/coordinator/dashboard', follow_redirects=True)
    assert b"Unauthorized access" in res.data or res.status_code == 200 and b"Coordinator Console" not in res.data
    client.get('/logout')

    # Driver tries to assign driver
    client.post('/login', data={'username': 'driver_muthu', 'password': 'Driver@123'})
    res2 = client.post('/coordinator/assign-driver', data={'task_id': 1, 'driver_id': 6}, follow_redirects=True)
    assert b"Unauthorized access" in res2.data
    client.get('/logout')

def test_role_based_phone_access_system(client):
    """
    Comprehensive verification of role-based contact access rules:
    1. Public visitor: contact_phone is null, direct API returns 403.
    2. Admin: sees real donor phone, audit log created in contact_access_logs.
    3. Assigned Driver: sees donor phone for assigned task #2, Call Donor rendered.
       Unassigned driver cannot see donor phone on unclaimed task.
    4. Approved Matched Receiver: sees donor phone on active handover.
       Unmatched receiver cannot see donor phone on Live Food Board.
    5. Direct API security: unauthorized users receive 403 denied.
    """
    # 1. Public Visitor: API returns 403 denied
    api_res = client.get('/api/contact-details/donation/1')
    assert api_res.status_code == 403
    assert api_res.get_json()['status'] == 'denied'

    # 2. Administrator Access
    client.post('/login', data={'username': 'admin_user', 'password': 'Admin@123'})
    admin_api = client.get('/api/contact-details/donation/1')
    assert admin_api.status_code == 200
    admin_data = admin_api.get_json()
    assert admin_data['status'] == 'success'
    assert admin_data['contact_phone'] == '9842412345'

    # Verify audit log in contact_access_logs
    conn = get_db_connection(TEST_DB)
    log = conn.execute("SELECT * FROM contact_access_logs WHERE contact_type = 'donor_phone' AND access_granted = 1").fetchone()
    assert log is not None
    assert log['role'] == 'admin'
    conn.close()
    client.get('/logout')

    # 3. Assigned Driver Access
    # volunteer_saravanan has task #2 assigned to him in seed data
    client.post('/login', data={'username': 'volunteer_saravanan', 'password': 'Volunteer@123'})
    drv_api = client.get('/api/contact-details/task/2')
    assert drv_api.status_code == 200
    drv_data = drv_api.get_json()
    assert drv_data['status'] == 'success'
    assert drv_data['donor_phone'] == '9842412345'
    assert drv_data['donor_phone_authorized'] is True

    # Driver dashboard check: Call Donor button exists
    drv_dash = client.get('/driver/dashboard')
    assert drv_dash.status_code == 200
    assert b"tel:9842412345" in drv_dash.data

    # But for a donation that is NOT assigned to driver:
    unassigned_api = client.get('/api/contact-details/donation/3')
    assert unassigned_api.status_code == 403
    client.get('/logout')

    # 4. Approved Matched Receiver Access
    # receiver_kitchen is matched to donation #2 (match #1 in seed data)
    client.post('/login', data={'username': 'receiver_kitchen', 'password': 'Receiver@123'})
    rec_dash = client.get('/receiver/dashboard')
    assert rec_dash.status_code == 200
    # Donor phone should be accessible on active handover
    assert b"tel:9842412345" in rec_dash.data

    # But on Live Food Board (unmatched donation #3), receiver cannot view private phone
    live_res = client.get('/api/live-food-board')
    live_json = live_res.get_json()
    for d in live_json['donations']:
        if d['id'] == 3:
            assert d['contact_phone'] is None
            assert d['is_phone_authorized'] is False
    client.get('/logout')





