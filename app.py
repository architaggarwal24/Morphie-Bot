from flask import Flask, request, render_template, jsonify, session
from dotenv import load_dotenv
from mistralai import Mistral
import os, json, re

load_dotenv()

app = Flask(__name__)
app.secret_key = "super-secret-key-change-this"

client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
MODEL = "mistral-large-latest"


@app.route("/")
def home():
    if "mode" not in session:
        session["mode"] = "chat"
    return render_template("chatbot.html")


@app.route("/chat", methods=["POST"])
def chat():
    if "mode" not in session:
        session["mode"] = "chat"

    user_input = request.json.get("message", "").strip()
    text = user_input.lower()

    # MODE SWITCHING
    if text == "design mode":
        session["mode"] = "design"
        return jsonify({"type": "text", "content": "🎨 Design mode activated."})

    if text == "chat mode":
        session["mode"] = "chat"
        return jsonify({"type": "text", "content": "💬 Chat mode activated."})

    # GREETINGS
    if text in ["hi", "hello", "hey", "yo", "hii"]:
        return jsonify({"type": "text", "content": "Hey 👋 I’m Morphie."})

    # ---------------- CHAT MODE ----------------
    if session["mode"] == "chat":
        response = client.chat.complete(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are Morphie, a friendly helpful chatbot."},
                {"role": "user", "content": user_input}
            ]
        )

        return jsonify({
            "type": "text",
            "content": response.choices[0].message.content
        })

    # ---------------- DESIGN MODE ----------------
    SYSTEM_PROMPT = """
You are Morphie, a website design assistant.

Respond ONLY with valid JSON.
NO explanations.
NO markdown.
NO extra text.

Schema:
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
"""

    response = client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ]
    )

    raw = response.choices[0].message.content

    try:
        match = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(match.group())
        return jsonify({"type": "theme", "data": data})
    except Exception:
        return jsonify({
            "type": "text",
            "content": "⚠️ I couldn’t generate a design theme. Try describing a website."
        })



if __name__ == "__main__":
    app.run(debug=True)
