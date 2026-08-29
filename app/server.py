#!/usr/bin/env python3
"""Khan Tutor - offline multilingual math tutor for grades 1-3.
Built to serve many devices at once on a weak CPU box:
 - Pages, lesson lists, quizzes and video ALWAYS return instantly (cache-first,
   English fallback). Translation never blocks a request.
 - Missing language caches are built in a background thread.
 - Heavy work (the AI model + translation) is rate-limited so a burst of devices
   queues instead of overwhelming the box.
Pure standard library. Talks to llama.cpp (:8080) and LibreTranslate (:5000).
"""
import json, os, re, threading, time, queue, datetime, hashlib, random, secrets, subprocess, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

CACHE_VER = "v24"   # bump to discard stale/partial language caches and rebuild

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(ROOT)
CONTENT = os.path.join(BASE, "content")
TRANSCRIPTS = os.path.join(BASE, "transcripts")
DATA = os.path.join(BASE, "data")
PROGRESS = os.path.join(DATA, "progress")
SUBS = os.path.join(DATA, "subs")
THUMBS = os.path.join(DATA, "thumbs")
FFMPEG = os.path.join(BASE, "tools", "ffmpeg")
STATIC = os.path.join(ROOT, "static")

# ---- configuration ----
# Settings load from (highest priority first): LIGHTBOX_<KEY> env var, then
# <BASE>/config.json, then the built-in defaults below. This lets an operator
# deploy to any machine/user without editing this file. See config.example.json.
_CFG = {}
_cfg_path = os.path.join(BASE, "config.json")
if os.path.exists(_cfg_path):
    try:
        with open(_cfg_path, encoding="utf-8") as _f:
            _CFG = json.load(_f) or {}
    except Exception as _e:
        print("config.json could not be read (%r); using defaults" % _e)
def _conf(key, default):
    return os.environ.get("LIGHTBOX_" + key.upper(), _CFG.get(key, default))

HOST = _conf("host", "0.0.0.0")                 # bind address (0.0.0.0 = all interfaces / LAN)
PORT = int(_conf("port", 8090))
LLAMA = _conf("llama_url", "http://127.0.0.1:8080/v1/chat/completions")
LTRANS = _conf("libretranslate_url", "http://127.0.0.1:5000/translate")
MODEL = _conf("model", "qwen2.5-3b-instruct-q4_k_m.gguf")
LANGS = {"en": "English", "fr": "Français", "es": "Español", "de": "Deutsch"}

USERS = os.path.join(DATA, "users")
CLASSES = os.path.join(DATA, "classes")
CLASSES_INDEX_PATH = os.path.join(DATA, "classes_index.json")
SESSIONS_PATH = os.path.join(DATA, "sessions.json")

# ---- first-run setup state (base language only - accounts are self-service) ----
# Stored in <DATA>/setup.json once the welcome wizard's language step has run.
SETUP_PATH = os.path.join(DATA, "setup.json")
def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
def load_setup():
    d = _read_json(SETUP_PATH, {}) or {}
    bl = d.get("base_lang")
    return {"configured": bool(d.get("configured")),
            "base_lang": bl if bl in LANGS else "en"}
SETUP = load_setup()
def save_setup(base_lang=None):
    if base_lang in LANGS:
        SETUP["base_lang"] = base_lang
    SETUP["configured"] = True
    # preserve any other fields already on disk (e.g. a dormant legacy field)
    # instead of clobbering them
    existing = _read_json(SETUP_PATH, {}) or {}
    existing["configured"] = True
    existing["base_lang"] = SETUP["base_lang"]
    os.makedirs(DATA, exist_ok=True)
    _write(SETUP_PATH, existing)
LT_TIMEOUT = 25          # per call; arrays are chunked so calls stay small
LLM_TIMEOUT = 180

for d in (PROGRESS, SUBS, USERS, CLASSES, THUMBS):
    os.makedirs(d, exist_ok=True)

_thumb_locks = {}
_thumb_locks_lock = threading.Lock()
def _thumb_lock(vid):
    with _thumb_locks_lock:
        l = _thumb_locks.get(vid)
        if l is None:
            l = threading.Lock()
            _thumb_locks[vid] = l
        return l

