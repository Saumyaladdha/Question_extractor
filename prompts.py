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
    "Very Long Answer":         5,   # also covers 6-mark questions
    "Match the Following":      None,  # dynamic = Column A item count
}
 
 
# ─────────────────────────────────────────────────────────────────────────────
# LATEX FORMATTING  (appended to every Phase-2 prompt)
# ─────────────────────────────────────────────────────────────────────────────
LATEX_INSTRUCTION = """
LATEX FORMATTING — apply to every question you extract:
- Wrap ALL mathematical expressions, symbols, and formulas in $...$ (inline math).
- Use $$...$$ only for standalone display equations on their own line.
- Common conversions:
    Superscripts  : x²→$x^{2}$  10⁸→$10^{8}$  e⁻→$e^{-}$
    Subscripts    : H₂O→$H_{2}O$  E₀→$E_{0}$
    Fractions     : 1/2→$\\frac{1}{2}$  c/λ→$\\frac{c}{\\lambda}$
    Greek letters : α→$\\alpha$ β→$\\beta$ γ→$\\gamma$ λ→$\\lambda$ μ→$\\mu$
                    ε→$\\varepsilon$ ω→$\\omega$ θ→$\\theta$ φ→$\\phi$
                    Ω→$\\Omega$ Φ→$\\Phi$ ρ→$\\rho$ σ→$\\sigma$
    Operators     : ×→$\\times$ ·→$\\cdot$ ±→$\\pm$ ∝→$\\propto$
                    ≈→$\\approx$ ≠→$\\neq$ ≥→$\\geq$ ≤→$\\leq$
                    √→$\\sqrt{}$ ∞→$\\infty$ ∫→$\\int$ Σ→$\\sum$
    Vectors       : F⃗→$\\vec{F}$  E⃗→$\\vec{E}$  B⃗→$\\vec{B}$
    Units         : Ω→$\\Omega$  μF→$\\mu F$  μC→$\\mu C$
                    μ₀→$\\mu_0$  ε₀→$\\varepsilon_0$  m/s²→$m/s^{2}$
    Blanks (FIB)  : keep as ______  (never wrap in LaTeX)
- Hindi/English text outside math stays plain — never wrap words in $...$
- Number+unit: wrap symbol only: "9×10⁸ m/s" → $9\\times10^{8}$ m/s
"""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# HELPER
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
        # Hard stop: Hindi section reads Q1→Q{N} in order; stop after max_q so we
        # don't bleed into the next section or the English section that follows.
        return (
            f"HARD BOUNDARY: Read ONLY question numbers {min_q} through {max_q}. "
            f"The moment you encounter Q{max_q + 1} or any number beyond Q{max_q}, "
            f"STOP immediately — do not extract from it under any circumstance. "
            f"Content beyond Q{max_q} belongs to a different section."
        )
    else:
        # English: use a SOFT RANGE FILTER instead of a hard stop.
        #
        # Why no hard stop for English:
        #   A hard "stop at Q{max_q+1}" is dangerous on separate-section bilingual papers
        #   (Hindi pages 1–N, English pages N+1 onward) because Q{max_q+1} appears in the
        #   Hindi section BEFORE the model ever reaches the English section.  The model
        #   fires the stop trigger on the Hindi question and never reads the English section.
        #   The language rule (skip Devanagari main-body text) already prevents extracting
        #   Hindi content, so a range filter is enough for section containment.
        stop_hint = ""
        if min_q > 10:
            # For higher question numbers (SA, LA, VLA), add a local stop signal.
            # This is safe here because by the time the model reads Q{max_q+1} in the
            # English section it has already passed the entire Hindi section — so the
            # stop trigger only fires on Latin-script content, not on Hindi content.
            stop_hint = (
                f" These questions (Q{min_q}–Q{max_q}) appear toward the end of the "
                f"English section. Skip all questions numbered below Q{min_q}. "
                f"Once you reach Q{min_q} in the English section, extract through "
                f"Q{max_q}, then STOP the moment you see Q{max_q + 1} — do not "
                f"extract from Q{max_q + 1} or beyond."
            )
        return (
            f"TARGET RANGE (English): Extract ONLY question numbers {min_q} through "
            f"{max_q} from the English (Latin-script) section. "
            f"If you see a question number below {min_q} or above {max_q}, skip it "
            f"and keep scanning. "
            f"IMPORTANT: If this is a bilingual paper with a Hindi (Devanagari) section "
            f"on earlier pages, scan PAST the entire Hindi section to reach the English "
            f"section, then apply this range filter to Latin-script questions only."
            + stop_hint
        )
 
 
