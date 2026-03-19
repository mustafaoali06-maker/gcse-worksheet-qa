import streamlit as st
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_TAB_ALIGNMENT, WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from openai import OpenAI
import os
import re
import time
import json
from io import BytesIO
from agents import (
    FORMATTING_AGENT_PROMPT,
    AGENT_1_PROMPT,
    AGENT_2_PROMPT,
    AGENT_3_PROMPT,
    AGENT_4_PROMPT,
    AGENT_5_PROMPT,
)

# ---------------- CONFIG ----------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
st.set_page_config(page_title="GCSE Worksheet QA Studio", layout="wide")

ANSWER_LINE = "____________________________________________________________________________"

# ---------------- STYLE ----------------
st.markdown("""
<style>
html, body, [class*="css"]  {
    background-color: #0e1117;
    color: white;
}
h1 { color: #f39c12; }
.stButton>button {
    background-color: #f39c12;
    color: black;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

st.title("GCSE Worksheet QA & Validation Studio")

# Logo display (if available)
logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
if os.path.exists(logo_path):
    st.image(logo_path, width=140)

# ---------------- SIDEBAR ----------------
with st.sidebar:
    worksheet_file = st.file_uploader("Upload Worksheet (.docx)", type=["docx"])
    markscheme_file = st.file_uploader("Upload Mark Scheme (.docx)", type=["docx"])

    st.markdown("### Specification (Optional)")
    spec_txt = st.file_uploader("Upload Spec (.txt)", type=["txt"])
    spec_docx = st.file_uploader("Upload Spec (.docx)", type=["docx"])
    pasted_spec = st.text_area("Or Paste Specification")

    run_button = st.button("Run Enhancement")

# ---------------- HELPERS ----------------

def extract_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def clean_text(text):
    return re.sub(r'[#*]+', '', text)

def add_answer_lines(text):
    lines = text.split("\n")
    output = []
    for line in lines:
        output.append(line)
        match = re.search(r"\((\d+)\)", line)
        if match:
            marks = int(match.group(1))
            for _ in range(min(marks, 4)):
                output.append(ANSWER_LINE)
    return "\n".join(output)

def extract_total(text):
    match = re.search(r"Total for paper\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else None

def fractional_marks_present(text):
    return bool(re.search(r"\(\d+\.\d+\)", text))

def keyword_overlap(text1, text2):
    words1 = set(re.findall(r'\b[a-zA-Z]{5,}\b', text1.lower()))
    words2 = set(re.findall(r'\b[a-zA-Z]{5,}\b', text2.lower()))
    if not words1:
        return 0
    return round((len(words1 & words2) / len(words1)) * 100, 1)

def extract_question_numbers(text):
    """
    Extract main question numbers from the start of lines.
    Avoid mis-reading data like '2500 J' as a question number by:
    - Only accepting numbers followed by a bracket, dot, or letter.
    - Ignoring very large numbers that are unrealistic as question numbers.
    """
    nums = set()
    for m in re.finditer(r"^\s*(\d+)\s*(?=[.(A-Za-z])", text, re.MULTILINE):
        n = m.group(1)
        try:
            v = int(n)
        except ValueError:
            continue
        if v <= 50:
            nums.add(n)
    return sorted(nums, key=lambda x: int(x))

def spec_coverage(worksheet_text, spec_text):
    if not spec_text.strip():
        return "No specification provided."
    spec_keywords = list(set(re.findall(r'\b[a-zA-Z]{6,}\b', spec_text.lower())))[:50]
    covered = [k for k in spec_keywords if k in worksheet_text.lower()]
    percent = round((len(covered) / len(spec_keywords)) * 100, 1) if spec_keywords else 0
    return f"Specification keyword coverage (sample-based): {percent}%"


def strip_answer_lines(text):
    """Remove existing answer line placeholders to give FormattingAgent clean question text."""
    lines = text.split("\n")
    return "\n".join([ln for ln in lines if ANSWER_LINE.strip() not in ln.strip()])


def detect_question_structure(text):
    """
    Detect question numbers, lettered sub-parts, and roman numeral sub-parts.
    Returns a structure the mark scheme generator uses to avoid hallucinating
    or skipping questions at any level of the hierarchy.
    """
    ROMAN_RE = re.compile(
        r"^\s*\((i{1,4}|iv|vi{0,3}|ix|xi{0,3}|x{1,3})\)\s", re.IGNORECASE
    )
    PART_RE = re.compile(r"^\s*\(([a-z])\)\s")

    structure = {}
    current_q = None
    current_part = None

    for line in text.split("\n"):
        if "Total for question" in line:
            continue

        m_main = re.match(r"^\s*(\d+)\s*(?=[.(A-Za-z])", line)
        if m_main:
            v = int(m_main.group(1))
            if v <= 50:
                current_q = m_main.group(1)
                current_part = None
                structure.setdefault(current_q, {"parts": {}})
            continue

        if current_q is None:
            continue

        m_roman = ROMAN_RE.match(line)
        if m_roman and current_part is not None:
            roman = m_roman.group(1).lower()
            structure[current_q]["parts"].setdefault(current_part, set())
            structure[current_q]["parts"][current_part].add(roman)
            continue

        m_part = PART_RE.match(line)
        if m_part:
            letter = m_part.group(1)
            structure[current_q]["parts"].setdefault(letter, set())
            current_part = letter

    result = []
    for qnum, info in structure.items():
        parts_list = []
        for letter in sorted(info["parts"].keys()):
            roman_set = sorted(info["parts"][letter])
            entry = {"letter": letter}
            if roman_set:
                entry["roman_subparts"] = roman_set
            parts_list.append(entry)
        result.append({"question_number": qnum, "parts": parts_list})
    return result


def read_spec_text(spec_txt_file, spec_docx_file, pasted_spec_text):
    parts = []
    if spec_txt_file is not None:
        try:
            parts.append(spec_txt_file.read().decode("utf-8"))
        except Exception:
            pass
    if spec_docx_file is not None:
        try:
            parts.append(extract_docx(spec_docx_file))
        except Exception:
            pass
    if pasted_spec_text:
        parts.append(pasted_spec_text)
    return "\n\n".join(p.strip() for p in parts if p and p.strip())

# ---------------- AI ----------------

def improve_worksheet(text):
    prompt = """
You are improving a GCSE worksheet to match a professional exam-standard format.
Follow these rules EXACTLY:

CONTENT RULES:
1. Make every question clear and unambiguous. Remove AI-sounding or strange wording.
2. Questions should replicate real GCSE exam questions in style and difficulty.
3. Ensure a MIX of question types: 1-mark recall, 2-3 mark describe, 3-4 mark explain, calculation questions.
4. Include at least one application-style question with a named scenario (e.g. "A student, Sarah, connects a circuit...").
5. Do NOT repeat questions or topics.
6. Ensure every multi-mark question has appropriate cognitive demand.
7. Numbers in question stems should be written as WORDS (e.g. "two" not "2"), EXCEPT for: physical values (e.g. "15 m/s"), equations, or units.

FORMATTING RULES:
8. Remove ALL topic headers (e.g. "Work and Energy Transfers", "Forces", "Section A").
9. Remove ALL formatting symbols: *, #, bullet points, dashes used as headers.
10. In any question context/stem text, replace " = " and " - " used as label separators with ": ".
    Example: "Work Done = Force × Distance" in a context line → "Work done: force × distance"
11. Question numbering must be consistent: 1, 2, 3 ... (a), (b), (c) ... (i), (ii), (iii).
    - Main question numbers should NOT have a dot (use "1" not "1.")
12. Do NOT add answer lines — these are handled separately.
13. Keep mark allocations exactly as shown, e.g. (2).
14. Ensure there is NO space between sub-parts (a), (b), (c) of the SAME question.
15. There SHOULD be a blank line between separate main questions (1, 2, 3...).
16. Do NOT completely rewrite questions — only improve clarity and GCSE realism.
17. If a question has sub-parts (a)(i), (a)(ii), the letter (a) alone should NOT be on its own line
    if it only introduces roman-numeral sub-parts. Use the format:
    (a) (i) question text here   (1)
        (ii) question text here  (2)

OUTPUT:
Return the improved worksheet only. No commentary or explanations.
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text}
        ],
        temperature=0
    )
    return add_answer_lines(clean_text(response.choices[0].message.content))


