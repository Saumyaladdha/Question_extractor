"""
Question Paper Extractor
- Uploads a PDF exam paper to OpenAI Files API
- Phase 1: detects paper structure using chain-of-thought prompt
- Phase 2: extracts each question type for each language IN PARALLEL per type
- Each OR-type extraction returns or_scan block with exact min_expected_rows
- Validator uses or_scan as ground truth — NOT the other language's count
- Sub-question types validated against sub_question_count from Phase 1
- VLA skipped entirely when Phase 1 assigns no question numbers to it
- Revalidation re-extracts under-extracted type/language combinations
- Exports structured Excel with one sheet per question type
"""
 
import io
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
 
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
 
load_dotenv()
 
from prompts import MARKS, PROMPTS, chapter_mapping_prompt, count_validator_prompt, extract_structure_prompt
from prompts_language import (
    LANGUAGE_STRUCTURE_PROMPTS,
    LANG_PROMPT_DISPATCH,
    LANG_PARSE_TYPE,
)
 
# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Question Paper Extractor",
    page_icon="📄",
    layout="wide",
)
 
# ─────────────────────────────────────────────────────────────────────────────
# Type category constants
# ─────────────────────────────────────────────────────────────────────────────
SHORT_ANSWER_TYPES = {"Short Answer", "Very Short Answer"}
OR_TYPES           = {"Very Short Answer", "Short Answer", "Long Answer", "Very Long Answer"}
SUB_Q_TYPES        = {"Multiple Choice Question", "Fill in the Blanks", "True and False", "One Word Answer"}
DEBUG_TYPES        = SHORT_ANSWER_TYPES | {"Match the Following"}   # types with verbose extraction logging
 
# ─────────────────────────────────────────────────────────────────────────────
# Short Answer Logger
# ─────────────────────────────────────────────────────────────────────────────
def _sa_log(msg: str):
    if "sa_logs" not in st.session_state:
        st.session_state["sa_logs"] = []
    st.session_state["sa_logs"].append(msg)
 
def _clear_sa_logs():
    st.session_state["sa_logs"] = []
 
 
# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing — now returns (rows, or_scan) tuple
# or_scan is the dict from the model's or_scan block, or None
# ─────────────────────────────────────────────────────────────────────────────
def _fix_latex_backslashes(s: str) -> str:
    # Double every backslash that is NOT already part of a valid JSON escape.
    # Valid JSON escapes to preserve: \\ (literal backslash), \" (quote), \uXXXX (unicode), \/ (slash)
    # Everything else (\frac, \vec, \hat, \,, \!, \;, \n, \t, \r, \f, \b, etc.)
    # is treated as a LaTeX backslash and doubled so json.loads succeeds.
    return re.sub(r'(?<!\\)\\(?!["\\u/])', r'\\\\', s)


# ── Post-processing helpers ────────────────────────────────────────────────

_DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')
_Q_NUM_PREFIX  = re.compile(r'^\s*(?:\(\s*\d+\s*\)\s*|[Qq]?\.?\s*\d+\s*[.):\s]\s*)')
_LEADING_OR    = re.compile(r'^\s*(OR|अथवा)\s+', re.IGNORECASE)

_HEADER_PATTERNS = [
    re.compile(r'write\s+answer\s+of\s+each\s+question',          re.I),
    re.compile(r'write\s+(?:the\s+)?answer\s+in\s+one\s+(word|sentence)', re.I),
    re.compile(r'एक\s+(शब्द|वाक्य)\s+में\s+उत्तर\s+(?:दीजिए|लिखिए)', re.I),
    re.compile(r'प्रत्येक\s+प्रश्न\s+का\s+एक',                    re.I),
    re.compile(r'^(write\s+)?true\s+or\s+false\s*:?\s*$',          re.I),
    re.compile(r'^सत्य\s+(या\s+)?असत्य\s+लिखि',                   re.I),
    re.compile(r'^fill\s+in\s+the\s+blank',                        re.I),
    re.compile(r'^रिक्त\s+स्थान\s+(में\s+)?भर',                   re.I),
    re.compile(r'^match\s+the\s+(column|following)\s*[:\.]?\s*$',   re.I),
]

def _has_devanagari(text: str) -> bool:
    """True if text contains at least one Devanagari character."""
    return bool(_DEVANAGARI_RE.search(text))


# Math/science keywords that appear in Latin script even in Hindi-medium papers.
# A row with only these (no actual English prose) should NOT be treated as "wrong language".
_MATH_KEYWORDS = frozenset({
    'sin', 'cos', 'tan', 'cot', 'sec', 'cosec', 'log', 'ln', 'lim',
    'det', 'max', 'min', 'vec', 'int', 'exp', 'mod', 'gcd', 'lcm',
    'div', 'curl', 'grad', 'abs', 'var', 'std', 'cov', 'let', 'if',
    'abc', 'ab', 'bc', 'ac', 'de', 'xy', 'dx', 'dy', 'dt',
    'and', 'or', 'not', 'then', 'for', 'all',
})
_ENGLISH_WORD_RE = re.compile(r'\b[A-Za-z]{3,}\b')


def _is_english_prose(text: str) -> bool:
    """
    Returns True only if the text contains substantial English prose
    (i.e. it is genuinely an English sentence, not just math notation).
    Math formulas — even ones entirely in Latin script like tan⁻¹(1/2) — return False.
    """
    words = _ENGLISH_WORD_RE.findall(text)
    non_math = [w for w in words if w.lower() not in _MATH_KEYWORDS]
    return len(non_math) >= 5   # 5+ non-math English words = real English prose

def _clean_question_text(text: str) -> str:
    """Strip leading question-number prefix ('13. ' / 'Q13.') and leading OR/अथवा."""
    text = _Q_NUM_PREFIX.sub('', text)
    text = _LEADING_OR.sub('', text)
    return text.strip()

def _is_instruction_line(text: str) -> bool:
    """True if text is a section-header/instruction line, not an actual question."""
    return any(p.search(text) for p in _HEADER_PATTERNS)


_CONTROL_CHARS = frozenset('\x08\x0c\r\t')
 
def _has_latex_corruption(items: list) -> bool:
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or item.get("text") or item.get("q") or "")
        if _CONTROL_CHARS.intersection(text):
            return True
    return False
 
 
def parse_json_response(raw: str, log_label: str = "") -> tuple[list[dict], dict | None]:
    """
    Returns (questions_list, or_scan_dict).
    or_scan_dict is None if the response had no or_scan block.
    """
    clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    is_sa = bool(log_label)
 
    def _try_parse(s: str):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            if is_sa:
                _sa_log(f"  JSONDecodeError: {e}")
            return None
 
    def _unwrap(data) -> tuple[list | None, dict | None]:
        or_scan = None
        if isinstance(data, dict):
            or_scan = data.get("or_scan") if isinstance(data.get("or_scan"), dict) else None
            for key in ("questions", "items", "results", "data"):
                if key in data and isinstance(data[key], list):
                    if is_sa:
                        _sa_log(f"  Unwrapped from key='{key}', count={len(data[key])}")
                    return data[key], or_scan
            for v in data.values():
                if isinstance(v, list):
                    if is_sa:
                        _sa_log(f"  Unwrapped from unknown key, count={len(v)}")
                    return v, or_scan
        if isinstance(data, list):
            return data, None
        return None, None
 
    if is_sa:
        _sa_log(f"\n--- parse_json_response [{log_label}] ---")
        _sa_log(f"  Raw length: {len(raw)} chars")
        _sa_log(f"  Cleaned snippet (first 300 chars): {clean[:300]}")
 
    # Pass 1
    if is_sa:
        _sa_log("  Pass 1: parsing as-is...")
    data = _try_parse(clean)
    if data is not None:
        result, or_scan = _unwrap(data)
        if result is not None:
            if not _has_latex_corruption(result):
                if is_sa:
                    _sa_log(f"  Pass 1 SUCCESS → {len(result)} items, or_scan={or_scan}")
                return result, or_scan
            elif is_sa:
                _sa_log("  Pass 1 parsed but LaTeX corruption detected")
 
    # Pass 2
    if is_sa:
        _sa_log("  Pass 2: fixing LaTeX backslashes...")
    fixed = _fix_latex_backslashes(clean)
    data  = _try_parse(fixed)
    if data is not None:
        result, or_scan = _unwrap(data)
        if result is not None:
            if is_sa:
                _sa_log(f"  Pass 2 SUCCESS → {len(result)} items, or_scan={or_scan}")
            return result, or_scan
 
    # Pass 3
    if is_sa:
        _sa_log("  Pass 3: regex extraction...")
    for candidate in (clean, fixed):
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", candidate)
        if match:
            block = match.group(1)
            for attempt in (block, _fix_latex_backslashes(block)):
                data = _try_parse(attempt)
                if data is not None:
                    result, or_scan = _unwrap(data)
                    if result is not None:
                        if is_sa:
                            _sa_log(f"  Pass 3 SUCCESS → {len(result)} items")
                        return result, or_scan
 
    if is_sa:
        _sa_log("  ALL PASSES FAILED → returning ([], None)")
    return [], None
 
 
