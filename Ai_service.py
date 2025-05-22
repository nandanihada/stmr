from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import json
import re
from datetime import datetime
import threading
import os
from integrations import forward_survey_data_to_partners


BASE_URL = "https://pepperadsresponses.web.app"

app = Flask(__name__)
CORS(app)

# Gemini API Configuration
genai.configure(api_key="AIzaSyAxEoutxU_w1OamJUe4FMOzr5ZdUyz8R4k")
model = genai.GenerativeModel("gemini-1.5-flash-latest")

# Firebase Setup
try:
    cred_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    cred = credentials.Certificate(json.loads(cred_json))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase connected successfully")
except Exception as e:
    print(f"Firebase initialization error: {e}")
    db = None

@app.route('/')
def index():
    return "Welcome to Survey AI Backend!"

@app.route('/save-email', methods=['POST'])
def save_email():
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email is required"}), 400

    try:
        doc_id = str(uuid.uuid4())
        email_data = {
            "email": email,
            "saved_at": firestore.SERVER_TIMESTAMP
        }
        db.collection("user_emails").document(doc_id).set(email_data)

        return jsonify({"message": "Email saved successfully", "id": doc_id})
    except Exception as e:
        print(f"Error saving email: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Received data:", data)
    db.collection('clicks').add(data)
    return {"status": "success"}, 200

def parse_survey_response(response_text):
    questions = []
    lines = response_text.split('\n')
    current_question = None

    for line in lines:
        line = line.strip()
        question_match = re.match(r'^(\d+\.\s*)(.*)', line)
        if question_match:
            if current_question:
                questions.append(current_question)
            current_question = {
                "question": question_match.group(2),
                "options": []
            }
            continue

        option_match = re.match(r'^([A-D])\)\s*(.*)', line)
        if option_match and current_question:
            current_question["options"].append(option_match.group(2))

    if current_question:
        questions.append(current_question)

    return questions