def generate_markscheme(text, mismatch_info: str = None):
    """
    Generate or regenerate a GCSE mark scheme from worksheet text.
    If `mismatch_info` is provided it is injected so the model knows what to fix.
    """
    mismatch_block = ""
    if mismatch_info:
        mismatch_block = f"""
CRITICAL — SPECIFIC ISSUES TO FIX IN THIS REGENERATION:
{mismatch_info}
You MUST resolve every issue listed above. Do not reproduce these errors.
"""
    prompt = f"""
You are generating a fully explicit GCSE-style mark scheme from a worksheet.
{mismatch_block}

CONTENT RULES:
1. Write a marking entry for EVERY question and EVERY sub-part in the worksheet.
2. NEVER skip any sub-question.
3. NEVER use vague placeholders like "Working step (1)" or "Answer (1)".
4. For CALCULATION questions:
   - Show the actual equation, numerical substitution, and final answer with units.
   - Do NOT award a mark for giving the equation alone (guideline rule).
   - Award marks for correct substitution (1) and correct answer with units (1).
   - Example: "a = (v - u) / t = (0 - 20) / 5 = -4 m/s² (1)(1)"
5. For NON-CALCULATION questions:
   - Give clear, specific marking points.
   - Allow reasonable alternatives: "OR" / "Accept..."
   - If 3+ possible answers exist, use: "Any [one/two/three] from:" followed by bullet points.
   - Use "OR" when only two alternatives exist.
6. Each mark MUST be a whole number — use (1) only. Never (2) for a single point.
7. Only the FIRST letter of each marking sentence should be capitalised.
   - WRONG: "Force = Mass × Acceleration (1)"
   - CORRECT: "Force = mass × acceleration (1)"
8. Sentences longer than 3-4 words MUST end with a full stop before the (1).
   Short labels may omit the full stop.
9. Any useful side note should be in italics formatting — prefix with [NOTE]:
   e.g. "[NOTE]: Accept velocity instead of speed"

FORMATTING RULES:
10. Bold question numbers: "1", "2" etc. (just the number).
11. Sub-part labels in brackets: (a), (b), (c), (i), (ii).
12. NO space between marking points WITHIN the same question part.
    Each mark point is on its own line but with NO blank line between them.
13. A SMALL space (one blank line) between DIFFERENT sub-parts (a)→(b)→(c).
14. A SMALL space between the last mark of one question and the Total line.
15. Include a "Total for question X = Y marks" line after each main question.
16. At the very END of the mark scheme, add on its own line:
    "Total marks for question paper: Z"
    where Z is the sum of all question totals.

STRUCTURE EXAMPLE:
1 (a) Correct substitution shown. (1)
      Correct answer = 4.0 m/s² (allow ±0.1). (1)

(b) Any two from: (2)
    • Reduces friction. (1)
    • Increases driving force. (1)
    • Reduces mass of vehicle. (1)

(c) The current decreases. (1)
    [NOTE]: Accept "resistance increases so current decreases"

(Total for question 1 = 5 marks)

Question mapping and numbering:
- Use EXACTLY the question numbers and sub-parts from the DETECTED QUESTION STRUCTURE below.
- Do NOT invent new question numbers or sub-parts.
- Do NOT omit any question or sub-part.
- Treat numbers inside sentences (e.g. "2.0 m/s", "5 kg") as data NOT question numbers.
- Only start a new question number at the beginning of a line.
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "WORKSHEET TEXT:\n"
                    + text
                    + "\n\nDETECTED QUESTION STRUCTURE (do NOT change these IDs):\n"
                    + json.dumps(detect_question_structure(text), ensure_ascii=False)
                ),
            },
        ],
        temperature=0
    )
    return clean_text(response.choices[0].message.content)


def run_agent(prompt, content: str) -> str:
    """Generic helper to call a text-only agent prompt."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def run_full_revision_via_agents(worksheet_text: str, markscheme_text: str, spec_text: str):
    """
    Run the current worksheet + mark scheme through the full multi-agent
    pipeline (Agents 1–5) to repair structural issues.
    """
    combined_ws_ms = f"WORKSHEET:\n{worksheet_text}\n\nMARK SCHEME:\n{markscheme_text}"

    report1 = run_agent(AGENT_1_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}")
    report2 = run_agent(AGENT_2_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}")
    report3 = run_agent(AGENT_3_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}")

    coverage_input = f"""WORKSHEET AND MARK SCHEME:
{combined_ws_ms}

INTENDED SCOPE:
{spec_text}
"""
    report4 = run_agent(AGENT_4_PROMPT, coverage_input)

    combined_input = f"""ORIGINAL WORKSHEET:
{worksheet_text}

ORIGINAL MARK SCHEME:
{markscheme_text}

INTENDED SCOPE:
{spec_text}

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
    return final_version


def parse_revised_output(text: str):
    """
    Split the Agent 5 result into revised worksheet and mark scheme.
    Tries three strategies, falls back to (None, None) on failure.
    """
    ws_marker = "--- REVISED WORKSHEET ---"
    ms_marker = "--- REVISED MARK SCHEME ---"

    ws_idx = text.find(ws_marker)
    ms_idx = text.find(ms_marker)
    if ws_idx != -1 and ms_idx != -1:
        ws_start = ws_idx + len(ws_marker)
        ms_start = ms_idx + len(ms_marker)
        return text[ws_start:ms_idx].strip(), text[ms_start:].strip()

    ws_match = re.search(r"-{2,}\s*REVISED\s+WORKSHEET\s*-{2,}", text, re.IGNORECASE)
    ms_match = re.search(r"-{2,}\s*REVISED\s+MARK\s+SCHEME\s*-{2,}", text, re.IGNORECASE)
    if ws_match and ms_match:
        ws_start = ws_match.end()
        ms_start = ms_match.end()
        worksheet_part = text[ws_start:ms_match.start()].strip()
        markscheme_part = text[ms_start:].strip()
        return worksheet_part, markscheme_part

    return None, None


def run_formatting_agent(worksheet_text):
    """
    Call the FormattingAgent to obtain structured formatting instructions.
    """
    cleaned = strip_answer_lines(clean_text(worksheet_text))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": FORMATTING_AGENT_PROMPT},
            {"role": "user", "content": cleaned},
        ],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"FormattingAgent returned invalid JSON ({exc}). "
            f"First 500 chars of raw output:\n{raw[:500]}"
        ) from exc


def render_formatted_preview(spec):
    """
    Render a structured, exam-style preview in Streamlit.
    """
    lines = spec.get("lines", [])
    st.markdown("### Formatted Worksheet Preview")

    st.markdown(
        """
