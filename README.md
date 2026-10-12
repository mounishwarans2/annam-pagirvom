# Annam Pagirvom (அன்னம் பகிர்வோம்) — Food Waste Reduction Platform

> **Event:** GENCRAFT’26 Hack4Goals  
> **Problem Statement:** PS14 — Food Waste Reduction Platform  
> **Brand Identity:** Annam Pagirvom (அன்னம் பகிர்வோம்)  
> **Tagline:** *Share Food, Spread Hope / உணவு பகிர்வோம், நல்வாழ்வு தருவோம்.*  
> **District Focus:** Karur District, Tamil Nadu (கரூர் மாவட்டம்)  

---

## 1. Overview & Core Purpose

**Annam Pagirvom (அன்னம் பகிர்வோம்)** is a full-stack, mobile-first progressive web application engineered to eliminate surplus food waste and hunger across Karur District, Tamil Nadu. It bridges two vital community networks:

1. **Food Donors:** Hotels, restaurants, college messes/canteens, marriage halls, event organizers, and households with wholesome surplus meals.
2. **Food Receivers:** Registered shelters, community kitchens, destitute homes, and charitable trusts requiring nutritious food.

The platform coordinates **rule-based matching, in-browser camera verification, GPS location tracking, volunteer pickup coordination, and dual-party handover confirmation**. It strictly upholds that **food safety must be verified by responsible humans upon handover**; deadlines and photos provide transparency, not blind safety guarantees.

---

## 2. Key Features & Implementation Architecture

### A. Full Bilingual Interface (தமிழ் & English)
- **Language Switcher:** Global language pill (`தமிழ்` / `EN`) in top navigation and mobile drawer.
- **Session Persistence:** Persistent language preference maintained across all routes and sessions.
- **Complete Localization:** Every form, dashboard, error message, emergency helpline, Chart.js label, and status badge translated into natural, conversational Tamil and clear English.

### B. Food Donation Form (Charcoal & Cyan UI)
- **Design System:** Charcoal backdrop (`#121417`), dark cards (`#1c1f24`), vibrant cyan highlights (`#06b6d4`), and accessible typography.
- **Fields:** Donor/Org Name, Organization Type (Restaurant, Hotel, Marriage Hall, Event, Canteen, Individual, Other), Contact Number (10-digit validated), Pickup Address, Food Category, Quantity & Unit, Preparation Time, Safe-Use Deadline, Storage Instructions, and Notes.
- **Safety Commitment:** Mandatory donor declaration certifying cleanliness and safe temperature storage.

### C. Live Food Camera & GPS Verification
- **Browser-Based Streaming:** Real `navigator.mediaDevices.getUserMedia` video stream with live container guides.
- **Capture Workflow:** Live preview ➔ `Capture Photo` ➔ `Retake` or `✓ Use This Photo` (with Canvas rasterization).
- **Graceful Fallbacks:** File upload (`<input type="file" accept="image/*" capture="environment">`) fallback when streaming is blocked or denied.
- **GPS Coordinates:** Geolocation API captures latitude, longitude, and accuracy radius, generating one-click OpenStreetMap navigation pins for volunteers.

### D. Complete Request Food Page (`/request-food`)
- **12 Comprehensive Fields:** Organization Name \*, Organization Type \*, Contact Person \*, Contact Number \* (10-digit check), Email (optional), Delivery Address \*, Number of People \*, Urgency Level \* (Emergency, Urgent today, Normal), Preferred Time (ASAP, Morning, Afternoon, Evening, Flexible), Dietary Restrictions, Additional Information, and Submit button.
- **Impact Metrics Cards:** Meals Delivered, Organizations Helped, and Areas Covered (displaying verified database records, with milestone goals explicitly labelled as illustrative targets).
- **Emergency Food Request Section:** Prominent red/amber emergency alert banner with callable priority helpline: **+91 8098016330** (`<a href="tel:+918098016330">`).
- **Guest Access & Persistence:** Unauthenticated community seekers can submit requests; the system securely registers their organization profile and auto-authenticates them to track live matches on the receiver console.

### E. Transparent Rule-Based Matching Engine
- **No black-box ML:** Transparent, explainable rule engine in `matching.py`.
- **Criteria Evaluated:**
  1. Safe-use deadline window (must not be expired; hours remaining scored).
  2. Category compatibility (exact match, parent category, or 'Any').
  3. Timing feasibility (donor pickup window matches receiver meal schedule).
  4. Quantity suitability (exact, surplus match, or receiver portion cap).
  5. Capacity limits (receiver capacity confirmed).