def make_thumb(vid):
    """Lazily extract one representative frame from a lesson video as its thumbnail,
    cropped/scaled identically for every video so the grid stays visually consistent
    (fixes some videos looking oddly cropped/angled next to each other)."""
    out = os.path.join(THUMBS, vid + ".jpg")
    if os.path.exists(out):
        return out
    src = os.path.join(CONTENT, vid + ".mp4")
    if not os.path.exists(src) or not os.path.exists(FFMPEG):
        return None
    with _thumb_lock(vid):
        if os.path.exists(out):
            return out
        tmp = out + ".tmp"
        try:
            subprocess.run([FFMPEG, "-y", "-ss", "5", "-i", src, "-frames:v", "1",
                             "-vf", "scale=320:200:force_original_aspect_ratio=increase,crop=320:200",
                             "-f", "mjpeg", tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, out)
                return out
        except Exception:
            pass
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
    return None

def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8-sig") as f:
        return json.load(f)

CATALOG = load("catalog.json")
CAT = {e["id"]: e for e in CATALOG}
QUIZZES = load("quizzes.json")
NOTES = load("notes.json") if os.path.exists(os.path.join(DATA, "notes.json")) else {}

# ---------- reading library (open-licensed storybooks under ~/lightbox/books) ----------
BOOKS = os.path.join(BASE, "books")

def _book_level(npages):
    if npages <= 5:
        return 1
    if npages <= 9:
        return 2
    if npages <= 13:
        return 3
    return 4

def load_books():
    """Scan books/<id>/{en,fr}.json into a per-language catalog + detail map (heuristic level)."""
    by_lang, detail = {}, {}
    if os.path.isdir(BOOKS):
        for d in sorted(os.listdir(BOOKS)):
            bdir = os.path.join(BOOKS, d)
            if not os.path.isdir(bdir):
                continue
            for lang in LANGS:                                  # en, fr, es, de
                fp = os.path.join(bdir, lang + ".json")
                if not os.path.exists(fp):
                    continue
                try:
                    with open(fp, encoding="utf-8-sig") as f:   # books were written with a UTF-8 BOM
                        b = json.load(f)
                except Exception:
                    continue
                lvl = _book_level(len(b.get("pages", [])))
                b["level"] = lvl
                grade = str(b.get("grade") or {1: "K", 2: "1", 3: "2", 4: "3"}.get(lvl, "1"))
                b["grade"] = grade
                imgs = b.get("images", [])
                by_lang.setdefault(lang, []).append({
                    "id": b.get("id", d), "title": b.get("title", ""), "level": lvl, "grade": grade,
                    "cover": (imgs[0] if imgs else b.get("cover", "")), "author": b.get("author"),
                    "illustrator": b.get("illustrator"), "page_count": len(b.get("pages", []))})
                detail[(b.get("id", d), lang)] = b
    for lang in by_lang:
        by_lang[lang].sort(key=lambda x: (x["level"], x["title"].lower()))
    return by_lang, detail

BOOKS_BY_LANG, BOOK_DETAIL = load_books()

UI = {
 "tagline": "Learn, read, and explore.", "welcome_to": "Welcome to",
 "signin_name": "Your name", "signin_code": "Lesson code (optional)",
 "start": "Start", "browse": "Browse lessons by grade", "or": "or",
 "choose_grade": "Choose a grade", "choose_topic": "Choose a topic", "lessons": "Lessons",
 "grade_K": "Kindergarten", "grade_1": "1st Grade", "grade_2": "2nd Grade",
 "grade_3": "3rd Grade", "grade_4": "4th Grade", "grade_5": "5th Grade", "grade_6": "6th Grade", "grade_7": "7th Grade", "grade_8": "8th Grade", "back": "Back", "home": "Home",
 "ask_tab": "Ask", "quiz_tab": "Quiz",
 "mark_complete": "Complete", "mark_todo": "To-do",
 "next_videos": "Next Videos", "todo_list_title": "My To-Do List",
 "topic_finished": "You've finished this topic!",
 "confirm_leave_title": "Wait, you're not done yet!",
 "confirm_leave_msg": "You haven't finished watching this video. Are you sure you want to move on?",
 "confirm_leave_stay": "Keep Watching", "confirm_leave_go": "Yes, Move On",
 "ask_ph": "Ask a question about this lesson...", "ask_btn": "Send", "thinking": "Thinking...",
 "welcome": "Watch the video, then ask me anything about it.",
 "question": "Question", "score": "Score", "check": "Check", "next": "Next",
 "see_stars": "Finish", "again": "Try again", "you_got": "You got",
 "amazing": "Excellent work!", "effort": "Good effort - watch it again and try once more.",
 "book_effort": "Good effort - read it again and try once more.",
 "type_answer": "Type your answer...", "language": "Language",
 "cant_find": "Lesson not found. Check the code.",
 "trouble": "Something went wrong. Please try again.", "loading": "Loading...",
 "name_required": "Please enter your name first.", "videos": "videos",
 "watched_word": "watched", "not_started": "Not started yet",
 "helper_btn": "Homework Helper", "helper_title": "Homework Helper",
 "helper_sub": "Ask me anything about your schoolwork - math, reading, science, and more.",
 # The bot's name is written into the sentence rather than substituted: LibreTranslate
 # DROPS a {placeholder} in French and Spanish ("Je suis ton aide aux devoirs"), but
 # carries the proper noun through cleanly and puts it in the right grammatical slot.
 "helper_welcome": "Hi! I'm LightBot, your homework helper. Tap a subject below to get started.",
 "helper_ph": "Type your question...",
 # homework helper chat chrome: speaker labels above each bubble, the reset button,
 # and the subject cards shown as the first step of the conversation
 "new_question": "New question", "helper_you": "You",
 # subject_word/grade_word now label the pinned summary line, not the old selects.
 # subj_general is still the default subject - the full-range tutor, not a degraded
 # one - so a student who has not chosen yet loses nothing.
 "subject_word": "Subject", "grade_word": "Grade", "language_word": "Language",
 "subj_general": "Anything",
 "read_aloud": "Read aloud", "subject_prompt": "Tap a subject to start",
 "subj_math": "Math", "subj_reading": "Reading", "subj_science": "Science", "subj_writing": "Writing",
 # The in-chat subject -> grade -> ask flow. The confirmation is assembled from
 # "helper_got_it" + the chosen labels + "helper_what_help" rather than one sentence
 # with {placeholders}: LibreTranslate translates or drops placeholder tokens, so a
 # templated sentence would come back broken in fr/de/es.
 "helper_grade_prompt": "Great choice! What grade are you in?",
 "helper_subject_again": "No problem. Which subject do you need help with?",
 "helper_got_it": "Got it!", "helper_what_help": "What do you need help with?",
 "helper_change": "Change", "helper_change_aria": "Change subject or grade",
 "role_student": "I'm a Student", "role_student_s": "Watch lessons, ask questions, take quizzes",
 "role_teacher": "I'm a Teacher", "role_teacher_s": "See your class's progress",
 "signin_pin": "Password", "pin_err": "That password isn't right. Try again.",
 "no_students": "No students yet. Ask your teacher to add you.",
 "continue": "Continue", "ach_btn": "My Achievement Box", "ach_title": "My Achievement Box",
 "ach_videos": "Videos finished", "ach_quizzes": "Quizzes passed",
 "ach_empty": "Finish a video or pass a quiz to earn your first star!",
 "ns_title": "My Next Step", "ns_redo": "That quiz was tricky - let's watch this again.",
 "ns_pass": "Great work! You're ready for the next lesson.",
 "ns_new": "Let's start learning! Here's a good first lesson.",
 "quiz_preparing": "Getting your quiz ready...", "quiz_newset": "Here are 3 brand-new questions!",
 "welcome_hi": "Welcome back,", "welcome_topic": "Ready to keep learning about",
 "welcome_new": "Ready to learn something new today?",
 "home_welcome_back": "Welcome back", "home_ready_topic": "ready to keep learning about",
 "home_ready_new": "ready to learn something new today?", "explore_title": "Explore",
 "browse_sub": "Find lessons for any grade level", "ach_btn_sub": "See the badges you've earned",
 "ai_badge": "AI", "quick_chat": "Quick Chat",
 "your_grade": "Your grade", "book_word": "book", "books_word": "books", "pages_word": "pages",
 "badge_earned_word": "badge earned", "badges_earned_word": "badges earned",
 "continue_reading": "Continue reading",
 "teacher": "Teacher", "access_code": "Access code",
 "enter": "Enter", "code_err": "Wrong access code.", "dash_title": "Class progress", "refresh": "Refresh",
 # accounts: sign in / sign up / join-a-class
 "login_title": "Sign In", "language_lbl": "Language",
 "username_lbl": "Username", "password_lbl": "Password",
 "login_btn": "Sign In", "login_err": "Wrong username or password.",
 "have_account": "Already have an account?", "signin_link": "Sign in",
 "no_account": "New here?", "signup_link": "Create an account",
 "signup_title": "Create Account", "signup_btn": "Create Account",
 "username_taken_err": "That username is already taken.",
 "bad_signup_err": "Choose a username and a password of at least 4 characters.",
 "join_title": "Join a Class", "join_sub": "Ask your teacher for your class access code.",
 "join_code_ph": "6-character code", "join_btn": "Request to Join",
 "invalid_code_err": "That code doesn't match a class. Check with your teacher.",
 "pending_msg": "Request sent! Waiting for your teacher to accept you.",
 "my_classes": "My Classes", "create_class_btn": "+ Create Class",
 "class_name_ph": "Class name (e.g. Room 12 Math)", "class_grade_lbl": "Grade level",
 "regenerate_btn": "Regenerate",
 "regenerate_confirm": "This invalidates the current code immediately for anyone who hasn't joined yet. Continue?",
 "pending_requests": "Pending Requests", "approve_btn": "Approve", "reject_btn": "Reject",
 "requested_at": "Requested", "no_pending": "No pending requests.",
 "select_class": "Class", "no_classes_yet": "Create a class above to get started.",
 "err_class_fields": "Enter a class name and choose a grade.",
 # profile / rewards menu, notification bell, assigned tests
 "view_rewards": "View My Rewards and Stars",
 "change_language": "Change Language", "sign_out": "Sign Out",
 "confirm_lang_title": "Change your language?",
 "confirm_lang_msg": "Are you sure you want to change your language to {lang}? You can change it any time.",
 "confirm_lang_yes": "Yes, Change It", "confirm_lang_cancel": "Cancel",
 "confirm_signout_title": "Sign out?",
 "confirm_signout_msg": "You'll be signed out and will need to sign back in to continue.",
 "confirm_signout_yes": "Yes, Sign Out",
 "welcome_to_class": "Welcome to {class} class!",
 "test_have": "You have a new test!", "test_title": "Your Test",
 "test_sub": "Answer every question, then send it to your teacher.",
 "test_submit": "Send my answers", "test_sent": "Sent to your teacher!",
 "test_answer_ph": "Type your answer...",
 # subject select + helper pills
 "subj_q": "What do you want to do today?",
 "subj_math": "Math", "subj_math_sub": "Watch lessons & take quizzes",
 "subj_reading": "Reading", "subj_reading_sub": "Read fun storybooks",
 "math_helper": "Math Helper", "math_helper_sub": "Ask me about math",
 "helper_any_sub": "Ask me about any subject",
 # reading hub + reader
 "reading_hub": "Reading Hub", "reading_awards": "My Reading Awards", "back_to_books": "Back to Books",
 "book_quiz_btn": "Take Book Quiz", "won_star": "You earned a star!",
 # teacher dashboard + history
 "hist_btn": "Past History Logs", "add_student": "Add a student",
 "add_student_btn": "Add student", "ph_student_name": "Username",
 "ph_password4": "Password (required for a new student)", "grade_opt": "Grade...",
 "back_live": "Back to live", "hist_filter": "Filter", "no_grade_yet": "No grade yet",
 # achievements / "about me" screen
 "ach_math_title": "My Math Awards", "ach_about_me_suffix": "About Me",
 "stat_gold_stars": "Gold stars", "stat_math_quizzes": "Math quizzes",
 "stat_videos_watched": "Videos watched", "stat_book_quizzes": "Book quizzes",
 "stat_books_read": "Books read", "tag_quiz_passed": "Quiz passed", "tag_watched": "Watched",
 "tag_book_quiz_passed": "Book quiz", "tag_read": "Read",
 "showcase_empty": "Pass a quiz to fill your showcase with gold stars!",
 "ach_showcase": "Showcase", "ach_all_awards": "All My Awards", "ach_badge_counts": "Badge Counts",
 # story reader chrome
 "page_word": "Page", "of_word": "of", "cover_word": "Cover", "last_page": "Last page",
 "reading_progress_aria": "Reading progress",
 # book byline + credits. by_author keeps "by" attached to the name so a language that
 # needs a different preposition or word order ("par", "por", "von") can move it.
 "by_author": "by {name}",
 "credit_story": "Story:", "credit_illustration": "Illustration:",
 "credit_translation": "Translation:", "credit_from": "From",
 "close_book_aria": "Close book", "prev_page_aria": "Previous page", "next_page_aria": "Next page",
 # math-specific homework helper (general helper already has helper_title/helper_welcome)
 "math_helper_welcome": "Hi! I'm LightBot, your math helper. Tap a subject below to get started.",
 # teacher history calendar
 "hist_today": "Today", "hist_all_students": "All students", "hist_clear_filter": "Clear filter",
 "hist_less": "Less", "hist_more": "More", "hist_activity_detail": "Activity detail", "hist_activity_report_suffix": "activity report",
 "hist_no_activity_day": "No activity recorded for this day.",
 "hist_no_individual_activities": "No individual activities logged.",
 "hist_showing_activity_for": "Showing activity for", "hist_only_suffix": "only.",
 "hist_star_word": "star", "hist_stars_word": "stars",
 "hist_activity_word": "activity", "hist_activities_word": "activities",
 "hist_video_word": "Video", "hist_print_export": "Print / export",
 "hist_log_word": "log", "hist_logs_word": "logs",
 "hist_math_quiz_suffix": "(math quiz)", "hist_book_quiz_suffix": "(book quiz)",
 "hist_csv_date": "Date", "hist_csv_student": "Student", "hist_csv_stars": "Stars",
 "hist_csv_videos_watched": "Videos Watched", "hist_csv_math_passed": "Math Quizzes Passed",
 "hist_csv_math_total": "Math Quizzes Total", "hist_csv_book_passed": "Book Quizzes Passed",
 "hist_csv_book_total": "Book Quizzes Total",
 # test builder / dashboard settings / setup wizard - previously JS-only (DEFAULTS)
 # fallback text with no server-side key at all, so it could never be translated
 "test_due": "Due:",
 "welcome_mission": ("Bringing free, offline learning to every classroom — because every child "
                     "deserves equal access to a great education."),
 "setup_lang": "Choose your starting language", "setup_go": "Continue",
 "setup_note": "You can change this anytime from the teacher dashboard.",
 "settings_btn": "Settings", "settings_title": "Settings",
 "settings_lang": "Base language (the default for all devices)",
 "settings_save": "Save settings", "settings_saved": "Saved",
 "sec_add_student": "Add a Student", "sec_tracking": "Student Progress & Tracking",
 "sec_tests": "Tests & Student Answers", "no_tests_yet": "No tests created yet.",
 "create_test": "Create Test", "build_test": "Build a test",
 "test_title_ph": "Test title (e.g. Week 3 Math Check)",
 "add_mc": "+ Multiple-choice", "add_text": "+ Free-response",
 "add_mc_tag": "Multiple choice", "add_text_tag": "Free response",
 "question_ph": "Question", "add_choice": "+ Choice", "tick_correct": "Tick the circle next to the correct answer.",
 "del_q": "Delete", "correct_lbl": "correct", "choice_ph": "Choice",
 "due_label": "Due date & time (optional)",
 "assign_grades": "Assign to grades:", "assign_students": "And/or individual students:",
 "create_test_btn": "Create test", "del_test": "Delete test",
 "assigned_to": "Assigned to:", "tests_answers": "Tests & student answers",
 "grades_word": "Grades", "questions_word": "questions", "due_word": "Due",
 "submitted_word": "submitted", "no_subs": "No submissions yet.", "correct_word": "correct",
 "confirm_del_test": "Delete this test and all its responses?",
 "err_choices": "Each multiple-choice question needs at least 2 choices.",
 "err_correct": "Mark the correct answer for every multiple-choice question.",
 "err_title": "Add a test title.", "err_noq": "Add at least one question.",
 "err_assign": "Assign to at least one grade or student.", "err_create": "Could not create test.",
 "hist_export_modal_title": "Print / export report",
 "hist_export_modal_msg": "Choose how much history to include.",
 "hist_dur_this_month": "This month", "hist_dur_3": "Last 3 months",
 "hist_dur_6": "Last 6 months", "hist_dur_12": "Last 12 months",
 "hist_download_report": "Download report", "hist_building_report": "Building report…",
 "hist_downloaded": "Downloaded.",
 "hist_prev_month_aria": "Previous month", "hist_next_month_aria": "Next month",
 "hist_close_aria": "Close",
 "hist_sun": "Sun", "hist_mon": "Mon", "hist_tue": "Tue", "hist_wed": "Wed",
 "hist_thu": "Thu", "hist_fri": "Fri", "hist_sat": "Sat",
 "hist_month_1": "January", "hist_month_2": "February", "hist_month_3": "March",
 "hist_month_4": "April", "hist_month_5": "May", "hist_month_6": "June",
 "hist_month_7": "July", "hist_month_8": "August", "hist_month_9": "September",
 "hist_month_10": "October", "hist_month_11": "November", "hist_month_12": "December",
 # teacher dashboard
 "dash_no_students": "No students yet — add one above.",
 # test builder's per-student picker. Distinct from "no_students", which is the
 # student-facing "ask your teacher to add you" copy and must never appear here.
 "tb_no_students": "No students in this class yet — add one from Class overview.",
 "dash_top_passed_today": "Top lessons passed today", "dash_no_passes_today": "No passes yet today",
 "dash_most_failed_today": "Most-failed lesson today", "dash_no_fails_today": "No fails yet today",
 "dash_students_active_now": "students active now",
 # video player settings
 "captions_lbl": "Captions", "caption_size_lbl": "Caption size",
 # misc errors
 "could_not_load_books": "Could not load books.", "no_books_lang_yet": "No books in this language yet.",
 "could_not_send_retry": "Could not send. Try again.", "could_not_add_student": "Could not add student.",
 "need_password_msg": "Enter a password (at least 4 characters) - it's required for a new student.",
 # legacy standalone /teacher portal (teacher.html) - distinct from the SPA's own
 # teacher dashboard/history screens, so it needs its own small set of keys
 "teacher_new_here": "New here?", "teacher_goto_app_link": "Go to the main app to create an account",
 "teacher_gate_err": "Wrong username or password, or this account isn't a teacher.",
 "tests_grading_tab": "Tests & grading",
 "assign_to_lbl": "Assign to:", "assign_whole_grade": "A whole grade",
 "assign_specific_students": "Specific students",
 "create_class_first_err": "Create a class first.",
 "th_student": "Student", "th_last_active": "Last active",
 "th_lessons_opened": "Lessons opened", "th_questions_asked": "Questions asked",
 "th_quiz_score": "Quiz score", "no_student_activity": "No student activity yet.",
 "details_word": "details", "quiz_word": "quiz",
 "pick_student_err": "Pick at least one student.",
 "test_created_msg": "Test created", "could_not_load_tests": "Could not load tests.",
 "no_answer_word": "(no answer)",
 # teacher dashboard sidebar restructure (Class Overview / Tests / Student Progress / History Logs)
 "dash_title_topbar": "Teacher dashboard",
 "nav_overview": "Class overview", "nav_tests": "Tests", "nav_progress": "Student progress",
 "tests_tab_create": "Create a test", "tests_tab_results": "Test results & answers",
 "roster_title": "Class roster", "progress_by_student": "Progress by student",
 "view_progress_btn": "View progress",
 "assignment_title": "Assignment", "free_response_hint": "Students will type a written answer.",
 "view_answers_btn": "View answers", "hide_answers_btn": "Hide answers",
 "test_status_open": "Open", "test_status_closed": "Closed",
 # tests results restructure: list view -> per-test detail view
 "col_title": "Title", "col_status": "Status", "col_due": "Due date",
 "col_submissions": "Submissions", "no_due_date": "No due date",
 "status_past_due": "Past due", "status_complete": "Complete",
 "all_tests_back": "All tests", "no_tests_list": "No tests yet. Create one to get started.",
 "class_average": "Class average", "avg_not_ready": "Class average not available yet",
 "avg_awaiting": "Awaiting more submissions - available after {due}, or once all {n} students submit.",
 "avg_awaiting_nodue": "Available once all {n} assigned students have submitted.",
 "avg_pct_correct": "% correct", "avg_ungraded": "Written answer - not auto-graded",
 "sort_by": "Sort by", "sort_newest": "Newest first", "sort_oldest": "Oldest first",
 "sort_name": "Student name", "filter_show": "Show", "filter_all": "All answers",
 "filter_incorrect": "Incorrect only", "filter_submitted": "Submitted only",
 "filter_pending": "Not yet submitted", "filter_student": "Student",
 "filter_all_students": "All students", "no_match_filters": "No submissions match these filters.",
 "submitted_at": "Submitted", "not_submitted": "Not yet submitted",
 "answered_lbl": "Answered:", "correct_answer_lbl": "correct answer:",
 "extended_badge": "Extended", "extended_to": "extended to",
 "students_count_badge": "{n} students",
 "edited_after_sub": "Edited after submission",
 "student_saw": "This student saw:", "was_correct_then": "Correct as originally asked.",
 # notifications
 "notifications": "Notifications", "mark_all_read": "Mark all read",
 "no_notifications": "No notifications yet.",
 "notif_created": "'{title}' has been created",
 "notif_submitted": "{student} submitted '{title}'",
 "notif_dismiss": "Dismiss",
 "just_now": "just now", "mins_ago": "{n}m ago", "hours_ago": "{n}h ago", "days_ago": "{n}d ago",
 # due date extensions
 "extend_due": "Extend due date", "extend_save": "Save new due date",
 "extend_whole": "Whole assignment", "extend_selected": "Selected students",
 "extend_new_due": "New due date", "extend_pick_students": "Choose who gets the extension",
 "extend_err_date": "Pick a new due date.", "extend_err_students": "Select at least one student.",
 "extend_current": "Currently due {due}", "extend_no_due": "No due date set yet",
 "extend_clear_hint": "Students you untick keep the assignment's own due date.",
 # editing a test after it has been assigned
 "edit_test": "Edit test", "save_changes": "Save changes", "cancel_edit": "Cancel",
 "edit_heads_up": "Heads up",
 "edit_warn_subs": "{n} student(s) have already submitted - editing may affect grading consistency. "
                   "Existing answers are kept exactly as they were, and any question you change "
                   "is flagged on those submissions.",
 "edit_saved": "Changes saved",
 # data & storage (auto-archival)
 "data_storage": "Data & storage",
 "data_storage_desc": "Manage how long test results stay on this Lunis host.",
 "retention_label": "Delete tests older than",
 "retention_never": "Never", "retention_30": "30 days", "retention_60": "60 days",
 "retention_90": "90 days", "retention_after_due": "after their due date",
 "retention_mode_archive": "Archive to a lightweight summary (class average + date, no per-student answers)",
 "retention_mode_confirm": "Ask me before deleting anything",
 "retention_save": "Save setting", "retention_saved": "Saved.",
 "retention_never_note": "Auto-deletion is off. Nothing will be removed until you choose a window.",
 "retention_pending_title": "{n} test(s) are past their retention window",
 "retention_review": "Review and delete", "retention_not_now": "Not now",
 "retention_archived_title": "Archived summaries",
 "retention_no_archive": "Nothing archived yet.",
 "retention_swept": "{n} test(s) archived and removed.",
 # general credits disclaimer (platform footer)
 "disclaimer": ("Educational content on this platform is compiled from various open-source public "
                "repositories and educational archives, including Khan Academy, StoryWeaver, the "
                "Global Digital Library, and Global Storybooks, to support offline classroom learning."),
}

# Each lesson's grade level (K/1/2/3) for folder-style navigation.
GRADES = {}
for _g, _ids in {
 "K": ["CO1", "CO2", "CO3", "CO4"],
 "1": ["CO5", "CO6", "PV1", "PV2", "PV3", "PV4", "PV5", "AS1", "AS2", "AS5", "AS9", "AS11",
       "AS12", "AS13", "AS14", "AS15", "AS17", "AS24", "AS26", "AS27", "MD1", "MD6", "MD7",
       "GE2", "GE4"],
 "2": ["AS3", "AS4", "AS6", "AS7", "AS8", "AS10", "AS16", "AS18", "AS19", "AS20", "AS21",
       "AS22", "AS23", "AS25", "MD2", "MD3", "MD4", "MD5", "GE1"],
 "3": ["GE3", "MU1", "MU2", "MU3", "MU4", "MU5", "MU6", "MU7", "MU8", "FR1", "FR2", "FR3",
       "FR4", "FR5", "FR6", "FR7", "FR8", "AP1", "AP2"],
 "4": ["MA1", "MA2", "MA3", "FM1", "FM2", "FR9", "FR10", "FR11", "FR12", "DE1", "DE2", "GE5"],
 "5": ["DE3", "DE4", "DE5", "DE6", "FR13", "FR14", "FR15", "OP1", "OP2", "VO1", "VO2", "CP1"],
 "6": ["RT1", "RT2", "PC1", "FR16", "IN1", "IN2", "CP2", "EE1", "EE2", "EE3", "GE6", "ST1"],
 "7": ["PR1", "PR2", "PR3", "IN3", "IN4", "EE4", "EE5", "PC2", "GE7", "GE8", "GE9", "ST2"],
 "8": ["EX1", "SR1", "SN1", "LE1", "LE2", "LE3", "FN1", "FN2", "GE10", "GE11", "GE12", "ST3"],
}.items():
    for _i in _ids:
        GRADES[_i] = _g

# rate limits so many devices can't overwhelm the shared model / translator
_LT_SEM = threading.Semaphore(3)
_LLM_SEM = threading.Semaphore(2)

# ---------- translation (offline, cached, bounded, non-blocking failure) ----------
_tlock = threading.Lock()
_tcache = {}
def _lt(items, source, target):
    body = json.dumps({"q": items, "source": source, "target": target,
                       "format": "text"}).encode("utf-8")
    req = urllib.request.Request(LTRANS, data=body,
                                 headers={"Content-Type": "application/json"})
    with _LT_SEM:
        with urllib.request.urlopen(req, timeout=LT_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))["translatedText"]

def _lt_chunked(items, source, target, chunk=12):
    """Translate a list in small batches so no single call is slow enough to time out."""
    out = []
    for i in range(0, len(items), chunk):
        part = items[i:i + chunk]
        res = _lt(part, source, target)
        if not (isinstance(res, list) and len(res) == len(part)):
            raise ValueError("shape")
        out.extend(res)
    return out

def _needs_tr(text):
    # never translate pure math/numbers ("1/2", "30 + 40") - LibreTranslate mangles them
    return bool(re.search(r"[A-Za-z]{2,}", text or ""))

