import streamlit as st
from docx import Document
from openai import OpenAI
import os
import re
import time
import json
from io import BytesIO
from docx.shared import Cm, Pt
from docx.enum.text import WD_TAB_ALIGNMENT
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
        # Conservative upper bound for GCSE question numbering
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
    # Roman numeral pattern â must be checked BEFORE the single-letter (a)/(b) pattern
    # so that (i), (ii), (iii) etc. are not mistakenly treated as lettered parts.
    ROMAN_RE = re.compile(
        r"^\s*\((i{1,4}|iv|vi{0,3}|ix|xi{0,3}|x{1,3})\)\s", re.IGNORECASE
    )
    PART_RE = re.compile(r"^\s*\(([a-z])\)\s")

    structure = {}          # {qnum: {"parts": {letter: set(roman_subparts)}}}
    current_q = None
    current_part = None

    for line in text.split("\n"):
        if "Total for question" in line:
            continue

        # ââ Main question number ââââââââââââââââââââââââââââââââââââââââââââââ
        m_main = re.match(r"^\s*(\d+)\s*(?=[.(A-Za-z])", line)
        if m_main:
            v = int(m_main.group(1))
            if v <= 50:
                current_q = m_main.group(1)
                current_part = None
                structure.setdefault(current_q, {"parts": {}})
            continue  # a main-number line won't also be a sub-part

        if current_q is None:
            continue

        # ââ Roman numeral sub-part (i), (ii) â¦ âââââââââââââââââââââââââââââââ
        m_roman = ROMAN_RE.match(line)
        if m_roman and current_part is not None:
            roman = m_roman.group(1).lower()
            structure[current_q]["parts"].setdefault(current_part, set())
            structure[current_q]["parts"][current_part].add(roman)
            continue

        # ââ Lettered sub-part (a), (b) â¦ âââââââââââââââââââââââââââââââââââââ
        m_part = PART_RE.match(line)
        if m_part:
            letter = m_part.group(1)
            # Skip if the single letter is one that only appears as a roman numeral
            # (i, v, x) â those are handled above when they follow a letter part.
            # Here we accept them as letter parts only if we have no current_part yet.
            structure[current_q]["parts"].setdefault(letter, set())
            current_part = letter

    # Build the serialisable result
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
    """
    Build a single specification text string from the available inputs.
    This is used both for coverage checks and to guide the multi-agent revision.
    """
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
Improve clarity and GCSE realism.
Preserve numbering.
Remove topic headers.
Ensure mixed difficulty.
Fix spacing between value and unit.
Keep mark formatting like (2).
Do NOT rewrite structure.
Do NOT add answer lines.
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
    If `mismatch_info` is provided (a plain-English description of what is wrong
    in the existing mark scheme), it is injected into the prompt so the model
    knows exactly what to fix rather than starting blind.
    """
    mismatch_block = ""
    if mismatch_info:
        mismatch_block = f"""
CRITICAL â SPECIFIC ISSUES TO FIX IN THIS REGENERATION:
{mismatch_info}
You MUST resolve every issue listed above. Do not reproduce these errors.
"""
    prompt = f"""
You are generating a **fully explicit GCSE Physics mark scheme** from a worksheet.
{mismatch_block}

You MUST:
- Write a marking scheme entry for **every question and every sub-part** that appears in the worksheet (e.g. if the worksheet has 1 (a), (b), (c) you must have 1 (a), (b), (c) in the mark scheme).
- Never skip any sub-questions.
- Never use vague placeholders like "Working step (1)" or "Answer (1)".

For **calculation questions**:
- Always show the **actual equation**, the **numerical substitution**, and the **final numerical answer with units**.
- Award method and answer marks explicitly, for example:
  1 (a) v = f Ã Î» (1)
      v = 2.5 Ã 0.8 = 2.0 m/s (1)
- Do NOT write generic text like "Working step (1)" or "Next step (1)" â use the real working that matches the question.

For **non-calculation questions**:
- Give clear marking points that state the acceptable ideas, not just "Answer (1)".
- Provide at least as many distinct marking points as there are marks.
- Where appropriate, allow reasonable alternative phrasings using "OR" / "Accept ...".

Question mapping and numbering:
- You will be given a DETECTED QUESTION STRUCTURE. You MUST:
  - Use exactly this set of question numbers and sub-parts.
  - Not invent any new question numbers or sub-parts.
  - Not omit any question or sub-part from the mark scheme.