- **Explanations:** Clear bullet points displayed on donor and receiver dashboards explaining why a match was proposed.

### F. Volunteer Pickup & Delivery Evidence Verification
- **Lifecycle:** `Posted` ➔ `Accepted` ➔ `Collected` ➔ `Delivered` (with comprehensive audit history).
- **Pickup Verification:** Volunteer photographs the actual food containers at donor premises, logs collected quantity, donor handover staff name, and optional GPS coordinates.
- **Delivery Verification:** Volunteer photographs handover at receiving shelter, logs delivered quantity, receiver authorized signature, and optional GPS coordinates.
- **Audit Logging:** Every transition is recorded with timestamp and responsible user ID.

### G. Live Food Board (`/live-board` & `/live-food-board`)
- **Real-Time Surplus Listings:** Displays all active, unexpired food batches across Karur District with auto-polling every 30 seconds.
- **Dynamic Metrics Strip:** Live counters for Available Food Portions Now, Active Donors, Karur Locations Covered, and Active Coordination Hours.
- **Transparent Urgency System:** Automatically classifies batches:
  - 🔴 **Urgent (< 2 hours remaining)**
  - 🟡 **Medium (2 to 5 hours remaining)**
  - 🟢 **Low (> 5 hours remaining)**
- **Live Client Countdown:** Real-time JavaScript countdown ticker updating every second; auto-disables requests when expired.
- **Smart Filtering:** Instant filtering by Urgency, Category (Cooked Meals, Bakery, Raw Produce, etc.), Dietary Preference (Veg / Non-Veg), and Karur locality.
- **GPS Distance Calculation:** Computes approximate distance in kilometers from user's current GPS location to donor address using Haversine formula, with manual area selection fallback.
- **Integrated Claim Modal:** Community shelters can request/claim food directly from the board with partial allocation support when allowed by the donor.
- **Emergency Food Assistance Panel:** Karur District Collectorate Control Room (`04324-222333`) and TN Disaster & Food Helpline (`1800-425-1333`).

### H. Driver Pickup & Delivery Coordination Console (`/driver/dashboard`)
- **Lifecycle Management:** Complete 6-stage delivery flow (`assigned` ➔ `accepted` ➔ `en_route_pickup` ➔ `collected` ➔ `en_route_delivery` ➔ `delivered`), plus `disputed` handling.
- **Google Maps Multi-Stop Navigation:** Prominent button **“Navigate: Donor → Trust”** on each assigned card launching:
  `https://www.google.com/maps/dir/?api=1&origin=My+Location&destination=RECEIVER_LOCATION&waypoints=DONOR_LOCATION&travelmode=driving`
  - Strict route sequence: Driver's current location (`My Location`) ➔ Donor Pickup (`waypoints`) ➔ Receiving Trust (`destination`).
  - Dedicated individual navigation buttons: "Navigate to Donor" and "Navigate to Trust".
  - Clickable phone dialer shortcuts: "Call Donor" and "Call Receiver".
- **Evidence Verification:** In-browser live camera capture for pickup utensil condition and delivery handover, dual signatures, and discrepancy reporting.
- **In-App Notifications:** Real-time alerts to donors and receivers on every milestone transition.

### I. Recent Verified Deliveries Public Ledger (`/impact`)
- **11-Column Inspection Ledger:**
  1. Delivery ID
  2. Actual Food Photo (click-to-preview full image modal)
  3. Food Item & Category
  4. Quantity Delivered
  5. Donor Organization & Logo
  6. Donor Contact Number (privacy-masked by default)
  7. Food Receiver Organization & Logo
  8. Receiver Contact Number (privacy-masked by default)
  9. Delivery Status (Verified Deliveries)
  10. Delivery Date & Time
  11. View Delivery Evidence (comprehensive modal displaying food photo, pickup utensils photo, delivery handover photo, donor signature, receiver signature, and GPS coordinates).
- **Privacy by Default:** Public visitors see masked numbers (e.g. `98424*****`). Authorized participants or organizations granting explicit consent display their full number.

### J. Organization Profiles & Settings (`/profile`)
- **Profile Management:** Edit organization name, type, contact person, phone, email, address, ward/area in Karur, capacity description.
- **Logo / Trust Badge:** Upload official logo (PNG/JPG/WEBP, up to 5MB) displayed across donation cards and delivery history.
- **Privacy Controls:** Checkbox granting or revoking public display of phone numbers on the delivery showcase.

