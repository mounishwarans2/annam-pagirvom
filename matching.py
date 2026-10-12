"""
Transparent rule-based matching engine for Annam Pagirvom.
Checks:
1. Food within safe-use window (not expired).
2. Category compatibility.
3. Quantity suitability (exact, partial surplus, or receiver need).
4. Timing feasibility (pickup can occur before safe-use deadline).
5. Transport compatibility and location reasonableness.
6. Receiver capacity verification.
"""

from datetime import datetime

def parse_time(timestr):
    """Parses standard ISO or YYYY-MM-DD HH:MM formatted timestamps."""
    if not timestr:
        return None
    cleaned = timestr.replace('T', ' ')
    if len(cleaned) == 16:
        cleaned += ':00'
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(cleaned[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None

def evaluate_match(donation, requirement):
    """
    Evaluates whether a donation and a requirement can match.
    Returns:
        dict: {
            'is_match': bool,
            'match_score': int (0-100),
            'matched_quantity': float,
            'reasons': list of positive notes,
            'disqualifiers': list of blocking reasons,
            'explanation_string': str
        }
    """
    now = datetime.now()
    reasons = []
    disqualifiers = []

    # 1. Food within safe-use deadline check
    safe_deadline = parse_time(donation['safe_use_deadline'])
    if not safe_deadline:
        disqualifiers.append("Missing or unreadable safe-use deadline")
    elif safe_deadline <= now:
        disqualifiers.append("Food has passed its safe-use deadline")
    else:
        hours_left = (safe_deadline - now).total_seconds() / 3600.0
        reasons.append(f"Within safe-use window ({hours_left:.1f}h remaining)")

    # 2. Timing feasibility between earliest pickup, requirement need, and deadline
    earliest_pickup = parse_time(donation['earliest_pickup_time'])
    required_by = parse_time(requirement['required_by_time'])

    if earliest_pickup and safe_deadline and earliest_pickup >= safe_deadline:
        disqualifiers.append("Earliest pickup is after the safe-use deadline")
    elif earliest_pickup and required_by:
        if earliest_pickup > required_by:
            disqualifiers.append("Donation pickup time is later than receiver's needed time")
        else:
            reasons.append("Pickup timing matches receiver schedule")

    # 3. Category suitability
    don_cat = (donation['category'] or '').strip().lower()
    req_cat = (requirement['preferred_category'] or '').strip().lower()

    if req_cat == 'any' or don_cat == 'any' or don_cat == req_cat or req_cat in don_cat or don_cat in req_cat:
        reasons.append(f"Category matched: {donation['category']}")
    else:
        disqualifiers.append(f"Category mismatch: '{donation['category']}' vs '{requirement['preferred_category']}'")

    # 4. Quantity evaluation
    avail_qty = float(donation['quantity'])
    need_qty = float(requirement['quantity_needed'])
    matched_qty = min(avail_qty, need_qty)

    if avail_qty <= 0:
        disqualifiers.append("Donation has 0 portions available")
    elif avail_qty >= need_qty:
        reasons.append(f"Quantity fully covers requirement ({matched_qty:.0f} of {need_qty:.0f} {requirement['unit']})")
    else:
        # Partial match available
        reasons.append(f"Partial quantity available ({avail_qty:.0f} of {need_qty:.0f} {requirement['unit']})")

    # 5. Receiver serving capacity check
    capacity = float(requirement['serving_capacity'])
    if capacity < matched_qty:
        disqualifiers.append(f"Receiver serving capacity ({capacity:.0f}) is below food batch ({matched_qty:.0f})")
    else:
        reasons.append(f"Receiver capacity verified ({capacity:.0f} max capacity)")

    # 6. Transport / Location verification
    don_area = (donation['location_area'] or '').strip().lower() if 'location_area' in donation.keys() else ''
    req_area = (requirement['location_area'] or '').strip().lower() if 'location_area' in requirement.keys() else ''
    transport = requirement['transport_arranged_by'] if 'transport_arranged_by' in requirement.keys() else 'volunteer'

    if don_area and req_area:
        if don_area == req_area or don_area in req_area or req_area in don_area:
            reasons.append(f"Same / adjacent cluster ({donation['location_area']})")
        else:
            reasons.append(f"Cross-cluster ({donation['location_area']} -> {requirement['location_area']}), transport mode: {transport}")

    # Determine match viability
    is_match = (len(disqualifiers) == 0)
    score = 0
    if is_match:
        score = 60 + (20 if avail_qty >= need_qty else 10) + (10 if don_area == req_area else 0) + 10
        explanation_string = " · ".join(reasons)
    else:
        explanation_string = "Blocked: " + "; ".join(disqualifiers)

    return {
        'is_match': is_match,
        'match_score': min(score, 100),
        'matched_quantity': matched_qty,
        'reasons': reasons,
        'disqualifiers': disqualifiers,
        'explanation_string': explanation_string
    }

def find_matches_for_donation(conn, donation_id):
    """Finds all compatible receiver requirements for an active donation."""
    donation = conn.execute("SELECT * FROM donations WHERE id = ?", (donation_id,)).fetchone()
    if not donation or donation['status'] != 'posted':
        return []

    requirements = conn.execute("""
        SELECT r.*, u.organization_name, u.phone as receiver_phone, u.location_area as receiver_area
        FROM requirements r
        JOIN users u ON r.receiver_id = u.id
        WHERE r.status = 'active'
    """).fetchall()

    matches = []
    for req in requirements:
        eval_result = evaluate_match(donation, req)
        if eval_result['is_match']:
            matches.append({
                'requirement': dict(req),
                'evaluation': eval_result
            })

    # Sort descending by match score
    matches.sort(key=lambda m: m['evaluation']['match_score'], reverse=True)
    return matches

def find_matches_for_requirement(conn, requirement_id):
    """Finds all compatible donations for an active receiver requirement."""
    requirement = conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone()
    if not requirement or requirement['status'] != 'active':
        return []

    donations = conn.execute("""
        SELECT d.*, u.organization_name as donor_org, u.phone as donor_phone, u.location_area as donor_area
        FROM donations d
        JOIN users u ON d.donor_id = u.id
        WHERE d.status = 'posted'
    """).fetchall()

    matches = []
    for don in donations:
        eval_result = evaluate_match(don, requirement)
        if eval_result['is_match']:
            matches.append({
                'donation': dict(don),
                'evaluation': eval_result
            })

    matches.sort(key=lambda m: m['evaluation']['match_score'], reverse=True)
    return matches
