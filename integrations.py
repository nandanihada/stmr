import requests

def forward_survey_data_to_partners(response_data):
    try:
        # Step 1: Send to SurveyTitans via GET postback
        username = response_data.get("username", "unknown")
        surveytitans_url = f"https://surveytitans.com/spb/8aee12653f60e80eee21523497824951?username={username}"
        titans_response = requests.get(surveytitans_url)

        if titans_response.status_code != 200:
            print("SurveyTitans postback failed:", titans_response.text)
            return False

        print("Successfully sent survey completion to SurveyTitans.")

        # Step 2 (Optional): Placeholder for PepperAds
        # TODO: Add PepperAds integration here when backend is ready

        return True

    except Exception as e:
        print("Error during partner forwarding:", str(e))
        return False
