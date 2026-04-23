"""
Extraction prompts for each question type.
 
Two-phase approach:
  Phase 1 — extract_structure_prompt(): reads the instruction block at the top of
             the paper and returns a JSON map of question numbers per type.
  Phase 2 — one prompt per question type, targeting EXACT question numbers.
"""
 
# ─────────────────────────────────────────────────────────────────────────────
# MARKS TABLE
# ─────────────────────────────────────────────────────────────────────────────
MARKS = {
    "Multiple Choice Question": 1,
    "Fill in the Blanks":       1,
    "True and False":           1,
    "One Word Answer":          1,
    "Very Short Answer":        2,
    "Short Answer":             3,
    "Long Answer":              4,
    "Very Long Answer":         5,
    "Match the Following":      None,
}
 
 
# ─────────────────────────────────────────────────────────────────────────────
# LATEX FORMATTING
# ─────────────────────────────────────────────────────────────────────────────
LATEX_INSTRUCTION = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY PRE-STEP — TABLE DETECTION (do this BEFORE building JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scan every question for any multi-column tabular data:
  • Balance Sheet / आर्थिक चिट्ठा
  • Trading / Profit & Loss / Income & Expenditure Account
  • Receipts & Payments / Trial Balance / Comparative Statement
  • Any table with two or more columns of financial or scientific data

If a table is present it MUST be embedded in the "question" string as a
LaTeX tabular environment. Outputting a table as plain prose text is WRONG.

EXACT FORMAT to use (copy the structure, fill in the actual data):
  \\\\begin{tabular}{|l|r|l|r|}
  \\\\hline
  \\\\multicolumn{4}{|c|}{\\\\textbf{BALANCE SHEET}} \\\\\\\\
  \\\\hline
  \\\\textbf{Liabilities} & \\\\textbf{₹} & \\\\textbf{Assets} & \\\\textbf{₹} \\\\\\\\
  \\\\hline
  Creditors & 60,000 & Cash & 36,000 \\\\\\\\
  \\\\hline
  General Reserve & 10,000 & Debtors \\\\quad 46,000 & \\\\\\\\
  \\\\hline
   & & (--) PBD \\\\quad \\\\underline{2,000} & 44,000 \\\\\\\\
  \\\\hline
   & \\\\textbf{1,60,000} & & \\\\textbf{1,60,000} \\\\\\\\
  \\\\hline
  \\\\end{tabular}

Quick reference:
  Column spec      : l=left-align  r=right-align  c=center  | = vertical border
  Row end          : \\\\\\\\ (FOUR backslashes in JSON → two backslashes = LaTeX row-end)
  Cell separator   : & (plain ampersand, no escaping needed)
  Horizontal line  : \\\\hline
  Merged cell      : \\\\multicolumn{n}{|c|}{content}
  Bold header      : \\\\textbf{text}
  Underlined total : \\\\underline{value}
  Indent / gap     : \\\\quad
  Line break in cell: \\\\newline
  ₹ symbol         : keep as plain ₹ (no LaTeX wrapper needed)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATH / FORMULA FORMATTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Wrap ALL mathematical expressions and formulas in $...$ (inline math).
- Use $$...$$ only for standalone display equations on their own line.
- Common conversions:
    Superscripts  : x²→$x^{2}$  10⁸→$10^{8}$  e⁻→$e^{-}$
    Subscripts    : H₂O→$H_{2}O$  E₀→$E_{0}$
    Fractions     : 1/2→$\\\\frac{1}{2}$  c/λ→$\\\\frac{c}{\\\\lambda}$
    Greek letters : α→$\\\\alpha$ β→$\\\\beta$ γ→$\\\\gamma$ λ→$\\\\lambda$ μ→$\\\\mu$
                    ε→$\\\\varepsilon$ ω→$\\\\omega$ θ→$\\\\theta$ φ→$\\\\phi$
                    Ω→$\\\\Omega$ Φ→$\\\\Phi$ ρ→$\\\\rho$ σ→$\\\\sigma$
    Operators     : ×→$\\\\times$ ·→$\\\\cdot$ ±→$\\\\pm$ ∝→$\\\\propto$
                    ≈→$\\\\approx$ ≠→$\\\\neq$ ≥→$\\\\geq$ ≤→$\\\\leq$
                    √→$\\\\sqrt{}$ ∞→$\\\\infty$ ∫→$\\\\int$ Σ→$\\\\sum$
    Vectors       : F⃗→$\\\\vec{F}$  E⃗→$\\\\vec{E}$  B⃗→$\\\\vec{B}$
    Units         : Ω→$\\\\Omega$  μF→$\\\\mu F$  μC→$\\\\mu C$
                    μ₀→$\\\\mu_0$  ε₀→$\\\\varepsilon_0$  m/s²→$m/s^{2}$
    Blanks (FIB)  : keep as ______  (never wrap in LaTeX)
- Hindi/English text outside math stays plain — never wrap words in $...$
- Number+unit: wrap symbol only: "9×10⁸ m/s" → $9\\\\times10^{8}$ m/s

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON BACKSLASH RULE — CRITICAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every LaTeX backslash MUST be written as TWO backslashes inside a JSON string.
  CORRECT  →  "\\\\frac{1}{2}"  "\\\\vec{a}"  "\\\\begin{tabular}"  "\\\\hline"
  WRONG    →  "\\frac{1}{2}"   "\\vec{a}"   "\\begin{tabular}"   "\\hline"
LaTeX row-end \\\\ (two backslashes) → write FOUR backslashes in JSON: \\\\\\\\
"""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _q_ref(q_nums: list[int] | None, fallback: str) -> str:
    if q_nums:
        return "Extract ONLY from question number(s): " + ", ".join(f"Q{n}" for n in q_nums) + "."
    return fallback
 
 
def _boundary_instruction(q_nums: list[int] | None, language: str = "Hindi") -> str:
    if not q_nums:
        return ""
    max_q = max(q_nums)
    min_q = min(q_nums)
 
    if language == "Hindi":
        return (
            f"HARD BOUNDARY: Read ONLY question numbers {min_q} through {max_q}. "
            f"— If you see a question number BELOW Q{min_q}, SKIP it — it belongs to a "
            f"different (lower-marks) section. "
            f"— The moment you encounter Q{max_q + 1} or any number ABOVE Q{max_q}, "
            f"STOP immediately — do not extract from it under any circumstance. "
            f"Content outside Q{min_q}–Q{max_q} belongs to a different section."
        )
    else:
        return (
            f"HARD BOUNDARY (English): Extract ONLY question numbers {min_q} through "
            f"{max_q} from the English (Latin-script) section. "
            f"— If you see a question number BELOW Q{min_q}, SKIP it — it belongs to a "
            f"different (lower-marks) section. "
            f"— Once you reach Q{min_q}, extract every question up to and including Q{max_q}. "
            f"— The moment you see Q{max_q + 1} or any number ABOVE Q{max_q}, STOP "
            f"immediately — do not extract from it under any circumstance. "
            f"IMPORTANT: If this is a bilingual paper with a Hindi (Devanagari) section "
            f"on earlier pages, scan PAST the entire Hindi section to reach the English "
            f"section, then apply this range filter to Latin-script questions only."
        )
 
 
def _language_instruction(language: str) -> str:
    if language == "Hindi":
        return """LANGUAGE RULE — HINDI EXTRACTION:

MONOLINGUAL PAPER (Hindi only):
  If this paper contains questions in Hindi (Devanagari) ONLY with no English version
  of each question, simply extract every question. Ignore all bilingual layout rules below.

BILINGUAL PAPER — possible layouts:
  (a) SAME-PAGE INTERLEAVED — both languages appear together on every page.
      Each question appears as a bilingual pair in one of two patterns:
        Pattern A:  [English version]  [Hindi/Devanagari version]
        Pattern B:  [Hindi/Devanagari version]  [English version]
      → Extract ONLY the Devanagari (Hindi) version from each pair.
      → Skip the adjacent Latin/English version — it is the same question.

  (b) SEPARATE SECTIONS — the ENTIRE Hindi section comes first, then the ENTIRE
      English section follows (or vice versa). This is common in board exam papers.
      Layout example:
        [Page 1–6]  ALL questions in Hindi/Devanagari   ← extract from here
        [Page 7–12] ALL questions in English/Latin      ← stop here, skip entirely
      → Read and extract from the Hindi section only.
      → STOP the moment you reach the English section header or the point where
        question text switches entirely to Latin script.
      → Do NOT accidentally extract English questions because they share Q-numbers
        with the Hindi section.

A question is "Hindi" if its MAIN BODY text is written in Devanagari script (क ख ग...).
Science/math Hindi questions ROUTINELY contain Latin symbols embedded in Devanagari:
  e.g. "C, Si तथा Ge में बंधन ऊर्जा", "P-N संधि डायोड", "Ohm का नियम", "Force F=ma"
These mixed-script questions are VALID Hindi questions — do NOT skip them.
Only skip a question whose ENTIRE main body is Latin/Roman with zero Devanagari.

OR/अथवा IN BILINGUAL PAPERS — CRITICAL:
  In interleaved papers, OR/अथवा separates two BILINGUAL PAIRS, not two Hindi-only lines.
  The structure around OR/अथवा looks like one of:
    Pattern A pairs:  [English Q1]  [Hindi Q1]  OR/अथवा  [English Q2]  [Hindi Q2]
    Pattern B pairs:  [Hindi Q1]  [English Q1]  OR/अथवा  [Hindi Q2]  [English Q2]
  For Hindi extraction:
    — Extract [Hindi Q1] from the first pair (BEFORE OR/अथवा)
    — After OR/अथवा, scan past the English version to find [Hindi Q2]
    — Extract [Hindi Q2] as the second row
    — NEVER grab the English version and label it as Hindi"""
    else:
        return """LANGUAGE RULE — ENGLISH EXTRACTION:

MONOLINGUAL PAPER (English only):
  If this paper contains questions in English (Latin script) ONLY with no Hindi version
  of each question, simply extract every question. Ignore all bilingual layout rules below.

BILINGUAL PAPER — possible layouts:
  (a) SAME-PAGE INTERLEAVED — both languages appear together on every page.
      Each question appears as a bilingual pair in one of two patterns:
        Pattern A:  [English version]  [Hindi/Devanagari version]
        Pattern B:  [Hindi/Devanagari version]  [English version]
      → Extract ONLY the Latin/Roman (English) version from each pair.
      → Skip the adjacent Devanagari/Hindi version — it is the same question.

  (b) SEPARATE SECTIONS — the ENTIRE Hindi section comes first, then the ENTIRE
      English section follows (or vice versa). This is common in board exam papers.
      Layout example:
        [Page 1–6]  ALL questions in Hindi/Devanagari   ← skip entirely
        [Page 7–12] ALL questions in English/Latin      ← extract from here
      → Skip the entire Hindi section at the beginning.
      → START extracting only when you reach the English section header or the point
        where question text switches to Latin script.
      → Do NOT stop early — read the English section to its end.

A question is "English" if its MAIN BODY text is in Latin/Roman script (a-z, A-Z).
Isolated Hindi words near an English question (e.g. अथवा, section headers) are FINE.
Only skip a question whose entire main body is in Devanagari with zero Latin text.

OR/अथवा IN BILINGUAL PAPERS — CRITICAL:
  In interleaved papers, OR/अथवा separates two BILINGUAL PAIRS, not two English-only lines.
  The structure around OR/अथवा looks like one of:
    Pattern A pairs:  [English Q1]  [Hindi Q1]  OR/अथवा  [English Q2]  [Hindi Q2]
    Pattern B pairs:  [Hindi Q1]  [English Q1]  OR/अथवा  [Hindi Q2]  [English Q2]
  For English extraction:
    — Extract [English Q1] from the first pair (BEFORE OR/अथवा)
    — After OR/अथवा, scan past the Hindi version to find [English Q2]
    — Extract [English Q2] as the second row
    — NEVER grab the Hindi version and label it as English"""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MANDATORY SUB-QUESTION COUNTING  (MCQ / FIB / T&F / OWA)
# This is the key fix for under-extraction in 1-mark sub-question block types.
# ─────────────────────────────────────────────────────────────────────────────
def _sub_question_count_instruction(q_nums: list[int] | None, question_type: str) -> str:
    if not q_nums:
        q_list = "all question numbers in TARGET"
    else:
        q_list = ", ".join(f"Q{n}" for n in q_nums)
 
    type_hints = {
        "Multiple Choice Question": (
            "sub-questions labeled (a),(b),(c)... or (अ),(ब),(स)... "
            "each followed by 4 options (i)(ii)(iii)(iv)"
        ),
        "Fill in the Blanks": (
            "sub-statements labeled (a),(b),(c)... or (i),(ii)... "
            "each containing a blank ______"
        ),
        "True and False": (
            "sub-statements labeled (a),(b),(c)... or (i),(ii)... "
            "each a complete declarative sentence"
        ),
        "One Word Answer": (
            "sub-questions labeled (a),(b),(c)... or (i),(ii)... "
            "each asking for a one-word or one-sentence answer"
        ),
    }
    hint = type_hints.get(question_type, "sub-questions inside the parent question")
 
    return f"""
MANDATORY PRE-EXTRACTION STEP — complete ALL steps BEFORE building your JSON:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step A — Physically count sub-questions for TARGET ({q_list}):
  • Open each question number in the PDF.
  • Count every {hint}.
  • Record: Q{{n}} contains X sub-questions.
  • TOTAL = sum of sub-question counts across all question numbers.
 
Step B — Extract every single sub-question as its own JSON item:
  • NEVER output the parent question as a single item.
  • Each labeled sub-question (a), (b), (c)... = exactly ONE array item.
  • Your JSON array length MUST equal TOTAL from Step A.
 
Step C — Self-check BEFORE returning:
  • Count your JSON items.
  • If count < TOTAL you missed sub-questions — re-scan the parent question.
  • MOST COMMON MISTAKE: stopping after (a),(b),(c) when the paper continues
    with (d),(e),(f)... Always read to the END of the parent question block
    before moving to the next question number.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# OR / अथवा COUNTING  (VSA / SA / LA / VLA)
# ─────────────────────────────────────────────────────────────────────────────
def _or_counting_instruction(q_nums: list[int] | None) -> str:
    if not q_nums:
        q_list = "all question numbers in TARGET"
    else:
        q_list = ", ".join(f"Q{n}" for n in q_nums)
 
    return f"""
MANDATORY PRE-EXTRACTION STEP — complete ALL steps BEFORE building your JSON:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step A — Understand the OR/अथवा structure for TARGET ({q_list}):
  • "अथवा"/"OR" may appear on its own line OR inline within the same line.
  • BILINGUAL INTERLEAVED PAPERS: OR/अथवा separates two BILINGUAL PAIRS.
    Each pair contains BOTH a Hindi and an English version side by side.
    The pattern looks like:
      [Your-language Q1]  [Other-language Q1]  OR/अथवा  [Your-language Q2]  [Other-language Q2]
    — You must extract [Your-language Q1] AND [Your-language Q2] as two separate rows.
    — After OR/अथवा, scan PAST the other language's version to find your language's version.
    — NEVER grab the other language's version as your alternative.
  • SINGLE-LANGUAGE OR MONOLINGUAL PAPERS: OR/अथवा simply separates two alternatives
    in the same language — extract both.
  • Let W = count of questions WITH an अथवा/OR alternative.
  • Let N = count of questions WITHOUT.
  • MINIMUM expected rows = (W × 2) + N

Step B — Extract each alternative as a SEPARATE row:
  • Question A अथवा Question B → TWO rows (one for A, one for B).
  • Strip "अथवा"/"OR" from the start of the second alternative's text.
  • "अथवा"/"OR" itself is NEVER a question row.

Step C — Self-check BEFORE returning:
  • Count your JSON items.
  • If count < (W×2)+N you missed an alternative — re-scan that question number.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
 
 
def _self_count_instruction(q_nums: list[int] | None, question_type: str) -> str:
    if not q_nums:
        return (
            "\nFINAL CHECK: Count the items in your JSON array before returning. "
            "If it seems unexpectedly low, re-scan the PDF section."
        )
    is_or_type = question_type in (
        "Very Short Answer", "Short Answer", "Long Answer", "Very Long Answer"
    )
    if is_or_type:
        count_hint = (
            f" For {len(q_nums)} question number(s), "
            f"each WITH अथवा/OR → 2 rows, each WITHOUT → 1 row."
        )
    else:
        count_hint = (
            f" You are targeting {len(q_nums)} parent question number(s): "
            f"{', '.join(f'Q{n}' for n in q_nums)}. "
            f"Each sub-question inside = 1 row."
        )
    return (
        f"\nFINAL CHECK: Count your JSON array items before returning.{count_hint} "
        f"If your count seems low, re-read the section."
    )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Detect paper structure (now also extracts sub_question_count)
# ─────────────────────────────────────────────────────────────────────────────
def extract_structure_prompt() -> str:
    return """You are reading an exam paper PDF. Your only task is to detect the
complete question structure and return a JSON map.
 
════════════════════════════════════════════════════════════
STEP 1 — READ THE INSTRUCTION BLOCK
════════════════════════════════════════════════════════════
Find the instruction block at the TOP of the paper.
Labels to search: "Instructions" / "निर्देश" / "सामान्य निर्देश" / "Note" / "सूचना"
 
Read EVERY line carefully. For each line note:
  • Question number range   e.g. "Q1 to Q4"  /  "प्रश्न क्र. 1 से 4 तक"
  • Marks per question      e.g. "5 marks"   /  "5 अंक"
  • Whether sub-questions each carry 1 mark
    e.g. "each sub-question carries 1 mark"  /  "प्रत्येक उपप्रश्न पर 1 अंक निर्धारित है"
 
Key Hindi vocabulary:
  अंक = marks          प्रत्येक = each        से = from       तक = to
  उपप्रश्न = sub-question               निर्धारित = allocated
  प्रश्न क्र. / क्रमांक = question number
 
OCR NOTE — treat common OCR errors as correct equivalents:
  प्रश्ि / प्रनत / प्रश् / परश्न  →  प्रश्न
  अऊक / अक / अँक               →  अंक
  परतयक / परतयेक               →  प्रत्येक
  उपप्रशन / उपप्रश्ि             →  उपप्रश्न
  नरदश / नरदेश                  →  निर्देश
 
════════════════════════════════════════════════════════════
FALLBACK CASCADE
════════════════════════════════════════════════════════════
Level 1 (preferred): Read the instruction block at the top.
 
Level 2 (if instruction block is missing or unreadable):
  Scan each question line for bracket marks on the right:
    e.g. "Q5. Describe Ohm's law. [3]" or "Q1. (i) ... [1×5=5]"
  [1×5=5] → 5 sub-questions × 1 mark each.
  [3] → standalone 3-mark → Short Answer.
 
Level 3 (last resort):
  {
    "Multiple Choice Question": {"question_numbers": [1], "marks_each": 1, "sub_question_count": 5},
    "Fill in the Blanks":       {"question_numbers": [2], "marks_each": 1, "sub_question_count": 5},
    "True and False":           {"question_numbers": [3], "marks_each": 1, "sub_question_count": 5},
    "Match the Following":      {"question_numbers": [4], "marks_each": 1, "sub_question_count": 5},
    "One Word Answer":          {"question_numbers": [5], "marks_each": 1, "sub_question_count": 5},
    "Very Short Answer":        {"question_numbers": [6,7,8,9,10], "marks_each": 2, "sub_question_count": null},
    "Short Answer":             {"question_numbers": [11,12,13,14,15], "marks_each": 3, "sub_question_count": null},
    "Long Answer":              {"question_numbers": [16,17,18,19,20], "marks_each": 4, "sub_question_count": null}
  }
  If you use Level 3, add: "_fallback": true
 
════════════════════════════════════════════════════════════
STEP 2 — CLASSIFY EACH RANGE
════════════════════════════════════════════════════════════
 
CASE A — Sub-question block (each sub-question = 1 mark):
  Look inside each parent question number to determine type:
    4 options (i)(ii)(iii)(iv)      → Multiple Choice Question
    blanks "......" or "______"     → Fill in the Blanks
    True/False / सत्य/असत्य         → True and False
    Two columns to match            → Match the Following
    Short questions, no options     → One Word Answer

  marks_each = 1 (per sub-question, not total)

  IMPORTANT — also count sub_question_count:
    Open each parent question number and count how many sub-questions (a),(b),(c)...
    are inside it. Sum across all question_numbers for that type.
    This is the EXACT minimum rows the extractor must produce.

CASE B — Standalone question:
  2 marks → Very Short Answer
  3 marks → Short Answer
  4 marks → Long Answer
  5 marks → Very Long Answer
  6 marks → Very Long Answer
  sub_question_count = null for all standalone types.

CASE C — History / Social Science special formats (NEVER classify as One Word Answer):
  These ALWAYS fall under Long Answer or Very Long Answer regardless of sub-item length.

  MAP-BASED QUESTION (मानचित्र सम्बन्धी प्रश्न):
    Keywords: "मानचित्र" / "map" / "outline map" / "रेखा-मानचित्र" / "⊙ चिह्न"
    Sub-items list PLACES / LOCATIONS to mark on a map of India.
    → Classify as Long Answer or Very Long Answer based on total marks.
    → sub_question_count = number of places listed.
    NEVER → One Word Answer.

  HISTORICAL DATES (ऐतिहासिक तिथियाँ):
    Keywords: "ऐतिहासिक तिथि" / "historical date" / "तिथि" followed by years like
    "185 B.C." / "320 A.D." / "1857 ईo" / "ईo पूo" listed as sub-items.
    Sub-items are YEARS labeled with Hindi letters (क/ख/ग…) OR English letters (a/b/c/d/e/f…).
    Sub-items are YEARS, not short-answer questions.
    → Classify as Long Answer or Very Long Answer based on total marks.
    → sub_question_count = number of dates listed.
    NEVER → One Word Answer.

  DECISION RULE for One Word Answer:
    Use "One Word Answer" ONLY when sub-items are short conceptual questions
    whose answers are a single word or phrase — NOT when sub-items are
    years/dates or place descriptions to mark on a map.
 
════════════════════════════════════════════════════════════
STEP 3 — SELF-CHECK  (MANDATORY before returning)
════════════════════════════════════════════════════════════
  • Every question number 1–N must appear in EXACTLY ONE type entry — never two.
  • Short Answer / Very Long Answer being absent is valid.
  • Long Answer (4-mark) and Very Long Answer (5/6-mark) are always separate keys.

  CRITICAL — NO OVERLAPPING RANGES:
  Take your draft JSON and list every question number that appears in more than
  one type entry. If ANY overlap exists you MUST fix it before returning:
    — Re-read the instruction block to find the true marks boundary.
    — Remove the number from the WRONG entry (keep it only in the entry whose
      marks_each matches the paper's instruction for that number).
    — Example of a CORRECT split: "Short Answer": [13,14,15,16]  and
      "Long Answer": [17,18,19,20] — ZERO shared numbers.
    — Example of a BAD split:    "Short Answer": [13,14,15,16,17] and
      "Long Answer": [17,18,19,20] — Q17 is in BOTH → WRONG, must fix.
  Only return once every number appears in exactly one entry.
 
════════════════════════════════════════════════════════════
OUTPUT FORMAT
════════════════════════════════════════════════════════════
Keys (omit absent types):
  "Multiple Choice Question", "Fill in the Blanks", "True and False",
  "One Word Answer", "Match the Following", "Very Short Answer",
  "Short Answer", "Long Answer", "Very Long Answer"

NOTE: Map-based questions and Historical Dates questions are classified as
"Long Answer" or "Very Long Answer" (whichever matches the marks).
Do NOT create separate keys for them — they use the same keys as regular
Long/Very Long Answer questions.
 
Each entry:
  {
    "question_numbers": [list of ints],
    "marks_each": <int>,
    "sub_question_count": <int or null>
  }
 
sub_question_count = total sub-questions across ALL question_numbers for that type.
null for standalone types (VSA, SA, LA, VLA, Match).
 
Always expand ranges: "Q5 to Q8" → [5,6,7,8]
 
════════════════════════════════════════════════════════════
EXAMPLE
════════════════════════════════════════════════════════════
Q1 has 5 MCQs, Q2 has 5 FIBs, Q3 has 5 T&Fs, Q4=Match(5 items), Q5=5 OWA,
Q6–Q10=2-mark, Q11–Q14=3-mark, Q15–Q18=4-mark:
{
  "Multiple Choice Question": {"question_numbers": [1],           "marks_each": 1, "sub_question_count": 5},
  "Fill in the Blanks":       {"question_numbers": [2],           "marks_each": 1, "sub_question_count": 5},
  "True and False":           {"question_numbers": [3],           "marks_each": 1, "sub_question_count": 5},
  "Match the Following":      {"question_numbers": [4],           "marks_each": 1, "sub_question_count": 5},
  "One Word Answer":          {"question_numbers": [5],           "marks_each": 1, "sub_question_count": 5},
  "Very Short Answer":        {"question_numbers": [6,7,8,9,10],  "marks_each": 2, "sub_question_count": null},
  "Short Answer":             {"question_numbers": [11,12,13,14], "marks_each": 3, "sub_question_count": null},
  "Long Answer":              {"question_numbers": [15,16,17,18], "marks_each": 4, "sub_question_count": null}
}
 
Return ONLY the JSON object, nothing else."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MULTIPLE CHOICE QUESTIONS
# ─────────────────────────────────────────────────────────────────────────────
def mcq_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for the MCQ / बहुविकल्पीय section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    sub_count = _sub_question_count_instruction(q_nums, "Multiple Choice Question")
    self_count = _self_count_instruction(q_nums, "Multiple Choice Question")
    return f"""You are extracting Multiple Choice Questions (MCQ) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{sub_count}
 
RULES:
1. A parent MCQ question contains sub-questions labeled (a),(b),(c)... or (अ),(ब),(स)...
   Each sub-question WITH its 4 options (i)(ii)(iii)(iv) = ONE individual row.
2. Include the sub-question label AND ALL four options in the question text.
3. Do NOT treat the whole parent block as one question.
4. NO OR/अथवा ALTERNATIVES — each sub-question appears exactly once. In bilingual
   papers, the Hindi and English versions of the same sub-question appear side by side;
   they are NOT separate alternatives. Extract ONLY your target language's version.
5. CRITICAL: Read to the LAST sub-question letter in the parent block. Do NOT stop
   after (a),(b),(c) if the paper continues with (d),(e)...
6. STOP at the hard boundary — do not read into the next question number.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<sub-question text with all 4 options>"}}
  ]
}}
 
EXAMPLE (Hindi — 3 sub-questions = 3 rows):
{{
  "questions": [
    {{"question": "(a) n-प्रकार के अर्धचालकों में बहुसंख्यक आवेश वाहक हैं –\\n(i) इलेक्ट्रॉन  (ii) होल  (iii) न्यूट्रॉन  (iv) गतिशील आयन"}},
    {{"question": "(b) वायु का परावैद्युतांक होता है –\\n(i) अनंत  (ii) शून्य  (iii) एक  (iv) दो"}},
    {{"question": "(c) गतिमान आवेश उत्पन्न करता है –\\n(i) केवल चुंबकीय क्षेत्र  (ii) केवल विद्युत क्षेत्र  (iii) दोनों  (iv) न चुंबकीय न विद्युत"}}
  ]
}}
 
EXAMPLE (English — same 3 rows):
{{
  "questions": [
    {{"question": "(a) Majority charge carriers in n-type semiconductors are –\\n(i) Electrons  (ii) Holes  (iii) Neutrons  (iv) Moving ions"}},
    {{"question": "(b) Dielectric constant of air is –\\n(i) Infinite  (ii) Zero  (iii) One  (iv) Two"}},
    {{"question": "(c) Moving charge produces –\\n(i) Only magnetic field  (ii) Only electric field  (iii) Both  (iv) Neither"}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# FILL IN THE BLANKS
# ─────────────────────────────────────────────────────────────────────────────
def fill_blanks_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for the Fill in the Blanks / रिक्त स्थान section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    sub_count = _sub_question_count_instruction(q_nums, "Fill in the Blanks")
    self_count = _self_count_instruction(q_nums, "Fill in the Blanks")
    return f"""You are extracting Fill in the Blanks questions from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{sub_count}
 
RULES:
1. Each numbered/lettered blank-statement = ONE question row.
2. Represent ALL blanks as "______" in the question text.
3. Do NOT extract True/False statements — those have no blanks.
4. NO OR/अथवा ALTERNATIVES — each blank-statement appears exactly once. In bilingual
   papers, the Hindi and English versions appear side by side; extract ONLY your target
   language's version. Never produce 2 rows from a single bilingual sub-statement.
5. CRITICAL: Read ALL labeled sub-statements (a),(b),(c),(d),(e)... Do not stop
   early. The parent question may have 5, 6, or more sub-statements.
6. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<statement with ______>"}}
  ]
}}
 
