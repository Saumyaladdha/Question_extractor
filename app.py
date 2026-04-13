"""
Question Paper Extractor
- Uploads a PDF exam paper to OpenAI Files API
- Extracts each question type using gpt-5.4-mini with targeted prompts
- Exports structured Excel with:
    • One "All Questions" sheet
    • One sheet per question type
    • Separate "Hindi Questions" and "English Questions" sheets
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
 
load_dotenv()  # reads OPENAI_API_KEY from .env if present
 
from prompts import MARKS, PROMPTS, chapter_mapping_prompt, extract_structure_prompt
 
# ──────────────────────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Question Paper Extractor",
    page_icon="📄",
    layout="wide",
)
 
# ──────────────────────────────────────────────────────────────────────────────
# Short Answer Logger  (session-state based, thread-safe append)
# ──────────────────────────────────────────────────────────────────────────────
SHORT_ANSWER_TYPES = {"Short Answer", "Very Short Answer"}  # adjust if your PROMPTS keys differ
 
def _sa_log(msg: str):
    """Append a log line to the Short Answer audit log in session state."""
    if "sa_logs" not in st.session_state:
        st.session_state["sa_logs"] = []
    st.session_state["sa_logs"].append(msg)
 
def _clear_sa_logs():
    st.session_state["sa_logs"] = []
 
# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
 
def _fix_latex_backslashes(s: str) -> str:
    r"""
    The model outputs LaTeX like \frac, \alpha, \vec inside JSON strings.
    These are invalid JSON escape sequences and cause JSONDecodeError.
    Fix: double any backslash that is NOT a valid JSON escape character.
    Valid JSON escapes after backslash: " \ / b f n r t u
    Everything else (LaTeX commands) needs to become \\ before json.loads().
    """
    return re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)
 
 
def parse_json_response(raw: str, log_label: str = "") -> list[dict]:
    """
    Robustly extract a JSON object/array from model output.
    Handles markdown code fences, plain JSON, and LaTeX backslashes.
 
    Strategy: try parsing as-is first (model often outputs valid JSON with
    properly escaped backslashes like \\Omega). Only apply the LaTeX backslash
    fix if the first attempt fails — applying the fix to already-valid JSON
    would corrupt properly escaped sequences (\\Omega -> \\\\Omega -> invalid).
    """
    # Strip markdown fences
    clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
 
    is_sa = bool(log_label)  # log_label is set only for Short Answer types
 
    def _try_parse(s: str):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            if is_sa:
                _sa_log(f"  JSONDecodeError: {e}")
            return None
 
    def _unwrap(data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("questions", "items", "results", "data"):
                if key in data and isinstance(data[key], list):
                    if is_sa:
                        _sa_log(f"  Unwrapped from key='{key}', count={len(data[key])}")
                    return data[key]
            for v in data.values():
                if isinstance(v, list):
                    if is_sa:
                        _sa_log(f"  Unwrapped from unknown key, count={len(v)}")
                    return v
        return None
 
    if is_sa:
        _sa_log(f"\n--- parse_json_response [{log_label}] ---")
        _sa_log(f"  Raw length: {len(raw)} chars")
        _sa_log(f"  Cleaned snippet (first 300 chars): {clean[:300]}")
 
    # Pass 1: parse as-is
    if is_sa:
        _sa_log("  Pass 1: parsing as-is...")
    data = _try_parse(clean)
    if data is not None:
        result = _unwrap(data)
        if result is not None:
            if is_sa:
                _sa_log(f"  Pass 1 SUCCESS → {len(result)} items")
            return result
 
    # Pass 2: fix single-backslash LaTeX sequences then parse
    if is_sa:
        _sa_log("  Pass 2: fixing LaTeX backslashes...")
    fixed = _fix_latex_backslashes(clean)
    data = _try_parse(fixed)
    if data is not None:
        result = _unwrap(data)
        if result is not None:
            if is_sa:
                _sa_log(f"  Pass 2 SUCCESS → {len(result)} items")
            return result
 
    # Pass 3: regex-extract the first JSON block, try both strategies
    if is_sa:
        _sa_log("  Pass 3: regex extraction...")
    for candidate in (clean, fixed):
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", candidate)
        if match:
            block = match.group(1)
            for attempt in (block, _fix_latex_backslashes(block)):
                data = _try_parse(attempt)
                if data is not None:
                    result = _unwrap(data)
                    if result is not None:
                        if is_sa:
                            _sa_log(f"  Pass 3 SUCCESS → {len(result)} items")
                        return result
 
    if is_sa:
        _sa_log("  ALL PASSES FAILED → returning []")
    return []
 
 
def _merge_duplicate_keys(pairs: list) -> dict:
    """
    object_pairs_hook for json.loads — merges duplicate type keys.
 
    Special rule for Long Answer / Very Long Answer:
      - "Long Answer" always means 4-mark questions.
      - "Very Long Answer" always means 5/6-mark questions.
      - If the model emits duplicate keys for either, merge their question_numbers
        within the same type (do NOT cross-merge between the two types).
      - marks_each is taken from whichever sub-group has more questions.
    """
    result: dict = {}
    for key, value in pairs:
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            existing = result[key]
            existing_nums: list = existing.get("question_numbers") or []
            new_nums: list = value.get("question_numbers") or []
            merged = sorted(set(existing_nums + new_nums))
            # keep marks_each of the group with more questions
            if len(new_nums) > len(existing_nums):
                marks_each = value.get("marks_each")
            else:
                marks_each = existing.get("marks_each")
            result[key] = {"question_numbers": merged, "marks_each": marks_each}
        else:
            result[key] = value
    return result
 
 
def get_paper_structure(client: OpenAI, file_id: str) -> dict:
    """
    Phase 1: Ask gpt-5.4-mini to read the instruction block at the top of the
    paper and return a mapping of question type → question numbers + marks.
    Returns {} on failure (Phase 2 prompts then fall back to header-based detection).
    """
    try:
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "file", "file": {"file_id": file_id}},
                        {"type": "text", "text": extract_structure_prompt()},
                    ],
                }
            ],
        )
        raw = response.choices[0].message.content or ""
        # parse top-level dict — merge_duplicate_keys handles repeated type keys
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data = json.loads(clean, object_pairs_hook=_merge_duplicate_keys)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}
 
 
def upload_pdf(client: OpenAI, pdf_bytes: bytes) -> str:
    """Upload PDF bytes to OpenAI Files API and return file_id."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as fh:
            file_obj = client.files.create(file=fh, purpose="user_data")
        return file_obj.id
    finally:
        os.unlink(tmp_path)
 
 