def _merge_duplicate_keys(pairs: list) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            existing    = result[key]
            existing_nums: list = existing.get("question_numbers") or []
            new_nums: list      = value.get("question_numbers") or []
            merged      = sorted(set(existing_nums + new_nums))
            marks_each  = (
                value.get("marks_each")
                if len(new_nums) > len(existing_nums)
                else existing.get("marks_each")
            )
            result[key] = {
                "question_numbers":  merged,
                "marks_each":        marks_each,
                "sub_question_count": value.get("sub_question_count") or existing.get("sub_question_count"),
            }
        else:
            result[key] = value
    return result
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — paper structure
# ─────────────────────────────────────────────────────────────────────────────
def get_paper_structure(client: OpenAI, file_id: str) -> dict:
    try:
        response = client.chat.completions.create(
            model="gpt-5.4",
            temperature=0,
            timeout=60,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "file", "file": {"file_id": file_id}},
                    {"type": "text", "text": extract_structure_prompt()},
                ],
            }],
        )
        raw   = response.choices[0].message.content or ""
        # Strip the FOUND_LINES preamble — extract only the JSON block
        json_match = re.search(r"(\{[\s\S]*\})", raw)
        if not json_match:
            return {}
        clean = json_match.group(1)
        data  = json.loads(clean, object_pairs_hook=_merge_duplicate_keys)
        if isinstance(data, dict):
            if data.get("_fallback"):
                _sa_log("Phase 1: used Level 3 minimal fallback structure")
                data.pop("_fallback", None)
            return data
    except Exception as e:
        _sa_log(f"Phase 1 error: {e}")
    return {}
 
 