### K. Progressive Web App (PWA)
- **Web App Manifest (`manifest.json`):** Configured with standalone mobile launch mode, app name, and 192px/512px icons.
- **Service Worker (`sw.js`):** Offline caching of static assets and friendly offline fallback page (`/offline`).
- **Install Pill:** In-app shortcut button to trigger native browser install prompt on supported mobile devices.

---

## 3. Technology Stack

- **Frontend:** Semantic HTML5, Vanilla JavaScript (ES6+), Modern CSS3 with CSS variables. Zero heavy frontend frameworks or build steps.
- **Backend:** Python 3 (Flask), Werkzeug (secure password hashing, filename sanitization).
- **Database:** SQLite 3 with enforced foreign keys (`PRAGMA foreign_keys = ON`) and automated schema migration.
- **Charts:** Chart.js for distribution funnels and category breakdowns.
- **Testing:** Pytest automated test suite.

---

## 4. Pre-Loaded Demo Accounts for Evaluation

All accounts use secure bcrypt-hashed credentials with pre-seeded demo records for Karur District:

| Role | Username | Password | Organization Name | Location Area | Capabilities |
|---|---|---|---|---|---|
| **Donor** | `donor_hotel` | `Donor@123` | Hotel Archana Grand & Caterers | Vengamedu, Karur | Post donations with camera photo, GPS, view matches & handover history |
| **Receiver** | `receiver_kitchen` | `Receiver@123` | Anbu Illam Karur Destitute Home | Gandhigramam, Karur | Post food requirements, claim surplus from Live Board, confirm handovers |
| **Driver** | `driver_muthu` | `Driver@123` | Muthu Rapid Express Delivery | Karur Town | View assigned missions, Google Maps Multi-Stop route, capture evidence |
| **Volunteer** | `volunteer_saravanan` | `Volunteer@123` | Saravanan Karur Youth Food Rescue Team | Karur Town | Claim unassigned missions, evidence capture, delivery handover |
| **Coordinator** | `coordinator_karur` | `Coordinator@123` | Karur District Food Logistics Coordination Unit | Thanthonimalai, Karur | Central matching (pair donations & requests), assign authorized drivers |
| **Admin** | `admin_user` | `Admin@123` | Karur District Food Redistribution Center | Thanthonimalai, Karur | Full administrative audit trail, system users, dispatch & reset tools |

*(Note: Guest users can also submit food requests at `/request-food` without prior registration; guest accounts are automatically registered and linked).*

---

## 5. Backend Architecture & Database Schema

The system uses a persistent, production-grade backend architecture:
- **Backend Service:** Python Flask with session authentication, bcrypt password hashing, and role-based access control decorators (`@login_required(roles=[...])`).
- **Primary Database:** SQLite 3 database located at `instance/foodbridge.db` with enforced foreign keys (`PRAGMA foreign_keys = ON`) and automated migration guards.
- **Configurable Database:** Standard connection abstraction supporting PostgreSQL / Supabase via `DATABASE_URL` environment variable.
- **Image Storage:** Persistent file storage at `static/uploads/` supporting base64 in-browser camera rasterization and binary multipart uploads.
- **Real-Time Polling Engine:** Client-side intervals querying `/api/live-food-board`, `/api/verified-deliveries`, `/api/driver/tasks`, `/api/coordinator/stats`, and `/api/notifications`.
- **Core Database Tables:**
  1. `users`: Stores credentials, role (`donor`, `receiver`, `volunteer`, `driver`, `coordinator`, `admin`), phone, area, logo, and phone privacy consent.
  2. `donations`: Food name, quantity, category, dietary type, prep time, safe deadline, GPS, maps link, storage instructions, and status.
  3. `requirements`: Organization requirements, quantity needed, dietary restrictions, urgency level, delivery address, and status.
  4. `matches`: Rule-based and coordinator pairings connecting donations and requirements.
  5. `pickup_tasks`: Driver delivery missions with 6-stage lifecycle (`assigned`, `accepted`, `en_route_pickup`, `collected`, `en_route_delivery`, `delivered`, `disputed`), multi-stop URLs, pickup photos, delivery photos, signatures, and coordinates.
  6. `status_history`: Comprehensive immutable audit ledger recording every entity transition, timestamp, and responsible user.
  7. `notifications`: In-app notification queue for immediate milestone alerts.