- Treat numbers inside sentences (e.g. "2.0 m/s", "5 kg") as data, NOT as question numbers.
- Only start a new question number at the beginning of a line.

Formatting requirements (follow this structure):

1 (a) [first valid marking point] (1)
      [second valid marking point / step] (1)
(b) [first valid marking point] (1)
      [second valid marking point] (1)
(c) [etc...]
(Total for question 1 = 6 marks)

Rules:
- Only (1) marks â no fractional marks.
- Show exactly where each mark is gained.
- Include a "Total for question X = Y marks" line for each numbered question.
- End with a final "Total for paper = Z marks" line.
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
    pipeline (Agents 1â5) to repair structural issues such as missing
    question numbers or misaligned scope.
    """
    # Agent 1â3 operate on combined worksheet/markscheme text
    combined_ws_ms = f"WORKSHEET:\n{worksheet_text}\n\nMARK SCHEME:\n{markscheme_text}"

    report1 = run_agent(AGENT_1_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}")
    report2 = run_agent(AGENT_2_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}")
    report3 = run_agent(AGENT_3_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}")

    # Agent 4 uses scope as well
    coverage_input = f"""WORKSHEET AND MARK SCHEME:
{combined_ws_ms}

INTENDED SCOPE:
{spec_text}
"""
    report4 = run_agent(AGENT_4_PROMPT, coverage_input)

    # Agent 5: final revision with all reports
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

    Tries three strategies in order:
    1. Exact string match on the canonical markers.
    2. Case-insensitive / whitespace-tolerant regex search (handles slight
       formatting variations the model sometimes introduces).
    3. Safe fallback â returns (None, None) so the caller can keep the
       originals instead of silently corrupting them.
    """
    ws_marker = "--- REVISED WORKSHEET ---"
    ms_marker = "--- REVISED MARK SCHEME ---"

    # ââ Strategy 1: exact match âââââââââââââââââââââââââââââââââââââââââââââââ
    ws_idx = text.find(ws_marker)
    ms_idx = text.find(ms_marker)
    if ws_idx != -1 and ms_idx != -1:
        ws_start = ws_idx + len(ws_marker)
        ms_start = ms_idx + len(ms_marker)
        return text[ws_start:ms_idx].strip(), text[ms_start:].strip()

    # ââ Strategy 2: fuzzy regex (tolerates extra dashes, varied spacing) âââââ
    ws_match = re.search(r"-{2,}\s*REVISED\s+WORKSHEET\s*-{2,}", text, re.IGNORECASE)
    ms_match = re.search(r"-{2,}\s*REVISED\s+MARK\s+SCHEME\s*-{2,}", text, re.IGNORECASE)
    if ws_match and ms_match:
        ws_start = ws_match.end()
        ms_start = ms_match.end()
        worksheet_part = text[ws_start:ms_match.start()].strip()
        markscheme_part = text[ms_start:].strip()
        return worksheet_part, markscheme_part

    # ââ Strategy 3: safe fallback â signal caller to keep originals âââââââââââ
    return None, None


def run_formatting_agent(worksheet_text):
    """
    Call the FormattingAgent to obtain structured formatting instructions
    for an already-enhanced worksheet.
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
    # GPT sometimes wraps JSON in markdown fences â strip them before parsing.
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
    Render a structured, exam-style preview in Streamlit based on
    FormattingAgent instructions.
    """
    lines = spec.get("lines", [])
    st.markdown("### Formatted Worksheet Preview")

    # Constrain width to simulate A4 column
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
    margin-bottom: 4px;
    font-family: Arial, sans-serif;
    font-size: 11pt;
}
.q-main {
    margin-top: 10px;
}
.q-indent-0 { padding-left: 0; }
.q-indent-1 { padding-left: 24px; }
.q-indent-2 { padding-left: 48px; }
.q-text {
    white-space: pre-wrap;
    flex: 1;
    padding-right: 12px;
}
.q-marks {
    min-width: 40px;
    text-align: right;
    font-weight: bold;
}
.q-total {
    margin-top: 8px;
    font-weight: bold;
}
.answer-line {
    border-bottom: 1px solid #666;
    margin: 2px 0 4px 0;
}
.answer-indent-1 { margin-left: 24px; margin-right: 40px; }
.answer-indent-2 { margin-left: 48px; margin-right: 40px; }
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

        # Vertical spacing before new main question
        main_class = " q-main" if qnum != last_q and not is_total else ""

        if is_total:
            html_lines.append(
                f'<div class="q-line q-total q-indent-0{main_class}">'
                f'<div class="q-text">(Total for question {qnum} = {marks} marks)</div>'
                f'</div>'
            )
            last_q = qnum
            continue

        # Compose left label + text
        label_prefix = ""
        if indent_level == 0 and qnum:
            label_prefix = f"{qnum} "
        elif indent_level == 1 and part_label:
            label_prefix = f"{part_label} "
        elif indent_level >= 2 and (subpart_label or part_label):
            label_prefix = f"{subpart_label or part_label} "

        html_lines.append(
            f'<div class="q-line q-indent-{indent_level}{main_class}">'
            f'<div class="q-text">{label_prefix}{question_text}</div>'
            f'<div class="q-marks">{f"({marks})" if marks else ""}</div>'
            f'</div>'
        )

        # Answer lines (proportional to marks, max 4)
        if marks and marks > 0:
            num_lines = min(int(marks), 4)
            ans_class = f"answer-indent-{min(indent_level, 2)}"
            for _ in range(num_lines):
                html_lines.append(
                    f'<div class="answer-line {ans_class}"></div>'
                )

        last_q = qnum

    html_lines.append("</div>")
    st.markdown("\n".join(html_lines), unsafe_allow_html=True)