def extract_one_type(
    client: OpenAI,
    file_id: str,
    question_type: str,
    language: str,
    exam_type: str,
    class_name: str,
    subject: str,
    year: str,
    q_nums: list[int] | None = None,    # from Phase 1 structure
    marks_each: int | None = None,      # from Phase 1 structure (overrides MARKS dict)
    _warnings: list | None = None,      # thread-safe warning collection (avoids st.warning in threads)
    _debug: list | None = None,         # captures (type, lang, raw) tuples when 0 rows returned
) -> list[dict]:
    """Call gpt-5.4-mini for one question type and return list of row dicts."""
    is_sa = question_type in SHORT_ANSWER_TYPES
    prompt_fn = PROMPTS[question_type]
    prompt_text = prompt_fn(language, q_nums)
 
    # ── Log: Short Answer prompt details ──────────────────────────────────────
    if is_sa:
        _sa_log(f"\n{'='*60}")
        _sa_log(f"EXTRACT: {question_type} | Language: {language}")
        _sa_log(f"  q_nums from Phase 1: {q_nums}")
        _sa_log(f"  marks_each from Phase 1: {marks_each}")
        _sa_log(f"  Prompt length: {len(prompt_text)} chars")
        _sa_log(f"  Prompt (first 600 chars):\n{prompt_text[:600]}")
 
    try:
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "file",
                            "file": {"file_id": file_id},
                        },
                        {
                            "type": "text",
                            "text": prompt_text,
                        },
                    ],
                }
            ],
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        msg = f"API error for {question_type} ({language}): {exc}"
        if is_sa:
            _sa_log(f"  API ERROR: {exc}")
        if _warnings is not None:
            _warnings.append(msg)
        else:
            st.warning(msg)
        return []
 
    # ── Log: Short Answer raw response ────────────────────────────────────────
    if is_sa:
        _sa_log(f"\n  RAW RESPONSE ({len(raw)} chars):")
        _sa_log(f"  First 800 chars:\n{raw[:800]}")
        if len(raw) > 800:
            _sa_log(f"  ... [truncated, total={len(raw)} chars] ...")
            _sa_log(f"  Last 200 chars:\n{raw[-200:]}")
 
    log_label = f"{question_type} | {language}" if is_sa else ""
    questions = parse_json_response(raw, log_label=log_label)
 
    if not questions and _debug is not None:
        _debug.append((question_type, language, prompt_text, raw))  # full prompt + full raw
 
    rows = []
    for q in questions:
        text = q.get("question") or q.get("text") or q.get("q") or ""
        text = text.strip()
        if not text:
            if is_sa:
                _sa_log(f"  SKIP empty text for item: {q}")
            continue
 
        # Marks priority:
        # 1. Match the Following → dynamic from model response (Column A count)
        # 2. marks_each from Phase 1 structure (e.g. Long Answer=4, Very Long Answer=5/6)
        # 3. Fallback to MARKS dict default
        if question_type == "Match the Following":
            marks = q.get("marks") or q.get("mark") or q.get("score")
            try:
                marks = int(marks)
            except (TypeError, ValueError):
                marks = 0
        elif marks_each is not None:
            marks = marks_each          # from Phase 1 instructions (authoritative)
        else:
            marks = MARKS[question_type]
 
        rows.append(
            {
                "Exam_Type": exam_type,
                "Class": class_name,
                "Language": language,
                "Subject": subject,
                "Question": text,
                "Question_Type": question_type,
                "Marks": marks,
                "Year": year,
            }
        )
 
    # ── Log: Short Answer final row count ─────────────────────────────────────
    if is_sa:
        _sa_log(f"\n  PARSED {len(questions)} items from JSON → {len(rows)} valid rows after filtering")
        if rows:
            _sa_log("  First 3 extracted questions:")
            for i, r in enumerate(rows[:3]):
                _sa_log(f"    [{i+1}] {r['Question'][:120]}")
        else:
            _sa_log("  ⚠️  ZERO ROWS — all items were either empty or unparseable")
 
    return rows
 
 
