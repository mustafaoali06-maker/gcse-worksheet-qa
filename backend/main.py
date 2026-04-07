"""
FastAPI backend for GCSE Worksheet QA Studio
Handles document processing, agent validation, and export operations
"""

import os
import re
import json
import base64
import secrets
from io import BytesIO
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_TAB_ALIGNMENT, WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from openai import OpenAI

# Import agent prompts
import sys
from pathlib import Path

# Add parent directory to path to import agents.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import (
    FORMATTING_AGENT_PROMPT,
    AGENT_1_PROMPT,
    AGENT_2_PROMPT,
    AGENT_3_PROMPT,
    AGENT_4_PROMPT,
    AGENT_5_PROMPT,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ANSWER_LINE = "_____________________________________________________________________________"
ANSWER_UNDERSCORES = {0: 79, 1: 76, 2: 72}
LABEL_CM = [0.0, 0.63, 1.27]
TEXT_CM = [0.7, 1.27, 1.90]

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="GCSE Worksheet QA Studio")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for frontend
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


# ── HTTP Basic Auth middleware ────────────────────────────────────────────────
# Only active when AUTH_PASSWORD environment variable is set.
# Local dev with no AUTH_PASSWORD set → no auth required.
@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    auth_password = os.getenv("AUTH_PASSWORD", "")
    if not auth_password:
        # No password configured — allow all (local dev)
        return await call_next(request)

    auth_user = os.getenv("AUTH_USER", "examqa")
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
            user_ok = secrets.compare_digest(username.strip(), auth_user)
            pass_ok = secrets.compare_digest(password.strip(), auth_password)
            if user_ok and pass_ok:
                return await call_next(request)
        except Exception:
            pass

    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="examqa"'},
        content="Unauthorized — please enter your credentials.",
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _set_run_font(run, bold=False, size_pt=11):
    """Set font properties for a run in a DOCX document."""
    run.font.name = "Arial"
    run.font.size = Pt(size_pt)
    run.bold = bold
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Arial")
    rFonts.set(qn("w:hAnsi"), "Arial")
    rPr.insert(0, rFonts)


