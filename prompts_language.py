"""
Language paper extraction prompts — Hindi and English.
Used when subject is "Hindi" or "English" (language papers, not science/math).
 
Phase 1 — detect paper sections (Comprehension / Writing / Grammar / Literature / Objective)
         + self-check: sum(marks_total for all sections) must equal paper's declared Maximum Marks.
 
Phase 2 — type-specific extraction per section:
    comprehension_engine_prompt   ->  passage + sub-questions (one row per passage)
    writing_engine_prompt         ->  essay/letter/application (one row per task)
    grammar_hindi_prompt          ->  sandhi/samas/alankar/ras (one row per item)
    grammar_english_prompt        ->  gap-fill/transformation/error (one row per item)
    literature_prompt             ->  short/long answer/reference to context
    mcq_prompt                    ->  objective MCQ items (language-agnostic)
    fill_blanks_prompt            ->  fill-in-the-blank items (language-agnostic)
    match_following_prompt        ->  match-the-columns items
    one_word_answer_prompt        ->  one-word / one-sentence answer items
    true_false_prompt             ->  true/false items
"""
 
from prompts import LATEX_INSTRUCTION
 
 
# =============================================================================
# SHARED HELPER BUILDERS  (private)
# =============================================================================
 
def _qref(q_nums, fallback):
    if q_nums:
        return "Extract ONLY from question number(s): " + ", ".join(f"Q{n}" for n in q_nums) + "."
    return fallback
 
 
def _boundary_instruction(q_nums):
    """Hard stop: do not read past max_q."""
    if not q_nums:
        return ""
    min_q = min(q_nums)
    max_q = max(q_nums)
    return f"""
-------------------------------------------------------------
HARD BOUNDARY - MANDATORY
-------------------------------------------------------------
Read ONLY question numbers {min_q} through {max_q}.
Question numbers may be written as Q{min_q}, Q.{min_q}, {min_q}., or Roman numerals — all formats count.
Stop immediately when you reach question {max_q + 1} (in any format) or any new section header
that follows question {max_q}. Do NOT extract anything beyond question {max_q}.
"""
 
 
def _sub_question_count_instruction(label="sub-items"):
    """Mandatory pre-extraction count (Steps A / B / C)."""
    return f"""
-------------------------------------------------------------
MANDATORY PRE-EXTRACTION - COUNT BEFORE BUILDING JSON
-------------------------------------------------------------
STEP A - Physically count every {label} across ALL question numbers in scope.
         Example:
           Q6: (i)(ii)(iii)(iv)(v)(vi)(vii) = 7 {label}
           Q7: (i)(ii)(iii)(iv)(v)(vi)(vii) = 7 {label}
           TOTAL = 14
 
STEP B - Extract ALL items found in Step A. Do NOT stop early.
 
STEP C - SELF-CHECK: count your JSON array length.
         If count < TOTAL from Step A, re-scan and add the missing items.
         Common miss: stopped at (kh)/(b)/(ii) when (g)(gh)/(c)/(d)/(iii)+ still follow.
"""
 
 
def _or_counting_instruction(or_word="OR"):
    """Mandatory OR-counting pre-step for writing / literature prompts."""
    return f"""
-------------------------------------------------------------
MANDATORY PRE-STEP - COUNT {or_word} ALTERNATIVES BEFORE BUILDING JSON
-------------------------------------------------------------
STEP A - Scan all questions in scope and count:
         W = questions that offer a '{or_word}' alternative  (each becomes 2 rows)
         N = questions WITHOUT any '{or_word}' alternative   (each becomes 1 row)
 
STEP B - Minimum expected rows = (W x 2) + N
 
STEP C - Build the JSON "questions" array.
 
STEP D - FINAL CHECK: count JSON items.
         If count < (W x 2) + N, re-read the section and add the missing rows.
         Most common miss: forgot to emit the second '{or_word}' alternative as its own row.
"""
 
 
def _final_count_check(item_label="questions"):
    """Final self-count block appended to every extracting prompt."""
    return f"""
-------------------------------------------------------------
FINAL CHECK - MANDATORY BEFORE RETURNING OUTPUT
-------------------------------------------------------------
Count the items in your JSON "{item_label}" array.
If the count is less than the TOTAL you computed in the pre-extraction step,
re-scan and add the missing items.
Common misses:
  * Stopped at (kh)/(b) when (g)/(gh)/(c)/(d) follow.
  * Forgot the second OR / athhva alternative as a separate row.
  * Skipped an item inside a 'do any N of M' block.
  * Missed a sub-question on a continuation page.
"""
 
 
# =============================================================================
# SHARED SKILL CATEGORY DETECTION RULE
# (reused verbatim in FillBlanks, OneWordAnswer, MatchFollowing, MCQ)
# =============================================================================
 
_SKILL_CATEGORY_DETECTION = """
- skill_category detection rules:
    * If the item names / references a specific lesson, poem, chapter, author, or
      character from the textbook  ->  "Literature"   (also set lesson_name)
    * If the item tests grammar terminology: ras, alankar, chhand, sandhi, samas,
      nipat, vachya, kaal, muhavare, lokokti, shabd shakti, vakya bhed, upasarg,
      pratyay, tatsam-tadbhav, etc.  ->  "Grammar"   (lesson_name = null)
    * General literary / journalistic / language knowledge not tied to a specific
      textbook chapter  ->  "General"   (lesson_name = null)
- lesson_name: set ONLY when skill_category = "Literature" AND the lesson / poem
  is clearly identifiable from the item text or its options. null in all other cases.
"""
 
 
# =============================================================================
# PHASE 1 - STRUCTURE DETECTION
# =============================================================================
 