def _language_instruction(language: str) -> str:
    if language == "Hindi":
        return """LANGUAGE RULE:
This paper contains questions in TWO possible ways:
  (a) Hindi and English versions appear on the SAME page one after another — in
      that case extract ONLY the Devanagari (Hindi) version of each question.
  (b) Hindi and English versions appear in SEPARATE sections/pages of the PDF —
      in that case read only the Hindi section.
A question is "Hindi" if its MAIN BODY text is written in Devanagari script (क ख ग घ अ आ...).
Science and math questions written in Hindi ROUTINELY contain Latin characters embedded
inside Devanagari text — for example: "C, Si तथा Ge", "P-N संधि", "A.C. जनित्र",
"Ohm का नियम", symbols like V, I, R, E. These are VALID Hindi questions. Do NOT
skip a Hindi question just because it contains scientific symbols, abbreviations, or
proper nouns written in Latin script.
Only skip questions whose ENTIRE main body is written in Latin/Roman script with no
Devanagari text at all."""
    else:
        return """LANGUAGE RULE:
This paper contains questions in TWO possible ways:
  (a) Hindi and English versions appear on the SAME page one after another —
      extract ONLY the Latin/Roman (English) version of each question.
  (b) Hindi and English versions appear in SEPARATE sections/pages of the PDF —
      skip past the entire Hindi (Devanagari) section; extract from the English
      section only (typically the second half of the paper).
A question is "English" if its MAIN BODY text is in Latin/Roman script (a-z, A-Z).
Isolated Hindi words that appear near an English question — such as अथवा (= OR),
section headers, or question numbering labels — are FINE. Do NOT skip an English
question just because a Hindi word or label appears nearby.
Only skip questions whose entire main body text is written in Devanagari script."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Detect paper structure
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

OCR NOTE — scanned papers often have garbled Hindi text. Treat these common
OCR errors as their correct equivalents:
  प्रश्ि / प्रनत / प्रश् / परश्न  →  प्रश्न  (question)
  अऊक / अक / अँक               →  अंक    (marks)
  परतयक / परतयेक               →  प्रत्येक (each)
  उपप्रशन / उपप्रश्ि             →  उपप्रश्न (sub-question)
  नरदश / नरदेश                  →  निर्देश  (instructions)
Do not fail to extract a range just because a keyword looks slightly garbled.

IF INSTRUCTION BLOCK IS UNCLEAR — FALL BACK TO INLINE MARKS:
  Some papers print marks in brackets on the right side of each question:
  e.g.  "Q5. Describe Ohm's law.  [3]"   or  "Q1. (i) ...  [1×5=5]"
  If the top instruction block is missing, incomplete, or ambiguous, scan the
  actual question lines for these bracket marks [ ] and use them to determine
  the mark value and question type instead.
  Read [1×5=5] as: 5 sub-questions × 1 mark each (sub-question block).
  Read [3] as: standalone 3-mark question → Short Answer.
 
════════════════════════════════════════════════════════════
STEP 2 — CLASSIFY EACH RANGE INTO A QUESTION TYPE
════════════════════════════════════════════════════════════
 
CASE A — Sub-question block
  Trigger: instruction says "each sub-question carries 1 mark" for that range
           OR the total marks for the question equal the count of sub-questions
           (e.g. 5-mark question with 5 sub-questions each worth 1 mark).
 
  These parent questions contain multiple 1-mark sub-questions inside them.
  They are NOT "Very Long Answer" even if total marks are 5 or 6.
  You MUST look at the actual content of EACH parent question number
  to determine its sub-type:
 
    If sub-questions have 4 options labeled (i)(ii)(iii)(iv) or (a)(b)(c)(d)
      → Multiple Choice Question
 
    If sub-statements contain blanks written as "......" or "______"
      → Fill in the Blanks
 
    If sub-statements ask to write True/False / सत्य/असत्य
      → True and False
 
    If the question has two columns to match (Column A/B / स्तंभ 'अ'/'ब')
      → Match the Following
 
    If sub-questions are short questions with no options and no blanks,
    expecting a one-word or one-sentence answer
      → One Word Answer
 
  Rules for sub-question blocks:
  • Each parent question number maps to exactly ONE sub-type.
  • Different parent question numbers in the same mark range CAN have
    different sub-types (e.g. Q1=MCQ, Q2=FIB, Q3=T&F, Q4=Match, Q5=OWA).
    Give each its own separate entry in the JSON output.
  • marks_each in the output = 1 (the per-sub-question mark, not the total).
 
CASE B — Standalone question (no sub-question structure)
  Map marks directly:
    2 marks → Very Short Answer
    3 marks → Short Answer
    4 marks → Long Answer
    5 marks → Very Long Answer
    6 marks → Very Long Answer   (treat identically to 5-mark)
 
  Critical rules for CASE B:
  • "Short Answer" (3-mark) may be absent entirely in some papers — that is valid.
    Some papers jump from 2-mark directly to 4-mark. Do NOT invent missing types.
  • "Very Long Answer" may also be absent — that is valid too.
  • If BOTH 5-mark and 6-mark standalone questions exist in one paper, put ALL
    of them under the single "Very Long Answer" key.
  • "Long Answer" (4-mark) and "Very Long Answer" (5/6-mark) are always two
    SEPARATE keys. Never merge 4-mark questions into Very Long Answer.
  • marks_each = the actual mark value from the paper.
 
════════════════════════════════════════════════════════════
STEP 3 — SELF-CHECK BEFORE RETURNING
════════════════════════════════════════════════════════════
Run ALL of these checks. If any fail, re-read the instruction block and fix.
 
  CHECK 1 — COMPLETE COVERAGE
    Every question number from 1 to N (N = total questions printed on the paper
    cover) must appear in exactly ONE type entry. No number may be missing or
    appear in two entries.
 
  CHECK 2 — ABSENT TYPES ARE VALID
    Short Answer or Very Long Answer being absent is CORRECT for some papers.
    Do not add them if the instruction block does not mention a 3-mark or
    5/6-mark standalone section.

  CHECK 3 — LONG ANSWER AND VERY LONG ANSWER ARE ALWAYS SEPARATE KEYS
    4-mark questions go ONLY under "Long Answer".
    5-mark and 6-mark questions go ONLY under "Very Long Answer".
    Never put 4-mark questions under "Very Long Answer" or vice versa.
 
════════════════════════════════════════════════════════════
OUTPUT FORMAT
════════════════════════════════════════════════════════════
Use EXACTLY these English key names (omit any type not present in this paper):
  "Multiple Choice Question"
  "Fill in the Blanks"
  "True and False"
  "One Word Answer"
  "Match the Following"
  "Very Short Answer"
  "Short Answer"
  "Long Answer"
  "Very Long Answer"
 
Each entry:
  { "question_numbers": [list of ints], "marks_each": <int> }
 
Always expand ranges: "Q5 to Q8" / "5 से 8 तक" → [5, 6, 7, 8]
Each key must appear ONLY ONCE in the JSON.
 
════════════════════════════════════════════════════════════
EXAMPLES
════════════════════════════════════════════════════════════
 
Example A — Q1–Q5 are sub-question blocks (5–6 marks total, each sub-question
= 1 mark). Q6–Q12 = 2-mark standalone. Q13–Q16 = 3-mark. Q17–Q20 = 4-mark.
No Very Long Answer section:
{
  "Multiple Choice Question": {"question_numbers": [1],                 "marks_each": 1},
  "Fill in the Blanks":       {"question_numbers": [2],                 "marks_each": 1},
  "True and False":           {"question_numbers": [3],                 "marks_each": 1},
  "Match the Following":      {"question_numbers": [4],                 "marks_each": 1},
  "One Word Answer":          {"question_numbers": [5],                 "marks_each": 1},
  "Very Short Answer":        {"question_numbers": [6,7,8,9,10,11,12], "marks_each": 2},
  "Short Answer":             {"question_numbers": [13,14,15,16],       "marks_each": 3},
  "Long Answer":              {"question_numbers": [17,18,19,20],       "marks_each": 4}
}
 
Example B — Q1–Q4 are sub-question blocks (5 marks total, each sub-question
= 1 mark). Q5–Q7 = 2-mark. Q8–Q10 = 3-mark. Q11–Q15 = 4-mark. Q16–Q18 = 5-mark:
{
  "Multiple Choice Question": {"question_numbers": [1],             "marks_each": 1},
  "Fill in the Blanks":       {"question_numbers": [2],             "marks_each": 1},
  "Match the Following":      {"question_numbers": [3],             "marks_each": 1},
  "One Word Answer":          {"question_numbers": [4],             "marks_each": 1},
  "Very Short Answer":        {"question_numbers": [5,6,7],         "marks_each": 2},
  "Short Answer":             {"question_numbers": [8,9,10],        "marks_each": 3},
  "Long Answer":              {"question_numbers": [11,12,13,14,15],"marks_each": 4},
  "Very Long Answer":         {"question_numbers": [16,17,18],      "marks_each": 5}
}
 
Example C — Q1–Q4 are sub-question blocks. Q5–Q8 = 2-mark. NO 3-mark section.
Q9–Q13 = 4-mark. Q14–Q16 = 5-mark. Q17–Q18 = 6-mark (both 5 and 6 mark go
under Very Long Answer):
{
  "Multiple Choice Question": {"question_numbers": [1],               "marks_each": 1},
  "Fill in the Blanks":       {"question_numbers": [2],               "marks_each": 1},
  "Match the Following":      {"question_numbers": [3],               "marks_each": 1},
  "One Word Answer":          {"question_numbers": [4],               "marks_each": 1},
  "Very Short Answer":        {"question_numbers": [5,6,7,8],         "marks_each": 2},
  "Long Answer":              {"question_numbers": [9,10,11,12,13],   "marks_each": 4},
  "Very Long Answer":         {"question_numbers": [14,15,16,17,18],  "marks_each": 5}
}
 
Now analyse the attached paper and return the correct JSON.
Return ONLY the JSON object, nothing else."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MULTIPLE CHOICE QUESTIONS  (1 mark each sub-question)
# ─────────────────────────────────────────────────────────────────────────────
def mcq_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for the MCQ / बहुविकल्पीय section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting Multiple Choice Questions (MCQ) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
RULES:
1. A parent MCQ question contains sub-questions labeled (a),(b),(c)... or (अ),(ब),(स)...
   Each sub-question WITH its 4 options (i)(ii)(iii)(iv) = ONE individual row.
2. Include the sub-question label and ALL four options as part of the question text.
3. Do NOT treat the whole parent block as one question.
   Each lettered sub-question is its own separate row.
4. Each sub-question = 1 mark.
5. STOP at the hard boundary above — do not read into the next question number.
 
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
 
EXAMPLE (English — same 3 sub-questions, same 3 rows):
{{
  "questions": [
    {{"question": "(a) Majority charge carriers in n-type semiconductors are –\\n(i) Electrons  (ii) Holes  (iii) Neutrons  (iv) Moving ions"}},
    {{"question": "(b) Dielectric constant of air is –\\n(i) Infinite  (ii) Zero  (iii) One  (iv) Two"}},
    {{"question": "(c) Moving charge produces –\\n(i) Only magnetic field  (ii) Only electric field  (iii) Both  (iv) Neither"}}
  ]
}}
 
{LATEX_INSTRUCTION}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# FILL IN THE BLANKS  (1 mark each)
# ─────────────────────────────────────────────────────────────────────────────
def fill_blanks_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for the Fill in the Blanks / रिक्त स्थान section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting Fill in the Blanks questions from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
RULES:
1. Extract ONLY from the targeted question number(s).
2. Each numbered/lettered blank-statement = ONE question row.
3. Represent ALL blanks as "______" in the question text.
4. Do NOT extract True/False statements — those have no blanks.
5. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<statement with ______>"}}
  ]
}}
 
EXAMPLE (Hindi):
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
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# TRUE AND FALSE  (1 mark each)
# ─────────────────────────────────────────────────────────────────────────────
def true_false_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for the True/False / सत्य-असत्य section.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting True/False statements from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
RULES:
1. Extract ONLY from the targeted question number(s).
2. Each lettered statement = ONE question row.
3. Extract the statement text ONLY — do not include any answer.
4. SKIP any item that contains "______" — those are Fill in the Blanks.
5. SKIP any item that ends with a dash "–" — those are One Word Answer stems.
6. A True/False statement is a COMPLETE declarative sentence ending with a full
   stop (। or .) that makes a factual claim. It has no question mark, no blank,
   and no trailing dash.
7. STOP at the hard boundary above.
 
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
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# ONE WORD ANSWER  (1 mark each sub-question)
# ─────────────────────────────────────────────────────────────────────────────
def one_word_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(
        q_nums,
        "Look for: 'One Word Answer' / 'Write answer in one sentence' / "
        "'एक शब्द में उत्तर' / 'एक वाक्य में उत्तर'."
    )
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting One Word Answer questions from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
RULES:
1. Extract ONLY from the targeted question number(s).
2. Each sub-question labeled (a),(b),(c)... or (अ),(ब),(स)... = ONE row.
3. BLANK CHECK — if any item contains "______" → SKIP IT (it is Fill in the Blanks).
4. TRUE/FALSE CHECK — if any item is a complete declarative sentence ending with
   a full stop and no dash → SKIP IT (it is True/False, not OWA).
5. COLUMN B CHECK — do NOT extract bare noun phrases that have no verb context.
   These are Column B items from a nearby Match the Following question and must
   be skipped entirely. See detection rules below.
6. SKIP the section header line itself (e.g. "Write answer in one sentence :").
7. STOP at the hard boundary above.
 
HOW TO DETECT A VALID OWA VERSUS A MATCH COLUMN B ITEM:
  ✓ VALID OWA — ends with "–" (incomplete statement asking for completion)
  ✓ VALID OWA — ends with "?" (direct question)
  ✓ VALID OWA — contains a question word: क्या, कौन, किसे, कितनी, कितना,
                 what, who, which, how many, find, write, state, define
  ✗ SKIP — bare noun phrase with no verb: e.g. "फोटॉन", "गतिशील कण",
            "कार्य फलन", "Moving particle", "Einstein", "Work function"
  ✗ SKIP — definition fragment with no question structure:
            e.g. "सतह से इलेक्ट्रॉन उत्सर्जन हेतु न्यूनतम ऊर्जा"
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<sub-question text>"}}
  ]
}}
 
EXAMPLE (Hindi — 5 sub-questions = 5 rows):
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
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VERY SHORT ANSWER  (2 marks each)
# ─────────────────────────────────────────────────────────────────────────────
def very_short_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for 2-mark questions (Very Short Answer / अति लघु उत्तरीय).")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting Very Short Answer questions (2 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling — READ THIS CAREFULLY:
   - "अथवा" / "OR" is only a separator word — NEVER output it as a question row.
   - If a question has "question A अथवा question B", extract A as one row
     and B as a separate row. Strip "अथवा"/"OR" from the beginning of B.
   - Each question number that has one OR alternative → 2 rows.
   - Each question number without an alternative → 1 row.
3. Do NOT extract from any question number outside TARGET.
4. Do NOT extract from 1-mark sections.
5. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text, no leading अथवा/OR>"}}
  ]
}}
 
EXAMPLE — Two question numbers, each with one OR = 4 rows total (Hindi):
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
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# SHORT ANSWER  (3 marks each)
# ─────────────────────────────────────────────────────────────────────────────
def short_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for 3-mark questions (Short Answer / लघु उत्तरीय).")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting Short Answer questions (3 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER output it as a question row.
   - Each alternative around "अथवा"/"OR" = a separate row.
   - Strip "अथवा" / "OR" from the beginning of any extracted question.
   - One OR per question number = 2 rows for that number.
3. Include sub-parts (a)/(b) in the same string if they share the same question number.
4. Do NOT extract from any question number outside TARGET.
5. STOP at the hard boundary above.
 
OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text — no leading अथवा/OR>"}}
  ]
}}
 
EXAMPLE (Hindi — 2 question numbers each with OR = 4 rows):
{{
  "questions": [
    {{"question": "विद्युत द्विध्रुव के कारण उसकी अक्ष पर स्थित किसी बिंदु पर विद्युत क्षेत्र की तीव्रता का व्यंजक स्थापित कीजिए।"}},
    {{"question": "गॉस प्रमेय की सहायता से कूलॉम के व्युत्क्रम वर्ग नियम का सत्यापन कीजिए।"}},
    {{"question": "एक समान चुंबकीय क्षेत्र में स्थित एक चुंबक पर लगने वाले बलयुग्म आघूर्ण के लिये व्यंजक स्थापित कीजिए।"}},
    {{"question": "दो समतल वृत्ताकार कुण्डलियों के मध्य अन्योन्य प्रेरकत्व के लिये व्यंजक ज्ञात कीजिये।"}}
  ]
}}
 
EXAMPLE (English — same 4 rows):
{{
  "questions": [
    {{"question": "Derive an expression for the intensity of electric field placed at any point on the axis of an electric dipole."}},
    {{"question": "Verify Coulomb inverse square law with the help of Gauss theorem."}},
    {{"question": "Derive an expression for the torque on a bar magnet placed in a uniform magnetic field."}},
    {{"question": "Derive an expression for mutual inductance between two plane circular coils."}}
  ]
}}
 
{LATEX_INSTRUCTION}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# LONG ANSWER  (4 marks each)
# ─────────────────────────────────────────────────────────────────────────────
def long_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for 4-mark questions (Long Answer / दीर्घ उत्तरीय — 4 अंक).")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting Long Answer questions (4 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
IMPORTANT: Extract 4-mark questions ONLY.
Do NOT extract 5-mark or 6-mark questions — those belong to Very Long Answer.
Do NOT extract 2-mark or 3-mark questions — those belong to other sections.
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER output it as a question row.
   - Each alternative around "अथवा"/"OR" = a separate row.
   - Strip "अथवा" / "OR" from the beginning of any extracted question.
   - One OR per question number = 2 rows for that number.
3. Include sub-parts (a)/(b)/(c)/(d) in the same string if they share the question number.
4. Do NOT extract from any question number outside TARGET.
5. If you encounter a question marked 5 or 6 marks, SKIP it entirely.
6. STOP at the hard boundary above.

OUTPUT — return ONLY this JSON:
{{
  "questions": [
    {{"question": "<full question text>"}}
  ]
}}
 
EXAMPLE (Hindi — 2 question numbers each with OR = 4 rows):
{{
  "questions": [
    {{"question": "समांतर प्लेट संधारित्र की धारिता के लिये व्यंजक ज्ञात कीजिए। इसे प्रभावित करने वाले दो कारक लिखिये।"}},
    {{"question": "दिए गए बिन्दुओं के आधार पर व्हीटस्टोन सेतु का वर्णन कीजिए: (a) सिद्धांत (b) नामांकित विद्युत परिपथ (c) आवश्यक शर्त (d) कोई एक उपयोग"}},
    {{"question": "बृत्ताकार धाराबाही कुण्डली की अक्ष पर स्थित बिंदु पर चुंबकीय क्षेत्र की तीव्रता ज्ञात कीजिए।"}},
    {{"question": "प्रत्यावर्ती धारा जनित्र किसे कहते हैं? इसका रेखाचित्र बनाकर कार्यविधि का वर्णन करो।"}}
  ]
}}
 
EXAMPLE (English — same 4 rows):
{{
  "questions": [
    {{"question": "Derive an expression for capacity of parallel plate capacitor and write two factors affecting it."}},
    {{"question": "Describe Wheatstone bridge under following points: (a) Principle (b) Labelled electric circuit (c) Necessary condition (d) Any one use"}},
    {{"question": "Find out the magnetic field intensity at a point situated on the axis of circular current carrying coil."}},
    {{"question": "What is A.C. Generator? Explain its working principle with diagram."}}
  ]
}}
 
{LATEX_INSTRUCTION}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VERY LONG ANSWER  (5 or 6 marks each)
# ─────────────────────────────────────────────────────────────────────────────
def very_long_answer_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(
        q_nums,
        "Look for 5-mark or 6-mark questions (Very Long Answer / दीर्घ उत्तरीय — 5/6 अंक)."
    )
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
    return f"""You are extracting Very Long Answer questions (5 or 6 marks each) from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
 