<style>
.worksheet-preview {
    max-width: 800px;
    padding: 12px 24px;
    border: 1px solid #444;
    border-radius: 6px;
    background-color: #11141f;
}
.q-line {
    display: flex;
    justify-content: space-between;
    margin-bottom: 2px;
    font-family: Arial, sans-serif;
    font-size: 11pt;
}
.q-main { margin-top: 14px; }
.q-indent-0 { padding-left: 0; }
.q-indent-1 { padding-left: 28px; }
.q-indent-2 { padding-left: 52px; }
.q-text { white-space: pre-wrap; flex: 1; padding-right: 12px; }
.q-marks { min-width: 40px; text-align: right; font-weight: bold; }
.q-total { margin-top: 6px; margin-bottom: 6px; font-weight: bold; }
.answer-line {
    border-bottom: 1px solid #666;
    margin: 3px 0;
    height: 18px;
}
.answer-indent-0 { margin-left: 0px; margin-right: 44px; }
.answer-indent-1 { margin-left: 28px; margin-right: 44px; }
.answer-indent-2 { margin-left: 52px; margin-right: 44px; }
.q-bold { font-weight: bold; }
</style>
        """,
        unsafe_allow_html=True,
    )

    html_lines = ['<div class="worksheet-preview">']
    last_q = None

    for line in lines:
        qnum = line.get("question_number")
        indent_level = int(line.get("indent_level", 0))
        part_label = line.get("part_label") or ""
        subpart_label = line.get("subpart_label") or ""
        question_text = line.get("question_text", "")
        marks = line.get("marks")
        is_total = bool(line.get("is_total_for_question"))

        main_class = " q-main" if (qnum != last_q and indent_level == 0 and not is_total) else ""

        if is_total:
            html_lines.append(
                f'<div class="q-line q-total q-indent-0">'
                f'<div class="q-text">(Total for question {qnum} = {marks} marks)</div>'
                f'</div>'
            )
            last_q = qnum
            continue

        # Compose label
        if indent_level == 0 and qnum:
            label_html = f'<span class="q-bold">{qnum}</span>&nbsp;&nbsp;'
        elif indent_level == 1 and part_label:
            label_html = f'<span class="q-bold">{part_label}</span>&nbsp;'
        elif indent_level >= 2 and (subpart_label or part_label):
            lbl = subpart_label or part_label
            label_html = f'<span class="q-bold">{lbl}</span>&nbsp;'
        else:
            label_html = ""

        html_lines.append(
            f'<div class="q-line q-indent-{indent_level}{main_class}">'
            f'<div class="q-text">{label_html}{question_text}</div>'
            f'<div class="q-marks">{f"({marks})" if marks else ""}</div>'
            f'</div>'
        )

        # Answer lines based on marks
        if marks and marks > 0:
            num_lines = min(int(marks) + 1, 5)
            ans_class = f"answer-indent-{min(indent_level, 2)}"
            for _ in range(num_lines):
                html_lines.append(f'<div class="answer-line {ans_class}"></div>')

        last_q = qnum

    html_lines.append("</div>")
    st.markdown("\n".join(html_lines), unsafe_allow_html=True)


# ================================================================
# DOCX HELPERS
# ================================================================

def _set_run_font(run, bold=False, size_pt=11):
    """Apply Arial 11pt and optional bold to a run."""
    run.font.name = "Arial"
    run.font.size = Pt(size_pt)
    run.bold = bold
    # Also set font in rPr for compatibility
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Arial')
    rFonts.set(qn('w:hAnsi'), 'Arial')
    rPr.insert(0, rFonts)


def _add_answer_underline(document, left_indent_cm, content_width_cm, num_lines=3):
    """
    Add answer lines as paragraphs with a bottom border, indented to match the question level.
    Using bottom border approach gives a clean professional line.
    """
    for _ in range(num_lines):
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(left_indent_cm)
        pf.right_indent = Cm(0.5)
        pf.space_before = Pt(0)
        pf.space_after = Pt(4)

        # Add bottom border via XML for a clean answer line
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '4')   # 0.5pt border
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '000000')
        pBdr.append(bottom)
        pPr.append(pBdr)

        # Empty run to set font
        run = p.add_run("")
        run.font.name = "Arial"
        run.font.size = Pt(11)


def build_formatted_docx(spec):
    """
    Build a fully formatted A4 Word document (.docx) based on
    FormattingAgent instructions, following the GCSE guideline:
    - A4, Moderate margins (top/bottom 2.54 cm, left/right 1.91 cm)
    - Arial 11pt
    - Bold question numbers and part labels
    - Right-aligned marks
    - Answer lines via bottom border
    - Space between questions, no space between sub-parts
    """
    document = Document()

    # --- Page setup: A4, Moderate margins ---
    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(1.91)
    section.right_margin = Cm(1.91)

    # --- Base style: Arial 11 ---
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)

    # Usable content width (for tab stop calculation)
    content_width = section.page_width - section.left_margin - section.right_margin
    # Right-aligned marks tab stop: near right margin
    mark_tab = content_width - Cm(0.3)

    # Indentation levels (cm) — how far the TEXT starts
    TEXT_INDENT = [Cm(0.8), Cm(1.5), Cm(2.3)]
    # Left hanging indent per level (where the LABEL starts)
    LEFT_INDENT = [Cm(0.0), Cm(0.8), Cm(1.5)]

    lines = spec.get("lines", [])
    paper_total = spec.get("paper_total_marks")
    last_q = None

    def add_question_paragraph(label, label_bold, text_content, marks, indent_level, space_before_pt):
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(space_before_pt)
        pf.space_after = Pt(0)

        # Hanging indent: label sticks left, text indented right
        li = LEFT_INDENT[indent_level]
        ti = TEXT_INDENT[indent_level]
        pf.left_indent = li
        pf.first_line_indent = -(ti - li)

        # Tab stops: text at (ti - li) from left, marks at far right
        pf.tab_stops.clear_all()
        pf.tab_stops.add_tab_stop(ti - li, WD_TAB_ALIGNMENT.LEFT)
        pf.tab_stops.add_tab_stop(mark_tab, WD_TAB_ALIGNMENT.RIGHT)

        if label:
            r = p.add_run(label)
            _set_run_font(r, bold=label_bold)
            p.add_run("\t")

        r2 = p.add_run(text_content)
        _set_run_font(r2, bold=False)

        if marks:
            p.add_run("\t")
            r3 = p.add_run(f"({marks})")
            _set_run_font(r3, bold=True)

        return p

    for line in lines:
        qnum = line.get("question_number")
        indent_level = int(line.get("indent_level", 0))
        part_label = line.get("part_label") or ""
        subpart_label = line.get("subpart_label") or ""
        question_text = line.get("question_text", "")
        marks = line.get("marks")
        is_total = bool(line.get("is_total_for_question"))

        # --- Total for question line ---
        if is_total:
            p = document.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = Pt(4)
            pf.space_after = Pt(10)
            r = p.add_run(f"(Total for question {qnum} = {marks} marks)")
            _set_run_font(r, bold=True)
            last_q = qnum
            continue

        # --- Determine spacing before this line ---
        if indent_level == 0:
            # New main question: add space above (except the very first)
            sp_before = 14 if (last_q is not None and qnum != last_q) else 0
        else:
            # Sub-parts: no extra space
            sp_before = 0

        # --- Compose label ---
        if indent_level == 0 and qnum:
            label = qnum
            label_bold = True
        elif indent_level == 1 and part_label:
            label = part_label
            label_bold = True
        elif indent_level >= 2 and (subpart_label or part_label):
            label = subpart_label or part_label
            label_bold = True
        else:
            label = ""
            label_bold = False

        add_question_paragraph(
            label=label,
            label_bold=label_bold,
            text_content=question_text,
            marks=marks,
            indent_level=min(indent_level, 2),
            space_before_pt=sp_before,
        )

        # --- Answer lines ---
        if marks and marks > 0:
            m = int(marks)
            # Number of answer lines based on marks
            if m == 1:
                num_ans = 2
            elif m == 2:
                num_ans = 3
            elif m == 3:
                num_ans = 4
            else:
                num_ans = 5

            ans_indent = TEXT_INDENT[min(indent_level, 2)].cm
            _add_answer_underline(document, ans_indent, content_width.cm, num_ans)

        last_q = qnum

    # --- Final total for paper ---
    if paper_total:
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(16)
        pf.space_after = Pt(0)
        r = p.add_run(f"Total for paper = {paper_total} marks")
        _set_run_font(r, bold=True)

    bio = BytesIO()
    document.save(bio)
    bio.seek(0)
    return bio


def build_markscheme_docx(markscheme_text: str) -> BytesIO:
    """
    Build a formatted A4 Word document for the mark scheme, following
    the GCSE guideline:
    - A4, Moderate margins
    - Arial 11pt
    - Bold question numbers
    - Each (1) mark on its own line
    - No space between marks within a part
    - Small space between sub-parts
    - Total marks for question paper line at the end
    """
    document = Document()

    # --- Page setup ---
    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(1.91)
    section.right_margin = Cm(1.91)

    # --- Base style ---
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)

    lines = markscheme_text.split("\n")

    # Patterns to detect structure
    MAIN_Q_RE = re.compile(r"^\s*(\d+)\s")
    PART_RE = re.compile(r"^\s*\(([a-z])\)")
    ROMAN_RE = re.compile(r"^\s*\((i{1,4}|iv|vi{0,3}|ix|xi{0,3}|x{1,3})\)", re.IGNORECASE)
    TOTAL_Q_RE = re.compile(r"\(Total for question", re.IGNORECASE)
    TOTAL_PAPER_RE = re.compile(r"Total marks for question paper", re.IGNORECASE)
    TOTAL_PAPER_ALT = re.compile(r"Total for paper\s*=", re.IGNORECASE)

    prev_was_part = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(0)

        # Total for paper (end line)
        if TOTAL_PAPER_RE.search(line) or TOTAL_PAPER_ALT.search(line):
            pf.space_before = Pt(14)
            r = p.add_run(line)
            _set_run_font(r, bold=True)
            continue

        # Total for question line
        if TOTAL_Q_RE.search(line):
            pf.space_before = Pt(4)
            pf.space_after = Pt(8)
            r = p.add_run(line)
            _set_run_font(r, bold=True)
            prev_was_part = False
            continue

        # New sub-part line (a), (b), (i), (ii) — small space before
        is_part_line = (PART_RE.match(line) or ROMAN_RE.match(line))
        is_main_q = MAIN_Q_RE.match(line)

        if is_main_q:
            pf.space_before = Pt(10) if prev_was_part else Pt(0)
            pf.left_indent = Cm(0)
            # Bold the question number
            m = MAIN_Q_RE.match(line)
            q_num = m.group(1)
            rest = line[m.end():]
            r1 = p.add_run(q_num + " ")
            _set_run_font(r1, bold=True)
            r2 = p.add_run(rest)
            _set_run_font(r2, bold=False)
            prev_was_part = False

        elif is_part_line:
            pf.space_before = Pt(4) if prev_was_part else Pt(0)
            pf.left_indent = Cm(0.8)
            r = p.add_run(line)
            _set_run_font(r, bold=False)
            prev_was_part = True

        else:
            # Continuation of a mark point (indented under its parent)
            pf.space_before = Pt(0)
            pf.left_indent = Cm(1.5)
            r = p.add_run(line)
            _set_run_font(r, bold=False)

    bio = BytesIO()
    document.save(bio)
    bio.seek(0)
    return bio


# ---------------- MAIN ----------------

if run_button and worksheet_file:

    progress = st.progress(0)
    status = st.empty()

    status.text("Reading files...")
    progress.progress(10)
    time.sleep(0.2)

    worksheet_text = extract_docx(worksheet_file)
    markscheme_text = extract_docx(markscheme_file) if markscheme_file else ""
    spec_text = read_spec_text(spec_txt, spec_docx, pasted_spec)

    status.text("Step 2: Cleaning & enhancing worksheet...")
    progress.progress(30)
    improved_ws = improve_worksheet(worksheet_text)

    status.text("Step 3: Generating / improving mark scheme...")
    progress.progress(60)
    improved_ms = generate_markscheme(improved_ws)

    progress.progress(100)
    status.text("Complete.")
    st.success("Enhancement complete — see outputs below.")

    st.session_state["worksheet_text"] = worksheet_text
    st.session_state["markscheme_text"] = markscheme_text
    st.session_state["improved_ws"] = improved_ws
    st.session_state["improved_ms"] = improved_ms
    st.session_state["spec_text"] = spec_text

if "worksheet_text" in st.session_state and st.session_state["worksheet_text"]:
    worksheet_text = st.session_state["worksheet_text"]
    markscheme_text = st.session_state.get("markscheme_text", "")
    improved_ws = st.session_state.get("improved_ws", "")
    improved_ms = st.session_state.get("improved_ms", "")
    spec_text = st.session_state.get("spec_text", "")

    # ---------------- OUTPUT ----------------

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Enhanced Worksheet")
        st.text_area("Worksheet Output", improved_ws, height=450, key="ws_output")

    with col2:
        st.subheader("Enhanced Mark Scheme")
        st.text_area("Mark Scheme Output", improved_ms, height=450, key="ms_output")

    # ---------------- VALIDATION ----------------

    with st.expander("🔎 QA Validation Report"):

        misaligned = False
        validation_ms_text = improved_ms or markscheme_text

        if validation_ms_text:
            overlap = keyword_overlap(improved_ws, validation_ms_text)
            st.write(f"Keyword alignment: {overlap}%")
            if overlap < 40:
                st.error("⚠ Content misalignment detected (low keyword overlap).")

        ws_total = extract_total(improved_ws)
        ms_total = extract_total(validation_ms_text)

        if ws_total and ms_total and ws_total != ms_total:
            st.error(f"⚠ Total mismatch: Worksheet = {ws_total}, Mark Scheme = {ms_total}")
            misaligned = True

        if fractional_marks_present(validation_ms_text):
            st.error("⚠ Fractional marks detected.")
            misaligned = True

        ws_questions = extract_question_numbers(improved_ws)
        ms_questions = extract_question_numbers(validation_ms_text)

        mismatch_details = []
        if ws_questions != ms_questions:
            missing_from_ms = [q for q in ws_questions if q not in ms_questions]
            extra_in_ms    = [q for q in ms_questions if q not in ws_questions]
            if missing_from_ms:
                mismatch_details.append(
                    f"Questions present in worksheet but MISSING from mark scheme: {missing_from_ms}"
                )
            if extra_in_ms:
                mismatch_details.append(
                    f"Questions in mark scheme but NOT in worksheet (remove them): {extra_in_ms}"
                )
            st.error("⚠ Question number mismatch detected.")
            st.write(f"Worksheet Questions: {ws_questions}")
            st.write(f"Mark Scheme Questions: {ms_questions}")
            misaligned = True
        else:
            st.success("Question numbers align correctly.")

        mismatch_info_str = "\n".join(mismatch_details) if mismatch_details else None

        if misaligned:
            if st.button("Regenerate Mark Scheme from Worksheet"):
                regenerated = generate_markscheme(improved_ws, mismatch_info=mismatch_info_str)
                st.session_state["improved_ms"] = regenerated
                st.text_area("Regenerated Mark Scheme", regenerated, height=400)
                st.success("Mark scheme regenerated and saved.")

            if st.button("Run full intelligent revision (Agents 1–5)"):
                try:
                    final_text = run_full_revision_via_agents(improved_ws, improved_ms, spec_text)
                    revised_ws, revised_ms = parse_revised_output(final_text)
                    if revised_ws is None:
                        st.error(
                            "⚠ Agent 5 returned output in an unexpected format — "
                            "the original worksheet and mark scheme have been kept unchanged. "
                            "Try clicking the button again."
                        )
                    else:
                        st.session_state["improved_ws"] = revised_ws
                        if revised_ms:
                            st.session_state["improved_ms"] = revised_ms
                        st.success("Worksheet and mark scheme revised via multi-agent pipeline. Scroll up to review.")
                except Exception as e:
                    st.error(f"Intelligent revision failed: {e}")
        else:
            st.success("Structural checks passed (totals, fractions, numbering).")

    # ---------------- EXPORT ----------------

    # Recompute flags for export section
    validation_ms_text = improved_ms or markscheme_text
    misaligned_for_export = False

    if validation_ms_text:
        ws_total = extract_total(improved_ws)
        ms_total = extract_total(validation_ms_text)
        if ws_total and ms_total and ws_total != ms_total:
            misaligned_for_export = True
        if fractional_marks_present(validation_ms_text):
            misaligned_for_export = True
        ws_questions = extract_question_numbers(improved_ws)
        ms_questions = extract_question_numbers(validation_ms_text)
        if ws_questions != ms_questions:
            misaligned_for_export = True

    st.subheader("Export Documents")
    override_ok = True

    if misaligned_for_export:
        st.warning(
            "QA checks found structural issues. You can still export, but please double-check the output."
        )
        override_ok = st.checkbox(
            "Proceed with export despite QA warnings",
            key="fmt_override",
        )

    if override_ok:
        col_a, col_b = st.columns(2)

        with col_a:
            if st.button("Generate Formatted Worksheet (.docx)", key="fmt_ws"):
                try:
                    with st.spinner("Formatting worksheet..."):
                        fmt_spec = run_formatting_agent(improved_ws)
                    render_formatted_preview(fmt_spec)
                    docx_bytes = build_formatted_docx(fmt_spec)
                    st.download_button(
                        "⬇ Download Worksheet (.docx)",
                        data=docx_bytes,
                        file_name="gcse_worksheet_formatted.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                except Exception as e:
                    st.error(f"Worksheet export failed: {e}")

        with col_b:
            if st.button("Download Mark Scheme (.docx)", key="fmt_ms"):
                try:
                    ms_to_export = st.session_state.get("improved_ms", improved_ms)
                    ms_bytes = build_markscheme_docx(ms_to_export)
                    st.download_button(
                        "⬇ Download Mark Scheme (.docx)",
                        data=ms_bytes,
                        file_name="gcse_markscheme_formatted.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                    st.success("Mark scheme ready to download.")
                except Exception as e:
                    st.error(f"Mark scheme export failed: {e}")