def language_structure_prompt_hindi():
    return """You are an expert at analysing Hindi examination papers.
Your task is to read the FULL paper and identify its major sections.
 
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Read the paper's instruction block (usually labelled nirdesh / samanya nirdesh at
the top) AND the paper body. Identify every major section and classify it.
 
SECTION TYPES:
    Comprehension   ->  apathit bodh, apathit gadyansh, apathit kavyansh, unseen passage
    Writing         ->  lekhan, rachnatmak lekhan, patra-lekhan, nibandh
    Grammar         ->  vyakaran, vyakaran evam rachna, bhasha-gyan
                        (sandhi / samas / alankar / ras / vachya / kaal sub-questions)
    Literature      ->  pathyapustak, sahitya, kshitij, sparsh, aaroh, vitan, antara,
                        sanchayan, kritika  -- questions about textbook chapters/poems/authors
    Objective       ->  Q1-Q5 style objective blocks at the start of the paper.
                        These test literature/general knowledge through objective formats.
                        Assign sub_type based on question FORMAT (see below).
 
OBJECTIVE SUB-TYPES - detect by question FORMAT, NOT by content topic:
    sub_type "MCQ"            -> bahuvikalpiya, options (a)(b)(s)(d) or (a)(b)(c)(d)
    sub_type "FillBlanks"     -> rikt sthan bhariye, choose from options in brackets
    sub_type "MatchFollowing" -> sahi jodi banaiye, two columns 'ka' and 'kha'
    sub_type "OneWordAnswer"  -> ek shabd / ek vakya mein uttar dijiye
    sub_type "TrueFalse"      -> satya / asatya ka chayan kijiye
 
PROMPT ROUTING - fill the "prompt" field for each section:
    sub_type MCQ              -> "mcq_prompt"
    sub_type FillBlanks       -> "fill_blanks_prompt"
    sub_type MatchFollowing   -> "match_following_prompt"
    sub_type OneWordAnswer    -> "one_word_answer_prompt"
    sub_type TrueFalse        -> "true_false_prompt"
    type Comprehension        -> "comprehension_engine_prompt"
    type Writing              -> "writing_engine_prompt"
    type Grammar              -> "grammar_hindi_prompt"
    type Literature           -> "literature_prompt"
 
CRITICAL ROUTING RULE FOR APATHIT (Q19 pattern):
    If an apathit passage question (kavyansh or gadyansh for unseen comprehension) appears
    INSIDE the short-answer or long-answer section (e.g. Q19 with a poem+questions),
    it MUST be routed to "comprehension_engine_prompt", NOT "literature_prompt".
    Mark its type as "Comprehension" in the sections array even if surrounded by
    literature questions.
 
-------------------------------------------------------------
KEY VOCABULARY / OCR EQUIVALENTS
-------------------------------------------------------------
    khand / khanda  = section (same word)
    prashni / pranati  ->  prashna  (OCR artefact)
    aook / ak   ->  ank    (OCR artefact)
    i at end of word ->  often = n
 
-------------------------------------------------------------
HOW TO IDENTIFY SECTION BOUNDARIES
-------------------------------------------------------------
1. Look for bold/capitalised labels: khand-a, khand-b, bhag-1, etc.
2. Read the instruction block: "khand 'a' mein ... 20 ank nirdharit hain."
3. Identify which question numbers belong to each section.
4. Record total_marks from the instruction block or by summing individual Q marks.
 
FALLBACK (if instruction block absent/unreadable):
    Scan the body for section headers. Infer from content:
    passage + questions -> Comprehension
    nibandh / patra / vigyapan -> Writing
    sandhi / samas / alankar / ras sub-items -> Grammar
    chapter/poet/author references -> Literature
    MCQ/FIB/Match/OWA/TF block at paper start -> Objective with sub_type
 
-------------------------------------------------------------
SELF-CHECK BEFORE OUTPUT
-------------------------------------------------------------
Rule 1: Every question number 1 ... N must appear in EXACTLY ONE section.
Rule 2: sum(marks_total for all sections) MUST equal the paper's declared Maximum Marks.
        If Rule 2 fails, set "marks_discrepancy" to a string describing the issue,
        e.g. "Sum is 76 but declared max is 80. Grammar section Q8 marks uncertain."
 
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{
  "declared_max_marks": 80,
  "sections_marks_sum": 80,
  "marks_discrepancy": null,
  "sections": [
    {"name": "vastunishth", "type": "Objective", "sub_type": "MCQ",            "q_nums": [1],       "marks_total": 6,  "prompt": "mcq_prompt"},
    {"name": "vastunishth", "type": "Objective", "sub_type": "FillBlanks",     "q_nums": [2],       "marks_total": 7,  "prompt": "fill_blanks_prompt"},
    {"name": "vastunishth", "type": "Objective", "sub_type": "MatchFollowing", "q_nums": [3],       "marks_total": 6,  "prompt": "match_following_prompt"},
    {"name": "vastunishth", "type": "Objective", "sub_type": "OneWordAnswer",  "q_nums": [4],       "marks_total": 7,  "prompt": "one_word_answer_prompt"},
    {"name": "vastunishth", "type": "Objective", "sub_type": "TrueFalse",      "q_nums": [5],       "marks_total": 6,  "prompt": "true_false_prompt"},
    {"name": "ati laghu uttariya", "type": "Literature", "sub_type": null,     "q_nums": [6,7,8,9,10,11,12,13,14,15], "marks_total": 20, "prompt": "literature_prompt"},
    {"name": "laghu uttariya",     "type": "Literature", "sub_type": null,     "q_nums": [16,17,18],"marks_total": 9,  "prompt": "literature_prompt"},
    {"name": "apathit bodh",       "type": "Comprehension","sub_type": null,   "q_nums": [19],      "marks_total": 3,  "prompt": "comprehension_engine_prompt"},
    {"name": "dirgha uttariya",    "type": "Literature", "sub_type": null,     "q_nums": [20,21],   "marks_total": 8,  "prompt": "literature_prompt"},
    {"name": "lekhan",             "type": "Writing",    "sub_type": null,     "q_nums": [22,23],   "marks_total": 8,  "prompt": "writing_engine_prompt"}
  ]
}
 
Rules for the JSON:
- "name"         : exact label from paper; if absent use canonical Hindi name (romanised is fine).
- "type"         : one of "Comprehension", "Writing", "Grammar", "Literature", "Objective".
- "sub_type"     : one of "MCQ","FillBlanks","MatchFollowing","OneWordAnswer","TrueFalse", or null.
- "q_nums"       : ascending array of integers.
- "marks_total"  : integer.
- "prompt"       : extraction prompt to call for this section (see PROMPT ROUTING above).
- Output ONLY the JSON object. No markdown fences, no explanation text.
"""
 
 
def language_structure_prompt_english():
    return """You are an expert at analysing English language examination papers.
Your task is to read the FULL paper and identify its major sections.
 
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Read the paper's instruction block (usually labelled "General Instructions",
"Directions", or appearing at the top) AND the paper body. Classify every section.
 
SECTION TYPES:
    Comprehension   ->  Reading Comprehension, Unseen Passage, Reading Section, Note-Making
    Writing         ->  Writing Skills, Writing Section, Composition, Creative Writing
    Grammar         ->  Grammar, Language Study, Grammar and Composition, Grammar Usage
    Literature      ->  Literature, Textbook, Supplementary Reader, Fiction, Poetry, Drama
 
KEY HEADER PATTERNS:
    Section A / Part A  -> typically Reading / Comprehension
    Section B / Part B  -> typically Writing
    Section C / Part C  -> typically Grammar  OR  Literature
    Section D / Part D  -> typically Literature
    "Unseen Passage", "Note-Making"                                          -> Comprehension
    "Essay", "Letter", "Notice", "Report", "Article", "Speech", "Advertisement" -> Writing
    "Gap Filling", "Editing", "Transformation", "Reported Speech"           -> Grammar
    Lesson/poem title references, extract-based questions                   -> Literature
 
-------------------------------------------------------------
HOW TO IDENTIFY SECTION BOUNDARIES
-------------------------------------------------------------
1. Look for bold/capitalised labels: SECTION A, SECTION B - Writing Skills, etc.
2. Read the instruction block: "Section A carries 20 marks and contains two passages."
3. Identify which question numbers belong to each section.
4. Record total_marks from the instruction block or by summing individual Q marks.
 
FALLBACK (if instruction block absent/unreadable):
    passage + questions about it -> Comprehension
    essay / letter / notice / report -> Writing
    fill-in-blank / error correction / reordering -> Grammar
    chapter title / author / poet / extract quote -> Literature
 
-------------------------------------------------------------
SELF-CHECK BEFORE OUTPUT
-------------------------------------------------------------
Rule 1: Every question number 1 ... N must appear in EXACTLY ONE section.
Rule 2: sum(marks_total for all sections) MUST equal the paper's declared Maximum Marks.
        If Rule 2 fails, set "marks_discrepancy" to a string describing the issue.
 
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{
  "declared_max_marks": 80,
  "sections_marks_sum": 80,
  "marks_discrepancy": null,
  "sections": [
    {"name": "Reading Comprehension", "type": "Comprehension", "sub_type": null, "q_nums": [1, 2],            "marks_total": 13, "prompt": "comprehension_engine_prompt"},
    {"name": "Writing Skills",        "type": "Writing",       "sub_type": null, "q_nums": [3, 4, 5],         "marks_total": 12, "prompt": "writing_engine_prompt"},
    {"name": "Grammar",               "type": "Grammar",       "sub_type": null, "q_nums": [6, 7],            "marks_total": 10, "prompt": "grammar_english_prompt"},
    {"name": "Literature",            "type": "Literature",    "sub_type": null, "q_nums": [8,9,10,11,12,13,14,15], "marks_total": 45, "prompt": "literature_prompt"}
  ]
}
 
Rules for the JSON:
- "name"        : exact label from paper; if absent use canonical English name.
- "type"        : one of "Comprehension", "Writing", "Grammar", "Literature".
- "sub_type"    : null for most sections; "MCQ"/"FillBlanks" etc. if English paper has objective block.
- "q_nums"      : ascending array of integers.
- "marks_total" : integer.
- "prompt"      : extraction prompt to call for this section.
- Output ONLY the JSON object. No markdown fences, no explanation text.
"""
 
 
# =============================================================================
# PHASE 2 - COMPREHENSION
# =============================================================================
 