IMPORTANT: Extract 5-mark and 6-mark questions ONLY.
Do NOT extract 4-mark questions — those belong to Long Answer.
Both 5-mark and 6-mark questions are treated identically here.
 
RULES:
1. Each question number in TARGET produces rows based on OR alternatives.
2. OR / अथवा handling:
   - "अथवा" / "OR" is only a separator — NEVER output it as a question row.
   - Each alternative around "अथवा"/"OR" = a separate row.
   - Strip "अथवा" / "OR" from the beginning of any extracted question.
   - One OR per question number = 2 rows for that number.
3. Include sub-parts (a)/(b)/(c)/(d) in the same string if they share the question number.
4. Do NOT extract from any question number outside TARGET.
5. If you encounter a question marked 4 marks, SKIP it entirely.
6. STOP at the hard boundary above.

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
    {{"question": "ट्रांसफार्मर का वर्णन निम्न बिन्दुओं पर कीजिए:\\n(1) ट्रांसफार्मर के प्रकार\\n(2) नामांकित चित्र\\n(3) सिद्धान्त\\n(4) कोई 2 अनुप्रयोग"}}
  ]
}}
 
EXAMPLE (English — same count):
{{
  "questions": [
    {{"question": "Explain the working of a p-n junction diode under forward and reverse bias. Draw the characteristic curve."}},
    {{"question": "C, Si and Ge have same lattice structure. Why is C insulator while Si and Ge are semiconductors?"}},
    {{"question": "Describe a transformer under the following headings:\\n(1) Kinds of transformer\\n(2) Labelled diagram\\n(3) Principle\\n(4) Any 2 applications"}}
  ]
}}
 