EXAMPLE (Hindi — 4 items = 4 rows):
{{
  "questions": [
    {{"question": "1 कूलॉम आवेश में ______ इलेक्ट्रॉन होते हैं।"}},
    {{"question": "चुंबकीय क्षेत्र रेखा के किसी बिंदु पर खींची गई ______ उस बिंदु पर परिणामी चुंबकीय क्षेत्र की दिशा दर्शाती है।"}},
    {{"question": "विद्युत चुंबकीय तरंगों के संचरण की प्रकृति ______ होती है।"}},
    {{"question": "प्रकाश के ______ की घटना से ऊर्जा का पुनर्वितरण होता है।"}}
  ]
}}
 
EXAMPLE (English — same count):
{{
  "questions": [
    {{"question": "One coulomb charge has ______ electrons."}},
    {{"question": "The ______ to the field line at a given point represents direction of resultant magnetic field at that point."}},
    {{"question": "Nature of propagation of electromagnetic waves are ______."}},
    {{"question": "______ of light shows redistribution of energy."}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# TRUE AND FALSE
# ─────────────────────────────────────────────────────────────────────────────
def true_false_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for the True/False / सत्य-असत्य section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    sub_count = _sub_question_count_instruction(q_nums, "True and False")
    self_count = _self_count_instruction(q_nums, "True and False")
    return f"""You are extracting True/False statements from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{sub_count}
 
RULES:
1. Each lettered statement = ONE question row.
2. Extract the statement text ONLY — do not include any answer.
3. SKIP any item containing "______" — those are Fill in the Blanks.
4. SKIP any item ending with a dash "–" — those are One Word Answer stems.
5. A valid T/F statement is a COMPLETE declarative sentence ending with । or .
6. NO OR/अथवा ALTERNATIVES — each statement appears exactly once. In bilingual
   papers, Hindi and English versions appear side by side; extract ONLY your target
   language's version. Never produce 2 rows from a single bilingual statement.
7. CRITICAL: Read ALL labeled sub-statements (a),(b),(c),(d),(e)... Do not stop
   early. Always read to the END of the parent question block.
8. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<statement text only>"}}
  ]
}}
 
EXAMPLE (Hindi):
{{
  "questions": [
    {{"question": "चालक के भीतर स्थिरवैद्युत क्षेत्र शून्य होता है।"}},
    {{"question": "चुंबकीय क्षेत्र रेखाएँ सदैव बंद पाश बनाती हैं।"}},
    {{"question": "दीर्घ रेडियो तरंगों की आवृत्ति सर्वाधिक होती है।"}}
  ]
}}
 
EXAMPLE (English — same count):
{{
  "questions": [
    {{"question": "Inside a conductor, electrostatic field is zero."}},
    {{"question": "Magnetic field lines always form closed loops."}},
    {{"question": "Frequency is maximum for long radio waves."}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# ONE WORD ANSWER
# ─────────────────────────────────────────────────────────────────────────────
def one_word_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(
        q_nums,
        "Look for: 'One Word Answer' / 'Write answer in one sentence' / "
        "'एक शब्द में उत्तर' / 'एक वाक्य में उत्तर'."
    )
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    sub_count = _sub_question_count_instruction(q_nums, "One Word Answer")
    self_count = _self_count_instruction(q_nums, "One Word Answer")
    return f"""You are extracting One Word Answer questions from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{sub_count}
 
RULES:
1. Each sub-question labeled (a),(b),(c)... or (अ),(ब),(स)... = ONE row.
2. NO OR/अथवा ALTERNATIVES — this is a 1-mark sub-question block. Sub-questions
   appear exactly ONCE each. There are no OR alternatives in this section.
   In bilingual papers, each sub-question has a Hindi version AND an English version
   side by side — these are the SAME sub-question, NOT an OR alternative. Extract
   ONLY your target language's version of each sub-question. Never produce 2 rows
   for a sub-question just because you see both a Hindi and English version.
3. BLANK CHECK — item contains "______" → SKIP (Fill in the Blanks).
4. TRUE/FALSE CHECK — complete declarative sentence with full stop, no dash → SKIP.
5. COLUMN B CHECK — bare noun phrase with no verb context → SKIP (Match column B item).
6. SKIP the section header line itself (e.g. "Write answer in one sentence:").
7. CRITICAL: Read ALL labeled sub-questions to the END of the parent block.
   Do not stop after (a),(b),(c) if (d),(e)... follow.
8. STOP at the hard boundary above.
 
HOW TO DETECT VALID OWA:
  ✓ VALID — ends with "–" (incomplete statement)
  ✓ VALID — ends with "?" (question)
  ✓ VALID — contains: क्या, कौन, किसे, कितनी, what, who, which, write, state, define
  ✗ SKIP  — bare noun: "फोटॉन", "Moving particle", "Work function"
  ✗ SKIP  — definition fragment with no question structure
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<sub-question text>"}}
  ]
}}
 
EXAMPLE (Hindi — 5 rows):
{{
  "questions": [
    {{"question": "वैद्युत आवेश के क्वाण्टीकरण का गणितीय रूप लिखिये।"}},
    {{"question": "दृश्य प्रकाश की आवृत्ति किस कोटि की होती है?"}},
    {{"question": "+ 0.5 मी. फोकस दूरी वाले लेंस की क्षमता कितनी होगी?"}},
    {{"question": "अन्योन्य प्रेरकत्व का SI मात्रक लिखिए।"}},
    {{"question": "प्रत्यावर्ती धारा का वर्गमाध्य मूल मान लिखिए।"}}
  ]
}}
 
EXAMPLE (English — same 5 rows):
{{
  "questions": [
    {{"question": "Write mathematical form of quantisation of electric charge."}},
    {{"question": "What is the degree of order of frequency of visible light?"}},
    {{"question": "What is power of a lens having +0.5 m focal length?"}},
    {{"question": "Write the SI unit of mutual inductance."}},
    {{"question": "Write the root mean square value of alternating current."}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VERY SHORT ANSWER  (2 marks)
# ─────────────────────────────────────────────────────────────────────────────
def very_short_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for 2-mark questions (Very Short Answer / अति लघु उत्तरीय).")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    or_counting = _or_counting_instruction(q_nums)
    self_count = _self_count_instruction(q_nums, "Very Short Answer")
    return f"""You are extracting Very Short Answer questions (2 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{or_counting}
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER output it as a question row.
   - "question A अथवा question B" → extract A as row 1, B as row 2.
   - Strip "अथवा"/"OR" from the beginning of B.
   - OR/अथवा may appear on its own line OR inline — treat both the same.
3. Do NOT extract from question numbers outside TARGET.
4. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text, no leading अथवा/OR>"}}
  ]
}}
 
EXAMPLE — 2 questions each with OR = 4 rows (Hindi):
{{
  "questions": [
    {{"question": "निज एवं बाह्य अर्धचालकों में दो अंतर लिखिये।"}},
    {{"question": "सामान्य ताप पर अर्धचालकों में धारा का प्रवाह नहीं होता, जबकि उच्च ताप पर होने लगता है, क्यों?"}},
    {{"question": "आयनन ऊर्जा किसे कहते हैं?"}},
    {{"question": "कक्षक में इलेक्ट्रॉन की ऋणात्मक ऊर्जा की सार्थकता स्पष्ट कीजिए।"}}
  ]
}}
 
EXAMPLE (English — same 4 rows):
{{
  "questions": [
    {{"question": "Write two differences between Intrinsic and Extrinsic semiconductors."}},
    {{"question": "Electric current doesn't flow in semiconductors at normal temperature while flow at higher temperature, why?"}},
    {{"question": "What is Ionization energy?"}},
    {{"question": "Clarify the significance of negative energy of an electron in the orbit."}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# SHORT ANSWER  (3 marks)
# ─────────────────────────────────────────────────────────────────────────────
def short_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for 3-mark questions (Short Answer / लघु उत्तरीय).")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    or_counting = _or_counting_instruction(q_nums)
    self_count = _self_count_instruction(q_nums, "Short Answer")
    return f"""You are extracting Short Answer questions (3 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{or_counting}
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER output it as a question row.
   - Each alternative = a separate row. Strip "अथवा"/"OR" from start of second row.
   - OR/अथवा may appear on its own line OR inline — treat both the same.
3. Include sub-parts (a)/(b) in the same string if they share the question number.
4. Do NOT extract from question numbers outside TARGET.
5. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text — no leading अथवा/OR>"}}
  ]
}}
 
EXAMPLE (Hindi — 2 questions each with OR = 4 rows):
{{
  "questions": [
    {{"question": "प्रकाश-विद्युत प्रभाव क्या है? इसकी कोई दो विशेषताएँ लिखिए।"}},
    {{"question": "प्रकाश के पूर्ण आंतरिक परावर्तन की शर्तें लिखिए तथा इसका एक उपयोग दीजिए।"}},
    {{"question": "बोर के हाइड्रोजन परमाणु मॉडल की दो अभिधारणाएँ लिखिए।"}},
    {{"question": "नाभिकीय विखंडन और संलयन में दो अंतर लिखिए।"}}
  ]
}}

EXAMPLE (English — same 4 rows):
{{
  "questions": [
    {{"question": "What is photoelectric effect? Write any two of its characteristics."}},
    {{"question": "Write conditions for total internal reflection and give one application."}},
    {{"question": "State any two postulates of Bohr's model of hydrogen atom."}},
    {{"question": "Write two differences between nuclear fission and fusion."}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# LONG ANSWER  (4 marks)
# ─────────────────────────────────────────────────────────────────────────────
def long_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for 4-mark questions (Long Answer / दीर्घ उत्तरीय — 4 अंक).")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    or_counting = _or_counting_instruction(q_nums)
    self_count = _self_count_instruction(q_nums, "Long Answer")
    return f"""You are extracting Long Answer questions (4 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{or_counting}
 
IMPORTANT: Extract 4-mark questions ONLY.
Do NOT extract 5-mark or 6-mark questions — those belong to Very Long Answer.
Do NOT extract 2-mark or 3-mark questions.

RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER a question row.
   - Each alternative = a separate row. Strip "अथवा"/"OR" from start of second row.
   - OR/अथवा may appear on its own line OR inline — treat both the same.
3. Include sub-parts (a)/(b)/(c)/(d) in the same string if they share the question number.
4. Do NOT extract from question numbers outside TARGET.
5. STOP at the hard boundary above.

SPECIAL FORMAT A — HISTORICAL DATES (ऐतिहासिक तिथियाँ):
If a question lists multiple historical years as sub-items (क/ख/ग… OR a/b/c/d/e/f/g…)
and asks to write the event for each — keep ALL dates as ONE row. Include the parent
instruction and all sub-items together in a single question string.

SPECIAL FORMAT B — MAP QUESTION (मानचित्र सम्बन्धी प्रश्न):
If a question asks to mark/show places on a map with sub-items (i, ii, iii…) —
keep ALL places as ONE row. Include the parent instruction and all sub-items together
in a single question string.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text>"}}
  ]
}}
 
EXAMPLE (Hindi — 2 questions each with OR = 4 rows, all 4-mark multi-part):
{{
  "questions": [
    {{"question": "समांतर प्लेट संधारित्र की धारिता के लिये व्यंजक ज्ञात कीजिए। इसे प्रभावित करने वाले दो कारक लिखिये।"}},
    {{"question": "व्हीटस्टोन सेतु का वर्णन निम्न बिन्दुओं पर कीजिए: (a) सिद्धांत (b) नामांकित विद्युत परिपथ (c) आवश्यक शर्त (d) कोई एक उपयोग"}},
    {{"question": "ट्रांसफार्मर का वर्णन कीजिए: (1) नामांकित चित्र (2) सिद्धांत (3) धारा-वोल्टता संबंध (4) कोई दो उपयोग"}},
    {{"question": "p-n संधि डायोड में अग्र एवं पश्च अभिनति की व्याख्या कीजिए। इसका नामांकित चित्र बनाइए।"}}
  ]
}}

EXAMPLE (English — same 4 rows, all 4-mark multi-part):
{{
  "questions": [
    {{"question": "Derive an expression for the capacitance of a parallel plate capacitor and write two factors affecting it."}},
    {{"question": "Describe Wheatstone bridge under the following points: (a) Principle (b) Labelled electric circuit (c) Necessary condition (d) Any one use"}},
    {{"question": "Describe a transformer under the following headings: (1) Labelled diagram (2) Principle (3) Current-voltage relation (4) Any two applications"}},
    {{"question": "Explain forward and reverse biasing of a p-n junction diode. Draw its labelled diagram."}}
  ]
}}
 
{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VERY LONG ANSWER  (5 or 6 marks)
# ─────────────────────────────────────────────────────────────────────────────
def very_long_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(
        q_nums,
        "Look for 5-mark or 6-mark questions (Very Long Answer / दीर्घ उत्तरीय — 5/6 अंक)."
    )
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    or_counting = _or_counting_instruction(q_nums)
    self_count = _self_count_instruction(q_nums, "Very Long Answer")
    return f"""You are extracting Very Long Answer questions (5 or 6 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
{or_counting}
 
IMPORTANT: Extract 5-mark and 6-mark questions ONLY.
Do NOT extract 4-mark questions — those belong to Long Answer.
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER a question row.
   - Each alternative = a separate row. Strip "अथवा"/"OR" from start of second row.
   - OR/अथवा may appear on its own line OR inline — treat both the same.
3. Include sub-parts (a)/(b)/(c)/(d) in the same string if they share the question number.
4. Do NOT extract from question numbers outside TARGET.
5. STOP at the hard boundary above.

SPECIAL FORMAT A — HISTORICAL DATES (ऐतिहासिक तिथियाँ):
If a question lists multiple historical years as sub-items (क/ख/ग… OR a/b/c/d/e/f/g…)
and asks to write the event for each — keep ALL dates as ONE row. Include the parent
instruction and all sub-items together in a single question string.
Example (English labels — UP Board style):
  Input: "Mention the events related to the following historical dates:
   d) 1490 A.D.  e) 1739 A.D.  f) 1765 A.D.  g) 1818 A.D.  h) 1857 A.D."
→ ONE row: {{"question": "Mention the events related to the following historical dates:\\nd) 1490 A.D.  e) 1739 A.D.  f) 1765 A.D.  g) 1818 A.D.  h) 1857 A.D."}}

SPECIAL FORMAT B — MAP QUESTION (मानचित्र सम्बन्धी प्रश्न):
If a question asks to mark/show places on a map with sub-items (i, ii, iii…) —
keep ALL places as ONE row. Include the parent instruction and all sub-items together
in a single question string.
Example (English — UP Board style):
  Input: "Show on map: i) The place where Mahabir Swami took birth.
   ii) The capital of Avanti Mahajanapada.  iii) The meeting place of Ganga-Yamuna."
→ ONE row: {{"question": "Show on map:\\ni) The place where Mahabir Swami took birth.\\nii) The capital of Avanti Mahajanapada.\\niii) The meeting place of Ganga-Yamuna."}}

OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text>"}}
  ]
}}