def comprehension_engine_prompt(language: str, q_nums: list[int] | None = None):
    qref = _qref(q_nums, "Extract ALL comprehension passages found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("sub-questions")
    final_check = _final_count_check("passages -> sub_questions per passage")
 
    hindi_instructions = """
-------------------------------------------------------------
HINDI-SPECIFIC RULES
-------------------------------------------------------------
- Look for gadyansh (Prose passage) and kavyansh (Poetry passage).
- gadyansh -> passage_type = "Prose".  kavyansh -> passage_type = "Poetry".
- body_text: the FULL Hindi text of the passage - every sentence / every line of verse.
- Sub-questions are labelled (ka)(kha)(ga)(gha) or (i)(ii)(iii) or 1. 2. 3.
- For MCQ-type sub-questions: capture ALL four options (a)(b)(s)(d) inside the
  sub_question object's "text" field.
- If the passage asks for shirshak, shabdarth, or saransh, include those as sub-questions.
- total_marks = sum of marks written after each sub-question.
- IMPORTANT: This prompt is also used for Q19-type apathit passages that appear
  physically inside the short-answer section of the paper. Treat them identically.
"""
 
    english_instructions = """
-------------------------------------------------------------
ENGLISH-SPECIFIC RULES
-------------------------------------------------------------
- Look for "Unseen Passage", "Read the following passage", "Comprehension" labels.
- passage_type = "Prose" for prose; "Poetry" for poem-based comprehension.
- Sub-questions include: MCQs (ALL 4 options), short answer, vocabulary, note-making,
  title-choosing, and summary/précis tasks.
- For MCQ sub-questions: capture ALL four options (a)(b)(c)(d) inside the sub_question
  object's "text" field. Example:
    "(i) Education is a sub-system of the wider ___.\n(a) social system  (b) political system\n(c) economical system  (d) religious system"
- Note-making and title-giving under the SAME passage -> both are sub-questions of
  that single passage. Do NOT split them into separate passage objects.
- total_marks = sum of marks written after each sub-question.
"""
 
    language_block = hindi_instructions if language == "Hindi" else english_instructions
 
    return f"""You are an expert at extracting comprehension questions from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every comprehension passage and all its sub-questions.
Produce ONE JSON object per passage. Two passages -> two objects in "passages" array.
{count_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
body_text     : COMPLETE text of the passage - every sentence, every line of poetry.
               Do NOT truncate or summarise. Preserve paragraph breaks as \\n\\n.
               For poetry: lines within a stanza separated by \\n; stanzas by \\n\\n.
 
sub_questions : Array of OBJECTS (not plain strings). Each object:
               {{
                 "text":  "(i) Full sub-question text including all MCQ options if any",
                 "type":  one of "MCQ" | "ShortAnswer" | "NoteMaking" | "TitleGiving" | "VocabMeaning",
                 "marks": integer marks for this sub-question
               }}
 
total_marks   : Integer. Sum of all sub-question marks.
 
passage_type  : "Prose" or "Poetry".
{language_block}
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Do NOT omit any sub-question. Count first (pre-extraction step above), then extract.
- Do NOT include the passage label line ("Q1. Read the following passage...") in body_text.
- Do NOT include question number labels (Q.1, prashna 1) in body_text.
- If OCR splits the passage across pages, reconstruct it as one continuous body_text.
- Sub-question type detection:
    options (a)(b)(c)(d) or MCQ options present   -> "MCQ"
    "make notes" / "note-making" / note instruction -> "NoteMaking"
    "give a title" / "shirshak"                    -> "TitleGiving"
    "find the meaning" / "shabdarth" / vocabulary  -> "VocabMeaning"
    all others                                     -> "ShortAnswer"
 
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "passages": [
    {{
      "body_text": "full passage text here - every word, every line",
      "sub_questions": [
        {{"text": "(i) Education is a sub-system of the wider ___\\n(a) social system  (b) political system\\n(c) economical system  (d) religious system", "type": "MCQ", "marks": 1}},
        {{"text": "(ii) Make notes on the above passage.", "type": "NoteMaking", "marks": 2}},
        {{"text": "(iii) Give a suitable title to the passage.", "type": "TitleGiving", "marks": 1}}
      ],
      "total_marks": 10,
      "passage_type": "Prose"
    }}
  ]
}}
"""
 
 
# =============================================================================
# PHASE 2 - WRITING
# =============================================================================
 
def writing_engine_prompt(language: str, q_nums: list[int] | None = None):
    qref = _qref(q_nums, "Extract ALL writing tasks found in the paper.")
    boundary = _boundary_instruction(q_nums)
    or_word = "अथवा / OR  (either word, or both, acts as separator)" if language == "Hindi" else "OR"
    or_step = _or_counting_instruction(or_word)
    final_check = _final_count_check("questions")
 
    hindi_categories = """
-------------------------------------------------------------
HINDI skill_category VALUES - use EXACTLY one of these
-------------------------------------------------------------
    "nibandh lekhan"       -- nibandh, nibandh-lekhan, essay
    "aupcharik patra"      -- aupcharik patra, formal letter, official letter,
                              pradhanacharya ko patra, sampadak ko patra,
                              jiladhish ko patra, adhikari ko patra
    "anaupcharik patra"    -- anaupcharik patra, informal letter,
                              mitra ko patra, mata-pita ko patra, pitaji ko patra
    "avedan patra"         -- avedan patra, application, prarthana patra
    "kahani lekhan"        -- kahani, story writing, kahani poorn kijiye
    "vigyapan lekhan"      -- vigyapan, advertisement, poster
    "samvad lekhan"        -- samvad, dialogue writing, batchit,
                              do mitron ke beech samvad
    "anuchchhed lekhan"    -- anuchchhed, paragraph writing, laghu nibandh
    "bhav vistar"          -- bhav vistar kijiye, expand the idea
 
Detection keywords:
    nibandh                                              -> "nibandh lekhan"
    patra + (aupcharik / pradhanacharya / sampadak /
             karyalay / jiladhish / adhikari)           -> "aupcharik patra"
    patra + (mitra / maa / pita / anaupcharik / pitaji) -> "anaupcharik patra"
    avedan / prarthana-patra                             -> "avedan patra"
    kahani                                               -> "kahani lekhan"
    vigyapan / poster                                    -> "vigyapan lekhan"
    samvad / vartalaap                                   -> "samvad lekhan"
    anuchchhed                                           -> "anuchchhed lekhan"
    bhav vistar                                          -> "bhav vistar"
"""
 
    english_categories = """
-------------------------------------------------------------
ENGLISH skill_category VALUES - use EXACTLY one of these
-------------------------------------------------------------
    "Essay Writing"          -- essay, composition, write an essay, paragraph on topic
    "Formal Letter"          -- formal letter, official letter, letter to principal,
                               letter to editor, complaint letter, invitation letter,
                               letter to authority
                               NOTE: "invitation letter" -> "Formal Letter" (formal communication)
    "Informal Letter"        -- informal letter, personal letter,
                               letter to friend, letter to relative
    "Article Writing"        -- article, write an article for a newspaper/magazine
    "Notice Writing"         -- notice, draft a notice
    "Advertisement Writing"  -- advertisement, classified advertisement, poster
    "Report Writing"         -- report, write a report, newspaper report
    "Speech Writing"         -- speech, write a speech, address
    "Story Writing"          -- story, creative story, complete the story
 
Detection keywords:
    essay / composition / paragraph on ... topic              -> "Essay Writing"
    formal / official / principal / editor /
    invitation letter / letter to authority                   -> "Formal Letter"
    letter to friend / personal / informal                    -> "Informal Letter"
    article                                                   -> "Article Writing"
    notice                                                    -> "Notice Writing"
    advertisement / poster                                    -> "Advertisement Writing"
    report / newspaper report                                 -> "Report Writing"
    speech                                                    -> "Speech Writing"
    story                                                     -> "Story Writing"
"""
 
    categories_block = hindi_categories if language == "Hindi" else english_categories
 
    return f"""You are an expert at extracting writing tasks from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every writing task. Produce ONE JSON row per task.
If a question offers a choice between two writing tasks separated by OR / athhva,
produce TWO separate rows - one for each option.
{or_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question       : COMPLETE writing task text — include EVERYTHING in this field:
                (a) The main instruction (what to write).
                (b) Any role/scenario given to the student (e.g. "You are Amit/Amita...").
                (c) Any hints, bullet points, or format guidelines — place on separate lines.
                (d) Word limit if specified (e.g. "Word limit: 120 words").
                Use \\n to separate lines. Do NOT put context in a separate field.
 
skill_category : Classify the writing task (see list below).
 
topic_options  : (OPTIONAL) Array of strings when the task offers multiple topic choices
                the student can pick from (e.g. "write on ANY ONE of the following").
                List each topic as a separate string. Omit or null if not applicable.
 
marks          : Integer marks for this task.
{categories_block}
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- OR / athhva separating two COMPLETE writing tasks -> 2 rows, same marks.
  Strip "OR" / "athhva" from the very start of the second row's question field.
- "Write on ANY ONE of the following N topics" -> ONE row; all topics go in topic_options.
- Word limits ("in about 120 words") -> embed inside question on its own line.
- Role/scenario lines ("You are Amit/Amita...", "Imagine you are...") -> embed inside question.
- Do NOT include marks labels like "[4]" or "(4 ank)" in the question field.
- If sub-items (ka)(kha)(ga) or (i)(ii)(iii) are offered as topic choices within ONE task,
  list them in topic_options - do NOT split into separate rows.
- NEVER create an inputs_given field - everything goes into question or topic_options.
 
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "Draft a notice giving information about the selection of two participants for the inter-school debate competition.\nYou are Amit/Amita, the cultural secretary of your school.",
      "skill_category": "Notice Writing",
      "topic_options": null,
      "marks": 4
    }},
    {{
      "question": "Write a paragraph in about 120 words on any one of the following topics.\nWord limit: 120 words",
      "skill_category": "Essay Writing",
      "topic_options": ["Science and Technology", "The importance of English Language", "My Ideal Leader", "Online learning uses and abuses"],
      "marks": 4
    }},
    {{
      "question": "Write a letter to the editor of your local newspaper expressing your concern over the increase in road accidents and rash driving, and suggest ways to control accidents.\nYou are Rahul/Rohini of 12B.\nGive possible solutions.",
      "skill_category": "Formal Letter",
      "topic_options": null,
      "marks": 5
    }}
  ]
}}
"""
 
 
# =============================================================================
# PHASE 2 - GRAMMAR (HINDI)
# =============================================================================
 
def grammar_hindi_prompt(q_nums: list[int] | None = None):
    qref = _qref(q_nums, "Extract ALL Hindi grammar items found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("grammar sub-items")
    final_check = _final_count_check("questions")
 
    return f"""You are an expert at extracting individual Hindi grammar exercise items from examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Each grammar question is a PARENT containing multiple sub-items labelled
(ka)(kha)(ga)(gha) or (i)(ii)(iii) or (a)(b)(c)(d) or 1. 2. 3. etc.
 
Produce ONE JSON row for EACH individual sub-item.
Do NOT produce a row for the parent instruction line.
 
WRONG:  question: "nimnalikhit shabdon ki sandhi kijiye:" <- parent line, SKIP
RIGHT:  question: "(ka) surya + uday ki sandhi kijiye."  <- sub-item, INCLUDE
{count_step}
-------------------------------------------------------------
OCR ACCURACY - CRITICAL FOR GRAMMAR TERMS
-------------------------------------------------------------
These are the EXACT terms being tested. Verify spelling before returning:
    sandhi      (not sadhi / sandhee)
    samas       (not saamas)
    alankar     (not alankar / alankaar)
    vyakaran    (not vyakaran with missing a)
    vachya      (not vachyr)
    upasarg     (not upasarg with missing a)
    pratyay     (correctly spelled)
 
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question       : Complete text of the individual sub-item. Include its label (ka)(kha)(i)(ii)
                at the START. If the operation verb comes from the parent instruction,
                incorporate it into the sub-item question.
                  Parent: "nimnalikhit mein sandhi-vichchhed kijiye:"
                  Sub:    "(ka) suryoday"
                  -> Row: "(ka) suryoday ka sandhi-vichchhed kijiye."
 
skill_category : Category of grammar (see list below).
 
marks          : Marks for this single sub-item (usually 1).
                If parent says "4x1=4", each sub-item = 1 mark.
 
-------------------------------------------------------------
skill_category VALUES - use EXACTLY one of these
-------------------------------------------------------------
    "sandhi"              -- sandhi kijiye, sandhi-vichchhed kijiye
    "samas"               -- samas vigrah kijiye, samas ka naam bataiye, samasik pad banaiye
    "alankar"             -- alankar pahchaniye, alankar ka naam likhiye
    "ras"                 -- ras pahchaniye, ras ka naam likhiye, ras ki paribhasha aur udaharan
    "chhand"              -- chhand ki paribhasha, chhand ka naam, kavitt / chaupai / doha / soratha
    "vakya bhed"          -- vakya bhed bataiye, saral/sanyukt/mishr vakya mein badliye,
                             vakya shuddh kijiye, nirdeshanusar vakya parivartit kijiye
    "muhavare"            -- muhavare ka arth, muhavare ka vakya mein prayog
    "lokoktiyan"          -- lokokti ka arth, vakya mein prayog
    "upasarg-pratyay"     -- upasarg/pratyay lagaiye, pahchaniye
    "vachya"              -- vachya pahchaniye, vachya badliye
    "kaal"                -- kaal badliye, kaal pahchaniye
    "karak"               -- karak pahchaniye, vibhakti bataiye
    "tatsam-tadbhav"      -- tatsam roop likhiye, tadbhav roop likhiye
    "shabd shakti"        -- shabd-shakti ki paribhasha aur udaharan (abhidha/lakshana/vyanjana)
    "takniki shabd"       -- takniki shabd ka arth, do takniki shabd likhiye
    "rashtra bhasha"      -- rashtra bhasha ki visheshataen
    "vakya parivartit"    -- nirdeshanusar vakya parivartit kijiye (prashnvachak/nakaratmak)
 
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Read ALL sub-items to the end - do NOT stop at (kha) if (ga)(gha) also exist.
- For alankar/ras/chhand questions: include the COMPLETE sentence or verse couplet.
- Do NOT include the parent instruction as a row.
- Do NOT include marks labels like "(1 ank)" or "[1]" in the question text.
- Preserve Devanagari script exactly; do not transliterate.
 
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "(ka) surya + uday ki sandhi kijiye.",
      "skill_category": "sandhi",
      "marks": 1
    }},
    {{
      "question": "(kha) deshbhakti ka samas vigrah kijiye.",
      "skill_category": "samas",
      "marks": 1
    }}
  ]
}}
"""
 
 
# =============================================================================
# PHASE 2 - GRAMMAR (ENGLISH)
# =============================================================================
 
def grammar_english_prompt(q_nums: list[int] | None = None):
    qref = _qref(q_nums, "Extract ALL English grammar items found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("grammar sub-items")
    final_check = _final_count_check("questions")
 
    return f"""You are an expert at extracting individual English grammar exercise items from examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Each grammar question is a PARENT containing multiple sub-items labelled
(a)(b)(c)(d) or (i)(ii)(iii)(iv) or 1. 2. 3. etc.
 
Produce ONE JSON row for EACH individual sub-item.
Do NOT produce a row for the parent instruction line.
 
WRONG: question: "Fill in the blanks with the correct form of the verb:" <- parent
RIGHT: question: "(a) He _____ (go) to school every day."               <- sub-item
{count_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question       : Complete text of the individual sub-item. Include its label at the START.
                If the operation verb comes from the parent, incorporate it:
                  Parent: "Transform into passive voice:"
                  Sub:    "(i) She is singing a song."
                  -> Row: "(i) Transform into passive voice: She is singing a song."
                For Gap Filling items that have MCQ options (a)(b)(c)(d) listed:
                  ALWAYS include ALL options in the question text on a new line.
                  Example: "(ii) Would you like to have _____ tea or coffee?\n(a) some  (b) any  (c) a  (d) no"
                For Gap Filling items without options: include just the sentence with blank.
 
skill_category : Category (see list below).
 
directive      : (OPTIONAL) The specific instruction in parentheses after the sentence.
                Captures granularity within "Sentence Transformation".
                Examples: "change the voice", "combine using both...and",
                          "rewrite using positive degree", "rewrite using as soon as",
                          "combine to make a complex sentence", "change into negative",
                          "combine using so...that".
                Set to null if not applicable.
 
marks          : Marks for this single sub-item (usually 1).
 
attempt_any    : (TOP-LEVEL field, not per-question) Integer. Present only when the
                parent says "attempt any N of 7" etc. Extract ALL M sub-items regardless.
 
-------------------------------------------------------------
skill_category VALUES - use EXACTLY one of these
-------------------------------------------------------------
    "Gap Filling"              -- fill in the blank(s), choose the correct option to fill,
                                  preposition / determiner / article / tense / modal choice
    "Sentence Transformation"  -- transform, change into (passive/active/direct/indirect/
                                  degree/negative), combine sentences, rewrite using ...
    "Error Correction"         -- find/spot/underline the error, correct the mistake
    "Reported Speech"          -- change into reported/indirect/direct speech
    "Reordering"               -- rearrange/reorder jumbled words or sentences
    "Editing"                  -- edit the passage, correct the passage (passage-level)
    "Tense & Voice"            -- identify the tense, identify active/passive voice
 
Auto-detection:
    fill in the blank / _____ / correct form / choose option  -> "Gap Filling"
    transform / change into passive or active / combine /
    rewrite using / positive degree / negative / as soon as /
    both...and / so...that / complex sentence                 -> "Sentence Transformation"
    find the error / spot the error / underline incorrect     -> "Error Correction"
    reported speech / indirect / direct speech                -> "Reported Speech"
    rearrange / reorder / jumbled                             -> "Reordering"
    edit the following passage / correct the passage          -> "Editing"
    identify the tense / name the voice                       -> "Tense & Voice"
 
-------------------------------------------------------------
EDITING RULE - passage-level vs line-level
-------------------------------------------------------------
If the editing task gives a NUMBERED passage where each line has its own number
(1., 2., 3.) AND each numbered line contains exactly one error -> each line = 1 row.
If the editing passage has NO line numbers (one undivided block) -> whole passage = 1 row.
 
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Read ALL sub-items to the end - do NOT stop at (b) if (c)(d) also exist.
- For Gap Filling with MCQ options: ALWAYS include the (a)(b)(c)(d) options in question text.
- For "Reordering": include ALL jumbled words/phrases in the question text.
- Do NOT include marks labels "[1]" or "(1 mark)" in the question text.
- Do NOT include the parent instruction as a row.
- If marks per sub-item are unstated but parent says "NxM=P", assign M marks each.
- "attempt any 5 of 7" -> extract ALL 7 sub-items; add top-level "attempt_any": 5.
 
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "attempt_any": 5,
  "questions": [
    {{
      "question": "(i) This table is made _____ wood.\n(a) from  (b) of  (c) with  (d) at",
      "skill_category": "Gap Filling",
      "directive": null,
      "marks": 1
    }},
    {{
      "question": "(ii) Would you like to have _____ tea or coffee?\n(a) some  (b) any  (c) a  (d) no",
      "skill_category": "Gap Filling",
      "directive": null,
      "marks": 1
    }},
    {{
      "question": "(i) Transform into passive voice: Someone is calling my name.",
      "skill_category": "Sentence Transformation",
      "directive": "change the voice",
      "marks": 1
    }}
  ]
}}
"""
 
 
# =============================================================================
# PHASE 2 - LITERATURE
# =============================================================================
 
def literature_prompt(language: str, q_nums: list[int] | None = None):
    qref = _qref(q_nums, "Extract ALL literature questions found in the paper.")
    boundary = _boundary_instruction(q_nums)
    or_word = "अथवा / OR  (either word, or both, acts as separator)" if language == "Hindi" else "OR"
    or_step = _or_counting_instruction(or_word)
    final_check = _final_count_check("questions")
 
    hindi_notes = """
-------------------------------------------------------------
HINDI LITERATURE - SPECIFIC RULES
-------------------------------------------------------------
Textbooks: kshitij, sparsh, aaroh, vitan, antara, sanchayan, kritika, kshitij bhag-1/2.
 
Question types handled here:
    ati laghu uttariya (2 marks, ~30 words)
    laghu uttariya     (3 marks, ~75 words)
    dirgha uttariya    (4 marks, ~120 words)
    kavyansh/gadyansh par aadharit prashna -- SEEN textbook extracts (NOT unseen apathit)
    lekhak/kavi parichay (author/poet biography questions)
 
EXTRACT-BASED (sandarbh-prasang):
    Include the FULL quoted extract AND all sub-questions in ONE row.
    Format: "[full extract text]\\n(ka) sandarbh likhiye.\\n(kha) prasang likhiye.\\n(ga) vyakhya kijiye."
 
MCQs: include ALL 4 options (a)(b)(s)(d) or (a)(b)(c)(d) in the question string.
 
athhva between TWO COMPLETE questions -> 2 separate rows; strip "athhva" from start of row 2.
 
"attempt any N of M" — TWO types:
TYPE A — Extract sub-parts (ka/kha/ga or a/b/c) about ONE SAME passage/extract:
    Keep all sub-parts in ONE row.
 
TYPE B — Independent questions about DIFFERENT lessons (most common):
    Parent: "koi panch prashno ke uttar dijiye", "koi do prashno ke uttar dijiye", etc.
    Produce ONE ROW PER sub-question. Strip the number prefix (1) (2) etc.
    Set attempt_any = N on EACH row. Assign per-sub-question marks.
    Do NOT merge them into one combined row.
 
lesson_name / author: if the question explicitly names a lesson/poem/author, capture it
    in the optional "lesson_name" and "author" fields.
"""
 
    english_notes = """
-------------------------------------------------------------
ENGLISH LITERATURE - SPECIFIC RULES
-------------------------------------------------------------
Textbooks: Flamingo, Vistas, First Flight, Footprints Without Feet, Beehive,
           Moments, Honeydew, It So Happened, Hornbill, Snapshots.
 
Question types handled here:
    MCQ extract-based (1 mark each, 4 options)
    Short answer (~30 words, 2 marks)
    Long answer (~75 words, 3 marks)
    Reference to Context / extract-based (SEEN textbook extracts - NOT unseen passages)
    Character sketch, value-based questions
 
EXTRACT-BASED / REFERENCE TO CONTEXT (RTC):
    Include the FULL quoted passage or poem lines AND all sub-questions in ONE row.
    Format: "Read the following extract and answer the questions:\\n'[extract]'\\n(a) ...\\n(b) ..."
 
MCQs: include ALL 4 options (a)(b)(c)(d) in the question string.
 
OR between TWO COMPLETE questions -> 2 separate rows; strip "OR" from start of row 2.
 
"attempt any N of M" — TWO types:
TYPE A — Extract sub-parts (a)(b)(c) about ONE SAME passage/extract:
    Keep all sub-parts in ONE row.
 
TYPE B — Independent questions about DIFFERENT lessons/chapters (most common):
    Parent: "Answer any five in about 30 words", "Answer any one in about 75 words", etc.
    Produce ONE ROW PER sub-question. Strip the number prefix (1) (2) (i) (ii) etc.
    Set attempt_any = N on EACH row. Assign per-sub-question marks.
    Do NOT merge them into one combined row.
    Example: "Answer any one: (1) Why is grandeur associated... (2) What symbol from nature..."
    -> Row 1: question="Why is grandeur associated...", marks=6, attempt_any=1
    -> Row 2: question="What symbol from nature...", marks=6, attempt_any=1
 
lesson_name / author: if the question explicitly names a lesson/poem/author, capture it
    in the optional "lesson_name" and "author" fields (null if not mentioned).
"""
 
    literature_block = hindi_notes if language == "Hindi" else english_notes
 
    return f"""You are an expert at extracting literature questions from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every literature question. Produce ONE JSON row per question.
{or_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question     : COMPLETE text of the question - including any quoted extract (for RTC),
               all sub-parts (a)(b)(c) or (ka)(kha)(ga), and all MCQ options.
               Use \\n to separate lines. Do NOT include marks labels here.
 
marks        : Integer. TOTAL marks for this question.
               For extract-based / RTC questions with multiple sub-parts (1)(2)(3) each
               worth N marks — sum them all: marks = N × number_of_sub_parts.
               Example: 3 sub-questions × 1 mark each = marks: 3 (NOT 1).
               For a plain single question: its individual marks value.
 
attempt_any  : (OPTIONAL) Integer. Only present when question says "attempt any N of M".
               Set to N. Extract ALL M sub-items regardless.
 
lesson_name  : (OPTIONAL) String. Name of the lesson/poem if explicitly stated. null otherwise.
 
author       : (OPTIONAL) String. Author/poet name if explicitly stated. null otherwise.
{literature_block}
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- OR / athhva on its own line between complete questions -> 2 separate rows.
  Strip "OR" / "athhva" from the very beginning of the second row's question text.
- Extract-based (RTC/sandarbh): quoted passage + sub-parts (a)(b)(c) = ONE row.
- Sub-parts of a SINGLE extract -> keep in ONE row. Do NOT split extract sub-parts.
- Independent sub-questions under "attempt any N" -> ONE ROW EACH (see TYPE B above).
  Strip number prefix (1) (2) (i) (ii) from each sub-question text.
- For extract-based: the quoted extract IS part of the question - include it first.
- MCQ options: include ALL four as part of the question string.
- Strip the question number (Q.11, prashna 12) from the start of question text.
- Keep lesson/poem/author references - they are essential context.
- Do NOT include marks labels inside the question text.
- For extract/RTC with N sub-questions each worth M marks: marks = N × M (total, not per sub-question).
 
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "What is the central theme of 'The Last Lesson'?",
      "marks": 3,
      "attempt_any": null,
      "lesson_name": "The Last Lesson",
      "author": "Alphonse Daudet"
    }},
    {{
      "question": "Read the following extract and answer the questions:\n'Yes, in spite of all / Some shape of beauty moves away the pall...'\n(1) What moves the pall from our dark spirits?\n(a) Any shape of beauty (b) Daffodils (c) Green world (d) Dooms\n(2) What does the poet mean by 'green world'?\n(a) Green forest (b) Daffodil's green surroundings (c) Greenhouse (d) Green walls\n(3) Which poetic device is used in 'Shady boon'?\n(a) Imagery (b) Alliteration (c) Metaphor (d) Personification",
      "marks": 3,
      "attempt_any": null,
      "lesson_name": "A Thing of Beauty",
      "author": "John Keats"
    }},
    {{
      "question": "What did Franz notice that was unusual about the school that day?",
      "marks": 2,
      "attempt_any": 5,
      "lesson_name": "The Last Lesson",
      "author": null
    }},
    {{
      "question": "What makes the city of Firozabad famous?",
      "marks": 2,
      "attempt_any": 5,
      "lesson_name": "Lost Spring",
      "author": null
    }},
    {{
      "question": "Why is grandeur associated with the mighty dead?",
      "marks": 6,
      "attempt_any": 1,
      "lesson_name": "A Thing of Beauty",
      "author": "John Keats"
    }}
  ]
}}
"""
 
 
# =============================================================================
# PHASE 2 - OBJECTIVE PROMPTS (Hindi papers Q1-Q5 style)
# Language-agnostic; routed by structure detection sub_type.
# =============================================================================
 
def lang_mcq_prompt(language: str, q_nums: list[int] | None = None):
    """
    For objective MCQ blocks (Hindi Q1 style).
    Tests literature/general knowledge through MCQ FORMAT.
    NOT for grammar sub-items - use grammar_hindi_prompt for those.
    """
    qref = _qref(q_nums, "Extract ALL MCQ items found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("MCQ sub-items")
    final_check = _final_count_check("questions")
 
    return f"""You are an expert at extracting objective MCQ items from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every MCQ sub-item. Produce ONE JSON row per sub-item.
Do NOT produce a row for the parent instruction line.
{count_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question       : Complete sub-item text including its label (i)/(ka) at the START,
                the question/statement, AND all four options.
                Example (Hindi):
                  "(i) Hindi padya sahitya ko baanta gaya hai -\\n(a) char kalon mein  (b) teen kalon mein\\n(s) paanch kalon mein  (d) chah kalon mein"
                Example (English):
                  "(i) Education is a sub-system of the wider ___\\n(a) social system  (b) political system\\n(c) economical system  (d) religious system"
 
skill_category : Classify the MCQ:
                 "Literature"  -- question is about a specific lesson/poem/chapter from the textbook
                 "Grammar"     -- question tests grammar concepts (sandhi, samas, nipat, vakya bhed,
                                  kaal, vachya, alankar, ras, etc.)
                 "General"     -- general literary/language knowledge not tied to a specific chapter
 
lesson_name    : (OPTIONAL) Name of the specific lesson/poem IF skill_category = "Literature"
                 AND the lesson is identifiable from the question or options. null otherwise.
 
marks          : Marks for this single item (usually 1).
 
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Include ALL four options in the question string.
- Grammar MCQs (vakya bhed, nipat, sandhi, etc.): skill_category = "Grammar", lesson_name = null.
- Literature MCQs (about a poem/lesson): skill_category = "Literature", lesson_name = lesson title.
- Do NOT include marks labels in question text.
- Preserve Devanagari script exactly for Hindi items.
{_SKILL_CATEGORY_DETECTION}
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "(i) 'दिन जल्दी-जल्दी ढलता है' गीत हरिवंशराय बच्चन के काव्य-संग्रह से लिया गया है -\\n(अ) निशा निमंत्रण  (ब) एकांत संगीत\\n(स) सतरंगिनी  (द) मधुशाला",
      "skill_category": "Literature",
      "lesson_name": "Aatmparichay, Ek Geet",
      "marks": 1
    }},
    {{
      "question": "(iii) अर्थ के आधार पर वाक्य के प्रकार होते हैं -\\n(अ) आठ  (ब) तीन\\n(स) सात  (द) नौ",
      "skill_category": "Grammar",
      "lesson_name": null,
      "marks": 1
    }}
  ]
}}
"""
 
 
def lang_fill_blanks_prompt(language: str, q_nums: list[int] | None = None):
    """
    For objective Fill-in-the-Blank blocks (Hindi Q2 style).
    Options are usually given in brackets after the blank.
    """
    qref = _qref(q_nums, "Extract ALL fill-in-the-blank items found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("fill-in-the-blank sub-items")
    final_check = _final_count_check("questions")
 
    return f"""You are an expert at extracting fill-in-the-blank items from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every FIB sub-item. Produce ONE JSON row per sub-item.
Do NOT produce a row for the parent instruction line.
{count_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question       : Complete sub-item text including its label at the START,
                the sentence with blank (___), AND ALL options if provided.
                Options may appear in two formats — include both:
                  Bracket format (Hindi):
                    "(i) khet ki tulana ________ ki gayi hai. (kagaz ke panne se / maidan se / parvat se)"
                  Lettered format (a)(b)(c)(d) - English or Hindi:
                    "(i) This table is made _____ wood.\n(a) from  (b) of  (c) with  (d) at"
                If no options are given, include just the sentence with blank.
 
skill_category : Classify the item:
                 "Literature"  -- statement references a specific lesson, poem, chapter,
                                  author, or character from the textbook.
                 "Grammar"     -- statement tests grammar terminology (ras, alankar, chhand,
                                  sandhi, samas, nipat, vachya, muhavare, shabd shakti, etc.)
                 "General"     -- general literary / journalistic / language knowledge not
                                  tied to a specific textbook chapter.
 
lesson_name    : (OPTIONAL) Name of the specific lesson/poem IF skill_category = "Literature"
                 AND the lesson is clearly identifiable from the statement or its options.
                 null in all other cases.
 
marks          : Marks for this single item (usually 1).
 
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- ALWAYS include the options (bracket or lettered) — they are part of the question.
- For lettered options (a)(b)(c)(d): append on a new line after the sentence.
- For bracket options: append on the same line after the blank.
- Preserve Devanagari script exactly for Hindi items.
- Do NOT include marks labels in question text.
{_SKILL_CATEGORY_DETECTION}
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "(i) 'RaamCharit Manas' mahakavya ki bhasha ________ hai. (Braj / Avadhi)",
      "skill_category": "Literature",
      "lesson_name": null,
      "marks": 1
    }},
    {{
      "question": "(v) sthayi bhav ko jagrat karne wale karan ko ________ kahte hain. (aalamban / uddipan)",
      "skill_category": "Grammar",
      "lesson_name": null,
      "marks": 1
    }},
    {{
      "question": "(iii) duniya ki sabse halki aur rangin cheez ________ hai. (patang / swapna)",
      "skill_category": "Literature",
      "lesson_name": "Patang",
      "marks": 1
    }},
    {{
      "question": "(i) This table is made _____ wood.\n(a) from  (b) of  (c) with  (d) at",
      "skill_category": "Grammar",
      "lesson_name": null,
      "marks": 1
    }}
  ]
}}
"""
 
 
def lang_match_following_prompt(language: str, q_nums: list[int] | None = None):
    """
    For Match-the-Following blocks (Hindi Q3 style).
    6-pair match with two columns 'ka' and 'kha'.
    column_a items are objects with text, skill_category, lesson_name
    because each item may come from a different chapter / topic.
    """
    qref = _qref(q_nums, "Extract the match-the-following question found in the paper.")
    boundary = _boundary_instruction(q_nums)
    final_check = _final_count_check("column_a")
 
    return f"""You are an expert at extracting match-the-following questions from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract the match-the-following question. Produce ONE JSON object with:
- column_a : left column items as OBJECTS (text + classification per item)
- column_b : right column items as plain strings (in original printed order)
- marks    : total marks = number of pairs in column_a
 
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
column_a_header : Label of left column as printed (e.g. "ka", "stambh-1", "Column A").
column_b_header : Label of right column as printed (e.g. "kha", "stambh-2", "Column B").
 
column_a        : Array of OBJECTS — one per left-column item, in original order.
                  Each object has exactly three fields:
                  {{
                    "text":           full item text with its printed label
                                      (e.g. "(i) Reetikaaleen kavita ki do visheshataen"),
                    "skill_category": one of "Literature" | "Grammar" | "General"
                                      (see detection rules below),
                    "lesson_name":    name of the lesson/poem if skill_category = "Literature"
                                      AND the lesson is clearly identifiable; null otherwise.
                  }}
 
column_b        : Array of plain strings — each right-column item in original printed order,
                  with its label included.
                  Do NOT reorder column_b — keep exactly as printed.
 
marks           : Integer. Total marks = len(column_a).
 
-------------------------------------------------------------
skill_category DETECTION — apply per column_a item
-------------------------------------------------------------
{_SKILL_CATEGORY_DETECTION}
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Include the printed label (i)/(ka)/(a) etc. at the START of every text entry.
- Preserve Devanagari script exactly for Hindi items.
- marks = len(column_a).
- lesson_name is null unless skill_category = "Literature" AND the lesson is unambiguous.
- Do NOT classify column_b items — they are plain strings only.
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "column_a_header": "ka",
  "column_b_header": "kha",
  "column_a": [
    {{"text": "(i) Hindi sahitya ka swarna yug",       "skill_category": "General",    "lesson_name": null}},
    {{"text": "(ii) Chayavaad ke pravartak kavi",      "skill_category": "General",    "lesson_name": null}},
    {{"text": "(iii) Masti ka sandesh",                "skill_category": "Literature", "lesson_name": "Aatmparichay, Ek Geet"}},
    {{"text": "(iv) Chaupai chhand",                   "skill_category": "Grammar",    "lesson_name": null}},
    {{"text": "(v) Chitrakaar",                        "skill_category": "Literature", "lesson_name": "Atit Mein Dabe Paav"}},
    {{"text": "(vi) Sampadakiya prishth",              "skill_category": "General",    "lesson_name": null}}
  ],
  "column_b": [
    "(a) Jaishankar Prasad",
    "(b) Bhaktikaal",
    "(s) 16 matraen",
    "(d) Harivanshray Bachchan",
    "(e) Akhbaar ki apni aavaaz",
    "(ee) Chitera"
  ],
  "marks": 6
}}
"""
 
 
def lang_owa_prompt(language: str, q_nums: list[int] | None = None):
    """
    For One-Word / One-Sentence Answer blocks (Hindi Q4 style).
    """
    qref = _qref(q_nums, "Extract ALL one-word/one-sentence answer items found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("OWA sub-items")
    final_check = _final_count_check("questions")
 
    return f"""You are an expert at extracting one-word / one-sentence answer items from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every OWA sub-item. Produce ONE JSON row per sub-item.
Do NOT produce a row for the parent instruction line.
{count_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question       : Complete sub-item text including its label at the START and the full question.
                Example: "(i) Soratha chhand matraaon ki drishti se kis chhand ka ulta hota hai?"
 
skill_category : Classify the item:
                 "Literature"  -- question is about a specific lesson, poem, chapter,
                                  author, or character from the textbook.
                 "Grammar"     -- question tests grammar concepts (chhand, alankar, sandhi,
                                  muhavare, lokokti, shabd shakti, ras, vakya bhed,
                                  upasarg, pratyay, etc.)
                 "General"     -- general literary / journalistic / language knowledge not
                                  tied to a specific textbook chapter.
 
lesson_name    : (OPTIONAL) Name of the specific lesson/poem IF skill_category = "Literature"
                 AND the lesson is clearly identifiable from the question. null otherwise.
 
marks          : Marks for this single item (usually 1).
 
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Preserve Devanagari script exactly for Hindi items.
- Do NOT include marks labels in question text.
{_SKILL_CATEGORY_DETECTION}
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "(i) Soratha chhand matraaon ki drishti se kis chhand ka ulta hota hai?",
      "skill_category": "Grammar",
      "lesson_name": null,
      "marks": 1
    }},
    {{
      "question": "(ii) gadya ki koi char pramukh vidhaon ke naam likhiye.",
      "skill_category": "General",
      "lesson_name": null,
      "marks": 1
    }},
    {{
      "question": "(iii) Raghuveer Sahay konse taar saptak ke kavi hain?",
      "skill_category": "Literature",
      "lesson_name": "Camra mein Band Apahij",
      "marks": 1
    }}
  ]
}}
"""
 
 
def lang_true_false_prompt(language: str, q_nums: list[int] | None = None):
    """
    For True/False blocks (Hindi Q5 style - satya/asatya).
    """
    qref = _qref(q_nums, "Extract ALL true/false items found in the paper.")
    boundary = _boundary_instruction(q_nums)
    count_step = _sub_question_count_instruction("true/false sub-items")
    final_check = _final_count_check("questions")
 
    return f"""You are an expert at extracting true/false items from {language} examination papers.
 
{qref}
{boundary}
-------------------------------------------------------------
OBJECTIVE
-------------------------------------------------------------
Extract every True/False sub-item. Produce ONE JSON row per sub-item.
Do NOT produce a row for the parent instruction line.
{count_step}
-------------------------------------------------------------
FIELD DEFINITIONS
-------------------------------------------------------------
question : Complete sub-item text including its label at the START and the full statement.
           Example: "(i) Shoshkon ke prati ghrina aur shoshiton ke prati karuna pragativaad hai."
 
marks    : Marks for this single item (usually 1).
 
-------------------------------------------------------------
GENERAL RULES
-------------------------------------------------------------
- Preserve Devanagari script exactly for Hindi items.
- Do NOT include marks labels in question text.
- Do NOT add "(satya/asatya)" to the question text - that is the instruction, not the item.
 
{LATEX_INSTRUCTION}
{final_check}
-------------------------------------------------------------
OUTPUT FORMAT - return ONLY valid JSON, no extra text, no markdown fences
-------------------------------------------------------------
{{
  "questions": [
    {{
      "question": "(i) Shoshkon ke prati ghrina aur shoshiton ke prati karuna pragativaad hai.",
      "marks": 1
    }}
  ]
}}
"""
 
 
# =============================================================================
# REGISTRY
# =============================================================================
 
LANGUAGE_STRUCTURE_PROMPTS = {
    "Hindi":   language_structure_prompt_hindi,
    "English": language_structure_prompt_english,
}
 
# Maps Phase-1 "prompt" field value → callable(language, q_nums) → prompt string
# All callables have the same signature: (language: str, q_nums: list | None) -> str
LANG_PROMPT_DISPATCH = {
    # Objective types (language paper versions, no collision with prompts.py)
    "mcq_prompt":                  lambda lang, q: lang_mcq_prompt(lang, q),
    "fill_blanks_prompt":          lambda lang, q: lang_fill_blanks_prompt(lang, q),
    "match_following_prompt":      lambda lang, q: lang_match_following_prompt(lang, q),
    "one_word_answer_prompt":      lambda lang, q: lang_owa_prompt(lang, q),
    "true_false_prompt":           lambda lang, q: lang_true_false_prompt(lang, q),
    # Core section types
    "comprehension_engine_prompt": lambda lang, q: comprehension_engine_prompt(lang, q),
    "writing_engine_prompt":       lambda lang, q: writing_engine_prompt(lang, q),
    "grammar_hindi_prompt":        lambda _, q: grammar_hindi_prompt(q),
    "grammar_english_prompt":      lambda _, q: grammar_english_prompt(q),
    "literature_prompt":           lambda lang, q: literature_prompt(lang, q),
}
 
# Response parse type: tells app.py how to interpret the JSON the model returns
# "questions"  -> {"questions": [...]}  standard list
# "passages"   -> {"passages": [...]}   comprehension
# "match"      -> {column_a_header, column_a, column_b, marks}  flat object
#                 NOTE: column_a items are now objects {text, skill_category, lesson_name}
#                 — update app.py parser to read item["text"] instead of the raw string.
LANG_PARSE_TYPE = {
    "mcq_prompt":                  "questions",
    "fill_blanks_prompt":          "questions",
    "match_following_prompt":      "match",
    "one_word_answer_prompt":      "questions",
    "true_false_prompt":           "questions",
    "comprehension_engine_prompt": "passages",
    "writing_engine_prompt":       "questions",
    "grammar_hindi_prompt":        "questions",
    "grammar_english_prompt":      "questions",
    "literature_prompt":           "questions",
}