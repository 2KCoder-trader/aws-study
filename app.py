import re
import json
import random
import os
from datetime import datetime
import pandas as pd
import anthropic
from flask import Flask, render_template, request, Response, stream_with_context, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

HISTORY_FILE = "quiz_history.json"

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE) as f:
        return json.load(f)

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

load_dotenv()

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
)
client = anthropic.Anthropic()

# Load questions
df = pd.read_csv("study.csv")
df = df[df["answer"].notna()].reset_index(drop=True)

def get_choices(row):
    choices = {}
    for letter in "ABCDEF":
        val = str(row.get(letter, "")).strip()
        if val and val != "nan":
            choices[letter] = val
    return choices

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify(load_history())

@app.route("/api/history/save", methods=["POST"])
def save_quiz():
    data = request.json
    history = load_history()
    entry = {
        "id": len(history) + 1,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "start_time": data["start_time"],
        "end_time": datetime.now().strftime("%H:%M:%S"),
        "duration_seconds": data["duration_seconds"],
        "score": data["score"],
        "total": data["total"],
        "percentage": round(data["score"] / data["total"] * 100),
        "questions": data["questions"],
    }
    history.append(entry)
    save_history(history)
    return jsonify({"ok": True, "id": entry["id"]})

@app.route("/api/questions")
def get_questions():
    count = int(request.args.get("count", 10))
    sample = df.sample(min(count, len(df)))
    questions = []
    for _, row in sample.iterrows():
        answer = str(row["answer"]).strip().upper()
        num_answers = len(answer.split(","))
        questions.append({
            "question_num": int(row["question_num"]),
            "question": row["question"],
            "choices": get_choices(row),
            "answer": answer,
            "num_answers": num_answers,
        })
    return {"questions": questions}

@app.route("/api/explain", methods=["POST"])
@limiter.limit("30 per hour; 100 per day")
def explain():
    data = request.json
    question_text = data["question"]
    choices = data["choices"]
    correct = data["correct"]
    user_answer = data["user_answer"]
    messages = data.get("messages", [])

    choices_fmt = "\n".join(f"{k}. {v}" for k, v in choices.items())
    full_question = f"{question_text}\n\n{choices_fmt}"

    if not messages:
        correct_letters = correct.split(",")
        correct_text = " | ".join(f"{l}. {choices.get(l, '')}" for l in correct_letters)
        user_prompt = (
            f"AWS exam question:\n{full_question}\n\n"
            f"The student answered: {user_answer}\n"
            f"The correct answer is: {correct_text}\n\n"
            "1. Explain why the correct answer is right and why the student's answer is wrong.\n"
            "2. List the KEY WORDS or phrases in the question that signal the correct answer. "
            "Label this section 'Keywords to watch for:'\n"
            "3. Give one concise exam tip for this topic or question type to help remember on test day. "
            "Label this section 'Exam tip:'"
        )
        messages = [{"role": "user", "content": user_prompt}]

    system = (
        "You are an AWS Solutions Architect exam tutor. "
        "Be concise and clear. Use bullet points."
    )

    def generate():
        full_response = ""
        try:
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=1024,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'text': text})}\n\n"
            messages.append({"role": "assistant", "content": full_response})
            yield f"data: {json.dumps({'done': True, 'messages': messages})}\n\n"
        except Exception as e:
            app.logger.error(f"Claude error: {e}")
            yield f"data: {json.dumps({'text': f'Error: {str(e)}'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'messages': messages})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
