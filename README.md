# 🤖 Morphie-Bot

Morphie is an **AI-powered design copilot** that helps users generate **website design themes**, including **color palettes and layout ideas**, through a clean chat-based interface.

Unlike basic chatbots, Morphie supports **two intelligent modes** — **Chat Mode** and **Design Mode** — giving users full control over how the AI behaves.

Powered by **Mistral AI** and built with **Flask**, Morphie focuses on **structured, usable design output** rather than random text generation.

---

## ✨ Key Features

### 💬 Chat Mode

* Natural conversational AI
* Handles greetings, casual questions, and general discussion
* Does **not** generate design themes
* Useful for ideation and clarification

### 🎨 Design Mode

* Generates **structured website themes**
* Returns:

  * 🎨 Primary / Secondary / Accent color palettes
  * 🧩 Layout suggestions
* Visual output (color swatches + labels)
* No raw JSON exposed to the user

### 🧠 Smart Mode Memory

* Remembers the active mode per session
* Switching modes preserves conversation history per mode
* Prevents accidental theme generation

### 🖥️ Interactive UI

* Modern, responsive chatbot interface
* Mode toggle buttons with active states
* Smooth animations and loading indicators

---

## 🛠️ Tech Stack

* **Frontend**: HTML, CSS, JavaScript
* **Backend**: Python (Flask)
* **AI Model**: Mistral AI
* **Session Management**: Flask Sessions
* **Environment Config**: python-dotenv

---

## 📦 Installation & Setup

### Prerequisites

* Python **3.8+**
* Mistral AI API Key

---

### 1️⃣ Clone the Repository

```sh
git clone https://github.com/yourusername/Morphie-Bot.git
cd Morphie-Bot
```

---

### 2️⃣ Create Virtual Environment & Install Dependencies

```sh
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

---

### 3️⃣ Configure Environment Variables

Create a `.env` file in the project root:

```env
MISTRAL_API_KEY=your_api_key_here
```

---

### 4️⃣ Run the Application

```sh
python app.py
```

---

### 5️⃣ Open in Browser

```
http://127.0.0.1:5000
```

---

## 🧪 How to Use

### Switching Modes

* Click **💬 Chat** for normal conversation
* Click **🎨 Design** to generate website themes
* Or type:

  * `chat mode`
  * `design mode`

### Generate a Design (Design Mode)

Example prompts:

```
design for ecommerce website
portfolio website theme
gaming website UI
```

### Chat Freely (Chat Mode)

Example prompts:

```
hey
how are you
tell me an idea
```

---

## 📁 Project Structure

```
├── .env                # Environment variables
├── app.py              # Flask backend
├── templates/
│   └── chatbot.html    # Frontend UI
├── requirements.txt    # Python dependencies
└── README.md
```

---

## 🚀 Future Improvements

* Theme refinement (change only accent / layout)
* Export themes as CSS variables
* Save themes per user
* Multi-step design wizard
* Persistent user sessions

---

## 👤 Author

**Archit Aggarwal**
GitHub: [https://github.com/architaggarwal24](https://github.com/architaggarwal24)
LinkedIn: [https://linkedin.com/in/architaggarwal24](https://linkedin.com/in/architaggarwal24)

---

## ⭐ Support

If you found Morphie useful or learned something from it, consider giving the repository a ⭐ — it really helps!