def tr(text, target, source="en"):
    if not text or target == source or target not in LANGS or not _needs_tr(text):
        return text
    key = (source, target, text)
    with _tlock:
        if key in _tcache:
            return _tcache[key]
    try:
        out = _lt(text, source, target)
    except Exception:
        return text                       # never cache a failure (would poison the cache)
    with _tlock:
        _tcache[key] = out
    return out

def tr_list(items, target, source="en"):
    """Lenient: translate a list in ONE call; on failure returns originals (no slow retries)."""
    try:
        return _tr_list_strict(items, target, source)
    except Exception:
        return list(items)

def _tr_list_strict(items, target, source="en"):
    """Strict: raises on any translation failure (so builders won't cache English)."""
    if target == source or target not in LANGS or not items:
        return list(items)
    idx = [i for i, x in enumerate(items) if _needs_tr(x)]
    if not idx:
        return list(items)
    sub = _lt_chunked([items[i] for i in idx], source, target)
    if not (isinstance(sub, list) and len(sub) == len(idx)):
        raise ValueError("shape")
    out = list(items)
    for j, i in enumerate(idx):
        out[i] = sub[j]
    return out

def _one_strict(text, lang):
    if not text or not _needs_tr(text):
        return text
    key = ("en", lang, text)
    with _tlock:
        if key in _tcache:
            return _tcache[key]
    r = _lt(text, "en", lang)             # raises on failure
    with _tlock:
        _tcache[key] = r
    return r

# ---------- per-language cache builders (run in background) ----------
def _p(name, lang):
    return os.path.join(DATA, "%s_%s_%s.json" % (name, CACHE_VER, lang.replace("-", "_")))

def build_ui(lang):
    keys = list(UI.keys())
    out = dict(zip(keys, _tr_list_strict([UI[k] for k in keys], lang)))
    _write(_p("i18n", lang), out)
    return out

def build_catalog(lang):
    titles = _tr_list_strict([e["title"] for e in CATALOG], lang)
    labels = _tr_list_strict([e["topic_label"] for e in CATALOG], lang)
    notes = _tr_list_strict([NOTES.get(e["id"], "") for e in CATALOG], lang)
    out = [{"id": e["id"], "yt": e["yt"], "title": ti, "topic_label": la, "note": no,
            "grade": GRADES.get(e["id"], ""), "duration_min": e["duration_min"]}
           for e, ti, la, no in zip(CATALOG, titles, labels, notes)]
    _write(_p("catalog", lang), out)
    return out

def _translate_quiz(vid, lang, strict=False):
    one = _one_strict if strict else (lambda t, l: tr(t, l))
    lst = _tr_list_strict if strict else tr_list
    out = []
    for item in QUIZZES[vid]["questions"]:
        o = {"type": item["type"], "q": one(item["q"], lang),
             "hint": one(item.get("hint", ""), lang)}
        if item["type"] == "mc":
            o["choices"] = lst(item["choices"], lang)
        out.append(o)
    return out

def build_quizzes(lang):
    out = {vid: _translate_quiz(vid, lang, strict=True) for vid in QUIZZES}
    _write(_p("quizzes", lang), out)
    return out

def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)   # atomic; readers never see a half-written file

# ONE background worker builds caches sequentially, so it can never overload
# LibreTranslate (concurrent builds caused timeouts -> English got cached).
# Priority 0 = lists/UI for every language first (fast, high value); 1 = quizzes.
_warm_q = queue.PriorityQueue()
_warm_lock = threading.Lock()
_warm_enq = set()            # (lang, kind)
_warm_started = [False]
_warm_seq = [0]

def _has_fast(lang):
    return os.path.exists(_p("i18n", lang)) and os.path.exists(_p("catalog", lang))
def _has_quiz(lang):
    return os.path.exists(_p("quizzes", lang))

def _enqueue(lang, kind, prio):
    if (lang, kind) in _warm_enq:
        return
    _warm_enq.add((lang, kind))
    _warm_seq[0] += 1
    _warm_q.put((prio, _warm_seq[0], lang, kind))

def _warm_worker():
    while True:
        _prio, _seq, lang, kind = _warm_q.get()
        ok = True
        try:
            if kind == "fast":
                if not os.path.exists(_p("i18n", lang)):
                    build_ui(lang)
                if not os.path.exists(_p("catalog", lang)):
                    build_catalog(lang)
            else:
                if not os.path.exists(_p("quizzes", lang)):
                    build_quizzes(lang)
        except Exception:
            ok = False
        with _warm_lock:
            _warm_enq.discard((lang, kind))
        if not ok:
            time.sleep(8)            # translator busy; retry the missing pieces
            ensure_lang_cache(lang)

def ensure_lang_cache(lang, want_quiz=False):
    # 'fast' (UI + lesson list) is warmed eagerly; quizzes are built lazily on first
    # use, so eager warming can't compete with the caption pre-build for the translator.
    if lang == "en" or lang not in LANGS:
        return
    with _warm_lock:
        if not _warm_started[0]:
            _warm_started[0] = True
            threading.Thread(target=_warm_worker, daemon=True).start()
        if not _has_fast(lang):
            _enqueue(lang, "fast", 0)
        if want_quiz and not _has_quiz(lang):
            _enqueue(lang, "quiz", 1)