def extract_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file."""
    doc = Document(BytesIO(file_bytes))
    return "\n".join([p.text for p in doc.paragraphs])


def clean_text(text: str) -> str:
    """Remove markdown-style formatting characters."""
    return re.sub(r"[#*]+", "", text)


def add_answer_lines(text: str) -> str:
    """Add underscore answer lines after questions with marks."""
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


def extract_total(text: str) -> Optional[int]:
    """Extract total marks from worksheet text."""
    match = re.search(r"Total for paper\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else None


def fractional_marks_present(text: str) -> bool:
    """Check if worksheet contains fractional marks."""
    return bool(re.search(r"\(\d+\.\d+\)", text))


def keyword_overlap(text1: str, text2: str) -> float:
    """Calculate keyword overlap percentage between two texts."""
    words1 = set(re.findall(r"\b[a-zA-Z]{5,}\b", text1.lower()))
    words2 = set(re.findall(r"\b[a-zA-Z]{5,}\b", text2.lower()))
    if not words1:
        return 0
    return round((len(words1 & words2) / len(words1)) * 100, 1)


def extract_question_numbers(text: str) -> list:
    """Extract main question numbers from worksheet."""
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


def strip_answer_lines(text: str) -> str:
    """Remove underscore answer lines from text."""
    lines = text.split("\n")
    return "\n".join([ln for ln in lines if ANSWER_LINE.strip() not in ln.strip()])


def detect_question_structure(text: str) -> list:
    """Detect the hierarchical structure of questions and sub-parts."""
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


def read_spec_text(
    spec_txt_bytes: Optional[bytes] = None,
    spec_docx_bytes: Optional[bytes] = None,
    pasted_spec_text: Optional[str] = None,
) -> str:
    """Combine specification text from multiple sources."""
    parts = []
    if spec_txt_bytes:
        try:
            parts.append(spec_txt_bytes.decode("utf-8"))
        except Exception:
            pass
    if spec_docx_bytes:
        try:
            parts.append(extract_docx(spec_docx_bytes))
        except Exception:
            pass
    if pasted_spec_text:
        parts.append(pasted_spec_text)
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


# ============================================================================
# AI FUNCTIONS
# ============================================================================


def improve_worksheet(text: str) -> str:
    """Improve worksheet quality and formatting using AI."""
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
            {"role": "user", "content": text},
        ],
        temperature=0,
    )
    return add_answer_lines(clean_text(response.choices[0].message.content))


def generate_markscheme(text: str, mismatch_info: Optional[str] = None) -> str:
    """Generate a mark scheme from the worksheet text."""
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
        temperature=0,
    )
    return clean_text(response.choices[0].message.content)


def run_agent(prompt: str, content: str) -> str:
    """Run an agent with a given prompt and content."""
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
) -> str:
    """Run all five validation agents and return revised output."""
    combined_ws_ms = f"WORKSHEET:\n{worksheet_text}\n\nMARK SCHEME:\n{markscheme_text}"

    agent_steps = [
        ("Checking command word alignment...", AGENT_1_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}"),
        ("Verifying mark allocations...", AGENT_2_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}"),
        ("Checking physics accuracy...", AGENT_3_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}"),
    ]
    coverage_input = f"WORKSHEET AND MARK SCHEME:\n{combined_ws_ms}\n\nINTENDED SCOPE:\n{spec_text}"
    agent_steps.append(("Evaluating topic coverage...", AGENT_4_PROMPT, coverage_input))

    reports = []
    for label, prompt, content in agent_steps:
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
    return run_agent(AGENT_5_PROMPT, combined_input)


def parse_revised_output(text: str) -> tuple:
    """Parse Agent 5 output to extract revised worksheet and mark scheme."""
    ws_marker = "--- REVISED WORKSHEET ---"
    ms_marker = "--- REVISED MARK SCHEME ---"
    ws_idx = text.find(ws_marker)
    ms_idx = text.find(ms_marker)
    if ws_idx != -1 and ms_idx != -1:
        return text[ws_idx + len(ws_marker) : ms_idx].strip(), text[ms_idx + len(ms_marker) :].strip()
    ws_match = re.search(r"-{2,}\s*REVISED\s+WORKSHEET\s*-{2,}", text, re.IGNORECASE)
    ms_match = re.search(r"-{2,}\s*REVISED\s+MARK\s+SCHEME\s*-{2,}", text, re.IGNORECASE)
    if ws_match and ms_match:
        return text[ws_match.end() : ms_match.start()].strip(), text[ms_match.end() :].strip()
    return None, None


def run_formatting_agent(worksheet_text: str) -> dict:
    """Run formatting agent to get JSON structure for document building."""
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


# ============================================================================
# DOCUMENT BUILDING FUNCTIONS
# ============================================================================


def build_formatted_docx(spec: dict) -> BytesIO:
    """
    Build a fully formatted A4 Word document matching AQA GCSE exam paper style.

    Layout:
      • Question text on its own line with label (no inline marks)
      • Answer lines as underscore-character paragraphs below the question
      • Marks (n) on a separate RIGHT-ALIGNED BOLD paragraph after answer lines
      • (Total for question X is Y marks) — right-aligned bold
    """
    document = Document()

    # Page setup (A4, 1.91cm side margins)
    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(1.91)
    section.right_margin = Cm(1.91)

    # Normal style
    style = document.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.space_before = Pt(0)

    lines = spec.get("lines", [])
    paper_total = spec.get("paper_total_marks")
    last_q = None
    prev_indent = None
    _COMB_RE_D = re.compile(r"^\(([a-z])\) \(([ivxlcdm]+)\)$", re.IGNORECASE)
    _seen_roman_d: dict = {}
    _orphan_qnum_d = None

    def _para(space_before_pt=0, space_after_pt=0, left_cm=0.0, hanging_cm=0.0, align=WD_ALIGN_PARAGRAPH.LEFT):
        p = document.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(space_before_pt)
        pf.space_after = Pt(space_after_pt)
        pf.alignment = align
        if left_cm:
            pf.left_indent = Cm(left_cm)
        if hanging_cm:
            pf.first_line_indent = Cm(-hanging_cm)
        return p

    _CMD_SPLIT_D = re.compile(
        r"(?<=[.?!])\s+(Calculate|Explain|State|Describe|Determine|Show|Find|"
        r"Compare|Evaluate|Suggest|Identify|Give|Write|Draw|Plot|Predict|Justify|"
        r"Define|Outline|Use|Work\s+out|Complete|Name|Tick|Circle|Underline|Label)\b",
        re.IGNORECASE,
    )

    for line in lines:
        qnum = line.get("question_number")
        indent_level = int(line.get("indent_level", 0))
        part_label = line.get("part_label") or ""
        subpart_label = line.get("subpart_label") or ""
        question_text = line.get("question_text") or ""
        if question_text.strip().lower() == "none":
            question_text = ""
        marks = line.get("marks")
        is_total = bool(line.get("is_total_for_question"))

        # Total for question
        if is_total:
            p = _para(space_before_pt=4, space_after_pt=12, align=WD_ALIGN_PARAGRAPH.RIGHT)
            r = p.add_run(f"(Total for question {qnum} is {marks} marks)")
            _set_run_font(r, bold=True)
            last_q = qnum
            prev_indent = None
            _orphan_qnum_d = None
            continue

        # Level-0 items with no text — save number to merge onto next line
        if indent_level == 0 and not question_text.strip():
            _orphan_qnum_d = qnum
            last_q = qnum
            continue

        # Roman numeral de-duplication
        _eff_indent = indent_level
        _eff_part = part_label
        if indent_level == 1:
            _mcd = _COMB_RE_D.match(part_label)
            if _mcd:
                _parent_d = _mcd.group(1)
                _roman_d = _mcd.group(2)
                _seen_roman_d.setdefault(qnum, set())
                if _parent_d in _seen_roman_d[qnum]:
                    _eff_indent = 2
                    _eff_part = f"({_roman_d})"
                else:
                    _seen_roman_d[qnum].add(_parent_d)

        # Merge orphan question number
        _ans_lvl_d = _eff_indent
        if _orphan_qnum_d is not None:
            _eff_part = (f"{_orphan_qnum_d}  {_eff_part}" if _eff_part else str(_orphan_qnum_d))
            _eff_indent = 0
            _orphan_qnum_d = None

        # Spacing before this paragraph
        if _eff_indent == 0:
            sp = 22 if (last_q is not None and qnum != last_q) else 0
        elif _eff_indent == 1:
            sp = 10 if (prev_indent is not None and prev_indent != 0) else 6
        else:  # level 2
            sp = 8

        # Label (plain text — no bold per AQA exam style)
        if _eff_indent == 0:
            label = _eff_part or (str(qnum) if qnum else "")
        elif _eff_indent == 1 and _eff_part:
            label = _eff_part
        elif _eff_indent >= 2 and (subpart_label or _eff_part):
            label = subpart_label or _eff_part
        else:
            label = ""
        label_bold = False

        # Question text paragraph
        lvl = min(_eff_indent, 2)
        _child_lvl = min(_ans_lvl_d, 2)
        if lvl == 0 and _child_lvl > 0:
            # Was a merged orphan — wrap at child TEXT_CM
            _left_cm = TEXT_CM[_child_lvl]
            _hang_cm = TEXT_CM[_child_lvl]
        else:
            _left_cm = TEXT_CM[lvl]
            _hang_cm = TEXT_CM[lvl] - LABEL_CM[lvl]

        # Auto-split context sentence from command word, then handle \n splits
        question_text = _CMD_SPLIT_D.sub(lambda m: "\n" + m.group(0).lstrip(), question_text)
        _qt_parts = [s for s in question_text.split("\n") if s.strip()]

        # First paragraph — label + first part of question text
        qp = _para(space_before_pt=sp, space_after_pt=0, left_cm=_left_cm, hanging_cm=_hang_cm)
        if label:
            r_lbl = qp.add_run(label + "  ")
            _set_run_font(r_lbl, bold=label_bold)
        if _qt_parts:
            r_txt = qp.add_run(_qt_parts[0])
            _set_run_font(r_txt, bold=False)

        # Continuation paragraphs (command word lines)
        for _qtp in _qt_parts[1:]:
            cp = _para(space_before_pt=0, space_after_pt=0, left_cm=TEXT_CM[min(_eff_indent, 2)])
            r_cp = cp.add_run(_qtp)
            _set_run_font(r_cp, bold=False)

        # Answer lines (underscore text)
        if marks and marks > 0:
            m = int(marks)
            num_ans = min(m, 6)
            _alvl = min(_ans_lvl_d, 2)
            underscores = "_" * ANSWER_UNDERSCORES.get(_alvl, 62)

            for i in range(num_ans):
                ap = _para(space_before_pt=0, space_after_pt=0, left_cm=LABEL_CM[_alvl])
                r = ap.add_run(underscores)
                _set_run_font(r, bold=False)

            # Marks on their own right-aligned line
            mp = _para(space_before_pt=0, space_after_pt=2, left_cm=LABEL_CM[_alvl], align=WD_ALIGN_PARAGRAPH.RIGHT)
            r_m = mp.add_run(f"({marks})")
            _set_run_font(r_m, bold=True)

        last_q = qnum
        prev_indent = _eff_indent

    # Paper total
    if paper_total:
        p = _para(space_before_pt=14, align=WD_ALIGN_PARAGRAPH.RIGHT)
        r = p.add_run(f"Total marks for question paper: {paper_total}")
        _set_run_font(r, bold=True)
        r.underline = True

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
        parts = re.split(r"(\(1\))", text)
        for part in parts:
            if part == "(1)":
                r = p.add_run("(1)")
                _set_run_font(r, bold=True)
            elif part:
                r = p.add_run(part)
                _set_run_font(r, bold=base_bold)

    prev_line_type = None

    for raw_line in markscheme_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # Total for paper
        if TOTAL_PAPER_RE.search(line) or TOTAL_PAPER_ALT.search(line):
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(line)
            _set_run_font(r, bold=True)
            r.underline = True
            prev_line_type = "total"
            continue

        # Total for question
        if TOTAL_Q_RE.search(line):
            # Normalise "=" -> "is"
            line = re.sub(
                r"(Total for question\s+\w+)\s*=\s*(\d+)",
                r"\1 is \2",
                line,
                flags=re.IGNORECASE,
            )
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(12)
            r = p.add_run(line)
            _set_run_font(r, bold=True)
            prev_line_type = "total"
            continue

        # Bullet point
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
            prev_line_type = "bullet"
            continue

        # Identify line type
        is_main = MAIN_Q_RE.match(line)
        is_part = PART_RE.match(line) or ROMAN_RE.match(line)

        if is_main:
            sp_before = 14 if prev_line_type in ("total", "part", "bullet", "other") else 0
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(sp_before)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(0)
            m = is_main
            r = p.add_run(m.group(1) + " ")
            _set_run_font(r, bold=True)
            add_inline_bold_marks(p, line[m.end() :])
            prev_line_type = "main"

        elif is_part:
            sp_before = 4 if prev_line_type in ("part", "bullet", "other") else 0
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(sp_before)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(0.8)
            add_inline_bold_marks(p, line)
            prev_line_type = "part"

        else:
            # Continuation / any-from line / notes
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.left_indent = Cm(1.5)
            add_inline_bold_marks(p, line)
            prev_line_type = "other"

    bio = BytesIO()
    document.save(bio)
    bio.seek(0)
    return bio


# ============================================================================
# API ENDPOINTS
# ============================================================================


async def process_stream_generator(
    worksheet_bytes: bytes,
    markscheme_bytes: Optional[bytes],
    spec_text: str,
):
    """Async generator for streaming processing steps."""
    step = 0

    # Step 0: Read files
    yield f'data: {json.dumps({"step": step, "label": "Reading files", "detail": "Parsing documents"})}\n\n'
    worksheet_text = extract_docx(worksheet_bytes)
    markscheme_text = extract_docx(markscheme_bytes) if markscheme_bytes else ""
    step += 1

    # Step 1: Improve worksheet
    yield f'data: {json.dumps({"step": step, "label": "Enhancing worksheet", "detail": "Improving quality"})}\n\n'
    improved_ws = improve_worksheet(worksheet_text)
    step += 1

    # Step 2: Generate mark scheme
    yield f'data: {json.dumps({"step": step, "label": "Generating mark scheme", "detail": "Creating marking points"})}\n\n'
    improved_ms = generate_markscheme(improved_ws)
    step += 1

    # Step 3: Agent 1 — Command words
    yield f'data: {json.dumps({"step": step, "label": "Agent 1", "detail": "Checking command words"})}\n\n'
    combined = f"WORKSHEET:\n{improved_ws}\n\nMARK SCHEME:\n{improved_ms}"
    r1 = run_agent(AGENT_1_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined}")
    step += 1

    # Step 4: Agent 2 — Mark structure
    yield f'data: {json.dumps({"step": step, "label": "Agent 2", "detail": "Verifying structure"})}\n\n'
    r2 = run_agent(AGENT_2_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined}")
    step += 1

    # Step 5: Agent 3 — Cognitive balance
    yield f'data: {json.dumps({"step": step, "label": "Agent 3", "detail": "Checking balance"})}\n\n'
    r3 = run_agent(AGENT_3_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined}")
    step += 1

    # Step 6: Agent 4 — Topic coverage
    yield f'data: {json.dumps({"step": step, "label": "Agent 4", "detail": "Evaluating coverage"})}\n\n'
    r4 = run_agent(AGENT_4_PROMPT, f"WORKSHEET AND MARK SCHEME:\n{combined}\n\nINTENDED SCOPE:\n{spec_text}")
    step += 1

    # Step 7: Agent 5 — Intelligent revision
    yield f'data: {json.dumps({"step": step, "label": "Agent 5", "detail": "Finalizing revision"})}\n\n'
    agent5_input = (
        f"ORIGINAL WORKSHEET:\n{improved_ws}\n\nORIGINAL MARK SCHEME:\n{improved_ms}\n\n"
        f"INTENDED SCOPE:\n{spec_text}\n\n"
        f"AGENT 1 REPORT:\n{r1}\n\nAGENT 2 REPORT:\n{r2}\n\n"
        f"AGENT 3 REPORT:\n{r3}\n\nAGENT 4 REPORT:\n{r4}"
    )
    final_text = run_agent(AGENT_5_PROMPT, agent5_input)
    revised_ws, revised_ms = parse_revised_output(final_text)
    if revised_ws:
        improved_ws = revised_ws
    if revised_ms:
        improved_ms = revised_ms

    # Final event with results
    yield f'data: {json.dumps({"done": True, "worksheet": improved_ws, "markscheme": improved_ms})}\n\n'


@app.post("/api/process")
async def process_worksheet(
    worksheet: UploadFile = File(...),
    markscheme: Optional[UploadFile] = File(None),
    spec_txt: Optional[UploadFile] = File(None),
    spec_docx: Optional[UploadFile] = File(None),
    pasted_spec: Optional[str] = Form(None),
):
    """
    Process a worksheet through the full validation pipeline.
    Returns Server-Sent Events stream with progress updates.
    """
    worksheet_bytes = await worksheet.read()
    markscheme_bytes = await markscheme.read() if markscheme else None
    spec_txt_bytes = await spec_txt.read() if spec_txt else None
    spec_docx_bytes = await spec_docx.read() if spec_docx else None

    spec_text = read_spec_text(spec_txt_bytes, spec_docx_bytes, pasted_spec)

    return StreamingResponse(
        process_stream_generator(worksheet_bytes, markscheme_bytes, spec_text),
        media_type="text/event-stream",
    )


@app.post("/api/export/worksheet")
async def export_worksheet(request: Request):
    """Export worksheet text as a DOCX file."""
    body = await request.json()
    text = body.get("text", "")
    spec = run_formatting_agent(text)
    docx_bytes = build_formatted_docx(spec)

    return StreamingResponse(
        iter([docx_bytes.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=worksheet.docx"},
    )


@app.post("/api/export/markscheme")
async def export_markscheme(request: Request):
    """Export mark scheme text as a DOCX file."""
    body = await request.json()
    text = body.get("text", "")
    docx_bytes = build_markscheme_docx(text)

    return StreamingResponse(
        iter([docx_bytes.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=markscheme.docx"},
    )


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """
    Chat endpoint for interactive revisions.
    Body: {"message": str, "worksheet": str, "markscheme": str}
    Returns: {"reply": str, "updated_worksheet": str|null, "updated_markscheme": str|null}
    """
    body = await request.json()
    message = body.get("message", "")
    worksheet = body.get("worksheet", "")
    markscheme = body.get("markscheme", "")

    system_prompt = """You are an AI assistant helping a teacher edit a GCSE physics worksheet and mark scheme.

