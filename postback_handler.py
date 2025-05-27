import os
import json
from flask import Blueprint, request, jsonify
import requests
import firebase_admin
from firebase_admin import credentials, firestore

# Create blueprint
postback_bp = Blueprint('postback_bp', __name__)

def get_db():
    return firestore.client()

# PepperAds Postback Handler
@postback_bp.route('/pepperads/postback', methods=['GET'])
def handle_pepperads_postback():
    sid = request.args.get("sid")
    uid = request.args.get("uid")
    status = request.args.get("status", "complete")

    if not sid or not uid:
        return "Missing sid or uid", 400

    try:
        db = get_db()
        responses_ref = db.collection("survey_responses") \
            .where("survey_id", "==", sid) \
            .where("status", "==", "pending") \
            .limit(1)

        result = list(responses_ref.stream())
        if not result:
            return "No matching pending survey found", 404

        doc = result[0]
        doc.reference.update({"status": status})

        print(f"✅ PepperAds postback recorded for sid={sid}, uid={uid}")
        return "Postback received", 200

    except Exception as e:
        print("Error handling PepperAds postback:", e)
        return "Internal error", 500