EXAMPLE (Hindi):
{{
  "questions": [
    {{"question": "p-n संधि डायोड की अग्र एवं पश्च अभिनति में कार्यविधि समझाइए। अभिलाक्षणिक वक्र बनाइए।"}},
    {{"question": "C, Si तथा Ge की जालक संरचना समान होती है। फिर भी C विद्युतरोधी है जबकि Si व Ge अर्धचालक क्यों हैं?"}},
    {{"question": "ट्रांसफार्मर का वर्णन निम्न बिन्दुओं पर कीजिए:\\n(1) प्रकार\\n(2) नामांकित चित्र\\n(3) सिद्धान्त\\n(4) कोई 2 अनुप्रयोग"}}
  ]
}}

EXAMPLE (English — same count):
{{
  "questions": [
    {{"question": "Explain the working of a p-n junction diode under forward and reverse bias. Draw the characteristic curve."}},
    {{"question": "C, Si and Ge have same lattice structure. Why is C insulator while Si and Ge are semiconductors?"}},
    {{"question": "Describe a transformer under the following headings:\\n(1) Kinds\\n(2) Labelled diagram\\n(3) Principle\\n(4) Any 2 applications"}}
  ]
}}

{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MATCH THE FOLLOWING
# ─────────────────────────────────────────────────────────────────────────────
def match_following_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for Match the Following / स्तंभ मिलाइए blocks.")
    boundary = _boundary_instruction(q_nums, language)
    self_count = _self_count_instruction(q_nums, "Match the Following")

    if language == "Hindi":
        lang_rule = """LANGUAGE RULE — HINDI:
This bilingual paper contains the Match block in ONE of these layouts:

LAYOUT A — TWO SEPARATE BLOCKS (most common):
  Block 1 (Hindi):   column headers स्तंभ 'अ' / स्तंभ 'ब'  — items in Devanagari
  Block 2 (English): column headers Column A / Column B     — items in Latin script
  → Extract ONLY Block 1 (Devanagari headers, Devanagari items).
  → SKIP Block 2 entirely.

LAYOUT B — INTERLEAVED ITEMS per row:
  Each row shows both versions side by side:  (a) [Hindi item]  [English item]
  → Extract ONLY the Devanagari item from each row; skip the adjacent Latin item."""
    else:
        lang_rule = """LANGUAGE RULE — ENGLISH:
This bilingual paper contains the Match block in ONE of these layouts:

LAYOUT A — TWO SEPARATE BLOCKS (most common):
  Block 1 (Hindi):   column headers स्तंभ 'अ' / स्तंभ 'ब'  — items in Devanagari
  Block 2 (English): column headers Column A / Column B     — items in Latin script
  → Extract ONLY Block 2 (Latin/English headers, Latin/English items).
  → SKIP Block 1 entirely.
  → IMPORTANT: Both blocks share the same Q-number — that is normal. You must
    scan past Block 1 (Devanagari) to find and extract Block 2 (English).
  → If column headers are bilingual (e.g. "स्तंभ 'अ' / Column A"), identify the
    block by its ITEM TEXT: Latin-script items = English block → extract it.

LAYOUT B — INTERLEAVED ITEMS per row:
  Each row shows both versions side by side:  (a) [English item]  [Hindi item]
  → Extract ONLY the Latin/English item from each row; skip the adjacent Devanagari item."""

    return f"""You are extracting Match the Following questions from an exam paper PDF.

TARGET: {ref}
{lang_rule}
{boundary}

RULES:
1. ONE complete block (all Column A + all Column B items) = ONE question row.
2. MARKS = count of Column A items (1 mark per item).
3. Format the "question" field as:
     <column A header line>
     (a) item text
     (b) item text
     ...
     ---
     <column B header line>
     (i) item text
     (ii) item text
     ...
4. Do NOT merge the Hindi block and the English block into one row — they are
   separate rows for the same Q-number.
5. STOP at the hard boundary above.

OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{
      "question": "<complete block with --- separator>",
      "marks": <integer count of Column A items>
    }}
  ]
}}

EXAMPLE (Hindi — 6 Column A items → marks=6):
{{
  "questions": [
    {{
      "question": "स्तंभ 'अ':\\n(a) प्रकाश की तीव्रता\\n(b) प्रकाश की आवृत्ति\\n(c) कार्य फलन\\n(d) द्रव्य तरंग\\n(e) देहली आवृत्ति\\n(f) प्रकाश की कणीय प्रकृति\\n---\\nस्तंभ 'ब':\\n(i) सतह से इलेक्ट्रॉन उत्सर्जन हेतु न्यूनतम ऊर्जा\\n(ii) न्यूनतम आवृत्ति\\n(iii) फोटॉन की आवृत्ति\\n(iv) फोटॉन की संख्या\\n(v) गतिशील कण\\n(vi) फोटॉन",
      "marks": 6
    }}
  ]
}}

EXAMPLE (English — same block extracted in English, 6 Column A items → marks=6):
{{
  "questions": [
    {{
      "question": "Column A:\\n(a) Intensity of light\\n(b) Frequency of light\\n(c) Work function\\n(d) Matter wave\\n(e) Threshold frequency\\n(f) Particle nature of light\\n---\\nColumn B:\\n(i) Minimum energy to emit electron from surface\\n(ii) Minimum frequency to emit electron\\n(iii) Frequency of photon\\n(iv) Number of photons\\n(v) Moving particle\\n(vi) Photon",
      "marks": 6
    }}
  ]
}}

{LATEX_INSTRUCTION}
{self_count}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Chapter mapping
# ─────────────────────────────────────────────────────────────────────────────
def chapter_mapping_prompt(
    questions: list,
    chapters: list,
    language: str = "English",
    for_language_paper: bool = False,
) -> str:
    chapter_lines  = "\n".join(f"  {c['number']}. {c['name']}" for c in chapters)
    question_lines = "\n".join(f"  Q{i + 1}: {q}" for i, q in enumerate(questions))
    n = len(questions)

    if language == "Hindi":
        lang_note = """LANGUAGE: The questions are written in Hindi (Devanagari script) and may contain
embedded English/Latin terms for scientific symbols, formulas, or proper nouns — this is normal.
Your job is to understand the CONCEPT being tested in each question and map it to the correct chapter.
Do not be confused by the script — a question asking "विद्युत द्विध्रुव के कारण अक्ष पर विद्युत क्षेत्र"
is asking about the electric field due to an electric dipole, which belongs to the Electrostatics chapter.
Similarly "अर्धचालक युक्तियाँ" = Semiconductor Devices, "प्रकाश का अपवर्तन" = Refraction of Light,
"नाभिकीय विखंडन" = Nuclear fission (Nuclear Physics chapter), and so on.
Read the whole question to identify its core physics or mathematics topic, then match it to a chapter."""
    else:
        lang_note = """LANGUAGE: The questions are written in English. Read each question carefully to
identify the core physics, chemistry, mathematics, or science concept being tested, then match it
to the most appropriate chapter from the list."""

    # Special handling for Hindi language paper Literature section
    if for_language_paper and language == "Hindi":
        language_paper_note = """
IMPORTANT — HINDI LANGUAGE PAPER SPECIAL RULE:
The chapter list contains prose/poetry chapters from textbooks. Questions NOT tied to any
specific textbook chapter must be assigned one of three special values. Choose carefully:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A) {"chapter_number": 0, "chapter_name": "Rachna Kaushal"}
   ONLY for creative WRITING TASKS where students must PRODUCE a piece of writing:
   • संवाद लेखन, पत्र लेखन (औपचारिक / अनौपचारिक), निबंध लेखन
   • अनुच्छेद लेखन, कहानी लेखन, सारांश लेखन, विज्ञापन लेखन
   Key test: the question asks the student to WRITE something in a specific form.