def build_formatted_docx(spec):
    """
    Build a fully formatted A4 Word document (.docx) based on
    FormattingAgent instructions.
    """
    document = Document()

    # Page setup: A4, 2.5 cm margins
    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)

    # Base font: Arial 11
    style = document.styles["Normal"]
    font = style.font
    font.name = "Arial"
    font.size = Pt(11)

    paper_total = spec.get("paper_total_marks")
    lines = spec.get("lines", [])

    # Tab stop for right-aligned marks (slightly inside right margin)
    mark_tab_pos = section.page_width - section.right_margin - Cm(0.5)

    last_q = None

    for line in lines:
        qnum = line.get("question_number")
        indent_level = int(line.get("indent_level", 0))
        part_label = line.get("part_label") or ""
        subpart_label = line.get("subpart_label") or ""
        question_text = line.get("question_text", "")
        marks = line.get("marks")
        is_total = bool(line.get("is_total_for_question"))

        # New main question spacing
        p = document.add_paragraph()
        pf = p.paragraph_format
        if qnum != last_q and last_q is not None and not is_total:
            pf.space_before = Pt(10)
        pf.space_after = Pt(2)

        # Indentation hierarchy
        if indent_level == 0:
            text_tab_pos = Cm(1.0)
        elif indent_level == 1:
            text_tab_pos = Cm(1.5)
        else:
            text_tab_pos = Cm(2.5)

        pf.left_indent = Cm(0)
        tab_stops = pf.tab_stops
        tab_stops.clear_all()
        tab_stops.add_tab_stop(text_tab_pos, WD_TAB_ALIGNMENT.LEFT)
        tab_stops.add_tab_stop(mark_tab_pos, WD_TAB_ALIGNMENT.RIGHT)

        # Totals: bold, left aligned, no right-aligned mark column required
        if is_total:
            run = p.add_run(f"(Total for question {qnum} = {marks} marks)")
            run.bold = True
            last_q = qnum
            continue

        # Compose "label    text            (marks)" line using tab stops
        label_prefix = ""
        if indent_level == 0 and qnum:
            label_prefix = f"{qnum}"
        elif indent_level == 1 and part_label:
            label_prefix = part_label
        elif indent_level >= 2 and (subpart_label or part_label):
            label_prefix = subpart_label or part_label

        if label_prefix:
            p.add_run(label_prefix)
        p.add_run("\t")
        p.add_run(question_text)
        if marks:
            p.add_run("\t")
            mark_run = p.add_run(f"({marks})")
            mark_run.bold = True

        # Answer lines (full-width across text column, capped at 4)
        if marks and marks > 0:
            num_lines = min(int(marks), 4)
            for _ in range(num_lines):
                lp = document.add_paragraph()
                lpf = lp.paragraph_format
                lpf.left_indent = text_tab_pos
                lpf.space_after = Pt(2)
                # Use a consistent underline run that stops before right margin
                underline_run = lp.add_run("_" * 80)

        last_q = qnum

    # Final total for paper, if supplied
    if paper_total:
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(12)
        total_run = p.add_run(f"Total for paper = {paper_total} marks")
        total_run.bold = True

    bio = BytesIO()
    document.save(bio)
    bio.seek(0)
    return bio