@app.route('/generate', methods=['POST'])
def generate_survey():
    data = request.json
    prompt = data.get("prompt", "")
    response_type = data.get("response_type", "multiple_choice")

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    try:
        ai_prompt = f"""
        Generate a survey with 10 questions about {prompt}. 
        For each question, provide 4 multiple-choice options (A-D).
        """

        response = model.generate_content(ai_prompt)
        questions = parse_survey_response(response.text)

        if not questions:
            return jsonify({"error": "Failed to generate valid questions"}), 500

        survey_id = str(uuid.uuid4())
        survey_data = {
            "id": survey_id,
            "prompt": prompt,
            "response_type": response_type,
            "questions": questions,
            "created_at": firestore.SERVER_TIMESTAMP,
            "shareable_link": f"{BASE_URL}/survey/{survey_id}/respond"
        }

        db.collection("surveys").document(survey_id).set(survey_data)

        return jsonify({"survey_id": survey_id, "questions": questions})

    except Exception as e:
        print(f"Survey generation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/submit', methods=['POST'])
def submit_response():
    data = request.json
    survey_id = data.get("survey_id")
    responses = data.get("responses")
    tracking_id = data.get("tracking_id")
    email = data.get("email")
    username = data.get("username")

    if not survey_id or not responses:
        return jsonify({"error": "Survey ID and responses required"}), 400

    try:
        survey_ref = db.collection("surveys").document(survey_id)
        if not survey_ref.get().exists:
            return jsonify({"error": "Survey not found"}), 404

        response_id = str(uuid.uuid4())
        response_data = {
            "id": response_id,
            "survey_id": survey_id,
            "responses": responses,
            "submitted_at": firestore.SERVER_TIMESTAMP
        }
        if email:
            response_data["email"] = email
        if username:
            response_data["username"] = username

        db.collection("survey_responses").document(response_id).set(response_data)
        forward_success = forward_survey_data_to_partners(response_data)
        if not forward_success:
            print("Survey forwarding failed (SurveyTitans)")


        if tracking_id:
            tracking_ref = db.collection("survey_tracking").document(tracking_id)
            if tracking_ref.get().exists:
                tracking_ref.update({
                    "submitted": True,
                    "submitted_at": firestore.SERVER_TIMESTAMP,
                    "response_id": response_id
                })

        return jsonify({"message": "Response submitted successfully", "response_id": response_id})

    except Exception as e:
        print(f"Response submission error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/track/survey/open', methods=['POST'])
def track_survey_open():
    data = request.json
    survey_id = data.get("survey_id")
    email = data.get("email")
    username = data.get("username")

    if not survey_id:
        return jsonify({"error": "Survey ID is required"}), 400

    try:
        tracking_id = str(uuid.uuid4())
        tracking_data = {
            "survey_id": survey_id,
            "tracking_id": tracking_id,
            "opened_at": firestore.SERVER_TIMESTAMP,
            "submitted": False,
            "user_agent": request.headers.get('User-Agent', 'Unknown'),
            "ip_address": request.remote_addr,
            "email": email,
            "username": username
        }
        db.collection("survey_tracking").document(tracking_id).set(tracking_data)

        return jsonify({"tracking_id": tracking_id, "message": "Survey opening tracked successfully"})

    except Exception as e:
        print(f"Survey tracking error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/survey/<survey_id>', methods=['GET'])
def get_survey(survey_id):
    try:
        survey_ref = db.collection("surveys").document(survey_id)
        survey = survey_ref.get()

        if survey.exists:
            tracking_id = str(uuid.uuid4())
            tracking_data = {
                "survey_id": survey_id,
                "tracking_id": tracking_id,
                "opened_at": firestore.SERVER_TIMESTAMP,
                "submitted": False,
                "user_agent": request.headers.get('User-Agent', 'Unknown'),
                "ip_address": request.remote_addr
            }
            db.collection("survey_tracking").document(tracking_id).set(tracking_data)

            survey_data = survey.to_dict()
            survey_data["tracking_id"] = tracking_id

            return jsonify(survey_data)
        else:
            return jsonify({"error": "Survey not found"}), 404

    except Exception as e:
        print(f"Survey fetch error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/survey/<survey_id>/respond', methods=['POST'])
def submit_public_response(survey_id):
    data = request.json
    responses = data.get("responses")
    tracking_id = data.get("tracking_id")
    email = data.get("email")
    username = data.get("username")

    if not responses:
        return jsonify({"error": "Responses required"}), 400

    try:
        survey_ref = db.collection("surveys").document(survey_id)
        if not survey_ref.get().exists:
            return jsonify({"error": "Survey not found"}), 404

        response_id = str(uuid.uuid4())
        response_data = {
            "id": response_id,
            "survey_id": survey_id,
            "responses": responses,
            "submitted_at": firestore.SERVER_TIMESTAMP,
            "is_public": True
        }
        if email:
            response_data["email"] = email
        if username:
            response_data["username"] = username

        db.collection("survey_responses").document(response_id).set(response_data)
        forward_success = forward_survey_data_to_partners(response_data)
        if not forward_success:
         print("Survey forwarding failed (SurveyTitans)")

        if tracking_id:
            tracking_ref = db.collection("survey_tracking").document(tracking_id)
            if tracking_ref.get().exists:
                tracking_ref.update({
                    "submitted": True,
                    "submitted_at": firestore.SERVER_TIMESTAMP,
                    "response_id": response_id
                })

        return jsonify({"message": "Response submitted successfully", "response_id": response_id})

    except Exception as e:
        print(f"Public response submission error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/insights', methods=['POST'])
def generate_insights():
    data = request.json
    survey_id = data.get("survey_id")

    if not survey_id:
        return jsonify({"error": "Survey ID is required"}), 400

    try:
        responses_ref = db.collection("survey_responses").where("survey_id", "==", survey_id)
        docs = responses_ref.stream()

        all_responses = []
        for doc in docs:
            response_data = doc.to_dict()
            responses = response_data.get("responses", {})
            for question, answer in responses.items():
                all_responses.append(f"{question}: {answer}")

        if not all_responses:
            return jsonify({"error": "No responses found"}), 404

        full_text = "\n".join(all_responses)

        prompt = (
            "Based on the following customer survey responses, suggest business strategies, improvements, or new market segments.\n"
            f"Responses:\n{full_text}\n\nBusiness Ideas:"
        )

        ai_response = model.generate_content(prompt)
        insights = ai_response.text.strip()

        return jsonify({"insights": insights})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-logic', methods=['POST'])
def check_logic():
    data = request.json
    responses = data.get("responses")

    q1 = responses.get("Do you want to start a business?")
    q2 = responses.get("Are you currently in college?")

    if q1 == "Yes" and q2 == "Yes":
        return jsonify({"next_page": "https://jobfinder-efe0e.web.app/public_survey.html?id=abc123"})
    else:
        return jsonify({"next_page": "thankyou.html"})

@app.route('/survey/<survey_id>/tracking', methods=['GET'])
def get_survey_tracking(survey_id):
    try:
        tracking_ref = db.collection("survey_tracking").where("survey_id", "==", survey_id)
        tracking_docs = tracking_ref.stream()

        total_views = 0
        total_submissions = 0
        view_data = []

        for doc in tracking_docs:
            data = doc.to_dict()
            total_views += 1
            view_data.append(data)

            if data.get("submitted", False):
                total_submissions += 1

        completion_rate = 0
        if total_views > 0:
            completion_rate = (total_submissions / total_views) * 100

        return jsonify({
            "survey_id": survey_id,
            "total_views": total_views,
            "total_submissions": total_submissions,
            "completion_rate": completion_rate,
            "view_data": view_data
        })

    except Exception as e:
        print(f"Survey tracking stats error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/survey/<survey_id>/view', methods=['GET'])
def view_survey(survey_id):
    try:
        survey_ref = db.collection("surveys").document(survey_id)
        survey = survey_ref.get()

        if not survey.exists:
            return jsonify({"error": "Survey not found"}), 404

        survey_data = survey.to_dict()
        responses_ref = db.collection("survey_responses").where("survey_id", "==", survey_id)
        responses = responses_ref.stream()

        response_list = [resp.to_dict() for resp in responses]

        return jsonify({"survey": survey_data, "responses": response_list})

    except Exception as e:
        print(f"Survey view error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