---

## 6. Environment Configuration (`.env`)

Copy `.env.example` to `.env` to configure application parameters:
```bash
cp .env.example .env
```
Key configuration variables:
- `SECRET_KEY`: Random session secret key.
- `DATABASE_URL`: Connection string (defaults to `sqlite:///instance/foodbridge.db`).
- `PORT`: Server port (default: `5000`).
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`: Optional Supabase cloud integration keys.

---

## 7. Local Setup & Execution

### Step 1: Initialize Database & Seed Karur Records
```bash
./venv/bin/python database.py
```

### Step 2: Run Automated Tests
```bash
./venv/bin/pytest tests/
```

### Step 3: Start the Web Application
```bash
./venv/bin/python app.py
```
Open **http://127.0.0.1:5000** in your browser.

---

## 6. Hardware & HTTPS Security Context

- **Camera & Geolocation:** Modern browsers strictly require a **Secure Context** (`https://` or `http://localhost` / `http://127.0.0.1`) to grant hardware access (`getUserMedia` and `geolocation`).
- When tested locally on `http://127.0.0.1:5000`, browsers automatically treat the origin as secure.
- For deployment on public domains, serve behind an HTTPS reverse proxy (Nginx, Caddy, or Cloudflare Tunnel) to enable camera streaming and GPS for mobile field volunteers.
- When hardware permissions are denied or unavailable, the application gracefully provides instant file-upload and manual address fallbacks.

---

## 7. Complete Verification Workflow Walkthrough

1. **Test Bilingual Switching:**
   - Tap `தமிழ்` in the navbar: Observe complete Tamil translation on all buttons, forms, and cards.
   - Tap `EN`: Switch seamlessly to English. Preference is persisted across navigation.
2. **Submit a Food Donation:**
   - Sign in as `donor_hotel` (Password: `Donor@123`).
   - Click **+ Donate Food / உணவு வழங்கவும்**.
   - Test **Open Camera** for live stream capture, or select an image file.
   - Click **Capture My Location (GPS)** to verify coordinates.
   - Submit and review the batch in your Donor Console.
3. **Submit a Food Request:**
   - Visit `/request-food`.
   - Inspect the verified impact cards and emergency helpline banner (+91 8098016330).
   - Fill the 12 fields and submit. The platform tracks real-time matches against available donations.
4. **Accept Match & Volunteer Handover:**
   - Accept the proposed match on the Donor Console.
   - Sign in as `volunteer_saravanan` (Password: `Volunteer@123`).
   - Claim the pickup mission. Expand **Capture Pickup Evidence**, enter donor staff name and collected quantity, and confirm collection.
   - Expand **Capture Delivery Evidence**, enter receiver signature and delivered quantity, and confirm delivery.
5. **Inspect Public Verified Ledger:**
   - Visit `/impact` to inspect the updated portion count, Chart.js diagrams, and Recent Verified Deliveries table with privacy-protected contact numbers and click-to-preview image modal.
6. **Manage Organization Profile:**
   - Click **⚙️ Profile** to edit organization details, upload logos, and toggle privacy consent.

---

## 8. Mobile PWA Installation & Offline Behavior

Annam Pagirvom is built as an installable Progressive Web Application (PWA) meeting modern Android standards:

### Key PWA Capabilities:
- **Web App Manifest (`static/manifest.json`):**
  - Name: `Annam Pagirvom (அன்னம் பகிர்வோம்)`
  - App ID: `org.annampagirvom.app`
  - Display: `standalone` (removes browser URL bar, runs like a native app)
  - Quick App Shortcuts: *Live Food Board*, *Donate Food*, *Request Food*, *Driver Console*
  - Theme / Background Colors: `#06b6d4` (Cyan accent) / `#121417` (Charcoal dark)
- **Service Worker (`static/sw.js`):**
  - Cache Version: `annampagirvom-v2`
  - Static Asset Cache: Caches CSS, JS, manifest, and icons for instant startup.
  - Offline Navigation: Renders responsive `/offline` page when connection drops.
  - API Offline Safety: `/api/` network requests return structured JSON `{ status: 'offline', message: '...' }` rather than crashing.
- **Offline Upload Blocker (`static/js/main.js`):**
  - Real-time online/offline detector dynamically updates `#networkStatusBanner`.
  - Blocks form submission when offline to prevent data loss; displays a clear warning to reconnect before retrying.
