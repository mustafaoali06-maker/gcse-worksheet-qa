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
import base64
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
html, body, [class*="css"] {
    background-color: #0e1117;
    color: #e8e8e8;
}
.app-header {
    background: linear-gradient(90deg, #161b27 0%, #1a2035 100%);
    border-bottom: 2px solid #f39c12;
    padding: 14px 28px;
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 24px;
    border-radius: 0 0 8px 8px;
}
.app-header img { height: 56px; object-fit: contain; }
.app-header-title {
    font-size: 1.5rem;
    font-weight: 700;
    color: #f39c12;
    letter-spacing: 0.02em;
}
.stButton>button {
    background-color: #f39c12;
    color: #0e1117;
    font-weight: 700;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    transition: background 0.2s;
}
.stButton>button:hover { background-color: #e08e0b; }
h2, h3, h1 { color: #f39c12; }
.stDownloadButton>button {
    background-color: #27ae60;
    color: white;
    font-weight: 700;
    border: none;
    border-radius: 6px;
}
.stDownloadButton>button:hover { background-color: #219a52; }
hr { border-color: #2a2f3e; }
</style>
""", unsafe_allow_html=True)

# ---------------- HEADER ----------------
_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 56" width="56" height="56">
  <rect width="56" height="56" rx="10" fill="#f39c12"/>
  <rect x="8" y="8" width="40" height="40" rx="6" fill="#0e1117"/>
  <text x="28" y="23" text-anchor="middle" font-family="Arial,sans-serif" font-weight="800" font-size="11" fill="#f39c12">GCSE</text>
  <line x1="10" y1="28" x2="46" y2="28" stroke="#f39c12" stroke-width="1.5" opacity="0.4"/>
  <text x="28" y="40" text-anchor="middle" font-family="Arial,sans-serif" font-weight="700" font-size="8.5" fill="#ffffff" letter-spacing="1">STUDIO</text>
</svg>"""
st.markdown(f"""
<div class="app-header">
    {_LOGO_SVG}
    <span class="app-header-title">GCSE Worksheet QA Studio</span>
</div>
""", unsafe_allow_html=True)

# ---------------- SIDEBAR ----------------
with st.sidebar:
    st.markdown("### Upload Files")
    worksheet_file = st.file_uploader("Worksheet (.docx)", type=["docx"])
    markscheme_file = st.file_uploader("Mark Scheme (.docx)", type=["docx"])
    st.markdown("### Specification (Optional)")
    spec_txt = st.file_uploader("Spec (.txt)", type=["txt"])
    spec_docx = st.file_uploader("Spec (.docx)", type=["docx"])
    pasted_spec = st.text_area("Or Paste Specification")
    run_button = st.button("▶  Run Enhancement", use_container_width=True)

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

def strip_answer_lines(text):
    lines = text.split("\n")
    return "\n".join([ln for ln in lines if ANSWER_LINE.strip() not in ln.strip()])

def detect_question_structure(text):
    ROMAN_RE = re.compile(r"^\s*\((i{1,4}|iv|vi{0,3}|ix|xi{0,3}|x{1,3})\)\s", re.IGNORECASE)
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
    Example: "Work Done = Force x Distance" in a context line -> "Work done: force x distance"
11. Question numbering must be consistent: 1, 2, 3 ... (a), (b), (c) ... (i), (ii), (iii).
    - Main question numbers should NOT have a dot (use "1" not "1.")
12. Do NOT add answer lines - these are handled separately.
13. Keep mark allocations exactly as shown, e.g. (2).
14. Ensure there is NO space between sub-parts (a), (b), (c) of the SAME question.
15. There SHOULD be a blank line between separate main questions (1, 2, 3...).
16. Do NOT completely rewrite questions - only improve clarity and GCSE realism.
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
    mismatch_block = ""
    if mismatch_info:
        mismatch_block = f"""
CRITICAL - SPECIFIC ISSUES TO FIX IN THIS REGENERATION:
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
   - Example: "a = (v - u) / t = (0 - 20) / 5 = -4 m/s2 (1)(1)"
5. For NON-CALCULATION questions:
   - Give clear, specific marking points.
   - Allow reasonable alternatives: "OR" / "Accept..."
   - If 3+ possible answers exist, use: "Any [one/two/three] from:" followed by bullet points.
   - Use "OR" when only two alternatives exist.
6. Each mark MUST be a whole number - use (1) only. Never (2) for a single point.
7. Only the FIRST letter of each marking sentence should be capitalised.
8. Sentences longer than 3-4 words MUST end with a full stop before the (1).
9. Any useful side note should be prefixed with [NOTE]:
   e.g. "[NOTE]: Accept velocity instead of speed"

FORMATTING RULES:
10. Bold question numbers: "1", "2" etc. (just the number).
11. Sub-part labels in brackets: (a), (b), (c), (i), (ii).
12. NO space between marking points WITHIN the same question part.
13. A SMALL space (one blank line) between DIFFERENT sub-parts (a)->(b)->(c).
14. A SMALL space between the last mark of one question and the Total line.
15. Include a "(Total for question X is Y marks)" line after each main question.
    CRITICAL: Use "is" NOT "=" — e.g. "(Total for question 1 is 6 marks)" NOT "(Total for question 1 = 6 marks)"
16. At the very END of the mark scheme, add on its own line:
    "Total marks for question paper: Z"
    where Z is the sum of all question totals.

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
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def run_full_revision_via_agents(
    worksheet_text: str,
    markscheme_text: str,
    spec_text: str,
    on_step=None,
):
    combined_ws_ms = f"WORKSHEET:\n{worksheet_text}\n\nMARK SCHEME:\n{markscheme_text}"

    agent_steps = [
        ("Checking command word alignment...",   AGENT_1_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}"),
        ("Verifying mark allocations...",        AGENT_2_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}"),
        ("Checking physics accuracy...",         AGENT_3_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}"),
    ]
    coverage_input = f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}\n\nINTENDED SCOPE:\n{spec_text}"
    agent_steps.append(("Evaluating topic coverage...", AGENT_4_PROMPT, coverage_input))

    reports = []
    total = 5
    for i, (label, prompt, content) in enumerate(agent_steps):
        if on_step:
            on_step(i, total, f"Agent {i+1}: {label}")
        reports.append(run_agent(prompt, content))

    report1, report2, report3, report4 = reports

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
    if on_step:
        on_step(4, total, "Agent 5: Intelligent revision and finalising...")
    return run_agent(AGENT_5_PROMPT, combined_input)


def parse_revised_output(text: str):
    ws_marker = "--- REVISED WORKSHEET ---"
    ms_marker = "--- REVISED MARK SCHEME ---"
    ws_idx = text.find(ws_marker)
    ms_idx = text.find(ms_marker)
    if ws_idx != -1 and ms_idx != -1:
        return text[ws_idx + len(ws_marker):ms_idx].strip(), text[ms_idx + len(ms_marker):].strip()
    ws_match = re.search(r"-{2,}\s*REVISED\s+WORKSHEET\s*-{2,}", text, re.IGNORECASE)
    ms_match = re.search(r"-{2,}\s*REVISED\s+MARK\s+SCHEME\s*-{2,}", text, re.IGNORECASE)
    if ws_match and ms_match:
        return text[ws_match.end():ms_match.start()].strip(), text[ms_match.end():].strip()
    return None, None


def run_formatting_agent(worksheet_text):
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
            f"First 500 chars:\n{raw[:500]}"
        ) from exc


def render_formatted_preview(spec):
    lines = spec.get("lines", [])
    st.markdown("#### Formatted Worksheet Preview")
    st.markdown("""
<style>
.worksheet-preview {
    max-width: 760px; padding: 16px 28px;
    border: 1px solid #2a2f3e; border-radius: 8px;
    background-color: #ffffff; color: #111;
}
.q-line {
    display: flex; justify-content: space-between;
    margin-bottom: 2px; font-family: Arial, sans-serif;
    font-size: 11pt; color: #111;
}
.q-main { margin-top: 26px; }
.q-subpart { margin-top: 16px; }
.q-roman { margin-top: 10px; }
.q-indent-0 { padding-left: 0; }
.q-indent-1 { padding-left: 28px; }
.q-indent-2 { padding-left: 52px; }
.q-text { white-space: pre-wrap; flex: 1; padding-right: 12px; }
.q-marks { min-width: 40px; text-align: right; font-weight: bold; color: #111; }
.q-total { margin-top: 6px; margin-bottom: 14px; font-weight: bold; color: #111; }
.answer-line { border-bottom: 1px solid #888; margin: 5px 0; height: 20px; }
.answer-indent-0 { margin-left: 0px; margin-right: 52px; }
.answer-indent-1 { margin-left: 28px; margin-right: 52px; }
.answer-indent-2 { margin-left: 52px; margin-right: 52px; }
.q-bold { font-weight: bold; }
</style>""", unsafe_allow_html=True)

    html_lines = ['<div class="worksheet-preview">']
    last_q = None
    prev_indent_preview = None
    for line in lines:
        qnum = line.get("question_number")
        indent_level = int(line.get("indent_level", 0))
        part_label = line.get("part_label") or ""
        subpart_label = line.get("subpart_label") or ""
        question_text = line.get("question_text") or ""
        # Sanitise: if AI wrote literal "None" or "none", treat as empty
        if question_text.strip().lower() == "none":
            question_text = ""
        marks = line.get("marks")
        is_total = bool(line.get("is_total_for_question"))

        if is_total:
            html_lines.append(
                f'<div class="q-line q-total q-indent-0">'
                f'<div class="q-text">(Total for question {qnum} is {marks} marks)</div></div>'
            )
            last_q = qnum
            prev_indent_preview = None
            continue

        # Determine spacing class
        if indent_level == 0 and qnum != last_q:
            spacing_class = " q-main"
        elif indent_level == 1 and prev_indent_preview is not None and prev_indent_preview != 0 and last_q == qnum:
            spacing_class = " q-subpart"
        elif indent_level == 2:
            spacing_class = " q-roman"
        else:
            spacing_class = ""

        if indent_level == 0 and qnum:
            label_html = f'<span class="q-bold">{qnum}</span>&nbsp;&nbsp;'
        elif indent_level == 1 and part_label:
            label_html = f'<span class="q-bold">{part_label}</span>&nbsp;'
        elif indent_level >= 2 and (subpart_label or part_label):
            label_html = f'<span class="q-bold">{subpart_label or part_label}</span>&nbsp;'
        else:
            label_html = ""

        html_lines.append(
            f'<div class="q-line q-indent-{indent_level}{spacing_class}">'
            f'<div class="q-text">{label_html}{question_text}</div>'
            f'<div class="q-marks">{f"({marks})" if marks else ""}</div></div>'
        )
        if marks and marks > 0:
            num_lines = min(int(marks) + 1, 8)
            ans_class = f"answer-indent-{min(indent_level, 2)}"
            for _ in range(num_lines):
                html_lines.append(f'<div class="answer-line {ans_class}"></div>')
        last_q = qnum
        prev_indent_preview = indent_level

    html_lines.append("</div>")
    st.markdown("\n".join(html_lines), unsafe_allow_html=True)


# ================================================================
# DOCX HELPERS
# ================================================================

def _set_run_font(run, bold=False, size_pt=11):
    run.font.name = "Arial"
    run.font.size = Pt(size_pt)
    run.bold = bold
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Arial')
    rFonts.set(qn('w:hAnsi'), 'Arial')
    rPr.insert(0, rFonts)


def _add_answer_underline(document, left_indent_cm, num_lines=3):
    """
    Add answer lines as paragraphs with a paragraph bottom border.
    left_indent_cm is a plain float (centimetres) — no .cm call needed.
    """
    for _ in range(num_lines):
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(left_indent_cm)
        pf.right_indent = Cm(0.5)
        pf.space_before = Pt(0)
        pf.space_after = Pt(2)
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '4')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '000000')
        pBdr.append(bottom)
        pPr.append(pBdr)
        run = p.add_run("")
        run.font.name = "Arial"
        run.font.size = Pt(11)


def build_formatted_docx(spec):
    """
    Build a fully formatted A4 Word document (.docx) from FormattingAgent spec.
    BUG FIX: All indentation is stored as plain cm floats to avoid the
    'int object has no attribute cm' error caused by arithmetic on Length/EMU values.
    """
    document = Document()

    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(1.91)
    section.right_margin = Cm(1.91)

    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)

    # Compute content width in EMU for tab stops (arithmetic on section props gives plain int/EMU)
    content_width_emu = (
        section.page_width - section.left_margin - section.right_margin
    )
    mark_tab_emu = content_width_emu - Cm(0.3)

    # Use plain cm floats throughout — avoids any .cm attribute error
    TEXT_INDENT_CM = [0.8, 1.5, 2.3]   # where text body starts
    LEFT_INDENT_CM = [0.0, 0.8, 1.5]   # where label starts

    lines = spec.get("lines", [])
    paper_total = spec.get("paper_total_marks")
    last_q = None
    prev_indent = None

    def add_question_paragraph(label, label_bold, text_content, marks, indent_level, space_before_pt):
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(space_before_pt)
        pf.space_after = Pt(0)

        li_cm = LEFT_INDENT_CM[indent_level]
        ti_cm = TEXT_INDENT_CM[indent_level]
        pf.left_indent = Cm(ti_cm)
        pf.first_line_indent = Cm(-(ti_cm - li_cm))

        pf.tab_stops.clear_all()
        pf.tab_stops.add_tab_stop(Cm(ti_cm), WD_TAB_ALIGNMENT.LEFT)
        pf.tab_stops.add_tab_stop(mark_tab_emu, WD_TAB_ALIGNMENT.RIGHT)

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
        question_text = line.get("question_text") or ""
        # Sanitise: if AI wrote literal "None" or "none", treat as empty
        if question_text.strip().lower() == "none":
            question_text = ""
        marks = line.get("marks")
        is_total = bool(line.get("is_total_for_question"))

        if is_total:
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(8)
            r = p.add_run(f"(Total for question {qnum} is {marks} marks)")
            _set_run_font(r, bold=True)
            last_q = qnum
            prev_indent = None
            continue

        if indent_level == 0:
            sp_before = 16 if (last_q is not None and qnum != last_q) else 0
        elif indent_level == 1:
            # Space before (b), (c) etc. — but NOT right after a main question stem
            sp_before = 8 if (prev_indent is not None and prev_indent != 0 and last_q == qnum) else 2
        elif indent_level == 2:
            sp_before = 4
        else:
            sp_before = 0

        # If indent_level=0 has no text and no marks, still render the question number
        # (never skip — question numbers must always appear)

        if indent_level == 0 and qnum:
            label, label_bold = qnum, False          # question numbers: plain
        elif indent_level == 1 and part_label:
            label, label_bold = part_label, True     # (a), (b): bold
        elif indent_level >= 2 and (subpart_label or part_label):
            label, label_bold = (subpart_label or part_label), True  # (ii): bold
        else:
            label, label_bold = "", False

        add_question_paragraph(
            label=label, label_bold=label_bold,
            text_content=question_text, marks=marks,
            indent_level=min(indent_level, 2), space_before_pt=sp_before,
        )

        if marks and marks > 0:
            m = int(marks)
            # marks+1 lines, capped at 5 for high-mark questions
            num_ans = min(m + 1, 5)
            # Use the plain cm float directly — no .cm call on any object
            ans_indent_cm = TEXT_INDENT_CM[min(indent_level, 2)]
            _add_answer_underline(document, ans_indent_cm, num_ans)

        last_q = qnum
        prev_indent = indent_level

    if paper_total:
        p = document.add_paragraph()
        p.paragraph_format.space_before = Pt(16)
        r = p.add_run(f"Total for paper = {paper_total} marks")
        _set_run_font(r, bold=True)

    bio = BytesIO()
    document.save(bio)
    bio.seek(0)
    return bio


def build_markscheme_docx(markscheme_text: str) -> BytesIO:
    """
    Build a mark scheme DOCX matching the Edexcel format:
    - Each marking point ends with bold (1)
    - 'Any X from:' lines followed by bullet points
    - (Total for question X is Y marks) — bold, 'is' not '='
    - Total marks line — bold + underlined
    """
    document = Document()
    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(1.91)
    section.right_margin = Cm(1.91)
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)

    MAIN_Q_RE = re.compile(r"^\s*(\d+)\s")
    PART_RE = re.compile(r"^\s*\(([a-z])\)")
    ROMAN_RE = re.compile(r"^\s*\((i{1,4}|iv|vi{0,3}|ix|xi{0,3}|x{1,3})\)", re.IGNORECASE)
    BULLET_RE = re.compile(r"^\s*[•\-\*]\s+")
    TOTAL_Q_RE = re.compile(r"\(Total for question", re.IGNORECASE)
    TOTAL_PAPER_RE = re.compile(r"Total marks for question paper", re.IGNORECASE)
    TOTAL_PAPER_ALT = re.compile(r"Total for paper\s*[=:]", re.IGNORECASE)

    def add_inline_bold_marks(p, text, base_bold=False):
        """Split text on (1) and emit alternating normal / bold runs."""
        parts = re.split(r'(\(1\))', text)
        for part in parts:
            if part == "(1)":
                r = p.add_run("(1)")
                _set_run_font(r, bold=True)
            elif part:
                r = p.add_run(part)
                _set_run_font(r, bold=base_bold)

    prev_line_type = None  # 'main', 'part', 'bullet', 'other', 'total'

    for raw_line in markscheme_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # ---- Total for paper ----
        if TOTAL_PAPER_RE.search(line) or TOTAL_PAPER_ALT.search(line):
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(line)
            _set_run_font(r, bold=True)
            r.underline = True
            prev_line_type = 'total'
            continue

        # ---- Total for question ----
        if TOTAL_Q_RE.search(line):
            # Normalise "=" -> "is"
            line = re.sub(
                r'(Total for question\s+\w+)\s*=\s*(\d+)',
                r'\1 is \2',
                line, flags=re.IGNORECASE
            )
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(12)
            r = p.add_run(line)
            _set_run_font(r, bold=True)
            prev_line_type = 'total'
            continue

        # ---- Bullet point ----
        if BULLET_RE.match(line):
            text_after_bullet = BULLET_RE.sub("", line).strip()
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(1.8)
            p.paragraph_format.first_line_indent = Cm(-0.4)
            r = p.add_run("\u2022 ")
            _set_run_font(r, bold=False)
            add_inline_bold_marks(p, text_after_bullet)
            prev_line_type = 'bullet'
            continue

        # ---- Identify line type ----
        is_main = MAIN_Q_RE.match(line)
        is_part = PART_RE.match(line) or ROMAN_RE.match(line)

        if is_main:
            sp_before = 14 if prev_line_type in ('total', 'part', 'bullet', 'other') else 0
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(sp_before)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(0)
            m = is_main
            r = p.add_run(m.group(1) + " ")
            _set_run_font(r, bold=True)
            add_inline_bold_marks(p, line[m.end():])
            prev_line_type = 'main'

        elif is_part:
            sp_before = 4 if prev_line_type in ('part', 'bullet', 'other') else 0
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(sp_before)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(0.8)
            add_inline_bold_marks(p, line)
            prev_line_type = 'part'

        else:
            # Continuation / any-from line / notes
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(1.5)
            add_inline_bold_marks(p, line)
            prev_line_type = 'other'

    bio = BytesIO()
    document.save(bio)
    bio.seek(0)
    return bio


# ================================================================
# MAIN PIPELINE
# ================================================================

if run_button and worksheet_file:
    _PIPELINE_STEPS = [
        ("📂", "Reading uploaded files"),
        ("✏️",  "Enhancing worksheet"),
        ("📋", "Generating mark scheme"),
        ("🔍", "Agent 1: Command word alignment"),
        ("📐", "Agent 2: Mark scheme structure"),
        ("🔬", "Agent 3: Cognitive balance"),
        ("🗂️", "Agent 4: Topic coverage"),
        ("✨", "Agent 5: Intelligent revision"),
    ]

    def _render_pipeline(current_step):
        rows = ""
        for i, (icon, label) in enumerate(_PIPELINE_STEPS):
            if i < current_step:
                dot = '<span style="color:#22c55e;font-size:1.1em">✓</span>'
                col = "#22c55e"
            elif i == current_step:
                dot = f'<span style="font-size:1.1em">{icon}</span>'
                col = "#60a5fa"
            else:
                dot = '<span style="color:#4b5563;font-size:1.1em">○</span>'
                col = "#6b7280"
            rows += (
                f'<div style="display:flex;align-items:center;gap:10px;padding:5px 0;'
                f'color:{col};font-family:Arial,sans-serif;font-size:14px">'
                f'{dot}<span>{label}</span></div>'
            )
        return (
            '<div style="background:#1a1f2e;border:1px solid #374151;border-radius:10px;'
            'padding:18px 22px;max-width:480px">'
            '<div style="font-weight:bold;color:#f9fafb;margin-bottom:12px;'
            'font-family:Arial,sans-serif;font-size:15px">⚙️ Running enhancement pipeline…</div>'
            + rows + '</div>'
        )

    _prog_box = st.empty()

    # Step 0: read files
    _prog_box.markdown(_render_pipeline(0), unsafe_allow_html=True)
    worksheet_text = extract_docx(worksheet_file)
    markscheme_text = extract_docx(markscheme_file) if markscheme_file else ""
    spec_text = read_spec_text(spec_txt, spec_docx, pasted_spec)

    # Step 1: enhance worksheet
    _prog_box.markdown(_render_pipeline(1), unsafe_allow_html=True)
    improved_ws = improve_worksheet(worksheet_text)

    # Step 2: generate mark scheme
    _prog_box.markdown(_render_pipeline(2), unsafe_allow_html=True)
    improved_ms = generate_markscheme(improved_ws)

    # Step 3–6: Agents 1–4
    _combined = f"WORKSHEET:\n{improved_ws}\n\nMARK SCHEME:\n{improved_ms}"
    _prog_box.markdown(_render_pipeline(3), unsafe_allow_html=True)
    _r1 = run_agent(AGENT_1_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{_combined}")

    _prog_box.markdown(_render_pipeline(4), unsafe_allow_html=True)
    _r2 = run_agent(AGENT_2_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{_combined}")

    _prog_box.markdown(_render_pipeline(5), unsafe_allow_html=True)
    _r3 = run_agent(AGENT_3_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{_combined}")

    _prog_box.markdown(_render_pipeline(6), unsafe_allow_html=True)
    _r4 = run_agent(AGENT_4_PROMPT,
        f"WORKSHEET AND MARK SCHEME:\n{_combined}\n\nINTENDED SCOPE:\n{spec_text}")

    # Step 7: Agent 5 — intelligent revision
    _prog_box.markdown(_render_pipeline(7), unsafe_allow_html=True)
    _agent5_input = (
        f"ORIGINAL WORKSHEET:\n{improved_ws}\n\nORIGINAL MARK SCHEME:\n{improved_ms}\n\n"
        f"INTENDED SCOPE:\n{spec_text}\n\n"
        f"AGENT 1 REPORT:\n{_r1}\n\nAGENT 2 REPORT:\n{_r2}\n\n"
        f"AGENT 3 REPORT:\n{_r3}\n\nAGENT 4 REPORT:\n{_r4}"
    )
    _final_text = run_agent(AGENT_5_PROMPT, _agent5_input)
    _revised_ws, _revised_ms = parse_revised_output(_final_text)
    if _revised_ws:
        improved_ws = _revised_ws
    if _revised_ms:
        improved_ms = _revised_ms

    # Show all steps complete
    _prog_box.markdown(
        '<div style="background:#1a1f2e;border:1px solid #374151;border-radius:10px;'
        'padding:18px 22px;max-width:480px;font-family:Arial,sans-serif">'
        '<div style="font-weight:bold;color:#22c55e;font-size:15px">✅ Enhancement complete — review and export below.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.session_state.update({
        "worksheet_text": worksheet_text,
        "markscheme_text": markscheme_text,
        "improved_ws": improved_ws,
        "improved_ms": improved_ms,
        "spec_text": spec_text,
    })
    for k in ("fmt_spec", "fmt_docx_bytes", "ms_docx_bytes"):
        st.session_state.pop(k, None)


# ================================================================
# OUTPUT SECTION
# ================================================================

if "worksheet_text" in st.session_state and st.session_state["worksheet_text"]:
    worksheet_text = st.session_state["worksheet_text"]
    markscheme_text = st.session_state.get("markscheme_text", "")
    improved_ws = st.session_state.get("improved_ws", "")
    improved_ms = st.session_state.get("improved_ms", "")
    spec_text = st.session_state.get("spec_text", "")

    st.markdown("---")
    st.subheader("Enhanced Worksheet")
    st.markdown(
        "<div style='color:#9ca3af;font-size:12px;margin-bottom:4px'>"
        "✏️ Edit directly below — click <strong>Save Edits</strong> to apply your changes.</div>",
        unsafe_allow_html=True,
    )
    _ws_edit = st.text_area("Worksheet Output", value=st.session_state.get("improved_ws", improved_ws),
                            height=400, key="ws_editor")
    if st.button("💾 Save Worksheet Edits", key="save_ws_edit"):
        st.session_state["improved_ws"] = _ws_edit
        for k in ("fmt_spec", "fmt_docx_bytes"):
            st.session_state.pop(k, None)
        st.success("Worksheet edits saved.")

    st.markdown("---")
    st.subheader("Enhanced Mark Scheme")
    st.markdown(
        "<div style='color:#9ca3af;font-size:12px;margin-bottom:4px'>"
        "✏️ Edit directly below — click <strong>Save Edits</strong> to apply your changes.</div>",
        unsafe_allow_html=True,
    )
    _ms_edit = st.text_area("Mark Scheme Output", value=st.session_state.get("improved_ms", improved_ms),
                            height=400, key="ms_editor")
    if st.button("💾 Save Mark Scheme Edits", key="save_ms_edit"):
        st.session_state["improved_ms"] = _ms_edit
        st.session_state.pop("ms_docx_bytes", None)
        st.success("Mark scheme edits saved.")

    st.markdown("---")

    # ---- QA Validation ----
    with st.expander("🔎 QA Validation Report"):
        misaligned = False
        validation_ms_text = improved_ms or markscheme_text

        if validation_ms_text:
            overlap = keyword_overlap(improved_ws, validation_ms_text)
            st.write(f"Keyword alignment: {overlap}%")
            if overlap < 40:
                st.error("Content misalignment detected (low keyword overlap).")

        ws_total = extract_total(improved_ws)
        ms_total = extract_total(validation_ms_text)
        if ws_total and ms_total and ws_total != ms_total:
            st.error(f"Total mismatch: Worksheet = {ws_total}, Mark Scheme = {ms_total}")
            misaligned = True
        if fractional_marks_present(validation_ms_text):
            st.error("Fractional marks detected.")
            misaligned = True

        ws_questions = extract_question_numbers(improved_ws)
        ms_questions = extract_question_numbers(validation_ms_text)
        mismatch_details = []
        if ws_questions != ms_questions:
            missing = [q for q in ws_questions if q not in ms_questions]
            extra   = [q for q in ms_questions if q not in ws_questions]
            if missing:
                mismatch_details.append(f"Missing from mark scheme: {missing}")
            if extra:
                mismatch_details.append(f"Extra in mark scheme (remove): {extra}")
            st.error("Question number mismatch detected.")
            st.write(f"Worksheet: {ws_questions}  |  Mark Scheme: {ms_questions}")
            misaligned = True
        else:
            st.success("✅ Question numbers align correctly.")

        mismatch_info_str = "\n".join(mismatch_details) if mismatch_details else None

        if misaligned:
            if st.button("Regenerate Mark Scheme from Worksheet"):
                regenerated = generate_markscheme(improved_ws, mismatch_info=mismatch_info_str)
                st.session_state["improved_ms"] = regenerated
                st.session_state.pop("ms_docx_bytes", None)
                st.text_area("Regenerated Mark Scheme", regenerated, height=400)
                st.success("Mark scheme regenerated and saved.")
        else:
            st.success("✅ Structural checks passed.")

    st.markdown("---")

    # ================================================================
    # EXPORT
    # ================================================================
    st.subheader("Export Documents")

    validation_ms_text = improved_ms or markscheme_text
    misaligned_for_export = False
    if validation_ms_text:
        ws_total = extract_total(improved_ws)
        ms_total = extract_total(validation_ms_text)
        if ws_total and ms_total and ws_total != ms_total:
            misaligned_for_export = True
        if fractional_marks_present(validation_ms_text):
            misaligned_for_export = True
        if extract_question_numbers(improved_ws) != extract_question_numbers(validation_ms_text):
            misaligned_for_export = True

    override_ok = True
    if misaligned_for_export:
        st.warning("QA checks found structural issues. You can still export — double-check the output.")
        override_ok = st.checkbox("Proceed with export despite QA warnings", key="fmt_override")

    if override_ok:
        st.markdown("#### Formatted Worksheet")
        if st.button("Generate Formatted Worksheet (.docx)", key="fmt_ws"):
            with st.spinner("Running FormattingAgent — structuring layout..."):
                try:
                    fmt_spec = run_formatting_agent(improved_ws)
                    docx_bytes = build_formatted_docx(fmt_spec)
                    st.session_state["fmt_spec"] = fmt_spec
                    st.session_state["fmt_docx_bytes"] = docx_bytes
                except Exception as e:
                    st.error(f"Worksheet export failed: {e}")

        if "fmt_spec" in st.session_state:
            render_formatted_preview(st.session_state["fmt_spec"])
            st.download_button(
                label="⬇  Download Worksheet (.docx)",
                data=st.session_state["fmt_docx_bytes"],
                file_name="gcse_worksheet_formatted.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="dl_ws",
            )

        st.markdown("---")
        st.markdown("#### Mark Scheme")
        if st.button("Generate Mark Scheme (.docx)", key="fmt_ms"):
            with st.spinner("Building mark scheme document..."):
                try:
                    ms_bytes = build_markscheme_docx(st.session_state.get("improved_ms", improved_ms))
                    st.session_state["ms_docx_bytes"] = ms_bytes
                except Exception as e:
                    st.error(f"Mark scheme export failed: {e}")

        if "ms_docx_bytes" in st.session_state:
            st.download_button(
                label="⬇  Download Mark Scheme (.docx)",
                data=st.session_state["ms_docx_bytes"],
                file_name="gcse_markscheme_formatted.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="dl_ms",
            )


# ================================================================
# AI CHAT ASSISTANT
# ================================================================

st.markdown("---")
st.markdown("### 💬 AI Assistant")
st.markdown(
    "<div style='color:#9ca3af;font-size:13px;margin-bottom:12px'>"
    "Ask the AI to make changes to your worksheet or mark scheme — it will apply them automatically. "
    "For a whole-document change (e.g. renaming a character) it can re-run the full pipeline. "
    "For a targeted fix (e.g. reword Q3b) it edits just that part."
    "</div>",
    unsafe_allow_html=True,
)

_CHAT_SYSTEM = """You are an expert GCSE Physics worksheet editor.
You help teachers improve their worksheets and mark schemes.

IMPORTANT: You MUST respond with ONLY valid JSON — no prose, no markdown fences, nothing outside the JSON object.

JSON schema:
{
  "message": "<short explanation of what you did or why>",
  "action": "modify" | "info",
  "rerun_pipeline": true | false,
  "changes": [
    {
      "target": "worksheet" | "markscheme",
      "find": "<exact text to find, verbatim from the document>",
      "replace": "<exact replacement text>"
    }
  ]
}

Rules:
- Use action "modify" when making any edit to the worksheet or mark scheme.
- Use action "info" for questions, explanations or when no edit is needed (changes array will be empty).
- Set rerun_pipeline to true ONLY for large global changes (e.g. rename student name throughout, change topic, restructure all questions). For individual question edits set it to false.
- "find" must be an exact verbatim substring of the current document — copy it exactly.
- "replace" is the new text that replaces that exact substring.
- You may include multiple change objects in the changes array (e.g. one for worksheet, one for markscheme).
- If action is "info", set changes to [] and rerun_pipeline to false.
"""

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []


def _apply_chat_changes(changes, ws, ms):
    """Apply a list of {target, find, replace} edits. Returns (new_ws, new_ms, applied_count)."""
    applied = 0
    for ch in changes:
        target = ch.get("target", "worksheet")
        find_str = ch.get("find", "")
        replace_str = ch.get("replace", "")
        if not find_str:
            continue
        if target == "worksheet" and find_str in ws:
            ws = ws.replace(find_str, replace_str, 1)
            applied += 1
        elif target == "markscheme" and find_str in ms:
            ms = ms.replace(find_str, replace_str, 1)
            applied += 1
    return ws, ms, applied


_chat_container = st.container()
with _chat_container:
    for msg in st.session_state["chat_history"]:
        role_label = "🧑 You" if msg["role"] == "user" else "🤖 Assistant"
        bubble_bg = "#1e2533" if msg["role"] == "user" else "#162032"
        display_text = msg.get("display", msg["content"])
        st.markdown(
            f'<div style="background:{bubble_bg};border-radius:8px;padding:10px 14px;'
            f'margin:6px 0;font-family:Arial,sans-serif;font-size:14px;color:#e8e8e8">'
            f'<strong style="color:#f39c12">{role_label}</strong><br>{display_text}</div>',
            unsafe_allow_html=True,
        )

with st.form("chat_form", clear_on_submit=True):
    _cols = st.columns([5, 1])
    _user_input = _cols[0].text_input(
        "Message", placeholder="e.g. Change 'Olivia' to 'Mustafa' throughout...", label_visibility="collapsed"
    )
    _send = _cols[1].form_submit_button("Send", use_container_width=True)

if _send and _user_input.strip():
    _ctx_ws = st.session_state.get("improved_ws", "")
    _ctx_ms = st.session_state.get("improved_ms", "")
    _context_block = ""
    if _ctx_ws:
        _context_block = (
            f"\n\nCurrent worksheet:\n{_ctx_ws[:4000]}"
            + (f"\n\nCurrent mark scheme:\n{_ctx_ms[:2500]}" if _ctx_ms else "")
        )

    _messages = [{"role": "system", "content": _CHAT_SYSTEM + _context_block}]
    for _m in st.session_state["chat_history"][-10:]:
        _messages.append({"role": _m["role"], "content": _m["content"]})
    _messages.append({"role": "user", "content": _user_input.strip()})

    st.session_state["chat_history"].append({"role": "user", "content": _user_input.strip(), "display": _user_input.strip()})

    with st.spinner("Thinking..."):
        _resp = client.chat.completions.create(
            model="gpt-4o",
            messages=_messages,
            max_tokens=1500,
            temperature=0.3,
        )
        _raw = _resp.choices[0].message.content.strip()

    # Parse JSON response
    try:
        # Strip markdown fences if model wrapped it anyway
        _clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", _raw, flags=re.DOTALL).strip()
        _parsed = json.loads(_clean)
    except Exception:
        _parsed = {"message": _raw, "action": "info", "rerun_pipeline": False, "changes": []}

    _action = _parsed.get("action", "info")
    _msg_text = _parsed.get("message", "")
    _changes = _parsed.get("changes", [])
    _rerun_pipeline = _parsed.get("rerun_pipeline", False)

    _display_msg = _msg_text
    _applied_count = 0

    if _action == "modify" and _changes:
        _cur_ws = st.session_state.get("improved_ws", "")
        _cur_ms = st.session_state.get("improved_ms", "")
        _new_ws, _new_ms, _applied_count = _apply_chat_changes(_changes, _cur_ws, _cur_ms)

        if _applied_count > 0:
            st.session_state["improved_ws"] = _new_ws
            st.session_state["improved_ms"] = _new_ms
            # Clear cached export bytes so they regenerate
            for _k in ("fmt_spec", "fmt_docx_bytes", "ms_docx_bytes"):
                st.session_state.pop(_k, None)

            if _rerun_pipeline:
                _display_msg = (
                    f"✅ Applied {_applied_count} change(s). "
                    "Re-running the full enhancement pipeline now — this may take a minute..."
                )
                st.session_state["chat_history"].append({"role": "assistant", "content": _raw, "display": _display_msg})
                st.rerun()
            else:
                _targets = ", ".join(sorted({c.get("target","worksheet") for c in _changes}))
                _display_msg = f"✅ Applied {_applied_count} change(s) to **{_targets}**. {_msg_text}"
        else:
            _display_msg = (
                f"⚠️ Could not find the exact text to replace. {_msg_text}\n\n"
                "Tip: Use the edit boxes above to make the change manually."
            )
    elif _action == "modify" and not _changes:
        _display_msg = _msg_text or "No changes specified."

    st.session_state["chat_history"].append({"role": "assistant", "content": _raw, "display": _display_msg})
    st.rerun()

if st.session_state["chat_history"]:
    if st.button("🗑  Clear chat", key="clear_chat"):
        st.session_state["chat_history"] = []
        st.rerun()