B) {"chapter_number": 0, "chapter_name": "व्याकरण"}
   For GRAMMAR, PROSODY, and RHETORIC definitions/comparisons NOT tied to a textbook lesson:
   • छंद परिभाषा / भेद / उदाहरण  (कवित्त, दोहा, सोरठा, मात्रिक, वार्णिक…)
   • अलंकार परिभाषा / भेद / उदाहरण  (अनुप्रास, उपमा, रूपक, विरोधाभास, श्लेष…)
   • रस / भाव परिभाषा — स्थायी भाव, संचारी भाव, रस-निष्पत्ति
   • समास, संधि, कारक, वाक्य-भेद, काल, विलोम, पर्यायवाची, तत्सम-तद्भव
   Key test: the question defines or compares a GRAMMATICAL or LITERARY-THEORY term.

C) {"chapter_number": 0, "chapter_name": "Sahitya Parichay"}
   For LITERARY HISTORY / GENRE KNOWLEDGE not tied to a specific textbook lesson:
   • Comparing literary forms/genres (नाटक और एकांकी में अंतर, उपन्यास और कहानी में अंतर)
   • Questions about authors, works, or movements NOT in the chapter list
     (e.g. जयशंकर प्रसाद का एकांकी, प्रेमचंद की कहानी-कला, रीतिकाल का परिचय)
   • काल-विभाजन, साहित्यिक युग, प्रवर्तक कवि, आंदोलन
   Key test: the question asks about LITERARY HISTORY or GENRES in general.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For questions that ARE about a specific textbook chapter — poem/passage analysis, questions