- **Mobile Native Bottom Navigation Bar:**
  - Fixed touch-friendly bottom bar (minimum 44×44px tap targets) for quick one-thumb navigation between Home, Live Board, Role Dashboard, Profile, and Sign In.

### Installing on Android (Chrome / Edge):
1. Open `http://<your-server-ip>:5000` or the production HTTPS domain in Android Chrome.
2. Tap the Chrome menu (`⋮`) and select **"Add to Home screen"** or **"Install app"**.
3. Tap **"Install"** on the prompt.
4. The Annam Pagirvom icon will appear on your app drawer and home screen.

---

## 9. Capacitor Native Android Packaging & Build Guide

The project includes an initialized Capacitor project (`@capacitor/android`, `@capacitor/core`, `@capacitor/cli`) allowing native APK compilation.

### Architecture:
- `capacitor.config.json` points to the Flask backend server (`http://10.0.2.2:5000` for Android emulator or your local Wi-Fi IP `http://192.168.x.x:5000` for physical devices).
- Native project files live in `android/`.
- `AndroidManifest.xml` is pre-configured with:
  - `INTERNET` permission
  - `CAMERA` permission
  - `ACCESS_FINE_LOCATION` and `ACCESS_COARSE_LOCATION` permissions
  - `android:usesCleartextTraffic="true"` for seamless local development over HTTP.

### Building the Debug APK:

#### Option A: Using Android Studio (Recommended)
1. Ensure Android Studio is installed with Android SDK (API 34/35).
2. Open the project in Android Studio:
   ```bash
   npx cap open android
   ```
3. In Android Studio, click **Build > Build Bundle(s) / APK(s) > Build APK(s)**.
4. Once compiled, the APK is located at:
   `android/app/build/outputs/apk/debug/app-debug.apk`

#### Option B: Using Command Line Gradle
If `ANDROID_HOME` or `local.properties` is configured on your machine:
```bash
cd android
./gradlew assembleDebug
```
The output debug APK will be created at:
`android/app/build/outputs/apk/debug/app-debug.apk`

### Testing on a Physical Android Device:
1. Find your machine's local Wi-Fi IP address (e.g. `192.168.1.5`):
   ```bash
   ip -br addr show
   ```
2. In `capacitor.config.json`, set:
   ```json
   "server": {
     "url": "http://192.168.1.5:5000",
     "cleartext": true
   }
   ```
3. Run `npx cap sync android`.
4. Ensure your Android phone is connected to the same Wi-Fi network and install the generated debug APK via `adb install` or file transfer.

---

## 10. Multi-Stop Google Maps Navigation for Drivers

The Driver Console includes one-touch turn-by-turn navigation buttons directly integrated with Google Maps:
- **"Navigate to Donor / நன்கொடையாளரிடம் செல்லவும்":**
  Direct navigation from current GPS position to donor's pickup address:
  `https://www.google.com/maps/dir/?api=1&origin=My+Location&destination=<DONOR_ADDRESS>&travelmode=driving`
- **"Navigate: Donor → Trust / நன்கொடையாளர் ➔ இல்லம் வழிசெலுத்து":**
  Multi-stop route starting from driver's location, picking up at donor address, and delivering to receiver trust:
  `https://www.google.com/maps/dir/?api=1&origin=My+Location&destination=<RECEIVER_ADDRESS>&waypoints=<DONOR_ADDRESS>&travelmode=driving`

---

## 11. Automated Test Suite & Verification

The project includes an automated test suite verifying all critical business logic and API endpoints:
```bash
./venv/bin/python -m pytest tests/test_foodbridge.py -v
```

### Verified Coverage:
- `test_homepage_loads`: Confirms public landing page renders.
- `test_language_switch`: Tests Tamil/English session persistence.
- `test_donate_food_page_accessible`: Validates donation form accessibility.
- `test_create_donation_and_persistence`: Tests real SQLite database record insertion with photo storage.
- `test_request_food_page_and_creation`: Validates request submission, organization creation, and urgent need flagging.
- `test_matching_algorithm`: Tests rule-based matching engine on expiration, capacity, and dietary constraints.
- `test_driver_workflow_and_handover`: Tests complete 6-stage delivery lifecycle with verification photos and receiver signatures.
- `test_impact_page_and_deliveries_table`: Verifies public ledger, statistics, and photo modals.
- `test_live_board_and_search`: Validates real-time live food board search and filtering.
- `test_pwa_manifest_and_sw`: Confirms valid `manifest.json` and service worker asset caching.

