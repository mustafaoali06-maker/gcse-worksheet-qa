import os
from openai import OpenAI
from docx import Document
from agents import *

# --------------------------------------------------
# ð OpenAI client configuration
# --------------------------------------------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



# --------------------------------------------------
# ð Extract text from Word file
# --------------------------------------------------
def extract_docx_text(file_path):
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return "\n".join(full_text)


# --------------------------------------------------
# ð Load scope from scope.txt
# --------------------------------------------------
def load_scope():
    with open("scope.txt", "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------
# ð¤ Run an agent
# --------------------------------------------------
def run_agent(prompt, content):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content}
        ],
        temperature=0
    )
    return response.choices[0].message.content


# --------------------------------------------------
# ð Main Execution
# --------------------------------------------------
def main():

    print("Loading worksheet...")
    worksheet_text = extract_docx_text("input.docx")

    print("Loading intended scope...")
    scope_text = load_scope()

    # ---------------------------
    # Agent 1
    # ---------------------------
    print("Running Agent 1 (Command Word Alignment)...")
    report1 = run_agent(
        AGENT_1_PROMPT,
        f"WORKSHEET AND MARK SCHEME:\n{worksheet_text}"
    )

    # ---------------------------
    # Agent 2
    # ---------------------------
    print("Running Agent 2 (Structural Validation)...")
    report2 = run_agent(
        AGENT_2_PROMPT,
        f"WORKSHEET AND MARK SCHEME:\n{worksheet_text}"
    )

    # ---------------------------
    # Agent 3
    # ---------------------------
    print("Running Agent 3 (Cognitive Balance)...")
    report3 = run_agent(
        AGENT_3_PROMPT,
        f"WORKSHEET AND MARK SCHEME:\n{worksheet_text}"
    )

    # ---------------------------
    # Agent 4 (Scope-Aware)
    # ---------------------------
    print("Running Agent 4 (Topic Coverage)...")
    report4 = run_agent(
        AGENT_4_PROMPT,
        f"""
WORKSHEET AND MARK SCHEME:
{worksheet_text}

INTENDED SCOPE:
{scope_text}
"""
    )

    # ---------------------------
    # Agent 5 (Final Revision)
    # ---------------------------
    print("Running Agent 5 (Final Intelligent Revision)...")

    combined_input = f"""
ORIGINAL WORKSHEET AND MARK SCHEME:
{worksheet_text}

INTENDED SCOPE:
{scope_text}

AGENT 1 REPORT:
{report1}

AGENT 2 REPORT:
{report2}

AGENT 3 REPORT:
{report3}

AGENT 4 REPORT:
{report4}
"""

    final_version = run_agent(AGENT_5_PROMPT, combined_input)

    print("\n\n================ FINAL OUTPUT ================\n")
    print(final_version)


if __name__ == "__main__":
    main()