def upload_pdf(client: OpenAI, pdf_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as fh:
            file_obj = client.files.create(file=fh, purpose="user_data")
        return file_obj.id
    finally:
        os.unlink(tmp_path)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — extract one question type for one language
# Returns (rows, or_scan)
# ─────────────────────────────────────────────────────────────────────────────
def extract_one_type(
    client: OpenAI,
    file_id: str,
    question_type: str,
    language: str,
    exam_type: str,
    class_name: str,
    subject: str,
    year: str,
    q_nums: list[int] | None       = None,
    marks_each: int | None         = None,
    _warnings: list | None         = None,
    _debug: list | None            = None,
) -> tuple[list[dict], dict | None]:
    """Returns (rows, or_scan_dict)."""
    is_sa       = question_type in DEBUG_TYPES
    prompt_fn   = PROMPTS[question_type]
    prompt_text = prompt_fn(language, q_nums)
 
    if is_sa:
        _sa_log(f"\n{'='*60}")
        _sa_log(f"EXTRACT: {question_type} | Language: {language}")
        _sa_log(f"  q_nums: {q_nums}  marks_each: {marks_each}")
 
    try:
        response = client.chat.completions.create(
            model="gpt-5.4",
            temperature=0,
            timeout=180,
            max_completion_tokens=16000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "file", "file": {"file_id": file_id}},
                    {"type": "text", "text": prompt_text},
                ],
            }],
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        msg = f"API error for {question_type} ({language}): {exc}"
        if is_sa:
            _sa_log(f"  API ERROR: {exc}")
        if _warnings is not None:
            _warnings.append(msg)
        return [], None
 
    if is_sa:
        _sa_log(f"\n  RAW RESPONSE ({len(raw)} chars):")
        _sa_log(f"  First 800 chars:\n{raw[:800]}")
 
    log_label = f"{question_type} | {language}" if is_sa else ""
    questions, or_scan = parse_json_response(raw, log_label=log_label)
 
    if not questions and _debug is not None:
        _debug.append((question_type, language, prompt_text, raw))
 
    rows            = []
    dropped_header  = 0
    dropped_no_deva: list[str] = []

    for q in questions:
        text = q.get("question") or q.get("text") or q.get("q") or ""
        text = text.strip()
        if not text:
            continue

        # Strip leading question-number prefix ("13." / "Q13.") and leading OR/अथवा
        cleaned = _clean_question_text(text)
        if is_sa and cleaned != text:
            _sa_log(f"  PREFIX STRIPPED: '{text[:70]}' → '{cleaned[:70]}'")
        text = cleaned
        if not text:
            continue

        # Drop section instruction / header lines that leaked in as questions
        if _is_instruction_line(text):
            dropped_header += 1
            if is_sa:
                _sa_log(f"  HEADER DROPPED: '{text[:80]}'")
            continue

        # Drop Hindi-labeled rows that are actual English prose (model returned wrong language).
        # KEEP rows that are pure math/science notation — those have no Devanagari by design
        # even in Hindi papers (e.g. tan⁻¹(1/2) + tan⁻¹(1/3) = tan⁻¹(1/5)).
        if language == "Hindi" and not _has_devanagari(text) and _is_english_prose(text):
            dropped_no_deva.append(text[:80])
            if is_sa:
                _sa_log(f"  NO-DEVA DROPPED (Hindi label, English prose): '{text[:80]}'")
            continue

        if question_type == "Match the Following":
            marks = q.get("marks") or q.get("mark") or q.get("score")
            try:
                marks = int(marks)
            except (TypeError, ValueError):
                marks = 0
        elif marks_each is not None:
            marks = marks_each
        else:
            marks = MARKS[question_type]

        rows.append({
            "Exam_Type":     exam_type,
            "Class":         class_name,
            "Language":      language,
            "Subject":       subject,
            "Question":      text,
            "Question_Type": question_type,
            "Marks":         marks,
            "Year":          year,
        })

    if dropped_header and _warnings is not None:
        _warnings.append(
            f"{question_type} ({language}): dropped {dropped_header} "
            f"instruction-header row(s) that leaked in as questions"
        )
    if dropped_no_deva and _warnings is not None:
        _warnings.append(
            f"{question_type} (Hindi): dropped {len(dropped_no_deva)} row(s) — "
            f"no Devanagari and contains English prose (wrong language). "
            f"Revalidation will re-extract correctly. First dropped: \"{dropped_no_deva[0]}\""
        )

    if is_sa:
        _sa_log(f"\n  or_scan: {or_scan}")
        _sa_log(
            f"  POST-PROCESS: dropped_header={dropped_header}, "
            f"dropped_no_deva={len(dropped_no_deva)}"
        )
        _sa_log(f"  FINAL: {len(questions)} parsed → {len(rows)} rows kept")
        for i, r in enumerate(rows):
            _sa_log(f"    [{i+1}] {r['Question'][:150]}")

    return rows, or_scan
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Per-type parallel extraction
# Returns (lang_results, or_scans, q_nums, marks_each, sub_q_count)
# ─────────────────────────────────────────────────────────────────────────────
def extract_type_both_languages(
    client: OpenAI,
    file_id: str,
    question_type: str,
    languages: list[str],
    structure: dict,
    exam_type: str,
    class_name: str,
    subject: str,
    year: str,
    extraction_warnings: list,
    extraction_debug: list,
) -> tuple[dict, dict, list | None, int | None, int | None]:
    """
    Returns:
      lang_results   — {lang: [rows]}
      or_scans       — {lang: or_scan_dict or None}
      q_nums         — list of ints or None
      marks_each     — int or None
      sub_q_count    — int or None
    """
    type_info   = structure.get(question_type, {})
    q_nums      = type_info.get("question_numbers")    if isinstance(type_info, dict) else None
    marks_each  = type_info.get("marks_each")          if isinstance(type_info, dict) else None
    sub_q_count = type_info.get("sub_question_count")  if isinstance(type_info, dict) else None
 
    try:
        marks_each  = int(marks_each)  if marks_each  is not None else None
    except (TypeError, ValueError):
        marks_each  = None
    try:
        sub_q_count = int(sub_q_count) if sub_q_count is not None else None
    except (TypeError, ValueError):
        sub_q_count = None
 
    if structure and question_type not in structure:
        if question_type in SHORT_ANSWER_TYPES:
            _sa_log(f"Phase 1 did not find '{question_type}' — fallback scan")
        q_nums      = None
        marks_each  = None
        sub_q_count = None
 
    results:  dict[str, list[dict]]    = {}
    or_scans: dict[str, dict | None]   = {}
 
    with ThreadPoolExecutor(max_workers=len(languages)) as executor:
        futures = {
            executor.submit(
                extract_one_type,
                client, file_id, question_type, lang,
                exam_type, class_name, subject, year,
                q_nums, marks_each,
                extraction_warnings, extraction_debug,
            ): lang
            for lang in languages
        }
        for future in as_completed(futures):
            lang = futures[future]
            try:
                rows, or_scan      = future.result()
                results[lang]      = rows
                or_scans[lang]     = or_scan
            except Exception as exc:
                extraction_warnings.append(f"{question_type} ({lang}) worker failed: {exc}")
                results[lang]  = []
                or_scans[lang] = None
 
    return results, or_scans, q_nums, marks_each, sub_q_count
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Expected count computation
# Uses or_scan from the model (ground truth) for OR-types.
# Uses sub_question_count from Phase 1 for sub-Q types.
# ─────────────────────────────────────────────────────────────────────────────
def _compute_expected_count(
    question_type: str,
    q_nums: list | None,
    sub_q_count: int | None,
    or_scans: dict,        # {lang: or_scan_dict or None}
) -> dict:                 # {lang: expected_int or None}
    """
    Returns per-language expected row counts based on independent ground truth.
    Returns None for a language if no ground truth is available.
    """
    expected = {}
 
    if question_type in OR_TYPES and q_nums:
        for lang, scan in or_scans.items():
            if scan and isinstance(scan, dict):
                min_exp = scan.get("min_expected_rows")
                if min_exp and int(min_exp) > 0:
                    expected[lang] = int(min_exp)
                    continue
            # or_scan missing or malformed — fall back to q_nums length (minimum 1 per Q)
            expected[lang] = len(q_nums)
 
    elif question_type in SUB_Q_TYPES:
        if sub_q_count:
            for lang in or_scans:
                expected[lang] = sub_q_count
        # else: no Phase 1 count, no ground truth → leave empty
 
    elif question_type == "Match the Following":
        # Each question number = 1 complete block = 1 row per language
        if q_nums:
            for lang in or_scans:
                expected[lang] = len(q_nums)

    return expected
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Revalidation — re-extract one under-extracted type/language
# ─────────────────────────────────────────────────────────────────────────────
def revalidate_mismatched_category(
    client: OpenAI,
    file_id: str,
    question_type: str,
    language_to_fix: str,
    other_language: str,
    expected_count: int,
    actual_count: int,
    exam_type: str,
    class_name: str,
    subject: str,
    year: str,
    q_nums: list[int] | None = None,
    marks_each: int | None   = None,
) -> tuple[list[dict], dict | None]:
    """Returns (rows, or_scan) from re-extraction."""
    # Build revalidation header, then re-use the original type-specific prompt
    # (which has the correct language rules, layout guidance, etc.) rather than
    # the generic count_validator_prompt which uses wrong instructions for some types.
    direction = "fewer" if actual_count < expected_count else "more"
    missing   = abs(expected_count - actual_count)
    reval_header = (
        f"REEXTRACTION — count mismatch detected\n\n"
        f"A previous extraction of \"{question_type}\" ({language_to_fix}) returned "
        f"{actual_count} rows but the expected count is {expected_count} "
        f"(based on the {other_language} extraction / Phase 1 count).\n"
        f"You got {direction} than expected — {missing} item(s) {'missing' if direction == 'fewer' else 'extra'}.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"MANDATORY PRE-EXTRACTION STEP — DO THIS FIRST:\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1. Scan the entire section for ALL numbered items: (1), (2), (3)… or (i), (ii)…\n"
        f"   Count them physically. Write the count in your head before building JSON.\n"
        f"2. The physical count MUST equal {expected_count}.\n"
        f"   If you see only {actual_count}, look again — you are missing {missing} item(s).\n"
        f"3. Common reasons for under-count:\n"
        f"   • Stopped at section boundary too early\n"
        f"   • Skipped an item that mixes scripts (Latin/Devanagari)\n"
        f"   • Missed an अथवा/OR alternative (each OR = 2 rows)\n"
        f"   • Missed sub-questions (stopped after (a)(b) when (c)(d) also exist)\n"
        f"   • For Match the Following: extracted only one column block, missed the other\n\n"
        f"ORIGINAL EXTRACTION PROMPT (follow ALL rules below exactly):\n"
        f"──────────────────────────────────────────────────────────\n\n"
    )
    original_prompt_fn = PROMPTS.get(question_type)
    if original_prompt_fn:
        original_prompt = original_prompt_fn(language_to_fix, q_nums)
    else:
        original_prompt = count_validator_prompt(
            question_type=question_type,
            language=language_to_fix,
            q_nums=q_nums,
            expected_count=expected_count,
            actual_count=actual_count,
            other_language=other_language,
        )
    prompt_text = reval_header + original_prompt

    try:
        response = client.chat.completions.create(
            model="gpt-5.4",
            temperature=0.3,   # non-zero so the model doesn't repeat the exact same answer
            timeout=180,
            max_completion_tokens=16000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "file", "file": {"file_id": file_id}},
                    {"type": "text", "text": prompt_text},
                ],
            }],
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        st.warning(f"Validator re-extraction failed for {question_type} ({language_to_fix}): {exc}")
        return [], None
 
    questions, or_scan = parse_json_response(raw)
    if not questions:
        return [], or_scan
 
    if marks_each is None:
        marks_each = MARKS.get(question_type)
 
    rows            = []
    dropped_no_deva: list[str] = []

    for q in questions:
        text = q.get("question") or q.get("text") or q.get("q") or ""
        text = text.strip()
        if not text:
            continue

        # Strip leading question-number prefix and leading OR/अथवा
        text = _clean_question_text(text)
        if not text:
            continue

        # Drop section instruction / header lines
        if _is_instruction_line(text):
            continue

        # Drop Hindi-labeled rows with zero Devanagari (model returned wrong language)
        if language_to_fix == "Hindi" and not _has_devanagari(text):
            dropped_no_deva.append(text[:80])
            continue

        if question_type == "Match the Following":
            marks = q.get("marks") or q.get("mark") or q.get("score")
            try:
                marks = int(marks)
            except (TypeError, ValueError):
                marks = 0
        elif marks_each is not None:
            marks = marks_each
        else:
            marks = MARKS[question_type]

        rows.append({
            "Exam_Type":     exam_type,
            "Class":         class_name,
            "Language":      language_to_fix,
            "Subject":       subject,
            "Question":      text,
            "Question_Type": question_type,
            "Marks":         marks,
            "Year":          year,
        })

    return rows, or_scan
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Cross-type duplicate remover
# If the model ignored range boundaries and extracted Q13 for both Short Answer
# AND Long Answer, this removes the wrong-type copy keeping the lower-marks one.
# ─────────────────────────────────────────────────────────────────────────────
def _deduplicate_cross_type(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Remove rows where the same question text appears in multiple Question_Type
    buckets for the same Language.  Keep the lower-Marks version (Short Answer
    beats Long Answer, etc.) since Phase 1 assigns lower q_nums to lower-marks
    types and the model should not have extracted those for the higher-marks type.

    Returns (deduplicated_df, list_of_warning_strings).
    """
    warnings: list[str] = []
    df = df.copy()

    # Normalise for fuzzy-safe exact match (collapse whitespace, lower)
    df["_norm"] = (
        df["Question"]
        .str.lower()
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

    dup_mask = df.duplicated(subset=["_norm", "Language"], keep=False)
    dups = df[dup_mask]

    if dups.empty:
        return df.drop(columns=["_norm"]), warnings

    idx_to_drop: set[int] = set()

    for (norm, lang), group in dups.groupby(["_norm", "Language"]):
        if group["Question_Type"].nunique() <= 1:
            continue  # same type — normal dup, not a range-overlap issue

        # Multiple types share this text — keep the lowest-marks version
        min_marks  = group["Marks"].min()
        keep_idx   = group[group["Marks"] == min_marks].index[0]
        drop_idxs  = group.index[group.index != keep_idx].tolist()
        idx_to_drop.update(drop_idxs)

        kept_type  = df.at[keep_idx, "Question_Type"]
        drop_types = [df.at[i, "Question_Type"] for i in drop_idxs]
        preview    = df.at[keep_idx, "Question"][:80]
        warnings.append(
            f"Range-overlap duplicate ({lang}): kept in '{kept_type}' "
            f"({min_marks} marks), removed from {drop_types}. "
            f'Q: "{preview}"'
        )

    df = (
        df.drop(index=list(idx_to_drop))
          .drop(columns=["_norm"])
          .reset_index(drop=True)
    )
    return df, warnings


# ─────────────────────────────────────────────────────────────────────────────
# Excel builder
# ─────────────────────────────────────────────────────────────────────────────
def build_excel(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="All Questions", index=False)
        for qtype in df["Question_Type"].unique():
            df[df["Question_Type"] == qtype].to_excel(
                writer, sheet_name=qtype[:31], index=False
            )
        for lang in ["Hindi", "English"]:
            lang_df = df[df["Language"] == lang]
            if not lang_df.empty:
                lang_df.to_excel(writer, sheet_name=f"{lang} Questions", index=False)
        if "Chapter_Name" in df.columns and df["Chapter_Name"].ne("Unknown").any():
            summary = (
                df[df["Chapter_Name"] != "Unknown"]
                .groupby(["Chapter_Number", "Chapter_Name", "Language"])
                .agg(Question_Count=("Question", "count"))
                .reset_index()
                .sort_values(["Chapter_Number", "Language"])
            )
            summary.to_excel(writer, sheet_name="Chapter Summary", index=False)
    return buffer.getvalue()
 


# ─────────────────────────────────────────────────────────────────────────────
# Language paper helpers
# ─────────────────────────────────────────────────────────────────────────────

_LANGUAGE_SUBJECTS = {"hindi", "english", "हिंदी", "अंग्रेजी", "hindi language", "english language"}

def _is_language_subject(subject: str) -> bool:
    return subject.strip().lower() in _LANGUAGE_SUBJECTS


def _detect_language_from_subject(subject: str) -> str:
    s = subject.strip().lower()
    if s in {"hindi", "हिंदी", "hindi language"}:
        return "Hindi"
    return "English"


def get_language_structure(client: OpenAI, file_id: str, language: str) -> dict:
    prompt_fn = LANGUAGE_STRUCTURE_PROMPTS.get(language)
    if not prompt_fn:
        return {}
    try:
        response = client.chat.completions.create(
            model="gpt-5.4",
            temperature=0,
            timeout=90,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "file", "file": {"file_id": file_id}},
                    {"type": "text", "text": prompt_fn()},
                ],
            }],
        )
        raw   = response.choices[0].message.content or ""
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data  = json.loads(clean)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        st.warning(f"Language structure detection failed: {exc}")
        return {}


def _recover_truncated_json(text: str) -> dict | None:
    """
    When the model response is truncated mid-JSON, try to close the array/object
    and parse whatever complete items were captured before the cut.
    Returns a dict like {"questions": [...]} with all complete objects, or None.
    """
    # Find the outermost array start (usually after the first key like "questions")
    arr_start = text.find("[")
    if arr_start == -1:
        return None
    fragment = text[arr_start:]
    # Collect complete top-level JSON objects by counting braces
    objects = []
    depth = 0
    start = None
    for i, ch in enumerate(fragment):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                obj_str = fragment[start:i + 1]
                try:
                    obj = json.loads(obj_str)
                    if isinstance(obj, dict):
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None
    if not objects:
        return None
    # Wrap in a questions dict so the caller's key-lookup works
    return {"questions": objects}


def _parse_language_section_response(raw: str, parse_type: str) -> list[dict]:
    """
    parse_type:
      "questions" -> {"questions": [...]}
      "passages"  -> {"passages": [...]}
      "match"     -> flat {column_a_header, column_a, column_b, marks}
    Returns a normalised list of dicts.
    """
    clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    def _try(s):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    data = _try(clean) or _try(_fix_latex_backslashes(clean))
    if not data:
        # JSON truncated — try to recover complete objects from the partial response
        data = _recover_truncated_json(clean)
        if not data:
            return []

    if parse_type == "questions":
        if isinstance(data, dict):
            # Try known keys first, then any list-valued key
            for key in ("questions", "items", "results", "literature_questions",
                        "writing_tasks", "grammar_items", "sub_items"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            # Fallback: first list-valued key in the dict
            for v in data.values():
                if isinstance(v, list) and v:
                    return v
        if isinstance(data, list):
            return data
        return []

    if parse_type == "passages":
        if isinstance(data, dict):
            if "passages" in data and isinstance(data["passages"], list):
                return data["passages"]
            # Fallback: first list-valued key
            for v in data.values():
                if isinstance(v, list) and v:
                    return v
        if isinstance(data, list):
            return data
        return []

    if parse_type == "match":
        if isinstance(data, dict) and "column_a" in data:
            return [data]
        # Wrapped: {"match": {...}} or similar
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, dict) and "column_a" in v:
                    return [v]
                if isinstance(v, list) and v and isinstance(v[0], dict) and "column_a" in v[0]:
                    return v
        return []

    return []


def _build_language_rows(
    items: list[dict],
    parse_type: str,
    section: dict,
    language: str,
    exam_type: str,
    class_name: str,
    subject: str,
    year: str,
) -> list[dict]:
    """Convert parsed model output to DataFrame rows for a single section."""
    section_name    = section.get("name", "")
    section_type    = section.get("type", "")
    section_subtype = section.get("sub_type") or ""
    rows: list[dict] = []

    qtype = section_subtype if (section_type == "Objective" and section_subtype) else section_type

    base = {
        "Exam_Type":     exam_type,
        "Class":         class_name,
        "Language":      language,
        "Subject":       subject,
        "Year":          year,
        "Section_Name":  section_name,
        "Question_Type": qtype,
    }

    def _empty_cols():
        return {
            "Skill_Category": "",
            "Question":       "",
            "Chapter_Number": 0,
            "Chapter_Name":   "",
            "Marks":          0,
        }

    if parse_type == "passages":
        for p in items:
            if not isinstance(p, dict):
                continue
            body        = (p.get("body_text") or "").strip()
            sub_qs      = p.get("sub_questions") or []
            total_marks = p.get("total_marks") or 0
            ptype       = p.get("passage_type") or "Prose"
            if language == "Hindi":
                skill = "अपठित काव्यांश" if ptype == "Poetry" else "अपठित गद्यांश"
            else:
                skill = "Reading Comprehension"

            # Build sub-questions as readable numbered text
            sq_lines = []
            for i, sq in enumerate(sub_qs, 1):
                if isinstance(sq, dict):
                    sq_text  = (sq.get("text") or "").strip()
                    sq_marks = sq.get("marks")
                elif isinstance(sq, str):
                    sq_text  = sq.strip()
                    sq_marks = None
                else:
                    continue
                if not sq_text:
                    continue
                if sq_marks is not None:
                    sq_lines.append(f"{i}. {sq_text}  [{sq_marks} marks]")
                else:
                    sq_lines.append(f"{i}. {sq_text}")
            sub_q_text = "\n".join(sq_lines)

            # Full question = passage label + body text + all sub-questions
            full_q = f"[{ptype} Passage]\n{body}"
            if sub_q_text:
                full_q += "\n\n" + sub_q_text

            row = {**base, **_empty_cols()}
            row.update({
                "Skill_Category": skill,
                "Question":       full_q.strip(),
                "Marks":          int(total_marks) if total_marks else 0,
                "Chapter_Name":   skill,
            })
            rows.append(row)

    elif parse_type == "match":
        for m in items:
            col_a   = m.get("column_a", [])
            col_b   = m.get("column_b", [])
            marks   = m.get("marks") or len(col_a)
            a_hdr   = m.get("column_a_header", "Column A")
            b_hdr   = m.get("column_b_header", "Column B")

            # column_a items may be plain strings (old format) or
            # dicts {text, skill_category, lesson_name} (new format)
            col_a_texts = []
            for item in col_a:
                if isinstance(item, dict):
                    col_a_texts.append(item.get("text", ""))
                else:
                    col_a_texts.append(str(item))

            question = (
                f"{a_hdr}:\n" + "\n".join(col_a_texts) +
                "\n---\n" +
                f"{b_hdr}:\n" + "\n".join(str(x) for x in col_b)
            )
            row = {**base, **_empty_cols()}
            row.update({
                "Skill_Category": "Match the Following",
                "Question":       question,
                "Marks":          int(marks) if marks else len(col_a),
                "Chapter_Name":   "Match the Following",
            })
            rows.append(row)

    else:  # "questions" — writing / grammar / literature / objective
        for q in items:
            if not isinstance(q, dict):
                continue
            text = (q.get("question") or q.get("text") or q.get("q") or "").strip()
            text = _clean_question_text(text)
            if not text:
                continue
            if _is_instruction_line(text):
                continue

            skill       = (q.get("skill_category") or "").strip()
            lesson_name = (q.get("lesson_name")    or "").strip()
            inputs      = (q.get("inputs_given")   or "").strip()
            topics      = q.get("topic_options")
            directive   = (q.get("directive")      or "").strip()
            attempt     = q.get("attempt_any")
            marks       = q.get("marks") or 0
            try:
                marks = int(marks)
            except (TypeError, ValueError):
                marks = 0

            # Chapter name logic:
            # Literature rows → blank (will be filled by run_language_chapter_mapping)
            # MCQ with lesson_name → use lesson_name as preliminary chapter (will be mapped)
            # Grammar MCQs or grammar section → "Grammar" / "व्याकरण"
            # Everything else → skill_category
            if section_type == "Literature":
                chapter_name = ""
            elif section_type == "Objective" and skill == "Grammar":
                chapter_name = "व्याकरण" if language == "Hindi" else "Grammar"
            elif section_type == "Objective" and lesson_name:
                chapter_name = lesson_name   # preliminary; chapter mapping will refine it
            else:
                chapter_name = skill

            # Build a single complete question string — append all context below
            full_q = text
            if directive and directive.lower() not in text.lower():
                full_q += "\n" + directive
            if inputs:
                full_q += "\n" + inputs
            if isinstance(topics, list) and topics:
                for i, t in enumerate(topics, 1):
                    topic_str = t if isinstance(t, str) else t.get("topic", str(t))
                    full_q += f"\n{i}. {topic_str}"
            row = {**base, **_empty_cols()}
            row.update({
                "Skill_Category": skill,
                "Question":       full_q.strip(),
                "Marks":          marks,
                "Chapter_Name":   chapter_name,
            })
            rows.append(row)

    return rows


def extract_language_section(
    client: OpenAI,
    file_id: str,
    section: dict,
    language: str,
    exam_type: str,
    class_name: str,
    subject: str,
    year: str,
) -> list[dict]:
    prompt_key = section.get("prompt", "")
    q_nums     = section.get("q_nums") or []
    dispatch   = LANG_PROMPT_DISPATCH.get(prompt_key)
    parse_type = LANG_PARSE_TYPE.get(prompt_key, "questions")

    if not dispatch:
        sname = section.get('name', '')
        st.warning(f"No prompt handler for section '{sname}' (prompt='{prompt_key}')")
        return []

    prompt_text   = dispatch(language, q_nums if q_nums else None)
    finish_reason = "unknown"
    raw           = ""

    try:
        response = client.chat.completions.create(
            model="gpt-5.4",
            temperature=0,
            timeout=180,
            max_completion_tokens=16000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "file", "file": {"file_id": file_id}},
                    {"type": "text", "text": prompt_text},
                ],
            }],
        )
        finish_reason = response.choices[0].finish_reason
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        sname2 = section.get('name', '')
        st.warning(f"Extraction failed for section '{sname2}': {exc}")
        return []

    sname3     = section.get('name', '')
    debug_info = (
        f"prompt   : {prompt_key}\n"
        f"parse    : {parse_type}\n"
        f"q_nums   : {q_nums}\n"
        f"finish   : {finish_reason}\n"
        f"resp_len : {len(raw)} chars"
    )

    if finish_reason == "length":
        st.warning(f"⚠️ '{sname3}': response truncated — some questions near the end may be missing.")

    items = _parse_language_section_response(raw, parse_type)

    if not items:
        st.warning(f"Section '{sname3}': 0 items after parse (parse_type={parse_type})")
        with st.expander(f"🔍 Debug — '{sname3}' FAILED (0 items parsed)", expanded=True):
            st.code(debug_info, language="text")
            st.divider()
            st.code(raw[:8000] if raw else "(empty response)", language="text")
        return []

    rows = _build_language_rows(items, parse_type, section, language, exam_type, class_name, subject, year)

    if not rows:
        with st.expander(f"🔍 Debug — '{sname3}' FAILED (parsed {len(items)} items → 0 rows after filter)", expanded=True):
            st.code(debug_info, language="text")
            st.json(items[:3])
        return []

    with st.expander(f"🔍 Debug — '{sname3}' OK ({len(rows)} rows)", expanded=False):
        st.code(debug_info, language="text")

    return rows


def run_language_chapter_mapping(
    client: OpenAI,
    df: pd.DataFrame,
    chapters: list,
    language: str,
) -> pd.DataFrame:
    if "Chapter_Number" not in df.columns:
        df["Chapter_Number"] = 0
    if "Chapter_Name" not in df.columns:
        df["Chapter_Name"] = df.get("Skill_Category", pd.Series("", index=df.index))

    # Map chapters for Literature rows + MCQ rows about specific lessons
    mcq_lit_mask = (
        (df["Question_Type"] == "MCQ") &
        (df["Chapter_Name"].ne("")) &
        (~df["Chapter_Name"].isin(["Grammar", "व्याकरण", "General", "general"]))
    )
    lit_mask = (df["Question_Type"] == "Literature") | mcq_lit_mask
    if not chapters or not lit_mask.any():
        return df

    lit_idx   = df.index[lit_mask].tolist()
    questions = df.loc[lit_idx, "Question"].tolist()
    assignments = assign_chapters(client, questions, chapters, language,
                                  for_language_paper=(language == "Hindi"))

    for i, idx in enumerate(lit_idx):
        df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
        df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]

    return df


def build_excel_language(df: pd.DataFrame) -> bytes:
    col_order = [
        "Exam_Type", "Class", "Language", "Subject", "Year",
        "Section_Name", "Question_Type", "Skill_Category",
        "Question", "Chapter_Number", "Chapter_Name", "Marks",
    ]
    df = df[[c for c in col_order if c in df.columns]]

    objective_types = {"MCQ", "FillBlanks", "MatchFollowing", "OneWordAnswer", "TrueFalse"}

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="All Questions", index=False)

        for sheet_name, mask_fn in [
            ("Comprehension", lambda d: d["Question_Type"] == "Comprehension"),
            ("Writing",       lambda d: d["Question_Type"] == "Writing"),
            ("Grammar",       lambda d: d["Question_Type"] == "Grammar"),
            ("Literature",    lambda d: d["Question_Type"] == "Literature"),
            ("Objective",     lambda d: d["Question_Type"].isin(objective_types)),
        ]:
            subset = df[mask_fn(df)]
            if not subset.empty:
                subset.to_excel(writer, sheet_name=sheet_name, index=False)

        lit_df = df[df["Question_Type"] == "Literature"]
        if not lit_df.empty and lit_df["Chapter_Name"].ne("").any():
            summary = (
                lit_df[lit_df["Chapter_Name"] != ""]
                .groupby(["Chapter_Number", "Chapter_Name"])
                .agg(Question_Count=("Question", "count"))
                .reset_index()
                .sort_values("Chapter_Number")
            )
            summary.to_excel(writer, sheet_name="Chapter Summary", index=False)

    return buffer.getvalue()

 
# ─────────────────────────────────────────────────────────────────────────────
# Chapter mapping helpers
# ─────────────────────────────────────────────────────────────────────────────
_SUBJECT_ALIASES = {
    "maths": "mathematics", "math": "mathematics", "bio": "biology",
    "pol science": "political_science", "political science": "political_science",
    "business studies": "business_studies", "business_studies": "business_studies",
    "pol. science": "political_science",
}
 
def load_chapter_mapping(subject: str) -> list:
    base_dir   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chapter_mapping")
    normalized = subject.strip().lower().replace(" ", "_")
    normalized = _SUBJECT_ALIASES.get(normalized, normalized)
    path       = os.path.join(base_dir, f"{normalized}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if "chapters" in data and isinstance(data["chapters"], list):
            return data["chapters"]
        if "books" in data and isinstance(data["books"], list):
            flat: list = []
            seq = 1
            for book in data["books"]:
                book_name = book.get("book", "")
                for ch in book.get("chapters", []):
                    flat.append({
                        "number": seq,
                        "name": f"[{book_name}] {ch['name']}" if book_name else ch["name"],
                    })
                    seq += 1
            return flat
    except Exception:
        pass
    return []
 
 
def assign_chapters(
    client: OpenAI,
    questions: list,
    chapters: list,
    language: str = "English",
    for_language_paper: bool = False,
) -> list:
    fallback = [{"chapter_number": 0, "chapter_name": "Unknown"}] * len(questions)
    if not questions or not chapters:
        return fallback
    try:
        prompt_text = chapter_mapping_prompt(questions, chapters, language, for_language_paper)
        response    = client.chat.completions.create(
            model="gpt-5.4",
            temperature=0,
            timeout=60,
            messages=[{"role": "user", "content": prompt_text}],
        )
        raw   = response.choices[0].message.content or ""
        items, _ = parse_json_response(raw)
        result   = []
        for item in items:
            try:
                result.append({
                    "chapter_number": int(item.get("chapter_number", 0)),
                    "chapter_name":   str(item.get("chapter_name", "Unknown")),
                })
            except (TypeError, ValueError):
                result.append({"chapter_number": 0, "chapter_name": "Unknown"})
        while len(result) < len(questions):
            result.append({"chapter_number": 0, "chapter_name": "Unknown"})
        return result[: len(questions)]
    except Exception as exc:
        st.warning(f"Chapter mapping error ({language}): {exc}")
        return fallback
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Configuration")
    _env_key = os.environ.get("OPENAI_API_KEY", "")
    if _env_key:
        st.success("API key loaded from .env")
        api_key = _env_key
    else:
        api_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
 
    st.divider()
    st.subheader("Paper Details")
    exam_type  = st.text_input("Exam Type",  placeholder="e.g., MP Board, CBSE")
    class_name = st.text_input("Class",      placeholder="e.g., 12, Class 10")
    subject    = st.text_input("Subject",    placeholder="e.g., Physics, Chemistry")
    year       = st.text_input("Year",       placeholder="e.g., 2025")
    language   = st.selectbox(
        "Extract Language",
        ["Hindi", "English", "Both (Hindi + English)"],
    )
 
    st.divider()
    st.subheader("Question Types & Marks")
    for qtype, marks in MARKS.items():
        if marks is None:
            st.markdown(f"- **{qtype}** — dynamic (= Column A count)")
        else:
            st.markdown(f"- **{qtype}** — {marks} mark{'s' if marks > 1 else ''}")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Main area
# ─────────────────────────────────────────────────────────────────────────────
st.title("Question Paper Extractor")
st.markdown(
    "question type and downloads them as a structured Excel sheet."
)
 
uploaded_file = st.file_uploader("Upload Question Paper PDF", type=["pdf"])
if uploaded_file:
    st.info(f"Uploaded: **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")
 
extract_btn = st.button("Extract Questions", type="primary", disabled=not uploaded_file)
 
if extract_btn:
    _clear_sa_logs()
 
    errors = []
    if not api_key:    errors.append("OpenAI API Key is required.")
    if not exam_type:  errors.append("Exam Type is required.")
    if not class_name: errors.append("Class is required.")
    if not subject:    errors.append("Subject is required.")
    if not year:       errors.append("Year is required.")
    if errors:
        for e in errors:
            st.error(e)
        st.stop()
 
    client         = OpenAI(api_key=api_key)
    languages      = (
        ["Hindi", "English"]
        if language == "Both (Hindi + English)"
        else [language]
    )
    question_types = list(PROMPTS.keys())
    do_bilingual   = len(languages) == 2
 
    # Load chapters
    chapters = load_chapter_mapping(subject)
    if chapters:
        st.info(f"Chapter mapping loaded for **{subject}** — {len(chapters)} chapters.")
    else:
        st.warning(f"No chapter mapping found for '{subject}' — Chapter columns will be blank.")
 
    # Upload PDF
    with st.spinner("Uploading PDF to OpenAI Files API..."):
        try:
            file_id = upload_pdf(client, uploaded_file.read())
        except Exception as exc:
            st.error(f"Failed to upload PDF: {exc}")
            st.stop()
    st.success(f"PDF uploaded (file_id: `{file_id}`)")

    # ── BRANCH: language paper vs science/math ────────────────────────────
    if _is_language_subject(subject):
        lang_paper_lang = _detect_language_from_subject(subject)
        st.markdown("---")
        st.markdown(f"**Language paper detected ({lang_paper_lang}) — running language extraction flow**")

        with st.spinner("Detecting paper sections (Phase 1)…"):
            lang_structure = get_language_structure(client, file_id, lang_paper_lang)

        sections = lang_structure.get("sections", [])
        disc     = lang_structure.get("marks_discrepancy")
        if disc:
            st.warning(f"Marks discrepancy: {disc}")
        if sections:
            parts = " | ".join(
                f"{s['name']} ({s['type']}, Q{s['q_nums']})" for s in sections
            )
            st.info(f"Sections detected: {parts}")
        else:
            st.warning("Could not detect sections — check paper format.")
            try:
                client.files.delete(file_id)
            except Exception:
                pass
            st.stop()

        lang_all_rows: list[dict] = []
        sec_progress = st.progress(0)
        for si, sec in enumerate(sections):
            sec_status = st.empty()
            sec_status.markdown(f"Extracting **{sec['name']}** ({sec['type']})…")
            rows = extract_language_section(
                client=client,
                file_id=file_id,
                section=sec,
                language=lang_paper_lang,
                exam_type=exam_type,
                class_name=class_name,
                subject=subject,
                year=year,
            )
            lang_all_rows.extend(rows)
            sec_status.markdown(f"✅ **{sec['name']}** — {len(rows)} rows")
            sec_progress.progress((si + 1) / len(sections))
        sec_progress.empty()

        try:
            client.files.delete(file_id)
        except Exception:
            pass

        if not lang_all_rows:
            st.warning("No questions extracted.")
            st.stop()

        lang_df = pd.DataFrame(lang_all_rows)

        # Phase 3: chapter mapping for Literature
        if chapters:
            with st.spinner("Mapping literature to chapters…"):
                lang_df = run_language_chapter_mapping(client, lang_df, chapters, lang_paper_lang)
            st.success(f"Chapter mapping done.")
        else:
            if "Chapter_Number" not in lang_df.columns:
                lang_df["Chapter_Number"] = 0
                lang_df["Chapter_Name"]   = lang_df["Skill_Category"].fillna("")

        # Summary
        st.subheader(f"Extracted {len(lang_df)} Questions")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Questions", len(lang_df))
        c2.metric("Sections",        lang_df["Section_Name"].nunique())
        c3.metric("Total Marks",     int(lang_df["Marks"].sum()))

        st.markdown("**Breakdown by Section**")
        breakdown = (
            lang_df.groupby(["Section_Name", "Question_Type", "Skill_Category"])
            .agg(Count=("Question", "count"), Marks=("Marks", "sum"))
            .reset_index()
        )
        st.dataframe(breakdown, use_container_width=True, hide_index=True)

        sel_type = st.multiselect(
            "Filter by Question Type",
            lang_df["Question_Type"].unique().tolist(),
            default=lang_df["Question_Type"].unique().tolist(),
        )
        filtered = lang_df[lang_df["Question_Type"].isin(sel_type)]
        display_cols = [c for c in [
            "Section_Name", "Question_Type", "Skill_Category",
            "Question", "Lesson_Name", "Author", "Chapter_Name", "Marks",
        ] if c in filtered.columns]
        st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

        lang_excel = build_excel_language(lang_df)
        file_name  = (
            f"questions_{exam_type.replace(' ', '_')}"
            f"_Class{class_name.replace(' ', '')}"
            f"_{subject.replace(' ', '_')}"
            f"_{year}.xlsx"
        )
        st.download_button(
            label="Download Excel",
            data=lang_excel,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        st.caption(
            "Excel contains: All Questions · Comprehension · Writing · "
            "Grammar · Literature · Objective · Chapter Summary"
        )
        st.stop()
    # ── END language branch — science/math flow continues below ──────────

    # Phase 1: structure
    structure: dict = {}
    with st.spinner("Reading paper structure (question number map)..."):
        structure = get_paper_structure(client, file_id)
 
    if structure:
        parts = []
        for k in structure:
            if isinstance(structure[k], dict) and structure[k].get("question_numbers"):
                sqc     = structure[k].get("sub_question_count")
                sqc_str = f" ({sqc} sub-Qs)" if sqc else ""
                parts.append(f"{k}: Q{structure[k]['question_numbers']}{sqc_str}")
        st.info("Paper structure detected: " + " | ".join(parts))
    else:
        st.warning("Could not detect paper structure — using section-header fallback.")
        _sa_log("Phase 1 FAILED — structure empty")
 
    # ── Phase 2: Per-type parallel extraction ─────────────────────────────
    st.markdown("---")
    st.markdown("**Extracting questions — Hindi + English run together per type:**")
 
    all_rows:            list[dict]  = []
    extraction_warnings: list[str]   = []
    extraction_debug:    list[tuple] = []
 
    # Caches for revalidation layer
    q_nums_cache:          dict[str, list | None]    = {}
    marks_each_cache:      dict[str, int | None]     = {}
    sub_q_count_cache:     dict[str, int | None]     = {}
    or_scans_cache:        dict[str, dict]           = {}   # {qtype: {lang: or_scan}}
    expected_counts_cache: dict[str, dict]           = {}   # {qtype: {lang: int}}
 
    # Build one status row per question type
    type_status_placeholders: dict[str, object] = {}
    for qtype in question_types:
        col_label, col_status = st.columns([3, 7])
        with col_label:
            st.markdown(f"`{qtype}`")
        with col_status:
            ph = st.empty()
            ph.markdown("⏳ waiting…")
            type_status_placeholders[qtype] = ph
 
    progress_bar = st.progress(0)
 
    for idx, qtype in enumerate(question_types):
        ph = type_status_placeholders[qtype]
 
        # Skip any type Phase 1 did not assign question numbers to.
        # Without q_nums the prompt has no boundary and extracts from
        # the wrong section (e.g. One Word Answer stealing VSA questions).
        # This applies to ALL types — any paper format is valid.
        if structure:
            type_info = structure.get(qtype, {})
            assigned  = type_info.get("question_numbers") if isinstance(type_info, dict) else None
            if not assigned:
                ph.markdown("⏭️ skipped — not present in this paper")
                q_nums_cache[qtype]          = None
                marks_each_cache[qtype]      = None
                sub_q_count_cache[qtype]     = None
                or_scans_cache[qtype]        = {}
                expected_counts_cache[qtype] = {}
                progress_bar.progress((idx + 1) / len(question_types))
                continue
 
        ph.markdown("🔄 extracting…")
 
        lang_results, or_scans, q_nums, marks_each, sub_q_count = extract_type_both_languages(
            client=client,
            file_id=file_id,
            question_type=qtype,
            languages=languages,
            structure=structure,
            exam_type=exam_type,
            class_name=class_name,
            subject=subject,
            year=year,
            extraction_warnings=extraction_warnings,
            extraction_debug=extraction_debug,
        )
 
        q_nums_cache[qtype]      = q_nums
        marks_each_cache[qtype]  = marks_each
        sub_q_count_cache[qtype] = sub_q_count
        or_scans_cache[qtype]    = or_scans
 
        counts_by_lang: dict[str, int] = {}
        for lang in languages:
            rows = lang_results.get(lang, [])
            all_rows.extend(rows)
            counts_by_lang[lang] = len(rows)
 
        # Compute independent expected counts
        expected = _compute_expected_count(qtype, q_nums, sub_q_count, or_scans)
        expected_counts_cache[qtype] = expected
 
        # Build status line
        counts_str = " | ".join(f"{l}: **{counts_by_lang[l]}**" for l in languages)
 
        if do_bilingual:
            h_count = counts_by_lang.get("Hindi",   0)
            e_count = counts_by_lang.get("English", 0)
            h_exp   = expected.get("Hindi")
            e_exp   = expected.get("English")
 
            h_ok = (h_count >= h_exp) if h_exp is not None else (h_count == e_count)
            e_ok = (e_count >= e_exp) if e_exp is not None else (e_count == h_count)
 
            if h_ok and e_ok:
                exp_str = f"(expected H≥{h_exp}, E≥{e_exp})" if h_exp else ""
                ph.markdown(f"✅ {counts_str} — OK {exp_str}")
            else:
                issues = []
                if not h_ok and h_exp: issues.append(f"Hindi got {h_count}, need ≥{h_exp}")
                if not e_ok and e_exp: issues.append(f"English got {e_count}, need ≥{e_exp}")
                if not issues:         issues.append(f"counts differ: H={h_count} E={e_count}")
                ph.markdown(f"⚠️ {counts_str} — {'; '.join(issues)} (revalidation will fix)")
        else:
            lang  = languages[0]
            count = counts_by_lang.get(lang, 0)
            exp   = expected.get(lang)
            if exp is None or count >= exp:
                ph.markdown(f"✅ {lang}: **{count}** questions")
            else:
                ph.markdown(f"⚠️ {lang}: **{count}** questions (expected ≥{exp})")
 
        progress_bar.progress((idx + 1) / len(question_types))
 
    progress_bar.empty()
 
    # Surface warnings
    for w in extraction_warnings:
        st.warning(w)
 
    # SA / Match the Following debug log
    sa_logs = st.session_state.get("sa_logs", [])
    if sa_logs:
        sa_row_counts = {}
        for r in all_rows:
            if r["Question_Type"] in DEBUG_TYPES:
                key = f"{r['Question_Type']} | {r['Language']}"
                sa_row_counts[key] = sa_row_counts.get(key, 0) + 1
        label_parts    = [f"{k}: {v}" for k, v in sa_row_counts.items()] if sa_row_counts else ["0 rows"]
        expander_label = "Extraction Debug Log — " + " | ".join(label_parts)
        with st.expander(expander_label, expanded=(not sa_row_counts)):
            st.code("\n".join(sa_logs), language="text")
 
    if extraction_debug:
        with st.expander(
            f"Debug — {len(extraction_debug)} extraction(s) returned 0 rows", expanded=True
        ):
            for dbg_type, dbg_lang, dbg_prompt, dbg_raw in extraction_debug:
                st.markdown(f"---\n### {dbg_type} ({dbg_lang})")
                with st.expander("Prompt sent to model", expanded=False):
                    st.code(dbg_prompt, language="text")
                st.markdown("**Raw model response:**")
                st.code(dbg_raw if dbg_raw else "(empty)", language="text")
 
    if not all_rows:
        st.warning(
            "No questions extracted. Check the PDF is readable, "
            "language selection matches the paper, and API key is valid."
        )
        st.stop()
 
    df = pd.DataFrame(all_rows)
 
    # ── Revalidation Layer ────────────────────────────────────────────────
    # Uses independently computed expected counts (or_scan + sub_q_count),
    # NOT the other language's count as truth.
    # Fires for both bilingual and single-language extractions.
    # ─────────────────────────────────────────────────────────────────────
    issues_to_fix: list[tuple] = []  # (qtype, lang, actual, expected)
 
    for qtype in question_types:
        exp_map = expected_counts_cache.get(qtype, {})
        if not exp_map:
            continue
        for lang in languages:
            mask   = (df["Question_Type"] == qtype) & (df["Language"] == lang)
            actual = int(mask.sum())
            exp    = exp_map.get(lang)
            if exp is not None and actual < exp:
                issues_to_fix.append((qtype, lang, actual, exp))
 
    if not issues_to_fix:
        st.success("✅ Extraction complete — all counts meet expected minimums.")
    else:
        review_label = (
            f"Revalidation needed — {len(issues_to_fix)} "
            f"type/language combination(s) under-extracted"
        )
        st.info(review_label)
        reval_progress    = st.progress(0)
        reval_status      = st.empty()
        revalidation_log: list[tuple] = []
 
        for ri, (qtype, lang_to_fix, actual, expected) in enumerate(issues_to_fix):
            other_lang = "English" if lang_to_fix == "Hindi" else "Hindi"
            reval_status.markdown(
                f"Re-validating **{qtype}** ({lang_to_fix}) — "
                f"got {actual}, need ≥{expected}…"
            )
 
            new_rows, new_or_scan = revalidate_mismatched_category(
                client=client,
                file_id=file_id,
                question_type=qtype,
                language_to_fix=lang_to_fix,
                other_language=other_lang,
                expected_count=expected,
                actual_count=actual,
                exam_type=exam_type,
                class_name=class_name,
                subject=subject,
                year=year,
                q_nums=q_nums_cache.get(qtype),
                marks_each=marks_each_cache.get(qtype),
            )
 
            new_count = len(new_rows)
 
            # If new extraction returned an or_scan, update expected
            if new_or_scan and qtype in OR_TYPES:
                new_min = new_or_scan.get("min_expected_rows")
                if new_min:
                    expected = int(new_min)
 
            if new_count >= expected:
                drop_mask = (
                    (df["Question_Type"] == qtype) &
                    (df["Language"] == lang_to_fix)
                )
                df = df[~drop_mask]
                df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
                revalidation_log.append(("ok",
                    f"{qtype} ({lang_to_fix}): {actual} → {new_count} ✓ (needed ≥{expected})"
                ))
                ph = type_status_placeholders.get(qtype)
                if ph and do_bilingual:
                    h_c = int(((df["Question_Type"] == qtype) & (df["Language"] == "Hindi")).sum())
                    e_c = int(((df["Question_Type"] == qtype) & (df["Language"] == "English")).sum())
                    ph.markdown(f"✅ Hindi: **{h_c}** | English: **{e_c}** — fixed by revalidation")
 
            elif new_count > actual:
                # Partial improvement — take it, it's better than what we had
                drop_mask = (
                    (df["Question_Type"] == qtype) &
                    (df["Language"] == lang_to_fix)
                )
                df = df[~drop_mask]
                df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
                revalidation_log.append(("warn",
                    f"{qtype} ({lang_to_fix}): {actual} → {new_count} "
                    f"(partial improvement, still below {expected})"
                ))
            else:
                revalidation_log.append(("error",
                    f"{qtype} ({lang_to_fix}): re-extraction got {new_count} — "
                    f"no improvement over {actual}, keeping original"
                ))
 
            reval_progress.progress((ri + 1) / len(issues_to_fix))
 
        reval_status.empty()
        reval_progress.empty()
 
        with st.expander(
            f"Re-validation Results ({len(issues_to_fix)} attempt(s))",
            expanded=True,
        ):
            for level, msg in revalidation_log:
                if level == "ok":     st.success(msg)
                elif level == "warn": st.warning(msg)
                else:                 st.error(msg)
 
    # Clean up uploaded file
    try:
        client.files.delete(file_id)
    except Exception:
        pass

    # ── Cross-type deduplication ──────────────────────────────────────────
    # Removes questions that leaked across type boundaries (e.g. Q13 extracted
    # by both Short Answer and Long Answer prompts).  Must run AFTER revalidation
    # so it doesn't interfere with count-based re-extraction logic.
    df, dedup_warnings = _deduplicate_cross_type(df)
    if dedup_warnings:
        with st.expander(
            f"⚠️ Range-overlap duplicates removed ({len(dedup_warnings)})",
            expanded=False,
        ):
            for w in dedup_warnings:
                st.warning(w)

    # ── Phase 3: Chapter mapping ──────────────────────────────────────────
    if chapters:
        chapter_progress = st.progress(0)
        chapter_status   = st.empty()
        qtypes_list      = df["Question_Type"].unique().tolist()

        if "Chapter_Number" not in df.columns:
            df["Chapter_Number"] = 0
            df["Chapter_Name"]   = "Unknown"

        for ci, qtype in enumerate(qtypes_list):
            chapter_status.markdown(
                f"Mapping chapters — **{qtype}** ({ci + 1}/{len(qtypes_list)})"
            )
            chapter_progress.progress((ci + 1) / len(qtypes_list))
            type_mask = df["Question_Type"] == qtype
            eng_idx   = df.index[type_mask & (df["Language"] == "English")].tolist()
            hin_idx   = df.index[type_mask & (df["Language"] == "Hindi")].tolist()

            # Run Hindi and English mapping calls in parallel — each language
            # uses its OWN question text with a language-aware prompt.
            futures_map: dict = {}
            with ThreadPoolExecutor(max_workers=2) as ch_executor:
                if eng_idx:
                    futures_map["English"] = ch_executor.submit(
                        assign_chapters,
                        client,
                        df.loc[eng_idx, "Question"].tolist(),
                        chapters,
                        "English",
                    )
                if hin_idx:
                    futures_map["Hindi"] = ch_executor.submit(
                        assign_chapters,
                        client,
                        df.loc[hin_idx, "Question"].tolist(),
                        chapters,
                        "Hindi",
                    )

            if "English" in futures_map:
                assignments = futures_map["English"].result()
                for i, idx in enumerate(eng_idx):
                    df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                    df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]

            if "Hindi" in futures_map:
                assignments = futures_map["Hindi"].result()
                for i, idx in enumerate(hin_idx):
                    df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                    df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]

        chapter_status.empty()
        chapter_progress.empty()
        st.success(f"Chapter mapping done — {df['Chapter_Name'].nunique()} chapters identified.")
    else:
        df["Chapter_Number"] = 0
        df["Chapter_Name"]   = "Unknown"
 
    # Reorder columns
    col_order = [
        "Exam_Type", "Class", "Language", "Subject",
        "Chapter_Number", "Chapter_Name",
        "Question", "Question_Type", "Marks", "Year",
    ]
    df = df[[c for c in col_order if c in df.columns]]
 
    # Summary
    st.subheader(f"Extracted {len(df)} Questions")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Questions", len(df))
    c2.metric("Question Types",  df["Question_Type"].nunique())
    c3.metric("Languages",       df["Language"].nunique())
    c4.metric("Total Marks",     int(df["Marks"].sum()))
 
    st.markdown("**Breakdown by Question Type**")
    breakdown = (
        df.groupby(["Question_Type", "Language"])
        .agg(Count=("Question", "count"), Marks=("Marks", "first"))
        .reset_index()
    )
    st.dataframe(breakdown, use_container_width=True, hide_index=True)
 
    st.markdown("---")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sel_type = st.multiselect(
            "Filter by Question Type",
            df["Question_Type"].unique().tolist(),
            default=df["Question_Type"].unique().tolist(),
        )
    with col_f2:
        sel_lang = st.multiselect(
            "Filter by Language",
            df["Language"].unique().tolist(),
            default=df["Language"].unique().tolist(),
        )
 
    filtered = df[
        df["Question_Type"].isin(sel_type) & df["Language"].isin(sel_lang)
    ]
    st.dataframe(filtered, use_container_width=True, hide_index=True)
 
    excel_bytes = build_excel(df)
    file_name   = (
        f"questions_{exam_type.replace(' ', '_')}"
        f"_Class{class_name.replace(' ', '')}"
        f"_{subject.replace(' ', '_')}"
        f"_{year}.xlsx"
    )
    st.download_button(
        label="Download Excel",
        data=excel_bytes,
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    st.caption(
        "Excel contains: All Questions · one sheet per question type · "
        "Hindi Questions · English Questions · Chapter Summary"
    )