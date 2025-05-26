from flask import Blueprint, request, jsonify
import requests
from firebase_admin import firestore

postback_bp = Blueprint('postback_bp', __name__)
db = firestore.client()

@postback_bp.route('/postback-handler', methods=['GET'])
def handle_postback():
    transaction_id = request.args.get("transaction_id")
    status = request.args.get("status")
    reward = request.args.get("reward")
    currency = request.args.get("currency")
    sid1 = request.args.get("sid1")

    if not all([transaction_id, status, reward, currency, sid1]):
        return "Missing required parameters", 400

    if 'pepeleads' not in request.headers.get('User-Agent', '').lower():
        return "Unauthorized", 403

    print("✅ Postback received from PepeLeads")

    try:
        # Find the pending survey response
        responses_ref = db.collection("survey_responses").where("tracking_id", "==", sid1).where("status", "==", "pending").limit(1)
        results = list(responses_ref.stream())

        if not results:
            return "No matching pending survey found", 404

        response_doc = results[0]
        response_data = response_doc.to_dict()

        # Forward to SurveyTitans
        surveytitans_url = "https://surveytitans.com/track"
        payload = {
            "sid": sid1,
            "responses": response_data.get("responses", {}),
            "email": response_data.get("email", "")
        }

        res = requests.post(surveytitans_url, json=payload)
        print(f"SurveyTitans response: {res.status_code}")

        # Update status to confirmed
        response_doc.reference.update({"status": "confirmed"})

        return "Survey forwarded to SurveyTitans", 200

    except Exception as e:
        print("Error handling postback:", e)
        return "Internal server error", 500
