# postback_handler.py

from flask import Blueprint, request
import requests

postback_bp = Blueprint('postback_bp', __name__)

@postback_bp.route('/postback-handler', methods=['GET'])
def handle_postback():
    transaction_id = request.args.get("transaction_id")
    status = request.args.get("status")
    reward = request.args.get("reward")
    currency = request.args.get("currency")
    sid1 = request.args.get("sid1")  # We'll use sid1 to forward

    if not all([transaction_id, status, reward, currency]):
        return "Missing required parameters", 400

    if 'pepeleads' not in request.headers.get('User-Agent', '').lower():
        return "Unauthorized", 403

    print("✅ Postback received from PepeLeads")
    print("Transaction:", transaction_id)
    print("Status:", status)
    print("Reward:", reward)
    print("Currency:", currency)

    # Forward to SurveyTitans (using sid1 or fallback to transaction_id)
    forward_id = sid1 or transaction_id
    try:
        surveytitans_url = f"https://surveytitans.com/track?sid={forward_id}"
        response = requests.get(surveytitans_url)
        print(f"SurveyTitans response: {response.status_code}")
    except Exception as e:
        print("Error sending to SurveyTitans:", e)
        return "Error contacting SurveyTitans", 500

    return "OK", 200
