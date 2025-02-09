# Morphie-Bot

Morphie is an AI-powered chatbot designed to assist users in generating website design ideas, color suggestions, and layout options based on user input. It leverages Mistral AI to analyze queries and provide structured responses.

## Features
- **Website Design Assistance**: Provides suggestions for website themes, color palettes, and layouts.
- **Smart Responses**: Responds only when queries match predefined design-related categories.
- **Interactive UI**: A responsive chatbot interface for seamless interaction.
- **Powerful Backend**: Uses Mistral AI for intelligent recommendations.

## Technologies Used
- **Frontend**: HTML, CSS, JavaScript
- **Backend**: Python (Flask)
- **Database**: JSON-based storage
- **AI Model**: Mistral AI

## Installation

### Prerequisites
- Python 3.8+
- Flask
- Mistral AI API Key

### Setup
1. Clone the repository:
   ```sh
   git clone https://github.com/yourusername/Morphie-Bot.git
   cd Morphie-Bot
   ```

2. Create a virtual environment and install dependencies:
   ```sh
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   - Create a `.env` file and add your Mistral API key:
     ```env
     MISTRAL_API_KEY="your API key"
     ```

4. Run the application:
   ```sh
   python app.py
   ```

5. Open the chatbot interface in your browser:
   ```
   http://localhost:5000
   ```

## Usage
- Enter a website type (e.g., "e-commerce", "portfolio") to get suggested colors and layouts.
- Request specific color palettes or layouts separately.
- If the input does not match the predefined categories, Morphie will not respond.

## File Structure
```
├── .env               # API Key storage
├── app.py             # Backend Flask application
├── chatbot.html       # Chatbot UI
```

## Future Enhancements
- Implement real-time chat support.
- Add more customization options for website themes.
- Improve response generation with machine learning models.

---
Feel free to contribute or submit pull requests!
