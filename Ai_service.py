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
import os, json
from firebase_admin import credentials

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


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Received data:", data)
    db.collection('clicks').add(data)
    return {"status": "success"}, 200

def parse_survey_response(response_text):
    """
    Parse AI-generated survey questions with a more robust method
    """
    questions = []
    # Split the text into lines
    lines = response_text.split('\n')
    current_question = None

    for line in lines:
        line = line.strip()

        # Check if line is a question
        question_match = re.match(r'^(\d+\.\s*)(.*)', line)
        if question_match:
            # If there's a previous question, add it to the list
            if current_question:
                questions.append(current_question)

            # Start a new question
            current_question = {
                "question": question_match.group(2),
                "options": []
            }
            continue

        # Check if line is an option
        option_match = re.match(r'^([A-D])\)\s*(.*)', line)
        if option_match and current_question:
            current_question["options"].append(option_match.group(2))

    # Add the last question
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
        # Enhanced AI prompt for more structured survey generation
        ai_prompt = f"""
        Generate a survey with 10 questions about {prompt}. 
        For each question, provide a clear, concise question followed by 4 distinct multiple-choice options.

        Format guidelines:
        - Number each question
        - Label options with A), B), C), D)
        - Ensure options cover different perspectives or responses
        - Make questions specific and easy to understand

        Example format:
        1. What is your primary mode of transportation?
        A) Car
        B) Public Transit
        C) Bicycle
        D) Walking

        Survey about: {prompt}
        """

        # Generate survey questions
        response = model.generate_content(ai_prompt)
        questions = parse_survey_response(response.text)

        # Validate questions
        if not questions or len(questions) == 0:
            return jsonify({"error": "Failed to generate valid questions"}), 500

        # Create unique survey ID
        survey_id = str(uuid.uuid4())

        # Prepare survey data for Firestore
        survey_data = {
            "id": survey_id,
            "prompt": prompt,
            "response_type": response_type,
            "questions": questions,
            "created_at": firestore.SERVER_TIMESTAMP,
            "shareable_link": f"/survey/{survey_id}/respond"
        }

        # Save survey to Firestore
        db.collection("surveys").document(survey_id).set(survey_data)

        return jsonify({
            "survey_id": survey_id,
            "questions": questions
        })

    except Exception as e:
        print(f"Survey generation error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/submit', methods=['POST'])
def submit_response():
    data = request.json
    survey_id = data.get("survey_id")
    responses = data.get("responses")
    tracking_id = data.get("tracking_id")

    if not survey_id or not responses:
        return jsonify({"error": "Survey ID and responses required"}), 400

    try:
        # Make sure the survey exists
        survey_ref = db.collection("surveys").document(survey_id)
        if not survey_ref.get().exists:
            return jsonify({"error": "Survey not found"}), 404

        # Generate a unique response ID
        response_id = str(uuid.uuid4())

        # Prepare response data
        response_data = {
            "id": response_id,
            "survey_id": survey_id,
            "responses": responses,
            "submitted_at": firestore.SERVER_TIMESTAMP
        }

        # Save to survey_responses collection
        db.collection("survey_responses").document(response_id).set(response_data)

        # Update tracking document if tracking_id is provided
        if tracking_id:
            tracking_ref = db.collection("survey_tracking").document(tracking_id)
            if tracking_ref.get().exists:
                tracking_ref.update({
                    "submitted": True,
                    "submitted_at": firestore.SERVER_TIMESTAMP,
                    "response_id": response_id
                })

        return jsonify({
            "message": "Response submitted successfully",
            "response_id": response_id
        })

    except Exception as e:
        print(f"Response submission error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/surveys', methods=['GET'])
def get_surveys():
    try:
        # Fetch surveys, ordered by creation time
        surveys_ref = db.collection("surveys").order_by("created_at", direction=firestore.Query.DESCENDING)
        surveys = surveys_ref.stream()

        survey_list = []
        for survey in surveys:
            survey_data = survey.to_dict()
            survey_list.append({
                "id": survey.id,
                "prompt": survey_data.get("prompt", ""),
                "created_at": survey_data.get("created_at")
            })

        return jsonify({"surveys": survey_list})

    except Exception as e:
        print(f"Surveys fetch error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/survey/<survey_id>', methods=['GET'])
def get_survey(survey_id):
    try:
        # Fetch specific survey
        survey_ref = db.collection("surveys").document(survey_id)
        survey = survey_ref.get()

        if survey.exists:
            # Generate a tracking ID for this survey view
            tracking_id = str(uuid.uuid4())

            # Create tracking document in Firestore
            tracking_data = {
                "survey_id": survey_id,
                "tracking_id": tracking_id,
                "opened_at": firestore.SERVER_TIMESTAMP,
                "submitted": False,
                "user_agent": request.headers.get('User-Agent', 'Unknown'),
                "ip_address": request.remote_addr
            }

            # Store tracking data
            db.collection("survey_tracking").document(tracking_id).set(tracking_data)

            # Add tracking ID to the survey data before returning
            survey_data = survey.to_dict()
            survey_data["tracking_id"] = tracking_id

            return jsonify(survey_data)
        else:
            return jsonify({"error": "Survey not found"}), 404

    except Exception as e:
        print(f"Survey fetch error: {e}")
        return jsonify({"error": str(e)}), 500


# Add this new route to get survey response page
@app.route('/survey/<survey_id>/view', methods=['GET'])
def view_survey(survey_id):
    try:
        # Get survey details
        survey_ref = db.collection("surveys").document(survey_id)
        survey = survey_ref.get()

        if not survey.exists:
            return jsonify({"error": "Survey not found"}), 404

        survey_data = survey.to_dict()

        # Get all responses for this survey
        responses_ref = db.collection("survey_responses").where("survey_id", "==", survey_id)
        responses = responses_ref.stream()

        response_list = [resp.to_dict() for resp in responses]

        return jsonify({
            "survey": survey_data,
            "responses": response_list
        })

    except Exception as e:
        print(f"Survey view error: {e}")
        return jsonify({"error": str(e)}), 500


# Add tracking for survey views and completions
@app.route('/track/survey/open', methods=['POST'])
def track_survey_open():
    data = request.json
    survey_id = data.get("survey_id")

    if not survey_id:
        return jsonify({"error": "Survey ID is required"}), 400

    try:
        # Generate a tracking ID
        tracking_id = str(uuid.uuid4())

        # Create tracking document in Firestore
        tracking_data = {
            "survey_id": survey_id,
            "tracking_id": tracking_id,
            "opened_at": firestore.SERVER_TIMESTAMP,
            "submitted": False,
            "user_agent": request.headers.get('User-Agent', 'Unknown'),
            "ip_address": request.remote_addr
        }

        # Store tracking data
        db.collection("survey_tracking").document(tracking_id).set(tracking_data)

        return jsonify({
            "tracking_id": tracking_id,
            "message": "Survey opening tracked successfully"
        })

    except Exception as e:
        print(f"Survey tracking error: {e}")
        return jsonify({"error": str(e)}), 500


# Add this new route for public response submission
@app.route('/survey/<survey_id>/respond', methods=['POST'])
def submit_public_response(survey_id):
    data = request.json
    responses = data.get("responses")
    tracking_id = data.get("tracking_id")

    if not responses:
        return jsonify({"error": "Responses required"}), 400

    try:
        # Verify survey exists
        survey_ref = db.collection("surveys").document(survey_id)
        if not survey_ref.get().exists:
            return jsonify({"error": "Survey not found"}), 404

        # Save response
        response_id = str(uuid.uuid4())
        response_data = {
            "id": response_id,
            "survey_id": survey_id,
            "responses": responses,
            "submitted_at": firestore.SERVER_TIMESTAMP,
            "is_public": True  # Mark as public response
        }

        db.collection("survey_responses").document(response_id).set(response_data)

        # Update tracking document if tracking_id is provided
        if tracking_id:
            tracking_ref = db.collection("survey_tracking").document(tracking_id)
            if tracking_ref.get().exists:
                tracking_ref.update({
                    "submitted": True,
                    "submitted_at": firestore.SERVER_TIMESTAMP,
                    "response_id": response_id
                })

        return jsonify({
            "message": "Response submitted successfully",
            "response_id": response_id
        })

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
        # Get all responses for this survey
        responses_ref = db.collection("survey_responses").where("survey_id", "==", survey_id)
        docs = responses_ref.stream()

        # Collect all responses into text
        all_responses = []
        for doc in docs:
            response_data = doc.to_dict()
            responses = response_data.get("responses", {})
            for question, answer in responses.items():
                all_responses.append(f"{question}: {answer}")

        if not all_responses:
            return jsonify({"error": "No responses found"}), 404

        full_text = "\n".join(all_responses)

        # Generate insights using Gemini
        prompt = (
            "Based on the following customer survey responses, suggest business strategies, improvements, or new market segments.\n"
            "Responses:\n"
            f"{full_text}\n\n"
            "Business Ideas:"
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


# Add routes to get tracking statistics
@app.route('/survey/<survey_id>/tracking', methods=['GET'])
def get_survey_tracking(survey_id):
    try:
        # Get tracking data for this survey
        tracking_ref = db.collection("survey_tracking").where("survey_id", "==", survey_id)
        tracking_docs = tracking_ref.stream()

        # Count total views and submissions
        total_views = 0
        total_submissions = 0
        view_data = []

        for doc in tracking_docs:
            data = doc.to_dict()
            total_views += 1
            view_data.append(data)

            if data.get("submitted", False):
                total_submissions += 1

        # Calculate completion rate
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


if __name__ == '__main__':
    app.run(debug=True)