def build_excel(df: pd.DataFrame) -> bytes:
    """
    Build Excel workbook with:
      - All Questions sheet
      - One sheet per question type
      - Hindi Questions sheet
      - English Questions sheet
      - Chapter Summary sheet (if Chapter_Name column present)
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # All questions
        df.to_excel(writer, sheet_name="All Questions", index=False)
 
        # Per question-type sheets
        for qtype in df["Question_Type"].unique():
            sheet_name = qtype[:31]  # Excel sheet name max length
            df[df["Question_Type"] == qtype].to_excel(
                writer, sheet_name=sheet_name, index=False
            )
 
        # Language-specific sheets
        for lang in ["Hindi", "English"]:
            lang_df = df[df["Language"] == lang]
            if not lang_df.empty:
                lang_df.to_excel(
                    writer, sheet_name=f"{lang} Questions", index=False
                )
 
        # Chapter summary sheet
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
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Chapter mapping helpers
# ──────────────────────────────────────────────────────────────────────────────
 
_SUBJECT_ALIASES = {
    "maths": "mathematics",
    "math": "mathematics",
    "bio": "biology",
    "pol science": "political_science",
    "political science": "political_science",
    "business studies": "business_studies",
    "business_studies": "business_studies",
    "pol. science": "political_science",
}
 
def load_chapter_mapping(subject: str) -> list:
    """
    Load chapter list for the given subject from chapter_mapping/<subject>.json.
    Handles two JSON structures:
      1. Top-level "chapters" array (most subjects)
      2. Top-level "books" array, each with a "chapters" sub-array (multi-book subjects
         like Political Science, Geography, Economics, etc.)
         → chapters are flattened; numbers are made sequential; book name is prepended.
    Returns list of {number, name} dicts, or [] if no mapping found.
    """
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chapter_mapping")
    normalized = subject.strip().lower().replace(" ", "_")
    normalized = _SUBJECT_ALIASES.get(normalized, normalized)
    path = os.path.join(base_dir, f"{normalized}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        # Simple flat structure
        if "chapters" in data and isinstance(data["chapters"], list):
            return data["chapters"]
        # Multi-book structure — flatten and make sequential numbers
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
 
 
def assign_chapters(client: OpenAI, questions: list, chapters: list) -> list:
    """
    Call the model once to assign a chapter to each question string.
    Returns list of {chapter_number, chapter_name} dicts (same length as questions).
    Falls back to {chapter_number: 0, chapter_name: "Unknown"} on any error.
    """
    fallback = [{"chapter_number": 0, "chapter_name": "Unknown"}] * len(questions)
    if not questions or not chapters:
        return fallback
    try:
        prompt_text = chapter_mapping_prompt(questions, chapters)
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            temperature=0,
            messages=[{"role": "user", "content": prompt_text}],
        )
        raw = response.choices[0].message.content or ""
        items = parse_json_response(raw)
        result = []
        for item in items:
            try:
                result.append({
                    "chapter_number": int(item.get("chapter_number", 0)),
                    "chapter_name": str(item.get("chapter_name", "Unknown")),
                })
            except (TypeError, ValueError):
                result.append({"chapter_number": 0, "chapter_name": "Unknown"})
        # Pad or trim to exactly len(questions)
        while len(result) < len(questions):
            result.append({"chapter_number": 0, "chapter_name": "Unknown"})
        return result[: len(questions)]
    except Exception as exc:
        st.warning(f"Chapter mapping error: {exc}")
        return fallback
 
 
def assign_chapters_to_df(client: OpenAI, df: pd.DataFrame, chapters: list) -> pd.DataFrame:
    """
    Phase 3: for each question_type, map English questions → chapters,
    then mirror the same chapter to Hindi questions at the same position.
    If only Hindi questions exist for a type, map them directly.
    Adds Chapter_Number and Chapter_Name columns to df.
    """
    df = df.copy()
    df["Chapter_Number"] = 0
    df["Chapter_Name"] = "Unknown"
 
    for qtype in df["Question_Type"].unique():
        type_mask = df["Question_Type"] == qtype
        eng_mask  = type_mask & (df["Language"] == "English")
        hin_mask  = type_mask & (df["Language"] == "Hindi")
 
        eng_idx = df.index[eng_mask].tolist()
        hin_idx = df.index[hin_mask].tolist()
 
        if eng_idx:
            assignments = assign_chapters(client, df.loc[eng_idx, "Question"].tolist(), chapters)
            for i, idx in enumerate(eng_idx):
                df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]
            for i, idx in enumerate(hin_idx):
                if i < len(assignments):
                    df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                    df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]
        elif hin_idx:
            assignments = assign_chapters(client, df.loc[hin_idx, "Question"].tolist(), chapters)
            for i, idx in enumerate(hin_idx):
                df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]
 
    return df
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Extraction validator
# ──────────────────────────────────────────────────────────────────────────────
 
def _extraction_validator(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    Compare Hindi vs English question counts per type.
    Returns a DataFrame with Status and Likely Cause columns, or None if
    fewer than 2 languages are present.
    """
    if df["Language"].nunique() < 2:
        return None
 
    counts = (
        df.groupby(["Question_Type", "Language"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
 
    h = counts.get("Hindi",   pd.Series(0, index=counts.index))
    e = counts.get("English", pd.Series(0, index=counts.index))
    counts["Diff"] = (h - e).abs()
 
    def _status(diff: int) -> str:
        if diff == 0:
            return "✅ OK"
        if diff == 1:
            return "⚠️ Minor"
        return "❌ Review"
 
    def _cause(row) -> str:
        h_val = int(row.get("Hindi",   0))
        e_val = int(row.get("English", 0))
        diff  = abs(h_val - e_val)
        if diff == 0:
            return "—"
        if h_val == 0:
            return "Type absent from Hindi — not found in Hindi section"
        if e_val == 0:
            return "Type absent from English — boundary issue or not in English section"
        if diff == 1:
            return "One OR/अथवा alternative may be missing in one language"
        return "Section boundary or OCR issue — re-run or check PDF manually"
 
    counts["Status"]       = counts["Diff"].apply(_status)
    counts["Likely Cause"] = counts.apply(_cause, axis=1)
    return counts
 
 
# ──────────────────────────────────────────────────────────────────────────────
# Sidebar — configuration
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Configuration")
    # API key: read silently from .env — never shown in the UI
    _env_key = os.environ.get("OPENAI_API_KEY", "")
    if _env_key:
        st.success("API key loaded from .env")
        api_key = _env_key
    else:
        api_key = st.text_input(
            "OpenAI API Key", type="password", placeholder="sk-..."
        )
 
    st.divider()
    st.subheader("Paper Details")
 
    exam_type = st.text_input("Exam Type", placeholder="e.g., MP Board, CBSE")
    class_name = st.text_input("Class", placeholder="e.g., 12, Class 10")
    subject = st.text_input("Subject", placeholder="e.g., Physics, Chemistry")
    year = st.text_input("Year", placeholder="e.g., 2025")
    language = st.selectbox(
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
 
# ──────────────────────────────────────────────────────────────────────────────
# Main area
# ──────────────────────────────────────────────────────────────────────────────
st.title("Question Paper Extractor")
st.markdown(
    "Upload an exam paper PDF. The app uses **gpt-5.4-mini** to extract every "
    "question type separately and downloads them as a structured Excel sheet."
)
 
uploaded_file = st.file_uploader(
    "Upload Question Paper PDF", type=["pdf"], label_visibility="visible"
)
 
if uploaded_file:
    st.info(
        f"Uploaded: **{uploaded_file.name}** "
        f"({uploaded_file.size / 1024:.1f} KB)"
    )
 
extract_btn = st.button("Extract Questions", type="primary", disabled=not uploaded_file)
 
if extract_btn:
    _clear_sa_logs()  # reset Short Answer logs for this run
 
    # ── Validation ────────────────────────────────────────────────────────────
    errors = []
    if not api_key:
        errors.append("OpenAI API Key is required.")
    if not exam_type:
        errors.append("Exam Type is required.")
    if not class_name:
        errors.append("Class is required.")
    if not subject:
        errors.append("Subject is required.")
    if not year:
        errors.append("Year is required.")
    if errors:
        for e in errors:
            st.error(e)
        st.stop()
 
    client = OpenAI(api_key=api_key)
    languages = (
        ["Hindi", "English"]
        if language == "Both (Hindi + English)"
        else [language]
    )
    question_types = list(PROMPTS.keys())
 
    # ── Load chapter mapping ──────────────────────────────────────────────────
    chapters = load_chapter_mapping(subject)
    if chapters:
        st.info(f"Chapter mapping loaded for **{subject}** — {len(chapters)} chapters.")
    else:
        st.warning(f"No chapter mapping found for '{subject}' — Chapter columns will be blank.")
 
    # ── Upload PDF ────────────────────────────────────────────────────────────
    with st.spinner("Uploading PDF to OpenAI Files API..."):
        try:
            file_id = upload_pdf(client, uploaded_file.read())
        except Exception as exc:
            st.error(f"Failed to upload PDF: {exc}")
            st.stop()
    st.success(f"PDF uploaded (file_id: `{file_id}`)")
 
    # ── Phase 1: Read paper structure (question number map) ───────────────────
    structure: dict = {}
    with st.spinner("Reading paper structure (question number map)..."):
        structure = get_paper_structure(client, file_id)
 
    if structure:
        st.info(
            "Paper structure detected: "
            + " | ".join(
                f"{k}: Q{structure[k]['question_numbers']}"
                for k in structure
                if isinstance(structure[k], dict) and structure[k].get("question_numbers")
            )
        )
        # ── Short Answer specific: log Phase 1 structure for SA types ─────────
        for sa_type in SHORT_ANSWER_TYPES:
            if sa_type in structure:
                _sa_log(f"Phase 1 structure for '{sa_type}': {structure[sa_type]}")
            else:
                _sa_log(f"Phase 1: '{sa_type}' NOT found in structure — will be skipped")
    else:
        st.warning("Could not detect paper structure — using section-header fallback.")
        _sa_log("Phase 1 FAILED — structure is empty, using fallback for all types")
 
    # ── Phase 2: Extract all (type × language) combinations in parallel ─────────
    all_rows: list[dict]      = []
    extraction_warnings: list[str] = []
    extraction_debug: list[tuple]  = []  # (type, lang, raw) for 0-row results
 
    # Build task list
    extraction_tasks: list[tuple] = []
    for qtype in question_types:
        type_info  = structure.get(qtype, {})
        q_nums     = type_info.get("question_numbers") if isinstance(type_info, dict) else None
        marks_each = type_info.get("marks_each")       if isinstance(type_info, dict) else None
        try:
            marks_each = int(marks_each) if marks_each is not None else None
        except (TypeError, ValueError):
            marks_each = None
        # Skip types absent from Phase 1 structure
        if structure and qtype not in structure:
            if qtype in SHORT_ANSWER_TYPES:
                _sa_log(f"SKIPPING '{qtype}' — not in Phase 1 structure")
            continue
        for lang in languages:
            extraction_tasks.append((qtype, lang, q_nums, marks_each))
 
    _sa_log(f"\nTotal extraction tasks: {len(extraction_tasks)}")
    _sa_log(f"SA tasks: {[(t[0], t[1]) for t in extraction_tasks if t[0] in SHORT_ANSWER_TYPES]}")
 
    total_steps = len(extraction_tasks)
    completed_count = 0
    progress_bar = st.progress(0)
    status_text   = st.empty()
    status_text.markdown(
        f"Running **{total_steps}** extraction tasks in parallel "
        f"({len(languages)} language(s) × {len(extraction_tasks) // max(len(languages), 1)} type(s))…"
    )
 
    def _run_one(task: tuple) -> tuple:
        qtype, lang, q_nums, marks_each = task
        rows = extract_one_type(
            client, file_id, qtype, lang,
            exam_type, class_name, subject, year,
            q_nums=q_nums, marks_each=marks_each,
            _warnings=extraction_warnings,
            _debug=extraction_debug,
        )
        return qtype, lang, rows
 
    with ThreadPoolExecutor(max_workers=min(total_steps, 6)) as executor:
        future_map = {executor.submit(_run_one, task): task for task in extraction_tasks}
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                qtype, lang, rows = future.result()
            except Exception as exc:
                qtype, lang = task[0], task[1]
                extraction_warnings.append(f"Task failed — {qtype} ({lang}): {exc}")
                if qtype in SHORT_ANSWER_TYPES:
                    _sa_log(f"EXCEPTION in thread for '{qtype}' ({lang}): {exc}")
                rows = []
            all_rows.extend(rows)
            completed_count += 1
            progress_bar.progress(completed_count / total_steps)
            status_text.markdown(
                f"**{completed_count}/{total_steps}** done — "
                f"last: **{qtype}** ({lang}) → {len(rows)} question(s)"
            )
 
    status_text.empty()
    progress_bar.empty()
 
    # Surface any API errors collected from worker threads
    for w in extraction_warnings:
        st.warning(w)
 
    # ── Short Answer Audit Log ─────────────────────────────────────────────────
    sa_logs = st.session_state.get("sa_logs", [])
    if sa_logs:
        sa_types_found = [
            t for t in SHORT_ANSWER_TYPES
            if any(t in line for line in sa_logs)
        ]
        # Count how many SA rows ended up in all_rows
        sa_row_counts = {}
        for r in all_rows:
            if r["Question_Type"] in SHORT_ANSWER_TYPES:
                key = f"{r['Question_Type']} | {r['Language']}"
                sa_row_counts[key] = sa_row_counts.get(key, 0) + 1
 
        label_parts = [f"{k}: {v}" for k, v in sa_row_counts.items()] if sa_row_counts else ["0 rows extracted"]
        expander_label = "🔍 Short Answer Debug Log — " + " | ".join(label_parts)
 
        with st.expander(expander_label, expanded=(not sa_row_counts)):
            st.markdown("**Short Answer / Very Short Answer extraction trace:**")
            st.code("\n".join(sa_logs), language="text")
            st.markdown("---")
            st.markdown("**Final SA row counts:**")
            if sa_row_counts:
                for k, v in sa_row_counts.items():
                    st.markdown(f"- `{k}` → **{v}** questions")
            else:
                st.error("No Short Answer rows were extracted at all.")
 
    # ── Debug: show prompt + raw model output for any type that returned 0 rows ─
    if extraction_debug:
        with st.expander(
            f"🔍 Debug — {len(extraction_debug)} extraction(s) returned 0 rows",
            expanded=True,
        ):
            for dbg_type, dbg_lang, dbg_prompt, dbg_raw in extraction_debug:
                st.markdown(f"---\n### {dbg_type} ({dbg_lang})")
                with st.expander("Prompt sent to model", expanded=False):
                    st.code(dbg_prompt, language="text")
                st.markdown("**Raw model response:**")
                st.code(dbg_raw if dbg_raw else "(empty — model returned nothing)", language="text")
 
    # ── Clean up uploaded file ────────────────────────────────────────────────
    try:
        client.files.delete(file_id)
    except Exception:
        pass
 
    # ── Results ───────────────────────────────────────────────────────────────
    if not all_rows:
        st.warning(
            "No questions were extracted. Check that the PDF is readable, "
            "the language selection matches the paper, and your API key is valid."
        )
        st.stop()
 
    df = pd.DataFrame(all_rows)
 
    # ── Extraction validator ──────────────────────────────────────────────────
    if len(languages) == 2:
        val_df = _extraction_validator(df)
        if val_df is not None:
            issues = val_df[val_df["Diff"] > 0]
            if issues.empty:
                st.success("✅ Extraction complete — Hindi and English counts match for all types.")
            else:
                review_count = len(val_df[val_df["Status"] == "❌ Review"])
                minor_count  = len(val_df[val_df["Status"] == "⚠️ Minor"])
                label = (
                    f"⚠️ Extraction Validator — "
                    f"{review_count} type(s) need review, {minor_count} minor diff(s)"
                )
                with st.expander(label, expanded=(review_count > 0)):
                    st.dataframe(val_df, use_container_width=True, hide_index=True)
                    if review_count > 0:
                        st.warning(
                            "❌ types above likely have missing questions in one language. "
                            "Common causes: section boundary issue (English section not reached) "
                            "or OCR miss. Check the PDF and re-run if needed."
                        )
 
    # ── Phase 3: Chapter mapping ──────────────────────────────────────────────
    if chapters:
        chapter_progress = st.progress(0)
        chapter_status   = st.empty()
        qtypes_list = df["Question_Type"].unique().tolist()
        for ci, qtype in enumerate(qtypes_list):
            chapter_status.markdown(f"Mapping chapters — **{qtype}** ({ci + 1}/{len(qtypes_list)})")
            chapter_progress.progress((ci + 1) / len(qtypes_list))
            type_mask = df["Question_Type"] == qtype
            eng_idx   = df.index[type_mask & (df["Language"] == "English")].tolist()
            hin_idx   = df.index[type_mask & (df["Language"] == "Hindi")].tolist()
 
            if "Chapter_Number" not in df.columns:
                df["Chapter_Number"] = 0
                df["Chapter_Name"]   = "Unknown"
 
            if eng_idx:
                assignments = assign_chapters(client, df.loc[eng_idx, "Question"].tolist(), chapters)
                for i, idx in enumerate(eng_idx):
                    df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                    df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]
                for i, idx in enumerate(hin_idx):
                    if i < len(assignments):
                        df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                        df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]
            elif hin_idx:
                assignments = assign_chapters(client, df.loc[hin_idx, "Question"].tolist(), chapters)
                for i, idx in enumerate(hin_idx):
                    df.at[idx, "Chapter_Number"] = assignments[i]["chapter_number"]
                    df.at[idx, "Chapter_Name"]   = assignments[i]["chapter_name"]
        chapter_status.empty()
        chapter_progress.empty()
        st.success(f"Chapter mapping done — {df['Chapter_Name'].nunique()} chapters identified.")
    else:
        df["Chapter_Number"] = 0
        df["Chapter_Name"]   = "Unknown"
 
    # Reorder columns for a clean Excel layout
    col_order = [
        "Exam_Type", "Class", "Language", "Subject",
        "Chapter_Number", "Chapter_Name",
        "Question", "Question_Type", "Marks", "Year",
    ]
    df = df[[c for c in col_order if c in df.columns]]
 
    # Summary metrics
    st.subheader(f"Extracted {len(df)} Questions")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Questions", len(df))
    c2.metric("Question Types", df["Question_Type"].nunique())
    c3.metric("Languages", df["Language"].nunique())
    c4.metric("Total Marks", int(df["Marks"].sum()))
 
    # Per-type breakdown
    st.markdown("**Breakdown by Question Type**")
    breakdown = (
        df.groupby(["Question_Type", "Language"])
        .agg(Count=("Question", "count"), Marks=("Marks", "first"))
        .reset_index()
    )
    st.dataframe(breakdown, use_container_width=True, hide_index=True)
 
    # Filters
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
 
    # ── Download ──────────────────────────────────────────────────────────────
    excel_bytes = build_excel(df)
    file_name = (
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
        "Excel contains: All Questions · one sheet per question type "
        "(MCQ, Fill Blanks, True/False, One Word, Very Short, Short, Long, Very Long, Match) · "
        "Hindi Questions · English Questions · Chapter Summary"
    )
 