{LATEX_INSTRUCTION}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MATCH THE FOLLOWING  (dynamic marks = Column A item count)
# ─────────────────────────────────────────────────────────────────────────────
def match_following_prompt(language: str, q_nums: list[int] | None = None) -> str:
    ref = _q_ref(q_nums, "Look for Match the Following / स्तंभ मिलाइए blocks.")
    lang = _language_instruction(language)
    boundary = _boundary_instruction(q_nums, language)
 
    if language == "Hindi":
        script_rule = (
            "Extract the Column A and Column B items written in Devanagari (Hindi) script. "
            "If you find a block in Latin script, skip it — that is the English version."
        )
    else:
        script_rule = (
            "Extract the Column A and Column B items written in Latin/Roman (English) script. "
            "If you find a block in Devanagari script, skip it — that is the Hindi version."
        )
 
    return f"""You are extracting Match the Following questions from an exam paper PDF.
 
TARGET: {ref}
{lang}
{boundary}
SCRIPT RULE: {script_rule}
 
RULES:
1. ONE complete block (all Column A items + all Column B items) = ONE question row.
2. MARKS = count of Column A items only (1 mark per Column A item).
   Count the labels (a),(b),(c)... in Column A to get the integer mark value.
3. Format the question text as:
   - All Column A items line by line
   - Then the separator line: ---
   - Then all Column B items line by line
4. Include the column header lines in the text (e.g. "स्तंभ 'अ':" / "Column A:").
5. Do NOT extract from any question number outside TARGET.
6. STOP at the hard boundary above.
 
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
      "question": "स्तंभ 'अ' को स्तंभ 'ब' से मिलाकर सही जोड़ी लिखिए:\\nस्तंभ 'अ':\\n(a) प्रकाश की तीव्रता\\n(b) प्रकाश की आवृत्ति\\n(c) कार्य फलन\\n(d) द्रव्य तरंग\\n(e) देहली आवृत्ति\\n(f) प्रकाश की कणीय प्रकृति\\n---\\nस्तंभ 'ब':\\n(i) सतह से इलेक्ट्रॉन उत्सर्जन हेतु न्यूनतम ऊर्जा\\n(ii) सतह से इलेक्ट्रॉन उत्सर्जन हेतु न्यूनतम आवृत्ति\\n(iii) फोटॉन की आवृत्ति\\n(iv) फोटॉन की संख्या\\n(v) गतिशील कण\\n(vi) फोटॉन\\n(vii) आईन्स्टीन",
      "marks": 6
    }}
  ]
}}
 
EXAMPLE (English — same block in English, same marks count):
{{
  "questions": [
    {{
      "question": "Match the column 'A' with column 'B' and write the correct pair:\\nColumn A:\\n(a) Intensity of light\\n(b) Frequency of light\\n(c) Work function\\n(d) Matter waves\\n(e) Threshold frequency\\n(f) Particle nature of light\\n---\\nColumn B:\\n(i) Minimum energy to emit electrons from the surface\\n(ii) Minimum frequency to emit electrons from the surface\\n(iii) Frequency of photon\\n(iv) Number of photons\\n(v) Moving particle\\n(vi) Photon\\n(vii) Einstein",
      "marks": 6
    }}
  ]
}}
 
{LATEX_INSTRUCTION}
Return ONLY the JSON object with "questions" key."""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Chapter mapping
# ─────────────────────────────────────────────────────────────────────────────
def chapter_mapping_prompt(questions: list, chapters: list) -> str:
    chapter_lines = "\n".join(
        f"  {c['number']}. {c['name']}" for c in chapters
    )
    question_lines = "\n".join(
        f"  Q{i + 1}: {q}" for i, q in enumerate(questions)
    )
    n = len(questions)
    return f"""You are a curriculum expert. Assign the most appropriate chapter to each exam question.
 
CHAPTER LIST:
{chapter_lines}
 
QUESTIONS (may be in Hindi or English — analyse the concept being tested, not the language):
{question_lines}
 
RULES:
1. For EACH question, pick the SINGLE most relevant chapter from the list above.
2. chapter_number and chapter_name must EXACTLY match the values in the list.
3. If a question spans multiple topics, choose the PRIMARY / dominant concept.
4. Return EXACTLY {n} objects — one per question, in the same order.
 
OUTPUT — return ONLY this JSON array, nothing else:
[
  {{"chapter_number": <int>, "chapter_name": "<exact name from list>"}},
  ...
]"""
 
 
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