# ---------- cache-first readers (never block on translation) ----------
def _read(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def ui_strings(lang):
    if lang == "en" or lang not in LANGS:
        return UI
    c = _read(_p("i18n", lang))
    if c:
        return c
    ensure_lang_cache(lang)
    return UI

def catalog_for(lang):
    base = [{"id": e["id"], "yt": e["yt"], "title": e["title"],
             "topic_label": e["topic_label"], "note": NOTES.get(e["id"], ""),
             "grade": GRADES.get(e["id"], ""), "duration_min": e["duration_min"]}
            for e in CATALOG]
    if lang == "en" or lang not in LANGS:
        return base
    c = _read(_p("catalog", lang))
    if c:
        return c
    ensure_lang_cache(lang)
    return base

def quiz_for(vid, lang):
    if vid not in QUIZZES:
        return None
    if lang != "en" and lang in LANGS:
        c = _read(_p("quizzes", lang))
        if c and vid in c:
            return c[vid]
        ensure_lang_cache(lang, want_quiz=True)   # build full file in background
        return _translate_quiz(vid, lang)         # translate just this one now (fast, bounded)
    # English
    out = []
    for item in QUIZZES[vid]["questions"]:
        o = {"type": item["type"], "q": item["q"], "hint": item.get("hint", "")}
        if item["type"] == "mc":
            o["choices"] = item["choices"]
        out.append(o)
    return out

# ---------- subtitles: translate srt -> WebVTT, cache, English fallback ----------
_vmaster = threading.Lock()
_vlocks = {}
def _vlock(key):
    with _vmaster:
        l = _vlocks.get(key)
        if l is None:
            l = threading.Lock()
            _vlocks[key] = l
        return l

def make_vtt(vid, lang):
    cache = os.path.join(SUBS, "%s.%s.vtt" % (vid, lang.replace("-", "_")))
    hit = _read_text(cache)
    if hit is not None:
        return hit
    srt = os.path.join(CONTENT, vid + ".srt")
    if not os.path.exists(srt):
        return None
    blocks = _parse_srt(srt)
    src = [b[1] for b in blocks]
    if lang == "en" or lang not in LANGS:
        return _emit_vtt(blocks, src, cache)
    lock = _vlock(cache)
    with lock:
        hit = _read_text(cache)
        if hit is not None:
            return hit
        try:
            trans = _lt_chunked(src, "en", lang)
            if not (isinstance(trans, list) and len(trans) == len(src)):
                raise ValueError
            return _emit_vtt(blocks, trans, cache)        # cache only on success
        except Exception:
            return _emit_vtt(blocks, src, None)           # English now, no cache (retry later)

def _parse_srt(path):
    blocks, cur_time, cur_text = [], None, []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f.read().splitlines():
            s = ln.strip()
            if "-->" in s:
                cur_time = s.replace(",", ".")
            elif s == "":
                if cur_time:
                    blocks.append((cur_time, " ".join(cur_text)))
                cur_time, cur_text = None, []
            elif s.isdigit() and cur_time is None:
                continue
            else:
                cur_text.append(re.sub(r"<[^>]+>", "", s))
    if cur_time:
        blocks.append((cur_time, " ".join(cur_text)))
    return blocks

def _emit_vtt(blocks, texts, cache):
    out = ["WEBVTT", ""]
    for (t, _), txt in zip(blocks, texts):
        out += [t, txt, ""]
    vtt = "\n".join(out)
    if cache:
        try:
            with open(cache, "w", encoding="utf-8") as f:
                f.write(vtt)
        except Exception:
            pass
    return vtt

def _read_text(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    return None

# ---------- AI ----------
def grounding(vid):
    n = NOTES.get(vid)
    if n:
        return n
    p = os.path.join(TRANSCRIPTS, vid + ".txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read().strip()[:600]
    return ""

SYS = ("You are Khan Buddy, a kind math helper for kids age 6 to 8. Answer using ONLY the "
       "lesson note. Keep it to 1 or 2 very short, simple sentences with small words. Be warm "
       "and encouraging. If the note doesn't answer it, say you're not sure and to ask the "
       "teacher.\n\nLESSON NOTE: {t}")

HELP_SYS = ("You are Lunis, a friendly, patient tutor for students (roughly ages 6 to 12). "
            "Help with ANY school subject - math, reading, writing, science, social studies, and "
            "study skills. Explain clearly and step by step in simple, encouraging language a young "
            "student understands; you may give helpful detail and examples. Keep it accurate and safe "
            "for children; if you are unsure, say so. Write math in plain text like 3 x 4 = 12, never "
            "LaTeX. Format clearly with short paragraphs, **bold** for key words, and bullet (-) or "
            "numbered (1.) lists for steps.")

MATH_HELP_SYS = ("You are Lunis Math Helper, a friendly, patient MATH tutor for children (ages 6 "
                 "to 12). Help ONLY with mathematics - counting, place value, addition, subtraction, "
                 "multiplication, division, fractions, shapes, measurement, time and money. If a child "
                 "asks about something that is not math, gently say you are the math helper and to use "
                 "the general Homework Helper for other subjects. Explain step by step in simple, "
                 "encouraging words. Write math in plain text like 3 x 4 = 12, never LaTeX. Format "
                 "clearly with short paragraphs, **bold** for key words, and numbered (1.) or bullet (-) lists for steps.")

ASK_SYS = ("You are Khan Buddy, a kind tutor helping a child (age 6 to 10) with the specific video "
           "lesson below. Answer the child's question clearly in 1 to 3 short, simple sentences, and "
           "connect it to what THIS lesson teaches. You may use simple, correct general knowledge to "
           "help. Be warm and encouraging. Write math in plain text like 3 x 4 = 12, never LaTeX.\n\n"
           "LESSON CONTENT:\n{ctx}")

def ask_context(vid):
    e = CAT.get(vid)
    parts = [e["title"]] if e else []
    if NOTES.get(vid):
        parts.append(NOTES[vid])
    p = os.path.join(TRANSCRIPTS, vid + ".txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            parts.append(f.read().strip()[:1100])
    return "\n".join(parts).strip()

def call_llama(messages, max_tokens=140, temp=0.3, timeout=None):
    body = json.dumps({"model": MODEL, "messages": messages, "max_tokens": max_tokens,
                       "temperature": temp, "stream": False}).encode("utf-8")
    req = urllib.request.Request(LLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with _LLM_SEM:
        with urllib.request.urlopen(req, timeout=timeout or LLM_TIMEOUT) as r:
            out = json.loads(r.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"].strip()

# ---------- personalized greeting ----------
GREET_SYS = ("Write ONE short, warm welcome-back line (max 25 words) for a child using a learning "
             "app. Use their name. If a recent topic is given, mention it and ask if they're ready "
             "to keep going. Cheerful, simple words. Output only the sentence, with no quotes.")

def generate_greeting(student, lang):
    data, p = load_progress(student)
    name = data.get("name", student) if os.path.exists(p) else (student or "friend")
    last_vid = data.get("last_quiz_video") or data.get("last_video") or ""
    topic = ""
    if last_vid and CAT.get(last_vid):
        topic = CAT[last_vid].get("topic_label") or CAT[last_vid].get("title") or ""
    try:
        u = "Child's name: %s." % name
        if topic:
            u += " Recent topic: %s." % topic
        sysmsg = GREET_SYS + ("" if lang == "en" else " Reply only in %s." % LANGS.get(lang, "English"))
        txt = call_llama([{"role": "system", "content": sysmsg},
                          {"role": "user", "content": u}], max_tokens=60, temp=0.7).strip().strip('"')
        if txt:
            return txt
    except Exception:
        pass
    base = ("Welcome back, %s! Ready to keep learning about %s?" % (name, topic)) if topic \
        else ("Welcome back, %s! Ready to learn something new today?" % name)
    return tr(base, lang) if lang != "en" else base

# ---------- smart quiz bank (anti-memorization) ----------
QUIZBANK = os.path.join(DATA, "quizbank")
os.makedirs(QUIZBANK, exist_ok=True)
BANK_TARGET, BANK_MIN, BANK_CAP = 12, 4, 15

def _bank_path(vid):
    return os.path.join(QUIZBANK, vid + ".json")

def load_bank(vid):
    return _read(_bank_path(vid))

def _valid_mcq(q):
    if not isinstance(q, dict) or q.get("type") != "mc":
        return False
    if not isinstance(q.get("q"), str) or not q["q"].strip():
        return False
    ch = q.get("choices")
    if not isinstance(ch, list) or not (2 <= len(ch) <= 4):
        return False
    if not all(isinstance(c, str) and c.strip() for c in ch):
        return False
    a = q.get("answer")
    return isinstance(a, int) and 0 <= a < len(ch)

def _seed_bank(vid):
    out = []
    for it in QUIZZES.get(vid, {}).get("questions", []):
        if it.get("type") == "mc" and _valid_mcq(it):
            out.append({"type": "mc", "q": it["q"], "choices": it["choices"],
                        "answer": it["answer"], "explain": it.get("explain", "")})
    return out

GEN_SYS = ("You write multiple-choice math quiz questions for children (age 6 to 10) about ONE "
           "lesson. Output ONLY a JSON array, no prose. Each element must be exactly: "
           '{"type":"mc","q":"<question>","choices":["a","b","c"],"answer":"<the EXACT text of the '
           'correct choice, copied character-for-character from the choices list>","explain":"<one '
           'short kid-friendly sentence>"}. Use 3 choices each, exactly one correct. FIRST work out '
           'the right answer, THEN make sure "answer" exactly equals one of the choices. Keep '
           "questions short, concrete and VARIED (different numbers) so a child cannot memorize them. "
           "Base them only on the lesson.")

_CPREFIX = re.compile(r'^\s*(?:\([A-Da-d]\)|[A-Da-d]\s*[\):.\-]|\d+\s*[\):.])\s*')
def _clean_choice(c):
    return _CPREFIX.sub("", str(c)).strip()

def _arith_expected(qtext):
    """If the question asks a simple arithmetic, return its numeric value, else None.
    Used to trust the math over the model's (often wrong) answer index."""
    s = qtext.lower()
    m = re.search(r'what (?:is|does|number)?(.*)$', s)
    seg = m.group(1) if m else s
    pats = [(r'(\d+)\s*(?:divided by|÷|/)\s*(\d+)', '/'),
            (r'(\d+)\s*(?:times|multiplied by|[x×*])\s*(\d+)', '*'),
            (r'(\d+)\s*(?:plus|\+)\s*(\d+)', '+'),
            (r'(\d+)\s*(?:minus|[-âˆ’])\s*(\d+)', '-')]
    cands = []                                   # (position, value)
    for pat, op in pats:
        for mm in re.finditer(pat, seg):
            a, b = int(mm.group(1)), int(mm.group(2))
            if op == '/':
                if b == 0:
                    continue
                v = a / b
            elif op == '*':
                v = a * b
            elif op == '+':
                v = a + b
            else:
                v = a - b
            cands.append((mm.start(), v))
    if not cands:
        return None
    cands.sort()
    return cands[-1][1]                          # rightmost expression = the asked one

def _coerce_mcq(q):
    """Validate + repair a model-generated MC question. Verifies arithmetic and drops junk."""
    if not isinstance(q, dict):
        return None
    qt = q.get("q") or q.get("question")
    ch = q.get("choices") or q.get("options")
    a = q.get("answer")
    if not isinstance(qt, str) or not qt.strip() or not isinstance(ch, list):
        return None
    ch = [c for c in (_clean_choice(x) for x in ch) if c]
    if not (2 <= len(ch) <= 4) or len(set(ch)) != len(ch):
        return None
    for c in ch:
        if len(c) == 1 and c.isalpha():            # placeholder choice like "a"/"b"
            return None
        if re.fullmatch(r'-?\d+\.\d+', c):          # decimals aren't grade 1-3 friendly
            return None
    ai = None
    if isinstance(a, bool):
        return None
    if isinstance(a, int):
        ai = a
    elif isinstance(a, str):
        s = _clean_choice(a)
        idx = next((i for i, c in enumerate(ch) if c.lower() == s.lower()), None)
        if idx is not None:
            ai = idx
        elif s.isdigit() and int(s) < len(ch):
            ai = int(s)
        elif len(s) == 1 and s.upper() in "ABCD":
            ai = ord(s.upper()) - 65
    if ai is None or not (0 <= ai < len(ch)):
        return None
    exp = _arith_expected(qt)                       # trust the math when computable
    if exp is not None:
        if exp != int(exp):
            return None                             # non-integer answer -> drop
        idx = next((i for i, c in enumerate(ch) if c == str(int(exp))), None)
        if idx is None:
            return None                             # correct value not offered -> drop
        ai = idx
    return {"type": "mc", "q": qt.strip(), "choices": ch, "answer": ai,
            "explain": str(q.get("explain", "")).strip()[:160]}

def _gen_batch(vid, n):
    # short context + small batch so each call finishes well within the LLM timeout on a weak box
    title = (CAT.get(vid) or {}).get("title", "")
    note = NOTES.get(vid, "")
    ctx = (title + "\n" + note).strip() or ask_context(vid)[:600]
    msgs = [{"role": "system", "content": GEN_SYS},
            {"role": "user", "content": "Lesson: %s\n\nLESSON:\n%s\n\nWrite %d different "
             "multiple-choice questions as a JSON array. Output ONLY the array." % (title, ctx[:700], n)}]
    raw = call_llama(msgs, max_tokens=520, temp=0.7)
    raw = re.sub(r"```(?:json)?", "", raw)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for q in (arr if isinstance(arr, list) else []):
        c = _coerce_mcq(q)
        if c:
            out.append(c)
    return out

def _dedupe(items):
    seen, out = set(), []
    for q in items:
        k = re.sub(r"\s+", " ", q["q"].strip().lower())
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out

def build_quiz_bank(vid):
    if vid not in CAT:
        return []
    bank = _seed_bank(vid)
    for _ in range(5):                      # several small passes; each is quick enough to finish
        if len(bank) >= BANK_TARGET:
            break
        try:
            new = _gen_batch(vid, 4)
        except Exception:
            break                           # LLM timeout/busy -> keep what we have
        if new:
            bank = _dedupe(bank + new)
    bank = bank[:BANK_CAP]
    if len(bank) >= BANK_MIN:
        _write(_bank_path(vid), {"questions": bank})
    return bank

_bank_q = queue.Queue()
_bank_enq = set()
_bank_started = [False]

def _bank_worker():
    while True:
        vid = _bank_q.get()
        try:
            if not load_bank(vid):
                build_quiz_bank(vid)
        except Exception:
            pass
        with _warm_lock:
            _bank_enq.discard(vid)

def ensure_bank(vid):
    if vid not in CAT or load_bank(vid):
        return
    with _warm_lock:
        if not _bank_started[0]:
            _bank_started[0] = True
            threading.Thread(target=_bank_worker, daemon=True).start()
        if vid not in _bank_enq:
            _bank_enq.add(vid)
            _bank_q.put(vid)

def quiz_attempt(vid, lang, seen, n=3):
    """Return n random questions from the bank, avoiding indices in `seen` (anti-memorization)."""
    bank = load_bank(vid)
    if not bank or not bank.get("questions"):
        ensure_bank(vid)
        seedq = _seed_bank(vid)             # serve curated questions until the bank is built
        if not seedq:
            return None
        bank = {"questions": seedq}
    qs = bank["questions"]
    pool = [i for i in range(len(qs)) if i not in seen]
    if len(pool) < n:
        pool = list(range(len(qs)))         # bank exhausted this session -> reset the pool
    random.shuffle(pool)
    out = []
    for i in sorted(pool[:n]):
        q = qs[i]
        item = {"type": "mc", "q": q["q"], "choices": list(q["choices"]), "bankIdx": i}
        if lang != "en" and lang in LANGS:
            item["q"] = tr(q["q"], lang)
            item["choices"] = tr_list(q["choices"], lang)
        out.append(item)
    return {"questions": out, "size": len(qs), "ready": bool(load_bank(vid))}

def _book_text(bid):
    b = BOOK_DETAIL.get((bid, "en")) or BOOK_DETAIL.get((bid, "fr")) or {}
    parts = [b.get("title", "")] + list(b.get("pages", []))
    return "\n".join(p for p in parts if p)

# ---------- book translation (LibreTranslate, cached per book) ----------
def translate_book(bid, lang):
    """Machine-translate an English book into `lang`, cache to <id>/<lang>.json, update catalog."""
    if lang == "en" or lang not in LANGS:
        return BOOK_DETAIL.get((bid, "en"))
    if (bid, lang) in BOOK_DETAIL:
        return BOOK_DETAIL[(bid, lang)]
    src = BOOK_DETAIL.get((bid, "en"))
    if not src:
        return None
    try:
        tpages = _tr_list_strict(list(src.get("pages", [])), lang)
        ttitle = tr(src.get("title", ""), lang)
    except Exception:
        return None
    b = dict(src)
    b["language"] = lang
    b["title"] = ttitle
    b["pages"] = tpages
    b["translator"] = "Machine translation (LibreTranslate)"
    b["mt"] = True
    try:
        with open(os.path.join(BOOKS, bid, lang + ".json"), "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False)
    except Exception:
        pass
    BOOK_DETAIL[(bid, lang)] = b
    lst = BOOKS_BY_LANG.setdefault(lang, [])
    if not any(x["id"] == bid for x in lst):
        imgs = b.get("images", [])
        lst.append({"id": bid, "title": ttitle, "level": b.get("level"),
                    # same fallback load_books() uses: a text-only chapter book has no
                    # page images, so its cover comes from the `cover` field. Without
                    # this, a book translated at runtime showed a blank cover in that
                    # language until the next restart rebuilt the catalog.
                    "cover": (imgs[0] if imgs else b.get("cover", "")),
                    "author": b.get("author"), "illustrator": b.get("illustrator")})
        lst.sort(key=lambda x: (x["level"], x["title"].lower()))
    return b

# ---------- fixed book quiz (3 Qs for easy books, 5 for longer; generated ONCE, cached, never changes) ----------
BOOKQUIZ = os.path.join(DATA, "bookquiz")
os.makedirs(BOOKQUIZ, exist_ok=True)
BQ_SYS = ("You write exactly %d simple multiple-choice reading-comprehension questions for a child, "
          "matched to reading level %d (1 = easiest, 4 = hardest), about the SHORT story below. "
          "Output ONLY a JSON array of %d items, each exactly: "
          '{"type":"mc","q":"<question>","choices":["<real option one>","<real option two>",'
          '"<real option three>"],"answer":"<the EXACT text of the correct option>","explain":'
          '"<one short sentence>"}. Each option MUST be a real short answer about the story (a word '
          "or short phrase) - NEVER the letters a, b or c. Exactly one option is correct. Base "
          "everything ONLY on the story. Vary the questions (characters, events, order, feelings, details).")

def _book_level_of(bid):
    return (BOOK_DETAIL.get((bid, "en")) or {}).get("level", 1)

def _bq_count(bid):
    return {1: 3, 2: 4, 3: 5, 4: 6}.get(_book_level_of(bid), 4)   # more + harder questions per level

def _bookquiz_path(bid):
    return os.path.join(BOOKQUIZ, re.sub(r"[^A-Za-z0-9_-]", "_", bid) + ".json")

def load_bookquiz(bid):
    return _read(_bookquiz_path(bid))

def _gen_book_quiz(bid, level, n):
    txt = _book_text(bid)
    if not txt:
        return []
    msgs = [{"role": "system", "content": BQ_SYS % (n, level or 1, n)},
            {"role": "user", "content": "STORY:\n%s\n\nWrite the %d questions as a JSON array now." % (txt[:1500], n)}]
    raw = call_llama(msgs, max_tokens=120 * n + 120, temp=0.7, timeout=240)
    raw = re.sub(r"```(?:json)?", "", raw)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    return [c for c in (_coerce_mcq(q) for q in (arr if isinstance(arr, list) else [])) if c]

def build_bookquiz(bid):
    """Generate a book's FIXED quiz once and cache it; it does not change afterwards."""
    if (bid, "en") not in BOOK_DETAIL and (bid, "fr") not in BOOK_DETAIL:
        return []
    n = _bq_count(bid)
    qs = []
    for _ in range(5):                      # batches of ~3 keep each LLM call short and reliable
        if len(qs) >= n:
            break
        try:
            new = _gen_book_quiz(bid, _book_level_of(bid), 3)
        except Exception:
            continue                        # transient timeout -> retry the batch
        if new:
            qs = _dedupe(qs + new)
    qs = qs[:n]
    if len(qs) >= 2:
        _write(_bookquiz_path(bid), {"questions": qs, "count": len(qs)})
    return qs

_bq_q = queue.Queue()
_bq_enq = set()
_bq_started = [False]

def _bookquiz_worker():
    while True:
        bid = _bq_q.get()
        try:
            if not load_bookquiz(bid):
                build_bookquiz(bid)
        except Exception:
            pass
        with _warm_lock:
            _bq_enq.discard(bid)

def ensure_bookquiz(bid):
    if load_bookquiz(bid):
        return
    with _warm_lock:
        if not _bq_started[0]:
            _bq_started[0] = True
            threading.Thread(target=_bookquiz_worker, daemon=True).start()
        if bid not in _bq_enq:
            _bq_enq.add(bid)
            _bq_q.put(bid)

def serve_bookquiz(bid, lang):
    """Return the book's fixed questions (no answers) instantly from cache. None if not built yet."""
    bq = load_bookquiz(bid)
    if not bq or not bq.get("questions"):
        ensure_bookquiz(bid)
        return None
    out = []
    for i, qd in enumerate(bq["questions"]):
        item = {"type": "mc", "q": qd["q"], "choices": list(qd["choices"]), "qi": i}
        if lang != "en" and lang in LANGS:
            item["q"] = tr(qd["q"], lang)
            item["choices"] = tr_list(qd["choices"], lang)
        out.append(item)
    return {"questions": out, "count": len(out)}

def load_progress(name):
    p = os.path.join(PROGRESS, re.sub(r"[^A-Za-z0-9_-]", "_", name or "guest") + ".json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("videos", {})   # legacy/hand-made records may lack it
            return data, p
        except Exception:
            pass
    return {"name": name, "videos": {}}, p

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def _toint(x, d=0):
    """Coerce a request field to int without crashing the handler on junk input."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return d

def _save(data, p):
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

VALID_GRADES = ("K", "1", "2", "3", "4", "5", "6", "7", "8")

# ---------- accounts: users, passwords, sessions ----------
def _sanitize(name):
    return re.sub(r"[^A-Za-z0-9_-]", "_", (name or "").strip())

_umaster = threading.Lock()
_ulocks = {}
def _ulock(key):
    with _umaster:
        l = _ulocks.get(key)
        if l is None:
            l = threading.Lock()
            _ulocks[key] = l
        return l

def _user_path(username):
    return os.path.join(USERS, _sanitize(username).lower() + ".json")

def load_user(username):
    return _read(_user_path(username))

def save_user(user):
    with _ulock(_sanitize(user["username"]).lower()):
        _write(_user_path(user["username"]), user)

def _pw_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, 150000)
    return h.hex(), salt.hex()

def _pw_ok(password, hash_hex, salt_hex):
    try:
        salt = bytes.fromhex(salt_hex or "")
    except Exception:
        return False
    h, _ = _pw_hash(password, salt)
    return bool(hash_hex) and h == hash_hex

def create_user(username, password, role, lang="en"):
    """Self-service signup. Returns the new user record, or None if the username is
    taken or the input is invalid (uniqueness is enforced by the file existing)."""
    username = (username or "").strip()
    key = _sanitize(username).lower()
    if not username or not key or len(username) < 2 or role not in ("teacher", "student"):
        return None
    if not password or len(password) < 4:
        return None
    if lang not in LANGS:
        lang = "en"
    with _ulock(key):
        p = _user_path(username)
        if os.path.exists(p):
            return None                      # username taken
        h, salt = _pw_hash(password)
        user = {"username": username, "password_hash": h, "password_salt": salt,
                "role": role, "lang": lang, "created": _now(), "last_login": ""}
        if role == "student":
            user["classes"] = []
            user["pending"] = None
        else:
            user["classes_owned"] = []
        _write(p, user)
        return user

def verify_login(username, password):
    user = load_user(username)
    if not user or not _pw_ok(password, user.get("password_hash", ""), user.get("password_salt", "")):
        return None
    user["last_login"] = _now()
    save_user(user)
    return user

# in-memory sessions, write-through to disk so a restart doesn't log everyone out
SESSIONS = _read_json(SESSIONS_PATH, {}) or {}
_slock = threading.Lock()

def persist_sessions():
    _write(SESSIONS_PATH, SESSIONS)

def new_session(username, role):
    token = secrets.token_urlsafe(32)
    with _slock:
        SESSIONS[token] = {"username": username, "role": role, "created": _now(), "last_seen": _now()}
        persist_sessions()
    return token

def session_info(token):
    if not token:
        return None
    with _slock:
        info = SESSIONS.get(token)
        if info:
            info["last_seen"] = _now()
        return dict(info) if info else None

def destroy_session(token):
    with _slock:
        if token in SESSIONS:
            del SESSIONS[token]
            persist_sessions()
            return True
    return False

def _session_role(token, role):
    info = session_info(token)
    return info["username"] if info and info.get("role") == role else None

def _session_student(token):
    return _session_role(token, "student")

def _session_teacher(token):
    return _session_role(token, "teacher")

def student_approved(username):
    u = load_user(username)
    return bool(u and u.get("classes"))

def gate_student(token):
    """A valid student session AND accepted into at least one class."""
    u = _session_student(token)
    return u if u and student_approved(u) else None

# ---------- classes: creation, access codes, join/approve/reject ----------
_cmaster = threading.Lock()
_clocks = {}
def _clock(key):
    with _cmaster:
        l = _clocks.get(key)
        if l is None:
            l = threading.Lock()
            _clocks[key] = l
        return l

_class_index_lock = threading.Lock()
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L - read aloud in class

def _class_path(cid):
    return os.path.join(CLASSES, _sanitize(cid) + ".json")

def load_class(cid):
    return _read(_class_path(cid))

def _write_class(c):
    """Write without locking - only call this from inside a `with _clock(cid):` block."""
    _write(_class_path(c["id"]), c)

def save_class(c):
    with _clock(c["id"]):
        _write_class(c)

def load_classes_index():
    return _read_json(CLASSES_INDEX_PATH, {}) or {}

def _gen_code(idx):
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if code not in idx:
            return code
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))  # astronomically unlikely fallback

def owns_class(teacher, cid):
    c = load_class(cid)
    return bool(c and c.get("teacher") == teacher)

def create_class(teacher, name, grade):
    name = (name or "").strip()
    if not name or grade not in VALID_GRADES:
        return None
    cid = "c_" + hashlib.sha256((name + teacher + str(random.random())).encode()).hexdigest()[:10]
    with _class_index_lock:
        idx = load_classes_index()
        code = _gen_code(idx)
        idx[code] = cid
        _write(CLASSES_INDEX_PATH, idx)
    c = {"id": cid, "name": name, "grade": grade, "teacher": teacher, "access_code": code,
         "created": _now(), "code_regenerated": _now(), "roster": [], "pending": []}
    save_class(c)
    u = load_user(teacher)
    if u is not None:
        u.setdefault("classes_owned", []).append(cid)
        save_user(u)
    return c

def regenerate_class_code(cid):
    c = load_class(cid)
    if not c:
        return None
    with _class_index_lock:
        idx = load_classes_index()
        idx.pop(c.get("access_code"), None)
        new_code = _gen_code(idx)
        idx[new_code] = cid
        _write(CLASSES_INDEX_PATH, idx)
    c["access_code"] = new_code
    c["code_regenerated"] = _now()
    save_class(c)
    return new_code

def teacher_classes(teacher):
    u = load_user(teacher)
    out = []
    for cid in (u or {}).get("classes_owned", []):
        c = load_class(cid)
        if c:
            out.append({"id": c["id"], "name": c["name"], "grade": c["grade"],
                        "access_code": c["access_code"], "created": c["created"],
                        "pending_count": len(c.get("pending", [])),
                        "roster_count": len(c.get("roster", []))})
    return out

def request_join(username, access_code):
    idx = load_classes_index()
    cid = idx.get((access_code or "").strip().upper())
    if not cid:
        return "invalid_code"
    with _clock(cid):
        c = load_class(cid)
        if not c:
            return "invalid_code"
        if username in c.get("roster", []):
            status = "approved"
        else:
            if not any(x["username"] == username for x in c.get("pending", [])):
                c.setdefault("pending", []).append({"username": username, "requested": _now()})
                _write_class(c)
            status = "pending"
    u = load_user(username)
    if u is not None:
        if status == "pending":
            u["pending"] = cid
        save_user(u)
    return status

def _link_student_to_class(username, grade):
    """Seed the student's progress file (created lazily, on first acceptance into a class)."""
    data, p = load_progress(username)
    if not os.path.exists(p):
        data["name"] = username
        data.setdefault("grade", grade if grade in VALID_GRADES else "")
        data.setdefault("videos", {})
        data.setdefault("created", _now())
        data.setdefault("last_active", "")
        _save(data, p)

def approve_student(cid, username):
    with _clock(cid):
        c = load_class(cid)
        if not c:
            return False
        c["pending"] = [x for x in c.get("pending", []) if x["username"] != username]
        if username not in c.get("roster", []):
            c.setdefault("roster", []).append(username)
        _write_class(c)
        grade = c.get("grade", "")
    u = load_user(username)
    if u is None:
        return False
    if u.get("pending") == cid:
        u["pending"] = None
    if cid not in u.setdefault("classes", []):
        u["classes"].append(cid)
    save_user(u)
    _link_student_to_class(username, grade)
    return True

def reject_student(cid, username):
    with _clock(cid):
        c = load_class(cid)
        if not c:
            return False
        c["pending"] = [x for x in c.get("pending", []) if x["username"] != username]
        _write_class(c)
    u = load_user(username)
    if u is not None and u.get("pending") == cid:
        u["pending"] = None
        save_user(u)
    return True

def unenroll_student(cid, username):
    """Drops a student from a class roster only - their account and progress history stay intact."""
    with _clock(cid):
        c = load_class(cid)
        if not c:
            return False
        c["roster"] = [n for n in c.get("roster", []) if n != username]
        _write_class(c)
    u = load_user(username)
    if u is not None:
        u["classes"] = [x for x in u.get("classes", []) if x != cid]
        save_user(u)
    return True

def class_status(username):
    u = load_user(username)
    if not u:
        return {"status": "none"}
    classes = u.get("classes") or []
    if classes:
        cid = classes[0]
        c = load_class(cid) or {}
        return {"status": "approved", "class": {"id": cid, "name": c.get("name", ""), "grade": c.get("grade", "")}}
    if u.get("pending"):
        c = load_class(u["pending"]) or {}
        return {"status": "pending", "class": {"id": u["pending"], "name": c.get("name", "")}}
    return {"status": "none"}

def teacher_add_student(cid, username, password, grade=""):
    """Teacher bypass: add a student straight to the roster, skipping the request/approve
    step - either creating a brand-new account (requires a password), or roster-adding an
    existing one (with an optional password reset - blank leaves it unchanged).
    Returns added|updated|need_password|bad."""
    username = (username or "").strip()
    if not username:
        return "bad"
    c = load_class(cid)
    if not c:
        return "bad"
    u = load_user(username)
    is_new = u is None
    if is_new:
        if not password or len(password) < 4:
            return "need_password"
        u = create_user(username, password, "student")
        if u is None:
            return "bad"
    elif u.get("role") != "student":
        return "bad"
    elif password:
        if len(password) < 4:
            return "need_password"
        h, salt = _pw_hash(password)
        u["password_hash"], u["password_salt"] = h, salt
        save_user(u)
    with _clock(cid):
        c = load_class(cid)
        if username not in c.get("roster", []):
            c.setdefault("roster", []).append(username)
            _write_class(c)
    u = load_user(username)
    if cid not in u.setdefault("classes", []):
        u["classes"].append(cid)
        save_user(u)
    _link_student_to_class(username, c.get("grade", ""))
    if grade in VALID_GRADES:
        teacher_set_grade(username, grade)
    return "added" if is_new else "updated"

def teacher_set_grade(name, grade):
    data, p = load_progress(name)
    if not os.path.exists(p):
        return False
    data["grade"] = grade if grade in VALID_GRADES else ""
    _save(data, p)
    return True

# ---------- notifications (persistent, server-side) ----------
# On disk rather than in client memory, so a teacher signing in tomorrow still sees what
# happened while they were away. Tests are global on this host (they carry no owner
# field), so the EVENT log is global too and only READ state is tracked per teacher -
# that stays correct if a second teacher account is ever added.
NOTIFS_PATH = os.path.join(DATA, "notifications.json")
NOTIF_MAX = 200          # ring buffer - this is a classroom feed, not an audit log
_notif_lock = threading.Lock()

def _load_notifs():
    d = _read_json(NOTIFS_PATH, {}) or {}
    d.setdefault("events", [])
    d.setdefault("read", {})        # {teacher: [event id, ...]}
    d.setdefault("dismissed", {})   # {teacher: [event id, ...]}
    return d

def add_notification(kind, msg_key, params, tid=""):
    """Events store a TRANSLATION KEY plus its parameters, never a rendered sentence.
    The dashboard language can change after an event is recorded, and a stored English
    string would stay frozen in the wrong language forever."""
    with _notif_lock:
        d = _load_notifs()
        d["events"].insert(0, {
            "id": "n_" + hashlib.sha256(
                (str(time.time()) + str(random.random())).encode()).hexdigest()[:10],
            "kind": kind, "key": msg_key, "params": params or {},
            "test_id": tid or "", "at": _now()})
        del d["events"][NOTIF_MAX:]
        _write(NOTIFS_PATH, d)

def list_notifications(teacher):
    d = _load_notifs()
    read = set(d["read"].get(teacher) or [])
    gone = set(d["dismissed"].get(teacher) or [])
    out = [dict(e, unread=e["id"] not in read) for e in d["events"] if e["id"] not in gone]
    return {"notifications": out, "unread": sum(1 for e in out if e["unread"])}

def mark_notifications(teacher, ids=None, all_read=False, dismiss=None):
    with _notif_lock:
        d = _load_notifs()
        if all_read:
            d["read"][teacher] = [e["id"] for e in d["events"]]
        elif ids:
            cur = set(d["read"].get(teacher) or [])
            cur.update(i for i in ids if isinstance(i, str))
            d["read"][teacher] = sorted(cur)
        if dismiss:
            cur = set(d["dismissed"].get(teacher) or [])
            cur.update(i for i in dismiss if isinstance(i, str))
            d["dismissed"][teacher] = sorted(cur)
        _write(NOTIFS_PATH, d)
    return list_notifications(teacher)

# ---------- teacher-built custom tests ----------
TESTS = os.path.join(DATA, "tests")
os.makedirs(TESTS, exist_ok=True)

def _test_path(tid):
    return os.path.join(TESTS, re.sub(r"[^A-Za-z0-9_-]", "_", tid or "") + ".json")

def load_test(tid):
    return _read(_test_path(tid))

def list_tests():
    out = []
    if os.path.isdir(TESTS):
        for fn in sorted(os.listdir(TESTS)):
            if fn.endswith(".json"):
                t = _read(os.path.join(TESTS, fn))
                if t:
                    out.append(t)
    out.sort(key=lambda t: t.get("created", ""), reverse=True)
    return out

def _clean_questions(questions):
    """Shared by create and update so an edited test can never be saved in a shape the
    creation path would have rejected."""
    if not isinstance(questions, list):
        return []
    qs = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        text = (q.get("q") or "").strip()
        if not text:
            continue
        if q.get("type") == "mc":
            ch = [str(c).strip() for c in (q.get("choices") or []) if str(c).strip()]
            ans = q.get("answer")
            if len(ch) >= 2 and isinstance(ans, int) and 0 <= ans < len(ch):
                qs.append({"type": "mc", "q": text, "choices": ch, "answer": ans})
        elif q.get("type") == "text":
            qs.append({"type": "text", "q": text})
    return qs

def create_test(title, questions, grades, students, due=""):
    title = (title or "").strip()
    if not title:
        return None
    qs = _clean_questions(questions)
    if not qs:
        return None
    tid = "t_" + hashlib.sha256((title + str(random.random())).encode()).hexdigest()[:10]
    # whole grades AND individual students can both be assigned at the same time
    grades = [g for g in (grades or []) if g in VALID_GRADES]
    students = [s for s in (students or []) if isinstance(s, str) and s.strip()]
    if not grades and not students:
        return None
    due = due.strip() if isinstance(due, str) else ""
    _write(_test_path(tid), {"id": tid, "title": title, "created": _now(), "due": due,
                             "questions": qs, "assign": {"grades": grades, "students": students},
                             "student_due": {}, "responses": {}})
    add_notification("create", "notif_created",
                     {"title": title, "due": due}, tid)
    return tid

def _student_grade(name):
    data, p = load_progress(name)
    return data.get("grade", "") if os.path.exists(p) else ""

def _assign_grades(test):
    a = test.get("assign", {})
    grades = a.get("grades")
    if grades is None:                       # backward-compat with the old single-grade format
        g = a.get("grade")
        grades = [g] if g else []
    return grades

def test_assigned(test, student, grade=None):
    a = test.get("assign", {})
    if student in (a.get("students") or []):
        return True
    grades = _assign_grades(test)
    if grades:
        if grade is None:
            grade = _student_grade(student)
        return grade in grades
    return False

def my_tests(student):
    """Tests assigned to this student that they have NOT submitted yet."""
    grade = _student_grade(student)
    return [{"id": t["id"], "title": t["title"], "due": t.get("due", "")} for t in list_tests()
            if test_assigned(t, student, grade) and student not in (t.get("responses") or {})]

def submit_test(student, tid, answers):
    t = load_test(tid)
    if not t or not test_assigned(t, student):
        return False
    # `asked` freezes the questions exactly as this student saw them. If the teacher
    # later edits the test, comparing asked-vs-live is what lets the results view say
    # "this question was edited after submission" instead of silently regrading them
    # against wording the student never read.
    t.setdefault("responses", {})[student] = {
        "at": _now(), "answers": answers,
        "asked": [_q_snapshot(q) for q in (t.get("questions") or [])]}
    _write(_test_path(tid), t)
    add_notification("submit", "notif_submitted",
                     {"student": student, "title": t.get("title", "")}, tid)
    return True

def update_test(tid, title, questions, grades, students, due=""):
    """Edit a test after it has been assigned. Responses are preserved verbatim: each one
    already carries the questions as that student saw them (submit_test -> "asked"), so
    the results view can show what changed rather than silently regrading old answers
    against wording those students never read. Only new submissions see the new text."""
    t = load_test(tid)
    if not t:
        return None
    title = (title or "").strip()
    qs = _clean_questions(questions)
    grades = [g for g in (grades or []) if g in VALID_GRADES]
    students = [s for s in (students or []) if isinstance(s, str) and s.strip()]
    if not title or not qs or (not grades and not students):
        return None
    t["title"] = title
    t["questions"] = qs
    t["assign"] = {"grades": grades, "students": students}
    t["due"] = due.strip() if isinstance(due, str) else ""
    t["edited"] = _now()
    _write(_test_path(tid), t)
    return t

def extend_due(tid, due, students=None):
    """Whole-assignment mode rewrites the test's own due date. Per-student mode writes
    into `student_due` and leaves the assignment default untouched, so extending one
    child never quietly moves the deadline for the rest of the class. Passing an empty
    due in per-student mode clears those students' overrides."""
    t = load_test(tid)
    if not t:
        return None
    due = (due or "").strip() if isinstance(due, str) else ""
    if students:
        od = dict(t.get("student_due") or {})
        for s in students:
            if not isinstance(s, str) or not s.strip():
                continue
            if due:
                od[s] = due
            else:
                od.pop(s, None)
        t["student_due"] = od
    else:
        if not due:
            return None                      # never blank the whole assignment by accident
        t["due"] = due
    _write(_test_path(tid), t)
    return t

def delete_test(tid):
    p = _test_path(tid)
    if tid and os.path.exists(p):
        try:
            os.remove(p)
            return True
        except Exception:
            return False
    return False

# ---------- test results: assignment roster, due dates, class average ----------
# Everything below is computed SERVER-SIDE against the server clock. The class average
# is deliberately not derivable on the client: a teacher (or a student on a shared
# laptop) must not be able to unlock an unfinished average by rolling their device
# date forward, so the readiness decision is made here and only its result is sent.

def all_known_students():
    """Every student on a class roster on this host - the universe a test can assign to."""
    seen = []
    if os.path.isdir(CLASSES):
        for fn in sorted(os.listdir(CLASSES)):
            if not fn.endswith(".json"):
                continue
            c = _read(os.path.join(CLASSES, fn)) or {}
            for n in c.get("roster") or []:
                if n not in seen:
                    seen.append(n)
    return seen

def assigned_students(test):
    """Everyone the assignment matches, plus anyone who has already responded - a student
    whose grade changed after submitting still belongs in the denominator."""
    out = [n for n in all_known_students() if test_assigned(test, n)]
    for n in (test.get("responses") or {}):
        if n not in out:
            out.append(n)
    return sorted(out)

def _due_dt(due):
    """Normalise a stored due value ("YYYY-MM-DD" or "YYYY-MM-DDTHH:MM") to the same
    "YYYY-MM-DD HH:MM" shape _now() emits, so the two compare correctly as plain strings
    (both are zero-padded big-endian). A date with no time means the END of that day -
    a test due "Friday" is not overdue at 00:01 on Friday morning."""
    d = (due or "").strip().replace("T", " ")
    if not d:
        return ""
    if len(d) == 10:
        d += " 23:59"
    return d

def effective_due(test, student=None):
    """A per-student extension always wins over the assignment-wide due date. Overrides
    live in their own map so the shared default is never rewritten for everyone else."""
    if student:
        od = (test.get("student_due") or {}).get(student)
        if od:
            return od
    return test.get("due", "")

def _due_passed(due):
    d = _due_dt(due)
    return bool(d) and _now() > d

def _q_snapshot(q):
    """The question as stored at submission time - see submit_test."""
    s = {"type": q.get("type"), "q": q.get("q", "")}
    if q.get("type") == "mc":
        s["choices"] = list(q.get("choices") or [])
        s["answer"] = q.get("answer")
    return s

def _q_changed(asked, cur):
    """True when the live question differs from the one this student actually answered."""
    if not asked or not cur:
        return False
    if (asked.get("q") or "") != (cur.get("q") or ""):
        return True
    if cur.get("type") == "mc":
        return (list(asked.get("choices") or []) != list(cur.get("choices") or [])
                or asked.get("answer") != cur.get("answer"))
    return False

def _answer_of(response, qi):
    """Answers arrive as a JS object keyed by question index, so they land here with
    STRING keys after the JSON round-trip - accept either form."""
    a = response.get("answers") or {}
    return a.get(str(qi), a.get(qi))

def _is_correct(q, ans):
    """Only multiple-choice grades automatically. Free response has no stored correct
    answer, so it returns None and is excluded from the average rather than counted
    wrong - marking every written answer incorrect would make the average meaningless."""
    if (q or {}).get("type") != "mc":
        return None
    return ans == q.get("answer")

def test_stats(test):
    """Class average + per-question breakdown, and whether they may be shown yet.

    Ready once at least one student has submitted AND either everyone assigned has
    submitted, or every still-pending student's own deadline has passed. Testing each
    pending student's EFFECTIVE due date is what makes extensions hold the average back:
    one student with an unexpired extension keeps the class average provisional, which
    is the point - a average that moves after you have acted on it is worse than none."""
    roster = assigned_students(test)
    resp = test.get("responses") or {}
    qs = test.get("questions") or []
    submitted = [s for s in roster if s in resp]
    pending = [s for s in roster if s not in resp]
    ready = bool(resp) and (not pending
                            or all(_due_passed(effective_due(test, s)) for s in pending))
    per_q, tot_c, tot_a = [], 0, 0
    for qi, q in enumerate(qs):
        c = a = 0
        for name in resp:
            ok = _is_correct(q, _answer_of(resp[name], qi))
            if ok is None:
                continue
            a += 1
            c += 1 if ok else 0
        per_q.append({"q": q.get("q", ""), "type": q.get("type"), "correct": c,
                      "answered": a, "pct": (int(round(c * 100.0 / a)) if a else None)})
        tot_c += c
        tot_a += a
    return {"roster": roster, "submitted": submitted, "pending": pending,
            "total": len(roster), "sub_count": len(submitted), "ready": ready,
            "average": (int(round(tot_c * 100.0 / tot_a)) if tot_a else None),
            "graded_answers": tot_a, "per_question": per_q,
            "due_passed": _due_passed(test.get("due", "")), "now": _now()}

def test_detail(test):
    """Everything the teacher's detail view needs, in one response: the test itself,
    the computed stats, and one row per assigned student (submitted or not) carrying
    their effective due date, whether it was individually extended, and their graded
    answers with the edited-after-submission flag resolved server-side."""
    resp = test.get("responses") or {}
    qs = test.get("questions") or []
    overrides = test.get("student_due") or {}
    stats = test_stats(test)
    rows = []
    for name in stats["roster"]:
        r = resp.get(name)
        row = {"student": name, "submitted": bool(r), "at": (r or {}).get("at", ""),
               "due": effective_due(test, name), "extended": name in overrides,
               "answers": []}
        if r:
            asked = r.get("asked") or []
            for qi, q in enumerate(qs):
                ans = _answer_of(r, qi)
                ok = _is_correct(q, ans)
                a0 = asked[qi] if qi < len(asked) else None
                row["answers"].append({
                    "q": q.get("q", ""), "type": q.get("type"), "correct": ok,
                    "answer": ans,
                    "answer_text": (q.get("choices") or [])[ans]
                                   if (q.get("type") == "mc" and isinstance(ans, int)
                                       and 0 <= ans < len(q.get("choices") or [])) else ans,
                    "correct_text": (q.get("choices") or [])[q.get("answer")]
                                    if (q.get("type") == "mc"
                                        and isinstance(q.get("answer"), int)
                                        and 0 <= q.get("answer") < len(q.get("choices") or [])) else "",
                    "edited": _q_changed(a0, q),
                    "asked_q": (a0 or {}).get("q", "") if _q_changed(a0, q) else "",
                    "asked_correct": ((a0 or {}).get("choices") or [None] * 99)[(a0 or {}).get("answer")]
                                     if (_q_changed(a0, q) and (a0 or {}).get("type") == "mc"
                                         and isinstance((a0 or {}).get("answer"), int)) else "",
                    "was_correct": _is_correct(a0, ans) if _q_changed(a0, q) else None})
        rows.append(row)
    return {"test": test, "stats": stats, "rows": rows}

# ---------- test retention / archival ----------
# Default is OFF ("never"): nothing is ever deleted until a teacher explicitly picks a
# window and saves it. When a sweep does run, the summary row is written and flushed to
# disk BEFORE any test file is removed, so an interrupted sweep can lose the detailed
# answers at worst and never the grade trend they contributed to.
ARCHIVE_PATH = os.path.join(DATA, "test_archive.json")
RETENTION_DAYS = ("never", "30", "60", "90")

def load_retention():
    d = (_read_json(SETUP_PATH, {}) or {}).get("retention") or {}
    days = str(d.get("days", "never"))
    return {"days": days if days in RETENTION_DAYS else "never",
            "mode": "confirm" if d.get("mode") == "confirm" else "archive"}

def save_retention(days, mode):
    days = str(days)
    if days not in RETENTION_DAYS:
        days = "never"
    mode = "confirm" if mode == "confirm" else "archive"
    existing = _read_json(SETUP_PATH, {}) or {}     # preserve base_lang / configured
    existing["retention"] = {"days": days, "mode": mode}
    os.makedirs(DATA, exist_ok=True)
    _write(SETUP_PATH, existing)
    return {"days": days, "mode": mode}

def load_archive():
    a = _read_json(ARCHIVE_PATH, None) or {}
    a.setdefault("summaries", [])
    return a

def archive_summary(test):
    """The lightweight record that outlives the test itself - enough to keep a grade
    trend readable, with no per-student answers retained."""
    st = test_stats(test)
    return {"id": test.get("id"), "title": test.get("title", ""),
            "due": test.get("due", ""), "created": test.get("created", ""),
            "average": st["average"], "sub_count": st["sub_count"],
            "total": st["total"], "q_count": len(test.get("questions") or []),
            "archived": _now()}

def _expired_tests(days):
    """Tests past the retention window, measured from the due date - or from the
    creation date when a test never had one, so undated tests still age out."""
    if days == "never":
        return []
    try:
        n = int(days)
    except (TypeError, ValueError):
        return []
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=n)).strftime("%Y-%m-%d %H:%M")
    out = []
    for t in list_tests():
        ref = _due_dt(t.get("due", "")) or _due_dt(t.get("created", ""))
        if ref and ref < cutoff:
            out.append(t)
    return out

def retention_status():
    r = load_retention()
    return {"retention": r,
            "pending": [archive_summary(t) for t in _expired_tests(r["days"])],
            "archived": load_archive()["summaries"]}

def run_archive_sweep(only_ids=None):
    """Background check invoked on dashboard load. In "confirm" mode it never deletes on
    its own - it reports what is eligible and waits for an explicit call carrying ids."""
    r = load_retention()
    if r["days"] == "never":
        return {"ran": False, "archived": [], "pending": []}
    targets = _expired_tests(r["days"])
    if only_ids is not None:
        targets = [t for t in targets if t.get("id") in only_ids]
    elif r["mode"] == "confirm":
        return {"ran": False, "archived": [],
                "pending": [archive_summary(t) for t in targets]}
    if not targets:
        return {"ran": True, "archived": [], "pending": []}
    arch = load_archive()
    have = {s.get("id") for s in arch["summaries"]}
    for t in targets:
        if t.get("id") not in have:
            arch["summaries"].insert(0, archive_summary(t))
    _write(ARCHIVE_PATH, arch)          # durable BEFORE anything is removed
    done = [t.get("id") for t in targets if delete_test(t.get("id"))]
    return {"ran": True, "archived": done, "pending": []}

def save_progress(student, vid, ok):
    data, p = load_progress(student)
    v = data["videos"].setdefault(vid, {})
    v["tried"] = v.get("tried", 0) + 1
    if ok:
        v["correct"] = v.get("correct", 0) + 1
    data["last_active"] = _now()
    _save(data, p)

def log_event(student, vid, kind, status=None):
    data, p = load_progress(student)
    _roll_day(data)
    data["last_active"] = _now()
    if kind == "view" and vid:
        v = data["videos"].setdefault(vid, {}); v["viewed"] = v.get("viewed", 0) + 1
        data["last_video"] = vid
    elif kind == "finish" and vid:
        v = data["videos"].setdefault(vid, {}); v["finished"] = True
        data["last_video"] = vid
        if vid not in data["today"]["watched"]:
            data["today"]["watched"].append(vid)
    elif kind == "ask":
        if vid == "helper":
            data["helper_asked"] = data.get("helper_asked", 0) + 1
        elif vid:
            v = data["videos"].setdefault(vid, {}); v["asked"] = v.get("asked", 0) + 1
    elif kind == "status" and vid:
        v = data["videos"].setdefault(vid, {})
        if status in ("complete", "todo"):
            v["status"] = status
        else:
            v.pop("status", None)
    _save(data, p)

def _today_str():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def _fresh_day(d):
    return {"date": d, "stars": 0, "tries": {}, "passed": [], "failed": [], "quizzes": {}, "watched": []}

def _roll_day(data):
    """Archive the previous day and start a fresh 'today' bucket when the date changes.
    Lazy daily reset so the dashboard starts clean every morning."""
    today = _today_str()
    cur = data.get("today")
    if cur and cur.get("date") == today:
        return False
    if cur and (cur.get("stars") or cur.get("tries") or cur.get("watched")):
        hist = data.setdefault("history", [])
        hist.append(cur)                       # archive the full day record (videos + scores)
        data["history"] = hist[-120:]
    data["today"] = _fresh_day(today)
    return True

def record_quiz(student, vid, correct, total):
    """Record a finished quiz attempt. Pass = at least 2 of 3 correct (>= 2/3)."""
    if vid not in CAT:
        return None
    data, p = load_progress(student)
    _roll_day(data)
    v = data["videos"].setdefault(vid, {})
    passed = (total >= 1 and correct * 3 >= total * 2)
    v["last_score"] = correct
    v["last_total"] = total
    v["last_quiz"] = _now()
    v["best"] = max(v.get("best", 0), correct)
    t = data["today"]
    t.setdefault("quizzes", {})
    t.setdefault("watched", [])
    t.setdefault("tries", {})
    t["tries"][vid] = t["tries"].get(vid, 0) + 1
    qd = t["quizzes"].setdefault(vid, {"tries": 0})
    qd["score"] = correct
    qd["total"] = total
    qd["tries"] = qd.get("tries", 0) + 1
    qd["passed"] = bool(passed or qd.get("passed"))
    if passed:
        v["passed"] = True
        if vid not in t["passed"]:
            t["passed"].append(vid)
            t["stars"] = t.get("stars", 0) + 1
        t["failed"] = [x for x in t.get("failed", []) if x != vid]
        if vid not in t["watched"]:
            t["watched"].append(vid)
    elif vid not in t["passed"] and vid not in t["failed"]:
        t["failed"].append(vid)
    data["last_quiz_video"] = vid
    data["last_quiz_passed"] = passed
    data["last_quiz_at"] = _now()
    data["last_active"] = _now()
    data["mode"] = "math"
    _save(data, p)
    return passed

def record_book_quiz(student, bid, title, correct, total):
    """Record a finished book quiz. Pass = >=2/3. Reading stars add to the same daily bar."""
    data, p = load_progress(student)
    _roll_day(data)
    passed = (total >= 1 and correct * 5 >= total * 3)      # 60%: 2 of 3, or 3 of 5
    t = data["today"]
    t.setdefault("book_quizzes", {})
    t.setdefault("book_passed", [])
    bq = t["book_quizzes"].setdefault(bid, {"tries": 0})
    bq["title"] = title; bq["score"] = correct; bq["total"] = total
    bq["tries"] = bq.get("tries", 0) + 1; bq["passed"] = bool(passed or bq.get("passed"))
    rec = data.setdefault("books", {}).setdefault(bid, {})
    rec["title"] = title
    if passed:
        rec["passed"] = True
        if bid not in t["book_passed"]:
            t["book_passed"].append(bid)
            t["stars"] = t.get("stars", 0) + 1      # reading star -> shared daily progress bar
    data["last_book_quiz"] = {"id": bid, "title": title, "passed": passed,
                              "score": correct, "total": total, "at": _now()}
    data["mode"] = "reading"
    data["last_active"] = _now()
    _save(data, p)
    return passed

def set_reading_mode(student, mode, bid, title, finished=False, page=None):
    """Track math/reading mode and the current book. A book only counts as READ once the child
    actually reaches the last page (finished=True) - opening it is not enough."""
    data, p = load_progress(student)
    _roll_day(data)
    if mode in ("reading", "math"):
        data["mode"] = mode
    if bid:
        data["current_book"] = {"id": bid, "title": title or ""}
        rec = data.setdefault("books", {}).setdefault(bid, {})
        rec["title"] = title or rec.get("title", "")
        if page is not None:
            try:
                rec["page"] = max(0, int(page))
            except Exception:
                pass
        if finished:
            rec["read"] = True                          # genuinely read to the end
            if bid not in data["today"].setdefault("books_read", []):
                data["today"]["books_read"].append(bid)
    data["last_active"] = _now()
    _save(data, p)

def class_summary(students):
    """Live class facts for the teacher: top passed lessons, most failed, active count."""
    passed_c, failed_c, active = {}, {}, 0
    now = datetime.datetime.now()
    for d in students:
        t = d.get("today", {})
        for vid in t.get("passed", []):
            passed_c[vid] = passed_c.get(vid, 0) + 1
        for vid in t.get("failed", []):
            failed_c[vid] = failed_c.get(vid, 0) + 1
        la = d.get("last_active", "")
        if la:
            try:
                if (now - datetime.datetime.strptime(la, "%Y-%m-%d %H:%M")).total_seconds() <= 900:
                    active += 1
            except Exception:
                pass
    title = lambda vid: (CAT.get(vid) or {}).get("title", vid)
    top = sorted(passed_c.items(), key=lambda x: -x[1])[:3]
    worst = sorted(failed_c.items(), key=lambda x: -x[1])[:1]
    return {"top_passed": [{"vid": v, "title": title(v), "count": c} for v, c in top],
            "most_failed": ({"vid": worst[0][0], "title": title(worst[0][0]), "count": worst[0][1]} if worst else None),
            "active": active}

# ---------- history (read-only; its own endpoint so it never touches the live screen) ----------
def _vtitle(vid):
    return (CAT.get(vid) or {}).get("title", vid)

def _norm_day(rec):
    """Normalize a today/history record into a display day with video titles."""
    watched = sorted(({"vid": x, "title": _vtitle(x)} for x in (rec.get("watched") or [])),
                     key=lambda x: x["title"].lower())
    quizzes = []
    qz = rec.get("quizzes")
    if isinstance(qz, dict):
        for vid, q in qz.items():
            quizzes.append({"vid": vid, "title": _vtitle(vid), "score": q.get("score"),
                            "total": q.get("total"), "passed": bool(q.get("passed"))})
        quizzes.sort(key=lambda x: x["title"].lower())
    bookq = []
    bqz = rec.get("book_quizzes")
    if isinstance(bqz, dict):
        for bid, q in bqz.items():
            bookq.append({"id": bid, "title": q.get("title", bid), "score": q.get("score"),
                          "total": q.get("total"), "passed": bool(q.get("passed"))})
        bookq.sort(key=lambda x: (x["title"] or "").lower())
    return {"date": rec.get("date", ""), "stars": rec.get("stars", 0),
            "watched": watched, "quizzes": quizzes, "book_quizzes": bookq}

def _all_days(data):
    days = []
    cur = data.get("today")
    if cur and (cur.get("stars") or cur.get("quizzes") or cur.get("watched")):
        days.append(cur)
    days.extend(data.get("history") or [])
    return days

def student_summary(data):
    """A safe view of a student's progress for the client (no password fields)."""
    return {"name": data.get("name", ""), "videos": data.get("videos", {}),
            "helper_asked": data.get("helper_asked", 0), "last_active": data.get("last_active", ""),
            "last_video": data.get("last_video", ""), "last_quiz_video": data.get("last_quiz_video", ""),
            "last_quiz_passed": data.get("last_quiz_passed"), "books": data.get("books", {}),
            "mode": data.get("mode", ""), "current_book": data.get("current_book"),
            "grade": data.get("grade", ""), "tests": my_tests(data.get("name", ""))}

def perf_level(student):
    """Adaptive level from a student's quiz history: 'struggling' | 'advanced' | ''."""
    if not student:
        return ""
    data, p = load_progress(student)
    if not os.path.exists(p):
        return ""
    vids = data.get("videos", {})
    tried = sum(v.get("tried", 0) for v in vids.values())
    correct = sum(v.get("correct", 0) for v in vids.values())
    last_passed = data.get("last_quiz_passed")
    ratio = (correct / tried) if tried else None
    if last_passed is None and tried < 3:
        return ""                       # not enough signal yet
    if last_passed is False or (ratio is not None and tried >= 4 and ratio < 0.5):
        return "struggling"
    if last_passed is True and (ratio is None or ratio >= 0.85):
        return "advanced"
    return ""

ADAPT = {
    "struggling": (" IMPORTANT: this child is finding the material hard. Use only very simple, "
                   "everyday words and very short sentences. Give lots of warm praise and "
                   "encouragement, and explain one tiny step at a time."),
    "advanced": (" NOTE: this child is doing extremely well. Use richer vocabulary and gently "
                 "challenge them with a slightly harder idea or a tougher follow-up question."),
}

# ---------- homework helper context: subject + grade + language -> ONE system prompt ----------
# The helper sends all three with every message and they are composed here, not client-side:
# the model must never be steered by whatever a browser chooses to send as a prompt.

# Subject framing. "general" is the default and adds nothing, so a child who has not
# picked a subject still gets the full-range tutor rather than a degraded one.
HELP_SUBJECT = {
    "math": (" The student has chosen MATH. Work the problem step by step and never just state "
             "the answer: show each step, say why it works, and where it helps, count or draw in "
             "words (for example: 4 groups of 3 = 3 + 3 + 3 + 3). Finish by asking them to try the "
             "next similar one."),
    "reading": (" The student has chosen READING. Help them understand meaning: explain tricky "
                "words in plainer words, retell confusing sentences more simply, and ask what they "
                "think happens next or why a character acted that way."),
    "science": (" The student has chosen SCIENCE. Explain with everyday comparisons they can "
                "picture, keep the facts correct, and separate what scientists know from what is "
                "still being studied. Invite them to notice the same thing in the world around them."),
    "writing": (" The student has chosen WRITING. Help them plan and improve their own words - "
                "never write the assignment for them. Suggest a structure, point out one or two "
                "things to fix at a time, and always name something they did well."),
}

# Grade bands. Kept to three bands rather than nine: the model cannot reliably tell a
# grade 5 from a grade 6 register, and pretending otherwise would be false precision.
GRADE_BAND = {
    "k2": (" The student is in kindergarten to grade 2 (about ages 5 to 8). Use very short "
           "sentences and the simplest everyday words. One idea per sentence. Keep the whole "
           "answer under about 80 words, and be warm and encouraging throughout."),
    "35": (" The student is in grades 3 to 5 (about ages 8 to 11). Use clear, simple language and "
           "short paragraphs. You may introduce a subject word if you explain it immediately. "
           "Keep the whole answer under about 140 words."),
    "68": (" The student is in grades 6 to 8 (about ages 11 to 14). You may use proper subject "
           "vocabulary and fuller explanations, and can assume the basics are known. Explain the "
           "reasoning rather than only the result; less hand-holding, but stay encouraging. State "
           "the method directly - do NOT count up or down one number at a time for a student "
           "this old."),
}

def grade_band(grade):
    g = str(grade or "").strip().upper()
    if g in ("K", "1", "2"):
        return "k2"
    if g in ("3", "4", "5"):
        return "35"
    if g in ("6", "7", "8"):
        return "68"
    return ""

def helper_system(mode, subject, grade, lang, student):
    """Compose the single system prompt for one homework-helper turn.

    Order matters: role, then subject, then grade band, then adaptive level, then the
    reply language LAST so it is the instruction nearest the conversation and least
    likely to be lost. Every part is optional - an unselected subject or an unknown
    grade simply contributes nothing rather than blocking the answer.
    """
    sys = MATH_HELP_SYS if mode == "math" else HELP_SYS
    # the math helper is already subject-locked; a second subject framing would fight it
    if mode != "math":
        sys += HELP_SUBJECT.get((subject or "").lower(), "")
    sys += GRADE_BAND.get(grade_band(grade), "")
    lvl = perf_level(student)
    if lvl in ADAPT:
        sys += ADAPT[lvl]
    # restated after the grade band: with "fuller explanations" appended, grade 6-8
    # answers began emitting LaTeX (\[ 52 - 8 \]) even though the base prompt bans it.
    # The last instruction about formatting has to be the one we want obeyed.
    sys += (" Write ALL mathematics in plain text - 52 - 8 = 44, 3 x 4 = 12 - and never use "
            "LaTeX, backslashes, or bracket notation.")
    if lang != "en":
        # last, and stated twice: a 3B model asked to change register AND language will
        # otherwise drift back to English partway through a long answer
        sys += (" Always reply in %s. Write your entire answer in %s, including every "
                "heading and list item." % (LANGS[lang], LANGS[lang]))
    return sys

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"     # keep-alive: fewer connections for many devices
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400" if cache else "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def _lang(self, q):
        l = q.get("lang", ["en"])[0]
        return l if l in LANGS else "en"

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        lang = self._lang(q)
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):], cache=True)
        if path == "/api/langs":
            return self._send(200, LANGS)
        if path == "/api/setup":
            return self._send(200, {"configured": SETUP["configured"],
                                    "base_lang": SETUP["base_lang"]})
        if path == "/api/i18n":
            return self._send(200, ui_strings(lang))
        if path == "/api/catalog":
            return self._send(200, catalog_for(lang))
        if path.startswith("/api/quiz/"):
            vid = path[len("/api/quiz/"):]
            seen = set()
            try:
                seen = set(int(x) for x in q.get("seen", [""])[0].split(",") if x.strip() != "")
            except Exception:
                seen = set()
            out = quiz_attempt(vid, lang, seen)
            return self._send(404, {"error": "no quiz"}) if out is None else self._send(200, out)
        if path == "/api/books":
            bl = lang if lang in LANGS else "en"
            items = BOOKS_BY_LANG.get(bl) or BOOKS_BY_LANG.get("en", [])
            seq = ["K", "1", "2", "3", "4", "5", "6", "7", "8"]
            groups = {}
            for b in items:
                g = b.get("grade") or "1"
                groups.setdefault(g, []).append({
                    "id": b["id"], "title": b["title"], "grade": g, "level": b.get("level"),
                    "cover": ("/api/bookimg/%s/%s" % (b["id"], b["cover"]) if b.get("cover") else ""),
                    "author": b["author"], "illustrator": b["illustrator"],
                    "pages": b.get("page_count", 0)})
            order = [g for g in seq if g in groups] + [g for g in groups if g not in seq]
            return self._send(200, [{"grade": g, "books": groups[g]} for g in order])
        if path.startswith("/api/book/"):
            bid = path[len("/api/book/"):]
            bl = lang if lang in LANGS else "en"
            b = BOOK_DETAIL.get((bid, bl))
            if not b and bl != "en":
                b = translate_book(bid, bl)   # machine-translate on the fly + cache
            if not b:
                b = BOOK_DETAIL.get((bid, "en")) or BOOK_DETAIL.get((bid, "fr"))
            if not b:
                return self._send(404, {"error": "no book"})
            imgs = b.get("images", []); pages = b.get("pages", [])
            if imgs:
                spreads = [{"image": "/api/bookimg/%s/%s" % (bid, im),
                            "text": (pages[i - 1] if 1 <= i <= len(pages) else "")} for i, im in enumerate(imgs)]
            else:                                   # text-only chapter book: cover + one spread per text page
                spreads = [{"image": "", "text": ""}] + [{"image": "", "text": p} for p in pages]
            credits = {k: b.get(k) for k in ("author", "illustrator", "translator", "source",
                                             "project_home", "source_url", "license", "license_url")}
            credits["mt"] = bool(b.get("mt"))
            ensure_bookquiz(bid)              # build the fixed quiz (if missing) while the child reads
            return self._send(200, {"id": bid, "language": b.get("language", bl),
                                    "title": b.get("title", ""), "level": b.get("level"),
                                    "grade": b.get("grade"), "textbook": (not imgs),
                                    "spreads": spreads, "credits": credits})
        if path.startswith("/api/bookimg/"):
            rel = path[len("/api/bookimg/"):].replace("..", "")
            fp = os.path.join(BOOKS, *[x for x in rel.split("/") if x])
            if not os.path.exists(fp):
                return self._send(404, "no", "text/plain")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), "image/jpeg", cache=True)
        if path.startswith("/api/bookquiz/"):
            bid = path[len("/api/bookquiz/"):]
            bl = lang if lang in LANGS else "en"
            out = serve_bookquiz(bid, bl)
            return self._send(200, out) if out else self._send(200, {"questions": [], "ready": False})
        if path.startswith("/api/video/"):
            return self._video(path[len("/api/video/"):])
        if path.startswith("/api/subs/"):
            return self._subs(path[len("/api/subs/"):].split(".")[0], lang)
        if path.startswith("/api/thumb/"):
            vid = path[len("/api/thumb/"):].split(".")[0]
            if vid not in CAT:
                return self._send(404, "no", "text/plain")
            fp = make_thumb(vid)
            if not fp:
                return self._send(404, "no thumb", "text/plain")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), "image/jpeg", cache=True)
        if path == "/teacher":
            return self._static("teacher.html")
        if path == "/api/teacher/classes":
            teacher = _session_teacher(q.get("session", [""])[0])
            if not teacher:
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"classes": teacher_classes(teacher)})
        if path == "/api/teacher/pending":
            teacher = _session_teacher(q.get("session", [""])[0])
            cid = q.get("class_id", [""])[0]
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            c = load_class(cid)
            return self._send(200, {"pending": (c or {}).get("pending", [])})
        if path == "/api/teacher/tests":
            if not _session_teacher(q.get("session", [""])[0]):
                return self._send(403, {"error": "forbidden"})
            # the list view only needs a summary row per test - the full question and
            # response payload is fetched on demand by /api/teacher/test/<id>
            rows = []
            for t in list_tests():
                st = test_stats(t)
                rows.append({"id": t["id"], "title": t.get("title", ""),
                             "due": t.get("due", ""), "created": t.get("created", ""),
                             "assign": t.get("assign", {}),
                             "q_count": len(t.get("questions") or []),
                             "sub_count": st["sub_count"], "total": st["total"],
                             "due_passed": st["due_passed"], "ready": st["ready"],
                             "average": st["average"]})
            return self._send(200, {"tests": rows, "now": _now()})
        if path.startswith("/api/teacher/test/"):
            if not _session_teacher(q.get("session", [""])[0]):
                return self._send(403, {"error": "forbidden"})
            t = load_test(path.rsplit("/", 1)[-1])
            if not t:
                return self._send(404, {"error": "not found"})
            return self._send(200, test_detail(t))
        if path == "/api/teacher/notifications":
            teacher = _session_teacher(q.get("session", [""])[0])
            if not teacher:
                return self._send(403, {"error": "forbidden"})
            return self._send(200, list_notifications(teacher))
        if path == "/api/teacher/retention":
            if not _session_teacher(q.get("session", [""])[0]):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, retention_status())
        if path.startswith("/api/test/"):
            t = load_test(path.rsplit("/", 1)[-1])
            if not t:
                return self._send(404, {"error": "not found"})
            # strip correct answers before sending to a student
            qs = [{"type": x["type"], "q": x["q"], "choices": x.get("choices", [])}
                  for x in t.get("questions", [])]
            return self._send(200, {"id": t["id"], "title": t["title"],
                                    "due": t.get("due", ""), "questions": qs})
        if path == "/api/student/class_status":
            student = _session_student(q.get("session", [""])[0])
            if not student:
                return self._send(403, {"error": "forbidden"})
            return self._send(200, class_status(student))
        if path.startswith("/api/teacher/class/"):
            rest = path[len("/api/teacher/class/"):]
            parts = rest.split("/")
            if len(parts) == 2 and parts[1] in ("progress_all", "history"):
                cid, action = parts
                teacher = _session_teacher(q.get("session", [""])[0])
                if not teacher or not owns_class(teacher, cid):
                    return self._send(403, {"error": "forbidden"})
                if action == "progress_all":
                    c = load_class(cid)
                    if not c:
                        return self._send(404, {"error": "not found"})
                    out = []
                    for username in c.get("roster", []):
                        data, p = load_progress(username)
                        if not os.path.exists(p):
                            continue
                        if _roll_day(data):          # archive + reset a stale day on read
                            _save(data, p)
                        out.append(data)
                    return self._send(200, {"students": out, "summary": class_summary(out)})
                # action == "history": same shape as the old global endpoint, scoped to this roster
                c = load_class(cid)
                recs = []
                for username in (c or {}).get("roster", []):
                    data, p = load_progress(username)
                    if os.path.exists(p):
                        recs.append(data)
                if q.get("meta", [""])[0]:
                    names = [d.get("name", "") for d in recs if d.get("name")]
                    return self._send(200, {"students": sorted(names, key=str.lower)})
                month = q.get("month", [""])[0]     # "YYYY-M", batched whole-month fetch for the calendar view
                if month:
                    try:
                        y_s, m_s = month.split("-")
                        y, m = int(y_s), int(m_s)
                        prefix = "%04d-%02d" % (y, m)
                    except Exception:
                        return self._send(400, {"error": "bad month"})
                    by_day = {}
                    for d in recs:
                        name = d.get("name", "")
                        for day in _all_days(d):
                            dt = day.get("date", "")
                            if dt.startswith(prefix):
                                nd = _norm_day(day)
                                nd["name"] = name
                                by_day.setdefault(dt, []).append(nd)
                    for dt in by_day:
                        by_day[dt].sort(key=lambda x: x["name"].lower())
                    return self._send(200, {"mode": "month", "year": y, "month": m, "days": by_day})
                return self._send(200, {"mode": "month", "year": 0, "month": 0, "days": {}})
        return self._send(404, {"error": "not found"})

    def _static(self, rel, cache=False):
        rel = rel.replace("..", "")
        fp = os.path.join(STATIC, rel)
        if not os.path.exists(fp):
            return self._send(404, "not found", "text/plain")
        ctype = {"html": "text/html", "js": "application/javascript", "css": "text/css",
                 "png": "image/png", "svg": "image/svg+xml", "woff2": "font/woff2"}.get(
                 rel.rsplit(".", 1)[-1], "application/octet-stream")
        long_cache = rel.endswith((".woff2", ".png", ".svg", ".jpg"))  # only fonts/images
        with open(fp, "rb") as f:
            self._send(200, f.read(), ctype + "; charset=utf-8", cache=long_cache)

    def _subs(self, vid, lang):
        if vid not in CAT:
            return self._send(404, "no", "text/plain")
        vtt = make_vtt(vid, lang)
        if vtt is None:
            return self._send(404, "no subs", "text/plain")
        self._send(200, vtt, "text/vtt; charset=utf-8")

    def _video(self, vid):
        if vid not in CAT:
            return self._send(404, "no video", "text/plain")
        fp = os.path.join(CONTENT, vid + ".mp4")
        if not os.path.exists(fp):
            return self._send(404, "file missing", "text/plain")
        size = os.path.getsize(fp)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            if m:
                start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
        end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "public, max-age=86400")
        if rng:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        try:
            with open(fp, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1048576, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._json()
        except Exception:
            return self._send(400, {"error": "bad json"})
        if path == "/api/ask":
            return self._ask(data)
        if path == "/api/chat":
            return self._chat(data)
        if path == "/api/grade":
            return self._grade(data)
        if path == "/api/signup":
            username = (data.get("username") or "").strip()
            password = data.get("password") or ""
            role = data.get("role")
            lang = data.get("lang") or "en"
            if role not in ("teacher", "student") or len(username) < 2 or len(password) < 4:
                return self._send(400, {"error": "bad_request"})
            user = create_user(username, password, role, lang)
            if not user:
                return self._send(200, {"ok": False, "error": "username_taken"})
            token = new_session(user["username"], user["role"])
            return self._send(200, {"ok": True, "session": token, "role": user["role"],
                                    "username": user["username"], "lang": user.get("lang", "en")})
        if path == "/api/login":
            user = verify_login(data.get("username"), data.get("password"))
            if not user:
                return self._send(200, {"ok": False, "error": "invalid_login"})
            token = new_session(user["username"], user["role"])
            return self._send(200, {"ok": True, "session": token, "role": user["role"],
                                    "username": user["username"], "lang": user.get("lang", "en")})
        if path == "/api/logout":
            destroy_session(data.get("session"))
            return self._send(200, {"ok": True})
        if path == "/api/set_lang":
            info = session_info(data.get("session"))
            lang = data.get("lang")
            if not info or lang not in LANGS:
                return self._send(400, {"error": "bad_request"})
            user = load_user(info["username"])
            if not user:
                return self._send(404, {"error": "not_found"})
            user["lang"] = lang
            save_user(user)
            return self._send(200, {"ok": True, "lang": lang})
        if path == "/api/setup":
            # first-run only: pick the base language (accounts are self-service, no password here)
            if SETUP["configured"]:
                return self._send(403, {"error": "already configured"})
            save_setup(base_lang=data.get("base_lang"))
            return self._send(200, {"ok": True, "base_lang": SETUP["base_lang"]})
        if path == "/api/teacher/settings":
            # change the site's default base language later
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            save_setup(base_lang=data.get("base_lang"))
            return self._send(200, {"ok": True, "base_lang": SETUP["base_lang"]})
        if path == "/api/teacher/create_class":
            teacher = _session_teacher(data.get("session"))
            if not teacher:
                return self._send(403, {"error": "forbidden"})
            c = create_class(teacher, data.get("name"), data.get("grade"))
            if not c:
                return self._send(400, {"error": "bad_request"})
            return self._send(200, {"ok": True, "class": c})
        if path == "/api/teacher/regenerate_code":
            teacher = _session_teacher(data.get("session"))
            cid = data.get("class_id")
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            code = regenerate_class_code(cid)
            return self._send(200, {"ok": bool(code), "access_code": code})
        if path == "/api/teacher/approve":
            teacher = _session_teacher(data.get("session"))
            cid = data.get("class_id")
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": approve_student(cid, data.get("username"))})
        if path == "/api/teacher/reject":
            teacher = _session_teacher(data.get("session"))
            cid = data.get("class_id")
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": reject_student(cid, data.get("username"))})
        if path == "/api/teacher/add_student":
            teacher = _session_teacher(data.get("session"))
            cid = data.get("class_id")
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            st = teacher_add_student(cid, data.get("username"), data.get("password", ""), data.get("grade", ""))
            return self._send(200, {"ok": st in ("added", "updated"), "status": st})
        if path == "/api/teacher/set_grade":
            teacher = _session_teacher(data.get("session"))
            cid = data.get("class_id")
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": teacher_set_grade(data.get("username"), data.get("grade", ""))})
        if path == "/api/teacher/remove_student":
            teacher = _session_teacher(data.get("session"))
            cid = data.get("class_id")
            if not teacher or not owns_class(teacher, cid):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": unenroll_student(cid, data.get("username"))})
        if path == "/api/teacher/create_test":
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            grades = data.get("grades")
            if not grades and data.get("grade"):     # accept the old single-grade field too
                grades = [data.get("grade")]
            tid = create_test(data.get("title"), data.get("questions"),
                              grades, data.get("students"), data.get("due", ""))
            if not tid:
                return self._send(400, {"error": "invalid test"})
            return self._send(200, {"ok": True, "id": tid})
        if path == "/api/teacher/delete_test":
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, {"ok": delete_test(data.get("id"))})
        if path == "/api/teacher/update_test":
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            grades = data.get("grades")
            if not grades and data.get("grade"):
                grades = [data.get("grade")]
            t = update_test(data.get("id"), data.get("title"), data.get("questions"),
                            grades, data.get("students"), data.get("due", ""))
            if not t:
                return self._send(400, {"error": "invalid test"})
            return self._send(200, {"ok": True, "id": t["id"]})
        if path == "/api/teacher/retention":
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            save_retention(data.get("days"), data.get("mode"))
            return self._send(200, dict({"ok": True}, **retention_status()))
        if path == "/api/teacher/archive_sweep":
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            ids = data.get("ids") if isinstance(data.get("ids"), list) else None
            res = run_archive_sweep(ids)
            return self._send(200, dict({"ok": True}, **res))
        if path == "/api/teacher/extend_due":
            if not _session_teacher(data.get("session")):
                return self._send(403, {"error": "forbidden"})
            studs = data.get("students") if isinstance(data.get("students"), list) else None
            t = extend_due(data.get("id"), data.get("due", ""), studs)
            if not t:
                return self._send(400, {"error": "invalid"})
            return self._send(200, {"ok": True, "detail": test_detail(t)})
        if path == "/api/teacher/notifications_read":
            teacher = _session_teacher(data.get("session"))
            if not teacher:
                return self._send(403, {"error": "forbidden"})
            ids = data.get("ids") if isinstance(data.get("ids"), list) else None
            dis = data.get("dismiss") if isinstance(data.get("dismiss"), list) else None
            return self._send(200, mark_notifications(teacher, ids,
                                                      bool(data.get("all")), dis))
        if path == "/api/student/request_join":
            student = _session_student(data.get("session"))
            if not student:
                return self._send(403, {"error": "forbidden"})
            status = request_join(student, data.get("access_code") or "")
            if status == "invalid_code":
                return self._send(200, {"ok": False, "error": "invalid_code"})
            return self._send(200, {"ok": True, "status": status})
        if path == "/api/test/submit":
            student = gate_student(data.get("session"))
            if not student:
                return self._send(403, {"error": "forbidden"})
            ok = submit_test(student, data.get("testId"), data.get("answers") or {})
            return self._send(200, {"ok": ok})
        if path == "/api/home":
            student = gate_student(data.get("session"))
            if not student:
                return self._send(403, {"error": "forbidden"})
            d, _ = load_progress(student)
            return self._send(200, student_summary(d))
        if path == "/api/greeting":
            student = gate_student(data.get("session"))
            if not student:
                return self._send(403, {"error": "forbidden"})
            lang = data.get("lang", "en")
            lang = lang if lang in LANGS else "en"
            return self._send(200, {"text": generate_greeting(student, lang)})
        if path == "/api/event":
            student = gate_student(data.get("session"))
            if student:
                log_event(student, data.get("id"), data.get("kind") or "view", data.get("status"))
            return self._send(200, {"ok": True})
        if path == "/api/quiz_done":
            student = gate_student(data.get("session"))
            if not student:
                return self._send(403, {"error": "forbidden"})
            passed = record_quiz(student, data.get("id"),
                                 _toint(data.get("correct")), _toint(data.get("total")))
            if passed is None:
                return self._send(400, {"error": "bad request"})
            return self._send(200, {"passed": passed})
        if path == "/api/reading":
            student = gate_student(data.get("session"))
            if student:
                set_reading_mode(student, data.get("mode"), data.get("bookId"), data.get("title"),
                                 bool(data.get("finished")), data.get("page"))
            return self._send(200, {"ok": True})
        if path == "/api/book_quiz_done":
            student = gate_student(data.get("session"))
            if not student:
                return self._send(403, {"error": "forbidden"})
            passed = record_book_quiz(student, data.get("bookId"),
                                      data.get("title", ""), _toint(data.get("correct")),
                                      _toint(data.get("total")))
            if passed is None:
                return self._send(400, {"error": "bad request"})
            return self._send(200, {"passed": passed})
        return self._send(404, {"error": "not found"})

    def _chat(self, data):
        question = (data.get("question") or "").strip()
        history = data.get("history") or []
        lang = data.get("lang", "en")
        lang = lang if lang in LANGS else "en"
        if not question:
            return self._send(400, {"error": "empty"})
        student = gate_student(data.get("session"))
        if student:
            log_event(student, "helper", "ask")
        # subject/grade/language arrive with every message and are composed into one
        # system prompt (see helper_system); unknown or missing values fall back rather
        # than erroring, so a student is never blocked by an unset selector
        subject = (data.get("subject") or "").lower()
        if subject not in HELP_SUBJECT:
            subject = ""
        grade = str(data.get("grade") or "")
        if grade not in VALID_GRADES:
            grade = (load_progress(student)[0].get("grade") or "") if student else ""
        sys = helper_system(data.get("mode"), subject, grade, lang, student)
        msgs = [{"role": "system", "content": sys}]
        for h in history[-6:]:
            if h.get("role") in ("user", "assistant"):
                msgs.append({"role": h["role"], "content": h.get("content", "")[:800]})
        msgs.append({"role": "user", "content": question[:700]})
        return self._stream_llm(msgs, max_tokens=350)

    def _stream_llm(self, msgs, max_tokens=320, temp=0.5):
        body = json.dumps({"model": MODEL, "messages": msgs, "max_tokens": max_tokens,
                           "temperature": temp, "stream": True}).encode("utf-8")
        req = urllib.request.Request(LLAMA, data=body,
                                     headers={"Content-Type": "application/json"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(obj):
            try:
                self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False
        try:
            with _LLM_SEM:
                with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
                    for raw in r:
                        line = raw.decode("utf-8", "ignore").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                        except Exception:
                            delta = ""
                        if delta and not emit({"t": delta}):
                            return
        except Exception:
            emit({"error": "the tutor is busy, please try again"})
        emit({"done": True})

    def _ask(self, data):
        vid = data.get("id")
        lang = data.get("lang", "en")
        lang = lang if lang in LANGS else "en"
        if vid not in CAT:
            return self._send(400, {"error": "bad id"})
        student = gate_student(data.get("session"))
        sysmsg = ASK_SYS.format(ctx=ask_context(vid))
        if lang != "en":
            sysmsg += "\nReply ONLY in %s." % LANGS[lang]
        lvl = perf_level(student)
        if lvl in ADAPT:
            sysmsg += ADAPT[lvl]
        if data.get("warm"):
            ensure_bank(vid)               # build the quiz bank while the child watches
            if student:
                log_event(student, vid, "view")
            # pre-process the (cacheable) transcript prompt so the first real question is fast
            try:
                call_llama([{"role": "system", "content": sysmsg},
                            {"role": "user", "content": "Hi"}], max_tokens=1)
            except Exception:
                pass
            return self._send(200, {"ok": True})
        question = (data.get("question") or "").strip()
        if not question:
            return self._send(400, {"error": "need question"})
        if student:
            log_event(student, vid, "ask")
        history = data.get("history") or []
        msgs = [{"role": "system", "content": sysmsg}]
        for h in history[-4:]:
            if h.get("role") in ("user", "assistant"):
                msgs.append({"role": h["role"], "content": h.get("content", "")[:400]})
        msgs.append({"role": "user", "content": question[:400]})
        return self._stream_llm(msgs, max_tokens=220)

    def _grade(self, data):
        vid = data.get("id")
        qi = data.get("qIndex")
        student = gate_student(data.get("session"))
        ans = data.get("answer")
        lang = data.get("lang", "en")
        lang = lang if lang in LANGS else "en"
        if data.get("bookId") is not None:
            bq = load_bookquiz(data.get("bookId")) or {"questions": []}
            qs = bq.get("questions", [])
            qi = data.get("qi")
            if not isinstance(qi, int) or qi < 0 or qi >= len(qs):
                return self._send(400, {"error": "bad quiz request"})
            item = qs[qi]
            ok = (ans == item.get("answer"))
            fb = ("Yes! " if ok else "Not quite. ") + item.get("explain", "")
            return self._send(200, {"correct": ok, "answerIndex": item.get("answer"),
                                    "feedback": tr(fb, lang) if lang != "en" else fb})
        if data.get("bankIdx") is not None:
            bank = load_bank(vid) or {"questions": _seed_bank(vid)}
            qs = bank.get("questions", [])
            bi = data.get("bankIdx")
            if not isinstance(bi, int) or bi < 0 or bi >= len(qs):
                return self._send(400, {"error": "bad quiz request"})
            item = qs[bi]
            ok = (ans == item.get("answer"))
            if student:
                save_progress(student, vid, ok)
            fb = ("Yes! " if ok else "Not quite. ") + item.get("explain", "")
            return self._send(200, {"correct": ok, "answerIndex": item.get("answer"),
                                    "feedback": tr(fb, lang) if lang != "en" else fb})
        qz = QUIZZES.get(vid)
        if not qz or not isinstance(qi, int) or qi < 0 or qi >= len(qz["questions"]):
            return self._send(400, {"error": "bad quiz request"})
        item = qz["questions"][qi]
        if item["type"] == "mc":
            ok = (ans == item["answer"])
            if student:
                save_progress(student, vid, ok)
            fb = ("Yes! " if ok else "Not quite. ") + item.get("explain", "")
            return self._send(200, {"correct": ok, "feedback": tr(fb, lang),
                                    "answerIndex": item["answer"]})
        ans_en = tr(str(ans), "en", lang) if lang != "en" else str(ans)
        prompt = [
            {"role": "system", "content":
             "You grade a young child's math answer (age 6-8). First decide if it shows the "
             "key idea. Reply with EXACTLY one word, CORRECT or TRYAGAIN, then a space, then "
             "1-2 short warm simple sentences for the child. Be encouraging even if wrong."},
            {"role": "user", "content": "Question: %s\nKey idea we want: %s\nChild said: %s"
             % (item["q"], item.get("look_for", ""), ans_en[:300])},
        ]
        try:
            raw = call_llama(prompt, max_tokens=90, temp=0.3)
        except Exception:
            raw = "TRYAGAIN Good try! " + (item.get("look_for", "") or "keep going!")
        word, _, rest = raw.partition(" ")
        ok = word.strip().upper().startswith("CORRECT")
        rest = rest.strip() or raw.strip()
        fb = ("Great job! " if ok else "Good try! ") + rest
        if student:
            save_progress(student, vid, ok)
        return self._send(200, {"correct": ok, "feedback": tr(fb, lang),
                                "look_for": item.get("look_for", "")})

class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128
    allow_reuse_address = True

if __name__ == "__main__":
    # warm every language's small caches in the background so first use is instant
    for _l in LANGS:
        ensure_lang_cache(_l)
    print("Lunis on %s:%d  videos:%d  langs:%s" % (HOST, PORT, len(CATALOG), ",".join(LANGS)))
    Server((HOST, PORT), H).serve_forever()