naming a character, title, or author from the chapter list — map to that chapter.

DECISION FLOW:
  1. Does it name a lesson/author/character from the chapter list? → map to that chapter
  2. Is it a WRITING TASK (student must compose something)? → Rachna Kaushal
  3. Is it a GRAMMAR/PROSODY/RHETORIC term definition or comparison? → व्याकरण
  4. Is it LITERARY HISTORY / GENRE knowledge not in the chapter list? → Sahitya Parichay
"""
    else:
        language_paper_note = ""

    return f"""You are an expert curriculum mapper with deep knowledge of school and college syllabi
(NCERT, MP Board, CBSE, and state boards). Your task is to assign each exam question to the
single most appropriate chapter from the provided chapter list.

CHAPTER LIST:
{chapter_lines}

{lang_note}
{language_paper_note}
QUESTIONS:
{question_lines}

MAPPING APPROACH — follow these steps for every question:
1. Read the full question text and identify what CONCEPT, TOPIC, or FORMULA it is testing.
   - For derivation questions: what law or expression is being derived?
   - For definition/explanation questions: what term or phenomenon is being defined?
   - For numerical/application questions: what formula or principle is being applied?
   - For comparison questions: what two concepts are being compared?
2. Match that concept to the chapter in the list that covers it.
3. If a question touches multiple chapters, assign it to the chapter covering the PRIMARY concept.
4. chapter_number and chapter_name must EXACTLY match the chapter list above — copy verbatim.
5. Never invent chapter names or numbers not present in the list.