# ---------------- MAIN ----------------

if run_button and worksheet_file:

    progress = st.progress(0)
    status = st.empty()

    status.text("Reading files...")
    progress.progress(20)
    time.sleep(0.3)

    worksheet_text = extract_docx(worksheet_file)
    markscheme_text = extract_docx(markscheme_file) if markscheme_file else ""
    spec_text = read_spec_text(spec_txt, spec_docx, pasted_spec)

    status.text("Improving worksheet...")
    progress.progress(50)
    improved_ws = improve_worksheet(worksheet_text)

    status.text("Generating / Improving mark scheme...")
    progress.progress(80)
    # Use the improved worksheet (not the raw original) so question numbering
    # and wording in the mark scheme matches what was actually enhanced.
    improved_ms = generate_markscheme(improved_ws)

    progress.progress(100)
    status.text("Complete.")
    st.success("Enhancement Complete")

    # Persist results so they survive future reruns (e.g. clicking checkboxes/buttons)
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

    st.subheader("Enhanced Worksheet")
    st.text_area("Worksheet Output", improved_ws, height=400, key="ws_output")

    st.subheader("Enhanced Mark Scheme")
    st.text_area("Mark Scheme Output", improved_ms, height=400, key="ms_output")

    # ---------------- VALIDATION ----------------

    with st.expander("ð QA Validation Report"):

        misaligned = False

        # Use the enhanced mark scheme for validation where available.
        # Compare against improved_ws (not the raw original) for consistency.
        validation_ms_text = improved_ms or markscheme_text

        if validation_ms_text:
            overlap = keyword_overlap(improved_ws, validation_ms_text)
            st.write(f"Keyword alignment: {overlap}%")
            if overlap < 40:
                st.error("â  Content misalignment detected (low keyword overlap).")

        ws_total = extract_total(improved_ws)
        ms_total = extract_total(validation_ms_text)

        if ws_total and ms_total and ws_total != ms_total:
            st.error(f"â  Total mismatch: Worksheet = {ws_total}, Mark Scheme = {ms_total}")
            misaligned = True

        if fractional_marks_present(validation_ms_text):
            st.error("â  Fractional marks detected.")
            misaligned = True

        # Question Number Alignment â compare improved worksheet vs improved mark scheme
        ws_questions = extract_question_numbers(improved_ws)
        ms_questions = extract_question_numbers(validation_ms_text)

        # Build a specific description of what is mismatched to pass into regeneration
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
            st.error("â  Question number mismatch detected.")
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

            if st.button("Run full intelligent revision (Agents 1â5)"):
                try:
                    final_text = run_full_revision_via_agents(improved_ws, improved_ms, spec_text)
                    revised_ws, revised_ms = parse_revised_output(final_text)
                    if revised_ws is None:
                        st.error(
                            "â  Agent 5 returned output in an unexpected format â "
                            "the original worksheet and mark scheme have been kept unchanged. "
                            "Try clicking the button again."
                        )
                    else:
                        st.session_state["improved_ws"] = revised_ws
                        # Only overwrite mark scheme if Agent 5 actually produced one
                        if revised_ms:
                            st.session_state["improved_ms"] = revised_ms
                        st.success("Worksheet and mark scheme revised via multi-agent pipeline. Scroll up to review.")
                except Exception as e:
                    st.error(f"Intelligent revision failed: {e}")
        else:
            st.success("Structural checks passed (totals, fractions, numbering).")

    # Offer formatting/export option outside the expander.
    # We recompute only the structural flags (no extra UI messages here).
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

    st.subheader("Formatted Worksheet Export")
    override_ok = True

    if misaligned_for_export:
        st.warning(
            "QA checks found structural issues with totals, fractional marks, or numbering. "
            "You can still export, but please doubleâcheck the output manually."
        )
        override_ok = st.checkbox(
            "Proceed with formatting/export despite QA warnings",
            key="fmt_override",
        )

    if override_ok and st.button("Generate Formatted Worksheet (.docx)", key="fmt_main"):
        try:
            fmt_spec = run_formatting_agent(improved_ws)
            render_formatted_preview(fmt_spec)
            docx_bytes = build_formatted_docx(fmt_spec)
            st.download_button(
                "Download A4 Word Worksheet (.docx)",
                data=docx_bytes,
                file_name="gcse_worksheet_formatted.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            st.error(f"FormattingAgent or export failed: {e}")
