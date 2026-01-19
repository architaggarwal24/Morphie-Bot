# from flask import Flask, request, render_template
# from dotenv import load_dotenv
# from mistralai import Mistral
# import os

# # Load environment variables
# load_dotenv()

# # Retrieve API key from .env file
# api_key = os.getenv("MISTRAL_API_KEY")
# if not api_key:
#     raise ValueError("MISTRAL_API_KEY is missing. Please check your .env file.")

# # Initialize Mistral API client
# client = Mistral(api_key=api_key)
# model = "mistral-large-latest"

# # Initialize Flask app
# app = Flask(__name__)

# @app.route('/')
# def index():
#     return render_template('chatbot.html')

# @app.route("/chat", methods=["POST"])
# def chat():
#     """
#     Handle chatbot interaction requests.
#     """
#     data = request.get_json()
#     user_input = data.get("message")

#     if not user_input:
#         return "No input provided", 400

#     try:
#         chat_response = client.chat.complete(
#             model=model,
#             messages=[
#                 {
#                     "role": "system",
#                     "content": (
#                         "You are a design assistant who responds only when the user’s question falls into one of three types:\n"
#                         "1. When the user states a type of website (e.g., e-commerce, blog, portfolio, marketing, etc.), you should "
#                         "respond with suggested colors and one of three layout types (masonry, bento, or grid).\n"
#                         "Return an object that contains 'colors' and 'layout' fields. Both should be lists with at least 3 items.\n"
#                         "Each item in the colors list should be an object with 'primary_color', 'secondary_color', 'accent_color', and 'background_color'.\n"
#                         "2. When the user asks for colors for a specific type of website, respond with an appropriate color palette.\n"
#                         "In this case, the 'layout' list should be empty.\n"
#                         "3. When the user asks for a layout for a specific type of website, respond with one of the three layouts: masonry, bento, or grid.\n"
#                         "In this case, the 'colors' list should be empty.\n"
#                         "If the user's question does not fall into these categories, do not respond with any information."
#                     ),
#                 },
#                 {"role": "user", "content": user_input},
#             ],
#         )

#         output = chat_response.choices[0].message.content
#         return output  # Return plain text, not JSON

#     except Exception as e:
#         return f"Error: {str(e)}", 500

# if __name__ == "__main__":
#     app.run(debug=True)





from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
from mistralai import Mistral
import os
import json
import re


load_dotenv()


app = Flask(__name__)


api_key = os.getenv("MISTRAL_API_KEY")
if not api_key:
    raise ValueError("MISTRAL_API_KEY is missing.")


client = Mistral(api_key=api_key)
MODEL = "mistral-large-latest"


@app.route("/")
def home():
    return render_template("chatbot.html")


@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "").strip()


    # 1️⃣ Handle greetings (UX fix)
    greetings = ["hi", "hello", "hey", "yo", "hii", "hola"]
    if user_input.lower() in greetings:
        return jsonify({
            "type": "text",
            "content": "Hey 👋 I’m Morphie. I help design websites. Tell me what kind you’re building!"
        })


    # 2️⃣ Call AI
    SYSTEM_PROMPT = """
                    You are Morphie, a website design assistant.

                    You MUST respond with ONLY valid JSON.
                    NO explanations.
                    NO markdown.
                    NO backticks.
                    NO extra text.

                    The JSON schema MUST be exactly:

                    {
                    "colors": [
                        {
                        "primary_color": "#hex",
                        "secondary_color": "#hex",
                        "accent_color": "#hex"
                        }
                    ],
                    "layouts": ["layout1", "layout2", "layout3"]
                    }

                    If the user asks about website ideas, themes, or design, generate this JSON."""
    
    
    response = client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ]
    )


    def extract_json(text):
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("No JSON object found")
        return json.loads(match.group())


    raw_text = response.choices[0].message.content

    try:
        data = extract_json(raw_text)
        return jsonify({
            "type": "theme",
            "data": data
        })
    except Exception as e:
        print("JSON PARSE ERROR:", raw_text)
        return jsonify({
            "type": "text",
            "content": "⚠️ I couldn’t generate a design theme. Try asking about a website type."
        })



if __name__ == "__main__":
    app.run(debug=True)