SELF-CHECK before returning:
  • Count your JSON items — must equal exactly {n}.
  • Every chapter_number and chapter_name must exist verbatim in the chapter list.

OUTPUT — return ONLY this JSON array, nothing else:
[
  {{"chapter_number": <int>, "chapter_name": "<exact name from list>"}},
  ...
]"""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# COUNT VALIDATOR — re-extraction for mismatched counts
# ─────────────────────────────────────────────────────────────────────────────
def count_validator_prompt(
    question_type: str,
    language: str,
    q_nums: list[int] | None,
    expected_count: int,
    actual_count: int,
    other_language: str,
) -> str:
    ref = _q_ref(q_nums, f"Look for the {question_type} section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
 
    is_or_type = question_type in (
        "Very Short Answer", "Short Answer", "Long Answer", "Very Long Answer"
    )
    or_counting = _or_counting_instruction(q_nums) if is_or_type else ""
 
    is_sub_type = question_type in (
        "Multiple Choice Question", "Fill in the Blanks", "True and False", "One Word Answer"
    )
    sub_counting = _sub_question_count_instruction(q_nums, question_type) if is_sub_type else ""
 
    type_hints = {
        "Multiple Choice Question": (
            "Each sub-question with 4 options = ONE row. "
            "Read ALL labeled sub-questions (a),(b),(c)... to the END — do not stop early."
        ),
        "Fill in the Blanks": (
            "Each statement containing '______' = ONE row. "
            "Read ALL labeled sub-statements to the END — do not stop early."
        ),
        "True and False": (
            "Each declarative statement = ONE row. "
            "Read ALL labeled sub-statements to the END — do not stop early."
        ),
        "One Word Answer": (
            "Each sub-question expecting a one-word answer = ONE row. "
            "Read ALL labeled sub-questions to the END — do not stop early."
        ),
        "Very Short Answer": (
            "Each 2-mark question = ONE row. "
            "अथवा/OR → extract BOTH alternatives as separate rows."
        ),
        "Short Answer": (
            "Each 3-mark question = ONE row. "
            "अथवा/OR → extract BOTH alternatives as separate rows."
        ),
        "Long Answer": (
            "Each 4-mark question = ONE row. "
            "अथवा/OR → extract BOTH alternatives as separate rows."
        ),
        "Very Long Answer": (
            "Each 5/6-mark question = ONE row. "
            "अथवा/OR → extract BOTH alternatives as separate rows."
        ),
        "Match the Following": "Each complete Column A + Column B block = ONE row.",
    }
    type_hint = type_hints.get(question_type, "Each question = ONE row.")
    direction = "fewer" if actual_count < expected_count else "more"
 
    return f"""REEXTRACTION — count mismatch detected
 
