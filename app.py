# # from flask import Flask, jsonify, request
# from dotenv import load_dotenv
# from mistralai import Mistral
# import os
# import json

# load_dotenv()

# api_key = os.getenv("MISTRAL_API_KEY")
# model = "mistral-large-latest"

# client = Mistral(api_key=api_key)

# user_input = input("Enter something: ")

# chat_response = client.chat.complete(
#     model=model,
#     messages=[
#         # context learning
#         {
#             "role": "system",
#             "content": (
#                 "You are a design assistant who responds only when the user’s question falls into one of three types:\n"
#                     "1. When the user states a type of website (e.g., e-commerce, blog, portfolio, marketing, etc.), you should "
#                     "respond with a suggested colors and one of three layout types (masonry, bento, or grid).\n"
#                     "Return an object that contains colors and layout field, both fields should be lists with 3 items at least\n"
#                     "Each item in colors list should be comprised of an object that has 'primary_color', 'secondary_color', 'accent_color' and 'background_color'\n"
#                     "2. When the user asks for a colors for a specific type of website, respond with an appropriate color palette.\n"
#                     "As the user has asked for colors only, layout list should not contain any values and should be empty.\n"
#                     "Return an object that contain colors field, the field should be list with 3 items at least\n"
#                     "3. When the user asks for a layout for a specific type of website, respond with one of the three layouts: masonry, bento, or grid.\n\n"
#                     "As the user has asked for layouts only, colors list should not contain any values and should be empty\n"
#                     "If the user's question does not fall into these categories, do not respond with any information.\n"
#             ),
#         },
#         # Example user message
#         {
#             "role": "user",
#             "content": user_input,
#         },
#     ]
# )

# """
# prompt with placeholders f"{values}

# """

# output = chat_response.choices[0].message.content

# start: int = -1
# end: int = -1

# for index in range(len(output)):
#     if output[index] == "{" and start == -1:
#         start = index
#     elif output[index] == "}":
#         end = index

# if end == -1:
#     print("no output")
#     print(output)
# else:
#     json_op = json.loads(output[start : end + 1])

#     print(json_op["colors"])
#     print(json_op["layout"])

# # app = Flask(__name__)

# # # Sample route that returns a JSON response
# # @app.route("/", methods=["GET"])
# # def sendData():
# #     chat_input = request.form.get("chat_input")
# #     return jsonify(message=f"Hello, {chat_input}!")

# # # Start the Flask app
# # if __name__ == "__main__":
# #     app.run(debug=True)





from flask import Flask, jsonify, request
from dotenv import load_dotenv
from mistralai import Mistral
import os
import json

load_dotenv()

app = Flask(__name__)

api_key = os.getenv("MISTRAL_API_KEY")
model = "mistral-large-latest"
client = Mistral(api_key=api_key)


@app.route("/chat", methods=["GET"])
def chat_endpoint():
    # Get the user input from the query string (GET parameter)
    #user_input = request.args.get("user_input")
    user_input = request.form.get("user_input")

    if not user_input:
        return jsonify({"error": "No user_input provided"}), 400

    chat_response = client.chat.complete(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a design assistant who responds only when the user’s question falls into one of three types:\n"
                    "1. When the user states a type of website (e.g., e-commerce, blog, portfolio, marketing, etc.), you should "
                    "respond with a suggested colors and one of three layout types (masonry, bento, or grid).\n"
                    "Return an object that contains colors and layout field, both fields should be lists with 3 items at least\n"
                    "Each item in colors list should be comprised of an object that has 'primary_color', 'secondary_color', 'accent_color' and 'background_color'\n"
                    "2. When the user asks for a colors for a specific type of website, respond with an appropriate color palette.\n"
                    "As the user has asked for colors only, layout list should not contain any values and should be empty.\n"
                    "Return an object that contain colors field, the field should be list with 3 items at least\n"
                    "3. When the user asks for a layout for a specific type of website, respond with one of the three layouts: masonry, bento, or grid.\n\n"
                    "As the user has asked for layouts only, colors list should not contain any values and should be empty\n"
                    "If the user's question does not fall into these categories, do not respond with any information.\n"
                ),
            },
            {
                "role": "user",
                "content": user_input,
            },
        ]
    )

    output = chat_response.choices[0].message.content

    # Parse JSON response from model
    start, end = output.find('{'), output.rfind('}') + 1
    if start != -1 and end != -1:
        try:
            json_op = json.loads(output[start:end])
            return jsonify(json_op), 200
        except json.JSONDecodeError:
            return jsonify({"error": "Could not parse response from model"}), 500
    else:
        return jsonify({"error": "No valid response generated"}), 500


if __name__ == "__main__":
    app.run(debug=True)
