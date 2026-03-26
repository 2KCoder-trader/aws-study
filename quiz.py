import re
import random
import threading
import time
import pandas as pd
import anthropic
from dotenv import load_dotenv

load_dotenv()  # Load API key from .env file

TIMER_SECONDS = 120  # 2 minutes per question

client = anthropic.Anthropic()

# Load questions that have answers
df = pd.read_csv("study.csv")
df = df[df["answer"].notna()].reset_index(drop=True)

def format_question(row):
    choices = ""
    for letter in "ABCDE":
        val = str(row.get(letter, "")).strip()
        if val and val != "nan":
            choices += f"  {letter}. {val}\n"
    return f"Q{row['question_num']}: {row['question']}\n\n{choices}"

def ask_claude(question_text, correct_letter, correct_text, user_answer):
    """Explain why the correct answer is right using Claude with streaming."""
    print("\n--- Claude is explaining ---\n")

    system = (
        "You are an AWS Solutions Architect exam tutor. "
        "Be concise and clear. Focus on why the correct answer is right "
        "and why the chosen answer is wrong. Use bullet points."
    )
    prompt = (
        f"AWS exam question:\n{question_text}\n\n"
        f"The student answered: {user_answer}\n"
        f"The correct answer is: {correct_letter}. {correct_text}\n\n"
        "Explain why the correct answer is right and why the student's answer is wrong. "
        "Then on a new line, list the KEY WORDS or phrases in the question that signal the correct answer "
        "(e.g. 'minimize operational overhead', 'without internet access', 'LEAST cost'). "
        "Label this section 'Keywords to watch for:'"
    )

    messages = [{"role": "user", "content": prompt}]

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
    print("\n")

    # Allow follow-up questions
    messages.append({"role": "assistant", "content": stream.get_final_message().content[0].text})
    while True:
        follow_up = input("Ask a follow-up question (or press Enter to continue): ").strip()
        if not follow_up:
            break
        messages.append({"role": "user", "content": follow_up})
        print()
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
        print("\n")
        messages.append({"role": "assistant", "content": stream.get_final_message().content[0].text})

def run_quiz(questions):
    score = 0
    for i, (_, row) in enumerate(questions.iterrows(), 1):
        print(f"\n{'='*60}")
        print(f"Question {i} of {len(questions)}  |  Score: {score}/{i-1}")
        print(f"{'='*60}\n")

        question_text = format_question(row)
        print(question_text)

        correct_answer = str(row["answer"]).strip().upper()
        is_multi = "," in correct_answer
        correct_letters = sorted(correct_answer.split(","))
        correct_text = " | ".join(
            f"{l}. {str(row.get(l, '')).strip()}" for l in correct_letters
        )

        # Timer setup
        time_up = threading.Event()
        def countdown(event=time_up):
            for _ in range(TIMER_SECONDS):
                if event.is_set():
                    return
                time.sleep(1)
            event.set()

        timer_thread = threading.Thread(target=countdown, daemon=True)
        timer_thread.start()

        prompt = "Your answers (e.g. AC or A,C): " if is_multi else "Your answer (A/B/C/D/E): "
        raw = input(prompt).strip().upper()
        time_up.set()

        if not raw:
            print("  Time's up — moving on.\n")
            continue

        # Normalize input: "AC", "A,C", "A C" → ["A","C"]
        user_letters = sorted(re.findall(r"[A-E]", raw))

        if user_letters == correct_letters:
            print(f"\n  ✓ Correct!\n")
            score += 1
        else:
            user_display = ",".join(user_letters)
            print(f"\n  ✗ Wrong. The correct answer was {correct_answer}.\n")
            ask_claude(question_text, correct_answer, correct_text, user_display)

    print(f"\n{'='*60}")
    print(f"  Final Score: {score} / {len(questions)}")
    print(f"{'='*60}\n")
    return score

def main():
    print("\n  AWS Solutions Architect Quiz")
    print("  ─────────────────────────────")
    print(f"  {len(df)} questions available | 2 min per question\n")

    while True:
        sample = df.sample(10)
        run_quiz(sample)

        again = input("Play again with new questions? (y/n): ").strip().lower()
        if again != "y":
            print("\n  Good luck on your exam!\n")
            break

if __name__ == "__main__":
    main()