You will receive:
- A user instruction (e.g. "Change Olivia to Mustafa throughout", "Make Q3b an explain question worth 4 marks")
- The current worksheet text
- The current mark scheme text

Rules:
1. If the instruction requires editing the worksheet, return the full updated worksheet after --- REVISED WORKSHEET ---.
2. If the instruction requires editing the mark scheme, return the full updated mark scheme after --- REVISED MARK SCHEME ---.
3. If only one document needs updating, only include that section.
4. Always start with a brief plain-English explanation of what you changed (2-3 sentences max).
5. Preserve all formatting, question numbers, and answer lines exactly.
6. Do not add commentary inside the document text itself.

Format your response as:
[Your brief explanation here]

--- REVISED WORKSHEET ---
[full updated worksheet, if changed]

--- REVISED MARK SCHEME ---
[full updated mark scheme, if changed]
"""

    user_content = f"""INSTRUCTION: {message}

CURRENT WORKSHEET:
{worksheet}

CURRENT MARK SCHEME:
{markscheme}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
    )
    full_reply = response.choices[0].message.content

    # Extract explanation (everything before first --- marker)
    ws_marker = re.search(r"-{2,}\s*REVISED\s+WORKSHEET\s*-{2,}", full_reply, re.IGNORECASE)
    ms_marker = re.search(r"-{2,}\s*REVISED\s+MARK\s+SCHEME\s*-{2,}", full_reply, re.IGNORECASE)

    explanation = full_reply
    updated_ws = None
    updated_ms = None

    if ws_marker:
        explanation = full_reply[: ws_marker.start()].strip()
        ws_end = ms_marker.start() if ms_marker else len(full_reply)
        updated_ws = full_reply[ws_marker.end() : ws_end].strip()

    if ms_marker:
        if not ws_marker:
            explanation = full_reply[: ms_marker.start()].strip()
        updated_ms = full_reply[ms_marker.end() :].strip()

    return {
        "reply": explanation or "Done — documents updated.",
        "updated_worksheet": updated_ws,
        "updated_markscheme": updated_ms,
    }


@app.get("/logo.png")
async def serve_logo():
    """Serve the examqa logo."""
    logo_file = Path(__file__).parent.parent / "logo.png"
    if logo_file.exists():
        return FileResponse(str(logo_file), media_type="image/png")
    return {"error": "Logo not found"}


@app.get("/")
async def serve_frontend():
    """Serve the frontend HTML file."""
    frontend_file = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_file.exists():
        return FileResponse(str(frontend_file), media_type="text/html")
    return {"message": "Frontend not found"}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