You are re-extracting "{question_type}" questions from an exam paper PDF.
 
MISMATCH:
  Language      : {language}
  Your count    : {actual_count}
  Expected      : {expected_count} (matches {other_language} section)
  Problem       : {language} has {direction} questions than {other_language}
 
YOUR TASK: Re-read the {language} section CAREFULLY and extract ALL
"{question_type}" questions to reach {expected_count} rows.
 
TARGET: {ref}
{lang}
{boundary}
{or_counting}
{sub_counting}
 
COUNTING RULE: {type_hint}

RANGE ENFORCEMENT — CRITICAL:
  Extract ONLY from the question numbers listed in TARGET above.
  Do NOT extract questions that carry different marks (e.g. if you are
  re-extracting Short Answer Q13–Q16, do NOT extract Q17–Q20 even if those
  questions look similar — they belong to Long Answer and carry 4 marks).
  Extracting out-of-range questions inflates your count but corrupts the data.

SELF-CHECK — must reach {expected_count} items:
  Common mistakes:
  1. Stopped reading sub-questions early (missed last (d),(e),(f)... items)
  2. Missed अथवा/OR alternative — each OR = 2 rows not 1
  3. Skipped question with mixed Latin+Devanagari text
  4. Section boundary confusion — stopped too early OR went too far
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text>"}}
  ]
}}
 
{LATEX_INSTRUCTION}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
PROMPTS = {
    "Multiple Choice Question": mcq_prompt,
    "Fill in the Blanks":       fill_blanks_prompt,
    "True and False":           true_false_prompt,
    "One Word Answer":          one_word_answer_prompt,
    "Very Short Answer":        very_short_answer_prompt,
    "Short Answer":             short_answer_prompt,
    "Long Answer":              long_answer_prompt,
    "Very Long Answer":         very_long_answer_prompt,
    "Match the Following":      match_following_prompt,
}
 