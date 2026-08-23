/* LightBox student app - all client-side behaviour for index.html: sign-in and join
   codes, browsing lessons by grade then topic, the video player, the Ask tab (talks to
   /api/ask), quizzes and unit tests, the reading books, progress, and the language
   picker. No framework and no build step - the browser loads this file as-is, so bump
   the ?v=NN in index.html whenever you change it or tablets keep the cached copy.

   Two things to know before editing:
   - Screens are sections in index.html toggled by CURRENT_SCREEN, not routes.
   - User-facing text comes from t("key") / data-i18n, never a literal string; a screen
     that builds its text in JS must also be listed in refreshScreenTexts() or it goes
     stale when the language changes. See docs/CONTRIBUTING.md. */
"use strict";
const $ = s => document.querySelector(s);
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
/* MUST list every grade in server.py's VALID_GRADES. This drives the math browse grade
   cards, so a grade missing here has no card at all and its lessons become unreachable
   by browsing - "8" was missing, hiding all 12 grade-8 lessons. Anything else that needs
   a grade list derives from this rather than repeating it. */
const GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8"];
const SPEECH = { en: "en-US", fr: "fr-FR", es: "es-ES", de: "de-DE" };
const SCREENS = ["welcome", "role", "login", "signup", "joincode", "subjects", "home", "reading", "reader", "dashboard", "history", "browse", "helper", "lesson", "achievements", "test"];
let CURRENT_SCREEN = "role";
let SESSION = localStorage.getItem("lb_session") || "";
let ME = { username: localStorage.getItem("lb_username") || "", role: localStorage.getItem("lb_role") || "" };
let SIGNUP_ROLE = "student";
let MY_CLASSES = [], CUR_CLASS_ID = localStorage.getItem("lb_class_id") || "";
let CATALOG = [], LANGS = {}, STR = {}, LANG = localStorage.getItem("lb_lang") || "en";
// strings for the reading language (see rt()); loaded on demand when the reading
// hub opens or its language segment changes
let RSTR = {}, RSTR_LANG = "";
// the two screens whose chrome follows the reading language rather than the app one
const READING_SCOPE = "#reading, #reader";
let CUR = null, HISTORY = [], nav = { grade: null, topic: null };
let watchedFrac = 0;
let captionLang = localStorage.getItem("cap_lang") || LANG, ccOn = true,
    cueSize = localStorage.getItem("cap_size") || "m";
/* Caption size lives in CSS now (.player[data-cap] -> --cap-scale, see style.css) so it
   can scale from the player's own width. cueSize here is just the persisted choice. */
let WARM_TIMER = null;

const DEFAULTS = {
  welcome_to: "Welcome to",
  role_student: "I'm a Student", role_teacher: "I'm a Teacher",
  home: "Home", choose_grade: "Choose a grade", lessons: "Lessons",
  question: "Question", next: "Next", check: "Check",
  see_stars: "Finish", again: "Try again", you_got: "You got",
  amazing: "Excellent work!", effort: "Good effort - watch it again and try once more.",
  book_effort: "Good effort - read it again and try once more.",
  type_answer: "Type your answer...", cant_find: "Lesson not found. Check the code.",
  videos: "videos", welcome: "Watch the video, then ask me anything about it.",
  thinking: "Thinking...", topic_finished: "You've finished this topic!",
  no_students: "No students yet. Ask your teacher to add you.",
  username_taken_err: "That username is already taken.",
  bad_signup_err: "Choose a username and a password of at least 4 characters.",
  invalid_code_err: "That code doesn't match a class. Check with your teacher.",
  pending_msg: "Request sent! Waiting for your teacher to accept you.",
  approve_btn: "Approve", reject_btn: "Reject", sign_out: "Sign Out",
  regenerate_confirm: "This invalidates the current code immediately for anyone who hasn't joined yet. Continue?",
  confirm_lang_cancel: "Cancel",
  requested_at: "Requested", no_pending: "No pending requests.",
  no_classes_yet: "Create a class above to get started.",
  err_class_fields: "Enter a class name and choose a grade.",
  math_helper: "Math Helper", reading_awards: "My Reading Awards", back_to_books: "Back to Books",
  confirm_lang_msg: "Are you sure you want to change your language to {lang}? You can change it any time.",
  confirm_signout_title: "Sign out?",
  confirm_signout_msg: "You'll be signed out and will need to sign back in to continue.",
  confirm_signout_yes: "Yes, Sign Out",
  welcome_to_class: "Welcome to {class} class!",
  grade_opt: "Grade...",
  grade_K: "Kindergarten", grade_1: "1st Grade", grade_2: "2nd Grade", grade_3: "3rd Grade",
  grade_4: "4th Grade", grade_5: "5th Grade", grade_6: "6th Grade", grade_7: "7th Grade", grade_8: "8th Grade",
  helper_welcome: "Hi! I'm LightBot, your homework helper. Tap a subject below to get started.",
  helper_title: "Homework Helper", helper_sub: "Ask me anything about your schoolwork.",
  helper_btn: "Homework Helper", helper_ph: "Type your question...", loading: "Loading...",
  new_question: "New question", helper_you: "You",
  subject_word: "Subject", grade_word: "Grade", language_word: "Language",
  subj_general: "Anything",
  read_aloud: "Read aloud", subject_prompt: "Tap a subject to start",
  subj_math: "Math", subj_reading: "Reading", subj_science: "Science", subj_writing: "Writing",
  // the in-chat subject -> grade -> ask flow
  helper_grade_prompt: "Great choice! What grade are you in?",
  helper_subject_again: "No problem. Which subject do you need help with?",
  helper_got_it: "Got it!", helper_what_help: "What do you need help with?",
  helper_change: "Change", helper_change_aria: "Change subject or grade",
  continue: "Continue", ach_btn: "My Achievement Box", ach_title: "My Achievement Box",
  ach_videos: "Videos finished", ach_quizzes: "Quizzes passed",
  ach_empty: "Finish a video or pass a quiz to earn your first star!",
  ns_title: "My Next Step", ns_redo: "That quiz was tricky - let's watch this again.",
  ns_pass: "Great work! You're ready for the next lesson.",
  ns_new: "Let's start learning! Here's a good first lesson.",
  quiz_preparing: "Getting your quiz ready...", quiz_newset: "Here are 3 brand-new questions!",
  welcome_hi: "Welcome back,", welcome_topic: "Ready to keep learning about",
  welcome_new: "Ready to learn something new today?",
  home_welcome_back: "Welcome back", home_ready_topic: "ready to keep learning about",
  home_ready_new: "ready to learn something new today?", explore_title: "Explore",
  browse_sub: "Find lessons for any grade level", ach_btn_sub: "See the badges you've earned",
  ai_badge: "AI", quick_chat: "Quick Chat",
  your_grade: "Your grade", book_word: "book", books_word: "books", pages_word: "pages",
  badge_earned_word: "badge earned", badges_earned_word: "badges earned",
  continue_reading: "Continue reading",
  watched_word: "watched", not_started: "Not started yet",
  view_rewards: "⭐ View My Rewards and Stars",
  test_have: "You have a new test!", test_title: "Your Test",
  test_sub: "Answer every question, then send it to your teacher.",
  test_submit: "Send my answers", test_sent: "Sent to your teacher! ✓",
  test_answer_ph: "Type your answer...", test_due: "Due:",
  // first-run welcome / setup wizard (language step only - accounts are self-service)
  welcome_mission: "Bringing free, offline learning to every classroom — because every child deserves equal access to a great education.",
  setup_lang: "Choose your starting language", setup_go: "Continue",
  setup_note: "You can change this anytime from the teacher dashboard.",
  trouble: "Something went wrong. Please try again.",
  // dashboard settings
  settings_btn: "Settings", settings_title: "Settings",
  settings_lang: "Base language (the default for all devices)",
  settings_save: "Save settings", settings_saved: "Saved",
  sec_add_student: "Add a Student", sec_tracking: "Student Progress & Tracking",
  sec_tests: "Tests & Student Answers", no_tests_yet: "No tests created yet.",
  create_test: "Create Test", build_test: "Build a test",
  test_title_ph: "Test title (e.g. Week 3 Math Check)",
  add_mc: "+ Multiple-choice", add_text: "+ Free-response",
  add_mc_tag: "Multiple choice", add_text_tag: "Free response",
  question_ph: "Question", add_choice: "+ Choice", tick_correct: "Tick the circle next to the correct answer.",
  del_q: "Delete", correct_lbl: "correct", choice_ph: "Choice",
  due_label: "Due date & time (optional)",
  assign_grades: "Assign to grades:", assign_students: "And/or individual students:",
  create_test_btn: "Create test", del_test: "Delete test",
  tests_answers: "Tests & student answers", assigned_to: "Assigned to:",
  grades_word: "Grades", questions_word: "questions", due_word: "Due",
  submitted_word: "submitted", no_subs: "No submissions yet.", correct_word: "correct",
  confirm_del_test: "Delete this test and all its responses?",
  err_choices: "Each multiple-choice question needs at least 2 choices.",
  err_correct: "Mark the correct answer for every multiple-choice question.",
  err_title: "Add a test title.", err_noq: "Add at least one question.",
  err_assign: "Assign to at least one grade or student.", err_create: "Could not create test.",
  hist_filter: "Filter", no_grade_yet: "No grade yet",
  // achievements / "about me" screen
  ach_math_title: "My Math Awards", ach_about_me_suffix: "About Me",
  stat_gold_stars: "Gold stars", stat_math_quizzes: "Math quizzes",
  stat_videos_watched: "Videos watched", stat_book_quizzes: "Book quizzes",
  stat_books_read: "Books read", tag_quiz_passed: "Quiz passed", tag_watched: "Watched",
  tag_book_quiz_passed: "Book quiz", tag_read: "Read",
  showcase_empty: "Pass a quiz to fill your showcase with gold stars!",
  ach_showcase: "Showcase", ach_all_awards: "All My Awards", ach_badge_counts: "Badge Counts",
  // story reader chrome
  page_word: "Page", of_word: "of", cover_word: "Cover", last_page: "Last page",
  reading_progress_aria: "Reading progress",
  by_author: "by {name}",
  credit_story: "Story:", credit_illustration: "Illustration:",
  credit_translation: "Translation:", credit_from: "From",
  close_book_aria: "Close book", prev_page_aria: "Previous page", next_page_aria: "Next page",
  // math-specific homework helper
  math_helper_welcome: "Hi! I'm LightBot, your math helper. Tap a subject below to get started.",
  // teacher history calendar
  hist_today: "Today", hist_all_students: "All students", hist_clear_filter: "Clear filter",
  hist_less: "Less", hist_more: "More", hist_activity_detail: "Activity detail",
  hist_activity_report_suffix: "activity report",
  hist_no_activity_day: "No activity recorded for this day.",
  hist_no_individual_activities: "No individual activities logged.",
  hist_showing_activity_for: "Showing activity for", hist_only_suffix: "only.",
  hist_star_word: "star", hist_stars_word: "stars",
  hist_activity_word: "activity", hist_activities_word: "activities",
  hist_video_word: "Video", hist_print_export: "Print / export",
  hist_log_word: "log", hist_logs_word: "logs",
  hist_math_quiz_suffix: "(math quiz)", hist_book_quiz_suffix: "(book quiz)",
  hist_csv_date: "Date", hist_csv_student: "Student", hist_csv_stars: "Stars",
  hist_csv_videos_watched: "Videos Watched", hist_csv_math_passed: "Math Quizzes Passed",
  hist_csv_math_total: "Math Quizzes Total", hist_csv_book_passed: "Book Quizzes Passed",
  hist_csv_book_total: "Book Quizzes Total",
  hist_export_modal_title: "Print / export report",
  hist_export_modal_msg: "Choose how much history to include.",
  hist_dur_this_month: "This month", hist_dur_3: "Last 3 months",
  hist_dur_6: "Last 6 months", hist_dur_12: "Last 12 months",
  hist_download_report: "Download report", hist_building_report: "Building report…",
  hist_downloaded: "Downloaded.",
  hist_prev_month_aria: "Previous month", hist_next_month_aria: "Next month",
  hist_close_aria: "Close",
  hist_sun: "Sun", hist_mon: "Mon", hist_tue: "Tue", hist_wed: "Wed",
  hist_thu: "Thu", hist_fri: "Fri", hist_sat: "Sat",
  hist_month_1: "January", hist_month_2: "February", hist_month_3: "March",
  hist_month_4: "April", hist_month_5: "May", hist_month_6: "June",
  hist_month_7: "July", hist_month_8: "August", hist_month_9: "September",
  hist_month_10: "October", hist_month_11: "November", hist_month_12: "December",
  // teacher dashboard
  dash_no_students: "No students yet — add one above.",
  tb_no_students: "No students in this class yet — add one from Class overview.",
  dash_top_passed_today: "Top lessons passed today", dash_no_passes_today: "No passes yet today",
  dash_most_failed_today: "Most-failed lesson today", dash_no_fails_today: "No fails yet today",
  dash_students_active_now: "students active now",
  // video player settings
  captions_lbl: "Captions", caption_size_lbl: "Caption size",
  // misc errors
  could_not_load_books: "Could not load books.", no_books_lang_yet: "No books in this language yet.",
  could_not_send_retry: "Could not send. Try again.", could_not_add_student: "Could not add student.",
  need_password_msg: "Enter a password (at least 4 characters) - it's required for a new student.",
  no_answer_word: "(no answer)",
  // teacher dashboard sidebar restructure
  dash_title_topbar: "Teacher dashboard",
  nav_overview: "Class overview", nav_tests: "Tests", nav_progress: "Student progress",
  tests_tab_create: "Create a test", tests_tab_results: "Test results & answers",
  roster_title: "Class roster", progress_by_student: "Progress by student",
  view_progress_btn: "View progress",
  assignment_title: "Assignment", free_response_hint: "Students will type a written answer.",
  view_answers_btn: "View answers", hide_answers_btn: "Hide answers",
  test_status_open: "Open", test_status_closed: "Closed",
  // tests results restructure: list view -> per-test detail view
  col_title: "Title", col_status: "Status", col_due: "Due date",
  col_submissions: "Submissions", no_due_date: "No due date",
  status_past_due: "Past due", status_complete: "Complete",
  all_tests_back: "All tests", no_tests_list: "No tests yet. Create one to get started.",
  class_average: "Class average", avg_not_ready: "Class average not available yet",
  avg_awaiting: "Awaiting more submissions - available after {due}, or once all {n} students submit.",
  avg_awaiting_nodue: "Available once all {n} assigned students have submitted.",
  avg_pct_correct: "% correct", avg_ungraded: "Written answer - not auto-graded",
  sort_by: "Sort by", sort_newest: "Newest first", sort_oldest: "Oldest first",
  sort_name: "Student name", filter_show: "Show", filter_all: "All answers",
  filter_incorrect: "Incorrect only", filter_submitted: "Submitted only",
  filter_pending: "Not yet submitted", filter_student: "Student",
  filter_all_students: "All students", no_match_filters: "No submissions match these filters.",
  submitted_at: "Submitted", not_submitted: "Not yet submitted",
  answered_lbl: "Answered:", correct_answer_lbl: "correct answer:",
  extended_badge: "Extended", extended_to: "extended to",
  students_count_badge: "{n} students",
  edited_after_sub: "Edited after submission",
  student_saw: "This student saw:", was_correct_then: "Correct as originally asked.",
  // notifications
  notifications: "Notifications", mark_all_read: "Mark all read",
  no_notifications: "No notifications yet.",
  notif_created: "'{title}' has been created",
  notif_submitted: "{student} submitted '{title}'",
  notif_dismiss: "Dismiss",
  just_now: "just now", mins_ago: "{n}m ago", hours_ago: "{n}h ago", days_ago: "{n}d ago",
  // due date extensions
  extend_due: "Extend due date", extend_save: "Save new due date",
  extend_whole: "Whole assignment", extend_selected: "Selected students",
  extend_new_due: "New due date", extend_pick_students: "Choose who gets the extension",
  extend_err_date: "Pick a new due date.", extend_err_students: "Select at least one student.",
  extend_current: "Currently due {due}", extend_no_due: "No due date set yet",
  extend_clear_hint: "Students you untick keep the assignment's own due date.",
  // editing a test after it has been assigned
  edit_test: "Edit test", save_changes: "Save changes", cancel_edit: "Cancel",
  edit_heads_up: "Heads up",
  edit_warn_subs: "{n} student(s) have already submitted - editing may affect grading consistency. " +
    "Existing answers are kept exactly as they were, and any question you change is flagged on those submissions.",
  edit_saved: "Changes saved",
  // data & storage (auto-archival)
  data_storage: "Data & storage",
  data_storage_desc: "Manage how long test results stay on this LightBox host.",
  retention_label: "Delete tests older than",
  retention_never: "Never", retention_30: "30 days", retention_60: "60 days",
  retention_90: "90 days", retention_after_due: "after their due date",
  retention_mode_archive: "Archive to a lightweight summary (class average + date, no per-student answers)",
  retention_mode_confirm: "Ask me before deleting anything",
  retention_save: "Save setting", retention_saved: "Saved.",
  retention_never_note: "Auto-deletion is off. Nothing will be removed until you choose a window.",
  retention_pending_title: "{n} test(s) are past their retention window",
  retention_review: "Review and delete", retention_not_now: "Not now",
  retention_archived_title: "Archived summaries",
  retention_no_archive: "Nothing archived yet.",
  retention_swept: "{n} test(s) archived and removed.",
};
const t = k => STR[k] || DEFAULTS[k] || k;
// Reading-hub chrome follows the READING language, not the app language: a kid who
// switches the shelf to French gets French headings and labels too, so the whole
// reading surface is in one language. RSTR holds that language's strings; it falls
// back to STR (app language) so a not-yet-loaded RSTR never blanks the hub.
// Everything outside the reading screens keeps using t()/STR.
const rt = k => RSTR[k] || STR[k] || DEFAULTS[k] || k;
// "by {name}" comes back from LibreTranslate with the PLACEHOLDER translated too -
// "par {nom}" in French, "por {nombre}" in Spanish - so substituting the literal
// "{name}" would leave the brace text on screen and drop the author entirely. Match
// whatever ended up between the braces, and if the translation lost them, fall back
// to appending the name so a byline never renders without one.
function fillSlot(s, value) {
  return /\{[^}]*\}/.test(s) ? s.replace(/\{[^}]*\}/, value) : (s + " " + value);
}
function byline(name) { return fillSlot(rt("by_author"), name); }
const topicKey = id => (id.match(/^[A-Za-z]+/) || [""])[0];
// `lang` overrides the app language for text that is not in it - the reading screens
// speak their praise in the shelf language, so an English-run app reading a French
// book does not read "Génial !" with an English voice
function speak(text, lang) {
  try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text);
    u.lang = SPEECH[lang || LANG] || "en-US"; u.rate = .98; speechSynthesis.speak(u); } catch (e) {}
}
function showLoading(on) { $("#loading").classList.toggle("hidden", !on); }
function getSession() { return SESSION; }
function getName() { return ME.username; }
function setIdentity(username, role, session) {
  ME = { username, role }; SESSION = session;
  localStorage.setItem("lb_username", username);
  localStorage.setItem("lb_role", role);
  localStorage.setItem("lb_session", session);
}
function clearIdentity() {
  ME = { username: "", role: "" }; SESSION = "";
  localStorage.removeItem("lb_username"); localStorage.removeItem("lb_role");
  localStorage.removeItem("lb_session"); localStorage.removeItem("lb_class_id");
  CUR_CLASS_ID = ""; MY_CLASSES = [];
}
async function apiLogout() {
  try { await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: getSession() }) }); } catch (e) {}
}

function applyI18n() {
  // fall back to DEFAULTS (English) rather than leaving the element's existing text
  // untouched - otherwise a key missing from the freshly-loaded STR (partial cache,
  // failed machine-translation call, etc.) silently leaves the PREVIOUS language's
  // text on screen after a language switch instead of showing anything current.
  // static markup inside the reading screens resolves against the READING language
  // (RSTR) for the same reason the JS-built hub text does - see rt()
  const tbl = e => (e.closest(READING_SCOPE) ? rt : t);
  document.querySelectorAll("[data-i18n]").forEach(e => { const v = tbl(e)(e.getAttribute("data-i18n")); if (v) e.textContent = v; });
  document.querySelectorAll("[data-i18n-ph]").forEach(e => { const v = tbl(e)(e.getAttribute("data-i18n-ph")); if (v) e.placeholder = v; });
  document.querySelectorAll("[data-i18n-aria]").forEach(e => { const v = tbl(e)(e.getAttribute("data-i18n-aria")); if (v) e.setAttribute("aria-label", v); });
}
async function loadStrings() { STR = await (await fetch("/api/i18n?lang=" + LANG)).json(); applyI18n(); }
// strings for the reading language. Cached by language so flipping the shelf's
// EN/FR/ES/DE segments back and forth refetches nothing. A failed load leaves RSTR
// empty, which rt() resolves through STR, so the hub degrades to the app language
// rather than to raw key names.
async function loadReadStrings() {
  const lang = READLANG || "en";
  if (RSTR_LANG === lang) return;
  try { RSTR = await (await fetch("/api/i18n?lang=" + lang)).json(); RSTR_LANG = lang; }
  catch (e) { RSTR = {}; RSTR_LANG = ""; }
  applyI18n();
}
async function loadCatalog() { CATALOG = await (await fetch("/api/catalog?lang=" + LANG)).json(); }

let SETUP_STATE = { configured: true, base_lang: "en" };
async function init() {
  LANGS = await (await fetch("/api/langs")).json();
  try { SETUP_STATE = await (await fetch("/api/setup")).json(); } catch (e) {}
  // the admin's base language is the default; an individual device can still override it
  if (!localStorage.getItem("lb_lang") && SETUP_STATE.base_lang && LANGS[SETUP_STATE.base_lang]) LANG = SETUP_STATE.base_lang;
  const sel = $("#lang"); sel.innerHTML = "";
  Object.keys(LANGS).forEach(c => { const o = el("option", null, LANGS[c]); o.value = c; if (c === LANG) o.selected = true; sel.appendChild(o); });
  const signupSel = $("#signupLang"); signupSel.innerHTML = "";
  Object.keys(LANGS).forEach(c => { const o = el("option", null, LANGS[c]); o.value = c; if (c === LANG) o.selected = true; signupSel.appendChild(o); });
  sel.onchange = async e => {
    LANG = e.target.value; localStorage.setItem("lb_lang", LANG);
    showLoading(true);
    try { await loadStrings(); await loadCatalog(); } finally { showLoading(false); }
    refreshScreenTexts();
  };
  await loadStrings(); await loadCatalog();
  // first-run setup wizard (language only) + dashboard settings
  $("#setupBtn").onclick = submitSetup;
  $("#settingsBtn").onclick = toggleSettings;
  $("#dashLogoutBtn").onclick = confirmSignOut;
  $("#histLogoutBtn").onclick = confirmSignOut;
  $("#settingsSave").onclick = saveSettings;
  // role select -> sign IN with that role (most kids/teachers already have an account);
  // "Create an account" from the login screen carries the chosen role into signup.
  $("#roleStudent").onclick = () => goLogin("student");
  $("#roleTeacher").onclick = () => goLogin("teacher");
  $("#goSignupBtnRole").onclick = () => goSignup(SIGNUP_ROLE);
  $("#goSignupBtn").onclick = () => goSignup(SIGNUP_ROLE);
  $("#goLoginBtn2").onclick = () => show("login");
  // sign in / sign up / join a class
  $("#loginBtn").onclick = doLogin;
  $("#loginPw").addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
  $("#signupBtn").onclick = doSignup;
  $("#signupPw").addEventListener("keydown", e => { if (e.key === "Enter") doSignup(); });
  $("#joinBtn").onclick = doRequestJoin;
  $("#joinCode").addEventListener("keydown", e => { if (e.key === "Enter") doRequestJoin(); });
  // student
  $("#startBtn").onclick = () => { const c = $("#code").value.trim().toUpperCase(); if (!c) { $("#code").focus(); return; } openLesson(c, "home"); };
  $("#code").addEventListener("keydown", e => { if (e.key === "Enter") $("#startBtn").click(); });
  $("#browseBtn").onclick = () => { nav = { grade: null, topic: null }; show("browse"); renderBrowse(); };
  $("#helperBtn").onclick = () => openHelper("math");
  $("#achBtn").onclick = () => openAchievements("math");
  $("#readAchBtn").onclick = () => openAchievements("reading");
  // teacher notification bell + dropdown
  $("#notifBell").onclick = e => { e.stopPropagation(); toggleNotifPanel(); };
  $("#notifMarkAll").onclick = e => { e.stopPropagation(); markNotifs({ all: true }); };
  document.addEventListener("click", e => {
    if (!$("#notifWrap").contains(e.target)) closeNotifPanel();
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeNotifPanel(); });
  // extend due date modal
  $("#extendSave").onclick = saveExtend;
  $("#extendCancel").onclick = closeExtendModal;
  $("#extendOverlay").onclick = e => { if (e.target === $("#extendOverlay")) closeExtendModal(); };
  // profile button + rewards dropdown
  $("#profileBtn").onclick = e => { e.stopPropagation(); $("#profileMenu").classList.toggle("hidden"); };
  $("#menuRewards").onclick = () => { $("#profileMenu").classList.add("hidden"); if (getName()) openAchievements("all"); };
  $("#menuLanguage").onclick = () => { $("#profileMenu").classList.add("hidden"); openLanguagePicker(); };
  $("#langPickerCancel").onclick = () => $("#langPicker").classList.add("hidden");
  $("#menuSignOut").onclick = () => { $("#profileMenu").classList.add("hidden"); confirmSignOut(); };
  document.addEventListener("click", e => { if (!$("#profileWrap").contains(e.target)) $("#profileMenu").classList.add("hidden"); });
  // test notification bell
  $("#testBell").onclick = () => { if (ASSIGNED_TESTS.length) openTest(ASSIGNED_TESTS[0]); };
  $("#testSubmit").onclick = submitTest;
  $("#subjMath").onclick = () => { sendMode("math"); openHome(); };
  $("#subjReading").onclick = () => { sendMode("reading"); openReading(); };
  $("#subjHelper").onclick = () => openHelper("general");
  $("#rbPrev").onclick = () => { if (BOOK && SPREAD > 0) { SPREAD--; renderSpread(); saveReadingPage(); } };
  $("#rbNext").onclick = () => { if (BOOK && SPREAD < BOOK.spreads.length - 1) { SPREAD++; renderSpread(); saveReadingPage(); } };
  $("#rbQuiz").onclick = () => startBookQuiz(false);
  $("#hudBack").onclick = () => openReading();
  $("#hudBackLbl").onclick = () => openReading();
  // teacher dashboard
  $("#dashRefresh").onclick = () => { renderDashboard(); loadPending(); };
  $("#createTestBtn").onclick = () => { showDashView("tests"); showTestsTab("create"); };
  $("#addStudentBtn").onclick = addStudent;
  $("#newName").addEventListener("keydown", e => { if (e.key === "Enter") $("#newPin").focus(); });
  $("#newPin").addEventListener("keydown", e => { if (e.key === "Enter") addStudent(); });
  document.querySelectorAll(".dash-nav-item[data-view]").forEach(b => b.onclick = () =>
    b.dataset.view === "history" ? openHistory() : showDashView(b.dataset.view));
  $("#testsTabCreate").onclick = () => showTestsTab("create");
  $("#testsTabResults").onclick = () => showTestsTab("results");
  $("#histBack").onclick = () => { showDashView("overview"); show("dashboard"); renderDashboard(); };
  $("#histSelect").onchange = onHistFilterChange;
  $("#histPrev").onclick = () => histChangeMonth(-1);
  $("#histNext").onclick = () => histChangeMonth(1);
  $("#histToday").onclick = histGoToday;
  $("#histClearFilter").onclick = () => { $("#histSelect").value = ""; onHistFilterChange(); };
  $("#histDetailClose").onclick = () => histSelectDay(HIST_SELECTED);
  $("#histExportBtn").onclick = openExportModal;
  $("#exportCancelBtn").onclick = closeExportModal;
  $("#exportDownloadBtn").onclick = runHistExport;
  document.querySelectorAll("input[name='exportDur']").forEach(r => r.onchange = () => {
    document.querySelectorAll(".hist-export-opt").forEach(l => l.classList.toggle("checked", l.querySelector("input").checked));
  });
  $("#classSelect").onchange = onClassChanged;
  $("#newClassBtn").onclick = () => $("#newClassForm").classList.toggle("hidden");
  $("#newClassSave").onclick = createClassSubmit;
  $("#regenBtn").onclick = regenerateCode;
  // lesson/helper chat
  // wrapped, not passed by reference: askHelper takes an optional preset question and
  // a bare handler would hand it the click Event
  $("#hsend").onclick = () => askHelper();
  $("#hq").addEventListener("keydown", e => { if (e.key === "Enter") askHelper(); });
  $("#hreset").onclick = () => openHelper(HELPER_MODE);
  $("#backBtn").onclick = goBack;
  $("#brandHome").onclick = goHome;
  $("#tabAsk").onclick = () => switchTab("ask");
  $("#tabQuiz").onclick = () => switchTab("quiz");
  $("#send").onclick = ask;
  $("#markComplete").onclick = () => {
    setVideoStatus(CUR.id, videoStatus(CUR.id) === "complete" ? "" : "complete");
    renderStatusButtons(CUR.id);
  };
  $("#markTodo").onclick = () => {
    setVideoStatus(CUR.id, videoStatus(CUR.id) === "todo" ? "" : "todo");
    renderStatusButtons(CUR.id);
  };
  $("#q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });
  setupPlayer();
  // Trap the browser Back button so it steps back through our in-app screens instead of leaving.
  try { history.pushState(null, ""); } catch (e) {}
  window.addEventListener("popstate", () => { goBack(); try { history.pushState(null, ""); } catch (e) {} });
  if (!SETUP_STATE.configured) { renderSetupWizard(); show("welcome"); }
  else await resumeSession();
}

/* ---------- accounts: sign up / sign in / join a class ---------- */
function goSignup(role) { SIGNUP_ROLE = role; renderSignupRole(); show("signup"); }
function goLogin(role) { SIGNUP_ROLE = role; show("login"); }
function renderSignupRole() {
  $("#signupRoleTag").textContent = SIGNUP_ROLE === "teacher" ? t("role_teacher") : t("role_student");
}
function flash(node) { node.style.borderColor = "#E25555"; setTimeout(() => node.style.borderColor = "", 1200); }

async function resumeSession() {
  if (!SESSION || !ME.username) { show("role"); return; }
  if (ME.role === "teacher") {
    const ok = await loadMyClasses();
    if (!ok) { clearIdentity(); show("role"); return; }
    showDashView("overview"); show("dashboard"); renderDashboard(); loadPending(); startDashPoll();
    return;
  }
  await routeStudent();
}
async function routeStudent() {
  let status;
  try {
    status = await (await fetch("/api/student/class_status?session=" + encodeURIComponent(getSession()))).json();
  } catch (e) { clearIdentity(); show("role"); return; }
  if (!status || status.status === undefined) { clearIdentity(); show("role"); return; }
  if (status.status === "approved") { refreshTests(); openSubjects(); }
  else renderJoinScreen(status);
}
function renderJoinScreen(status) {
  const pending = status && status.status === "pending";
  $("#joinForm").classList.toggle("hidden", pending);
  $("#joinPending").classList.toggle("hidden", !pending);
  if (pending) {
    $("#joinPendingMsg").textContent = t("pending_msg") + (status.class && status.class.name ? " (" + status.class.name + ")" : "");
  } else {
    $("#joinCode").value = ""; $("#joinErr").classList.add("hidden");
  }
  show("joincode");
  // while waiting on the teacher, watch for approval ourselves instead of making
  // the student refresh the page and log back in to find out they got in
  if (pending) startJoinPoll(); else stopJoinPoll();
}
let _joinPoll = null;
function startJoinPoll() { if (!_joinPoll) _joinPoll = setInterval(checkJoinApproval, 4000); }
function stopJoinPoll() { if (_joinPoll) { clearInterval(_joinPoll); _joinPoll = null; } }
async function checkJoinApproval() {
  if ($("#joincode").classList.contains("hidden") || $("#joinPending").classList.contains("hidden")) { stopJoinPoll(); return; }
  let status;
  try { status = await (await fetch("/api/student/class_status?session=" + encodeURIComponent(getSession()))).json(); }
  catch (e) { return; }
  if (status && status.status === "approved") {
    stopJoinPoll();
    refreshTests();
    openSubjects();
    showJoinToast(status.class && status.class.name);
  }
}
let _joinToastTimer = null;
function showJoinToast(className) {
  $("#joinToastText").textContent = (t("welcome_to_class") || "Welcome to {class} class!").replace("{class}", className || "");
  $("#joinToast").classList.remove("hidden");
  clearTimeout(_joinToastTimer);
  _joinToastTimer = setTimeout(() => $("#joinToast").classList.add("hidden"), 4000);
}
function openLanguagePicker() {
  if (!getName()) return;   // language is tied to an account; nothing to change if signed out
  const list = $("#langPickerList"); list.innerHTML = "";
  Object.keys(LANGS).forEach(c => {
    const b = el("button", "lang-pick-btn" + (c === LANG ? " on" : ""), LANGS[c]);
    b.type = "button";
    b.onclick = () => { $("#langPicker").classList.add("hidden"); confirmLangChange(c); };
    list.appendChild(b);
  });
  $("#langPicker").classList.remove("hidden");
}
function confirmLangChange(code) {
  $("#confirmLangMsg").textContent = (t("confirm_lang_msg") || "").replace("{lang}", LANGS[code] || code);
  $("#confirmLang").classList.remove("hidden");
  const cleanup = () => { $("#confirmLang").classList.add("hidden"); $("#confirmLangYes").onclick = null; $("#confirmLangCancel").onclick = null; };
  $("#confirmLangCancel").onclick = cleanup;
  $("#confirmLangYes").onclick = async () => {
    cleanup();
    await applyAccountLang(code);
    fetch("/api/set_lang", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), lang: code }) }).catch(() => {});
  };
}
async function applyAccountLang(lang) {
  if (!lang || lang === LANG || !LANGS[lang]) return;
  LANG = lang; localStorage.setItem("lb_lang", LANG);
  const sel = $("#lang"); if (sel) sel.value = LANG;
  showLoading(true);
  try { await loadStrings(); await loadCatalog(); } finally { showLoading(false); }
  refreshScreenTexts();
}
// applyI18n() (called by loadStrings) only refreshes elements tagged data-i18n in the
// static HTML. Screens that build their own text at render time via t() (the home
// hero heading, next-step card, to-do list, browse cards, lesson chrome, achievements,
// the "Hi, {name}!" subjects heading, the teacher dashboard) go stale after a language
// switch unless their render function runs again - this re-invokes whichever one is
// currently on screen so nothing is left showing the previous language.
function refreshHistoryTexts() {
  if (HIST_YEAR == null) return;   // history screen was never opened this session
  renderHistWeekdays();
  const sel = $("#histSelect");
  if (sel.options.length) sel.options[0].textContent = t("hist_all_students");
  renderHistCalendar();
  if (HIST_SELECTED) renderHistDetail(HIST_SELECTED);
  if (HIST_FILTER) $("#histFilterBannerText").textContent = t("hist_showing_activity_for") + " " + HIST_FILTER + " " + t("hist_only_suffix");
}
// The helper's speaker labels, subject starters and "Thinking..." text are built in
// JS, so a language switch has to re-translate them - but re-opening the screen would
// throw away the conversation in progress, so this only touches the translated pieces
// and leaves every bubble where it is.
function refreshHelperTexts() {
  const ttl = $("#helper .screen-title");
  if (ttl) ttl.textContent = HELPER_MODE === "math" ? t("math_helper") : t("helper_title");
  document.querySelectorAll("#hchat .hrow").forEach(r => {
    const who = r.querySelector(".hwho");
    if (who) who.textContent = r.classList.contains("me") ? t("helper_you") : BOT_NAME;
  });
  renderHelperOpts();          // re-label the language selector, keeping the choice
  const tl = $("#hchat .msg.thinking .tlabel");
  if (tl) tl.textContent = t("thinking");
  document.querySelectorAll("#hchat .spk").forEach(b => {
    b.setAttribute("aria-label", t("read_aloud")); b.title = t("read_aloud");
  });
  // the picker and the summary line are built in JS, so they need re-rendering here;
  // both read the current HSTEP/HSUBJECT/HGRADE, so nothing the child chose is lost
  renderHelperPicker();
  renderHelperSummary();
}
function refreshScreenTexts() {
  const s = CURRENT_SCREEN;
  // the bell lives in the shared top bar, so its list is re-rendered for every screen
  // rather than inside one screen's branch. It reads the cached NOTIFS array, so this
  // re-translates the feed without refetching or losing read state.
  renderNotifications();
  if (!$("#extendOverlay").classList.contains("hidden")) renderExtendModal();
  if (!$("#settingsPanel").classList.contains("hidden")) renderRetention();
  if (!$("#retentionBanner").classList.contains("hidden")) renderRetentionBanner();
  // every screen that renders its own text via JS (rather than relying only on the
  // generic data-i18n sweep in applyI18n) must be re-rendered here on language switch,
  // or its visible text silently stays in the previous language. Screens with no
  // custom-rendered text (welcome/role/login/signup/joincode) don't need an entry -
  // applyI18n() alone keeps them current.
  if (s === "home") openHome();
  else if (s === "browse") renderBrowse();
  else if (s === "lesson" && CUR) openLesson(CUR.id);
  else if (s === "helper") refreshHelperTexts();
  else if (s === "achievements") renderAchievements(SUMMARY || { videos: {}, books: {} }, _achScope);
  else if (s === "subjects") openSubjects();
  else if (s === "dashboard") { renderDashboard(); if (DASH_VIEW === "tests") (TESTS_TAB === "create" ? renderTestBuilder() : renderTestsArea()); }
  else if (s === "reading") openReading();
  else if (s === "reader" && BOOK) renderSpread();
  else if (s === "history") refreshHistoryTexts();
  else if (s === "helper") {
    const ttl = $("#helper .screen-title");
    if (ttl) ttl.textContent = HELPER_MODE === "math" ? t("math_helper") : t("helper_title");
  } else if (s === "test" && CUR_TEST && CUR_TEST.due) {
    $("#testDue").textContent = "⏰ " + t("test_due") + " " + fmtDue(CUR_TEST.due);
  }
}
async function doSignup() {
  const username = $("#signupUser").value.trim(), password = $("#signupPw").value;
  const lang = $("#signupLang") ? $("#signupLang").value : LANG;
  const err = $("#signupErr");
  err.classList.add("hidden");
  if (username.length < 2 || password.length < 4) { err.textContent = t("bad_signup_err"); err.classList.remove("hidden"); return; }
  let j;
  try {
    j = await (await fetch("/api/signup", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, role: SIGNUP_ROLE, lang }) })).json();
  } catch (e) { err.textContent = t("trouble"); err.classList.remove("hidden"); return; }
  if (!j.ok) {
    err.textContent = j.error === "username_taken" ? t("username_taken_err") : t("bad_signup_err");
    err.classList.remove("hidden"); flash($("#signupUser")); return;
  }
  $("#signupUser").value = ""; $("#signupPw").value = "";
  setIdentity(j.username, j.role, j.session);
  await applyAccountLang(j.lang);
  await resumeSession();
}
async function doLogin() {
  const username = $("#loginUser").value.trim(), password = $("#loginPw").value;
  $("#loginErr").classList.add("hidden");
  if (!username || !password) { flash($("#loginUser")); return; }
  let j;
  try {
    j = await (await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }) })).json();
  } catch (e) { $("#loginErr").classList.remove("hidden"); return; }
  if (!j.ok) { $("#loginErr").classList.remove("hidden"); flash($("#loginPw")); return; }
  $("#loginUser").value = ""; $("#loginPw").value = "";
  setIdentity(j.username, j.role, j.session);
  await applyAccountLang(j.lang);
  await resumeSession();
}
async function doRequestJoin() {
  const code = $("#joinCode").value.trim().toUpperCase(), err = $("#joinErr");
  err.classList.add("hidden");
  if (!code) { flash($("#joinCode")); return; }
  let j;
  try {
    j = await (await fetch("/api/student/request_join", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), access_code: code }) })).json();
  } catch (e) { err.textContent = t("trouble"); err.classList.remove("hidden"); return; }
  if (!j.ok) { err.textContent = t("invalid_code_err"); err.classList.remove("hidden"); flash($("#joinCode")); return; }
  if (j.status === "approved") { refreshTests(); openSubjects(); return; }
  renderJoinScreen({ status: "pending" });
}

/* ---------- first-run setup wizard + dashboard settings ---------- */
function langButtons(container, selected, onPick) {
  container.innerHTML = "";
  Object.keys(LANGS).forEach(c => {
    const b = el("button", "setup-lang" + (c === selected ? " on" : ""), LANGS[c]);
    b.type = "button";
    b.onclick = () => onPick(c);
    container.appendChild(b);
  });
}
function renderSetupWizard() {
  langButtons($("#setupLangs"), LANG, async c => {
    LANG = c; localStorage.setItem("lb_lang", c);
    const sel = $("#lang"); if (sel) sel.value = c;
    await loadStrings();           // re-render the whole wizard in the chosen language
    renderSetupWizard();           // refresh the selected-language highlight
  });
}
async function submitSetup() {
  const err = $("#setupErr");
  err.classList.add("hidden");
  let j;
  try {
    j = await (await fetch("/api/setup", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_lang: LANG }) })).json();
  } catch (e) { err.textContent = t("trouble"); err.classList.remove("hidden"); return; }
  if (!j.ok) { err.textContent = t("trouble"); err.classList.remove("hidden"); return; }
  SETUP_STATE.configured = true; SETUP_STATE.base_lang = j.base_lang || LANG;
  show("role");
}
function toggleSettings() {
  const p = $("#settingsPanel");
  if (p.classList.contains("hidden")) {
    renderSettingsLangs(); $("#settingsMsg").textContent = ""; $("#settingsErr").classList.add("hidden");
    loadRetention();
    p.classList.remove("hidden"); p.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } else p.classList.add("hidden");
}

/* ---------- data & storage: opt-in auto-archival ----------
   Default is "never" and the server enforces that too - this UI can only ever widen what
   gets removed by an explicit save, never by being rendered. */
let RETENTION = { days: "never", mode: "archive" }, RETENTION_PENDING = [], RETENTION_ARCHIVED = [];
async function loadRetention() {
  try {
    const j = await (await fetch("/api/teacher/retention?session=" +
      encodeURIComponent(getSession()))).json();
    if (!j || !j.retention) return;
    RETENTION = j.retention; RETENTION_PENDING = j.pending || []; RETENTION_ARCHIVED = j.archived || [];
  } catch (e) { return; }
  renderRetention();
}
function renderRetention() {
  const box = $("#retentionBox"); if (!box) return;
  box.innerHTML = "";
  box.appendChild(el("h4", "add-title", t("data_storage")));
  box.appendChild(el("p", "muted-note", t("data_storage_desc")));
  const row = el("div", "ret-row");
  row.appendChild(el("span", null, t("retention_label")));
  const sel = el("select", "field select-pill");
  [["never", t("retention_never")], ["30", t("retention_30")],
   ["60", t("retention_60")], ["90", t("retention_90")]].forEach(([v, lab]) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = lab; if (v === RETENTION.days) o.selected = true;
    sel.appendChild(o);
  });
  sel.onchange = () => { RETENTION.days = sel.value; renderRetention(); };
  row.appendChild(sel);
  row.appendChild(el("span", null, t("retention_after_due")));
  box.appendChild(row);
  if (RETENTION.days === "never") {
    box.appendChild(el("div", "ret-note", t("retention_never_note")));
  } else {
    const modes = el("div", "ret-modes");
    [["archive", "retention_mode_archive"], ["confirm", "retention_mode_confirm"]].forEach(([v, k]) => {
      const l = el("label", "ret-mode");
      const r = document.createElement("input");
      r.type = "radio"; r.name = "retmode"; r.value = v; r.checked = RETENTION.mode === v;
      r.onchange = () => { RETENTION.mode = v; renderRetention(); };
      l.appendChild(r); l.appendChild(el("span", null, t(k)));
      modes.appendChild(l);
    });
    box.appendChild(modes);
  }
  const save = el("button", "btn primary", t("retention_save"));
  save.onclick = saveRetention;
  box.appendChild(save);
  box.appendChild(Object.assign(el("span", "tb-msg"), { id: "retMsg" }));
  if (RETENTION_ARCHIVED.length) {
    box.appendChild(el("h4", "add-title ret-arch-h", t("retention_archived_title")));
    const list = el("div", "ret-arch");
    RETENTION_ARCHIVED.forEach(s => {
      const r2 = el("div", "ret-arch-row");
      r2.appendChild(el("span", "ret-arch-t", s.title));
      r2.appendChild(el("span", "ret-arch-m",
        (s.due ? fmtDue(s.due) + " · " : "") +
        (s.average == null ? "—" : s.average + "%") + " · " +
        s.sub_count + "/" + s.total));
      list.appendChild(r2);
    });
    box.appendChild(list);
  }
}
async function saveRetention() {
  const msg = $("#retMsg");
  try {
    const j = await (await fetch("/api/teacher/retention", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), days: RETENTION.days, mode: RETENTION.mode })
    })).json();
    if (j && j.retention) {
      RETENTION = j.retention; RETENTION_PENDING = j.pending || []; RETENTION_ARCHIVED = j.archived || [];
    }
  } catch (e) { return; }
  renderRetention();
  const m = $("#retMsg") || msg;
  if (m) { m.textContent = t("retention_saved"); m.style.color = "#1E8E4E"; }
  archiveSweep();
}
/* Background check, run on dashboard load and after a settings save. With "never" or
   "confirm" the server refuses to delete on its own; confirm mode surfaces a banner and
   waits for an explicit click. */
async function archiveSweep() {
  if (ME.role !== "teacher") return;
  let j;
  try {
    j = await (await fetch("/api/teacher/archive_sweep", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession() }) })).json();
  } catch (e) { return; }
  RETENTION_PENDING = (j && j.pending) || [];
  renderRetentionBanner();
  if (j && j.archived && j.archived.length) {
    if (DASH_VIEW === "tests" && TESTS_TAB === "results") renderTestsArea();
    loadRetention();
  }
}
function renderRetentionBanner() {
  const host = $("#retentionBanner"); if (!host) return;
  host.innerHTML = "";
  host.classList.toggle("hidden", !RETENTION_PENDING.length);
  if (!RETENTION_PENDING.length) return;
  host.appendChild(el("div", "ret-ban-t",
    t("retention_pending_title").replace("{n}", RETENTION_PENDING.length)));
  const list = el("div", "ret-ban-list");
  RETENTION_PENDING.forEach(s => {
    const r = el("div", "ret-ban-row");
    r.appendChild(el("span", null, s.title));
    r.appendChild(el("span", "ret-arch-m", s.due ? fmtDue(s.due) : ""));
    list.appendChild(r);
  });
  host.appendChild(list);
  const acts = el("div", "ret-ban-acts");
  const go = el("button", "btn primary sm", t("retention_review"));
  go.onclick = async () => {
    const ids = RETENTION_PENDING.map(s => s.id);
    try {
      await fetch("/api/teacher/archive_sweep", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: getSession(), ids }) });
    } catch (e) {}
    RETENTION_PENDING = [];
    renderRetentionBanner();
    if (DASH_VIEW === "tests" && TESTS_TAB === "results") renderTestsArea();
  };
  const no = el("button", "btn ghost sm", t("retention_not_now"));
  no.onclick = () => { RETENTION_PENDING = []; renderRetentionBanner(); };
  acts.appendChild(go); acts.appendChild(no);
  host.appendChild(acts);
}
function renderSettingsLangs() {
  langButtons($("#settingsLangs"), SETUP_STATE.base_lang || LANG, c => {
    SETUP_STATE.base_lang = c; renderSettingsLangs();
  });
}
async function saveSettings() {
  const err = $("#settingsErr"), msg = $("#settingsMsg");
  err.classList.add("hidden");
  let j;
  try {
    j = await (await fetch("/api/teacher/settings", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), base_lang: SETUP_STATE.base_lang }) })).json();
  } catch (e) { return; }
  if (j.ok) {
    SETUP_STATE.base_lang = j.base_lang || SETUP_STATE.base_lang;
    msg.textContent = t("settings_saved"); msg.style.color = "#1E8E4E";
  } else { err.textContent = j.error || t("trouble"); err.classList.remove("hidden"); }
}

/* ---------- avatars (used on teacher dashboard student/pending cards) ---------- */
const AV_COLORS = ["#16233B", "#2B6CB0", "#2F855A", "#B7791F", "#9B2C2C", "#6B46C1", "#0E7490", "#B83280"];
function avatarColor(name) { let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0; return AV_COLORS[h % AV_COLORS.length]; }
function initials(name) {
  const p = (name || "").trim().split(/\s+/).filter(Boolean);
  if (!p.length) return "?";
  return p.length > 1 ? p[0][0] + p[1][0] : p[0][0];
}
function resetIdentity() { SUMMARY = null; ASSIGNED_TESTS = []; }

/* ---------- personalized home ---------- */
let SUMMARY = null;
function openSubjects() { $("#subjHi").textContent = (t("welcome_hi") || "Hi,") + " " + getName() + "!"; show("subjects"); }

/* ---------- per-video complete/to-do status ---------- */
async function ensureSummary() {
  if (SUMMARY) return SUMMARY;
  try {
    SUMMARY = await (await fetch("/api/home", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession() }) })).json();
  } catch (e) { SUMMARY = { videos: {} }; }
  return SUMMARY;
}
function videoStatus(vid) {
  return ((SUMMARY && SUMMARY.videos && SUMMARY.videos[vid]) || {}).status || "";
}
function statusDot(vid) {
  const st = videoStatus(vid);
  return el("span", "status-dot" + (st ? " " + st : ""));
}
function setVideoStatus(vid, status) {
  if (!SUMMARY) SUMMARY = { videos: {} };
  if (!SUMMARY.videos) SUMMARY.videos = {};
  const v = SUMMARY.videos[vid] || (SUMMARY.videos[vid] = {});
  if (status) v.status = status; else delete v.status;
  fetch("/api/event", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: getSession(), id: vid, kind: "status", status: status || "" }) }).catch(() => {});
}

/* ---------- assigned tests + notification bell ---------- */
let ASSIGNED_TESTS = [];   // [{id, title}]
function updateBell() {
  const b = $("#testBell");
  if (!b) return;
  const on = ASSIGNED_TESTS.length > 0 && !$("#profileWrap").classList.contains("hidden");
  b.classList.toggle("hidden", !on);
  b.title = ASSIGNED_TESTS.length ? (ASSIGNED_TESTS[0].title || t("test_have")) : "";
}
async function refreshTests() {
  if (!getName()) { ASSIGNED_TESTS = []; updateBell(); return; }
  try {
    const sum = await (await fetch("/api/home", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession() }) })).json();
    if (sum && typeof sum === "object") SUMMARY = sum;   // keep cached summary fresh for the new student
    ASSIGNED_TESTS = (sum && sum.tests) || [];
  } catch (e) { ASSIGNED_TESTS = []; }
  updateBell();
}
let CUR_TEST = null;
async function openTest(meta) {
  show("test");
  $("#testMsg").textContent = "";
  const form = $("#testForm");
  form.innerHTML = "<p class='muted-note'>" + t("loading") + "</p>";
  try {
    CUR_TEST = await (await fetch("/api/test/" + encodeURIComponent(meta.id))).json();
  } catch (e) { form.innerHTML = "<p class='muted-note'>Could not load the test.</p>"; return; }
  $("#testHeading").textContent = CUR_TEST.title || t("test_title");
  const dueEl = $("#testDue");
  if (CUR_TEST.due) { dueEl.textContent = "⏰ " + t("test_due") + " " + fmtDue(CUR_TEST.due); dueEl.classList.remove("hidden"); }
  else dueEl.classList.add("hidden");
  form.innerHTML = "";
  (CUR_TEST.questions || []).forEach((q, i) => {
    const card = el("div", "card test-q");
    card.appendChild(el("div", "test-q-text", (i + 1) + ". " + q.q));
    if (q.type === "mc") {
      (q.choices || []).forEach((c, ci) => {
        const lab = el("label", "test-choice");
        const r = document.createElement("input");
        r.type = "radio"; r.name = "tq" + i; r.value = String(ci);
        lab.appendChild(r); lab.appendChild(el("span", null, c));
        card.appendChild(lab);
      });
    } else {
      const ta = document.createElement("textarea");
      ta.className = "field test-text"; ta.rows = 3; ta.dataset.q = String(i);
      ta.placeholder = t("test_answer_ph");
      card.appendChild(ta);
    }
    form.appendChild(card);
  });
}
async function submitTest() {
  if (!CUR_TEST) return;
  const answers = {};
  (CUR_TEST.questions || []).forEach((q, i) => {
    if (q.type === "mc") {
      const sel = document.querySelector("input[name=tq" + i + "]:checked");
      if (sel) answers[i] = parseInt(sel.value, 10);
    } else {
      const ta = document.querySelector("textarea[data-q='" + i + "']");
      if (ta && ta.value.trim()) answers[i] = ta.value.trim();
    }
  });
  const r = await fetch("/api/test/submit", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: getSession(), testId: CUR_TEST.id, answers }) });
  const j = await r.json();
  if (j.ok) {
    $("#testMsg").textContent = t("test_sent");
    ASSIGNED_TESTS = ASSIGNED_TESTS.filter(x => x.id !== CUR_TEST.id);
    updateBell();
    setTimeout(() => openSubjects(), 1100);
  } else {
    $("#testMsg").style.color = "#C0392B";
    $("#testMsg").textContent = t("could_not_send_retry");
  }
}
function saveReadingPage() {
  if (SUMMARY) { SUMMARY.books = SUMMARY.books || {}; (SUMMARY.books[BOOK.id] = SUMMARY.books[BOOK.id] || {}).page = SPREAD; }
  sendMode("reading", BOOK.id, BOOK.title, false, SPREAD);
}
function sendMode(mode, bookId, title, finished, page) {
  const body = { session: getSession(), mode: mode, bookId: bookId || "", title: title || "", finished: !!finished };
  if (page != null) body.page = page;
  fetch("/api/reading", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).catch(() => {});
}

/* ---------- reading hub (bookshelf) ---------- */
let READLANG = null;
// which grade's tab/grid is currently shown; seeded once per session from the
// student's own grade, then left alone so re-visiting the hub keeps whatever
// grade they last picked (persists for the session, not across reloads)
let ACTIVE_GRADE = null;
function renderReadLangs() {
  const box = $("#readLangs"); box.innerHTML = "";
  ["en", "fr", "es", "de"].forEach(l => {
    const on = l === READLANG;
    const b = el("button", "read-lang-seg" + (on ? " on" : ""), l.toUpperCase());
    b.onclick = () => { if (l !== READLANG) { READLANG = l; localStorage.setItem("lb_readlang", l); openReading(); } };
    box.appendChild(b);
  });
}
// `tr` lets the reading hub pass rt() so grade names follow the shelf language,
// while every other caller (browse, roster, dashboard) keeps the app language
function gradeLabel(g, tr) { tr = tr || t; return g ? tr("grade_" + g) : tr("no_grade_yet"); }
// per-grade accent hue + icon (warm K-2, green/teal 3-5, blue/purple 6-8) - used only as
// a pastel tab tint + the active-grade icon tile, never as a solid fill
const GRADE_ACCENTS = { K: "#E28A4E", "1": "#DB9A3C", "2": "#C9A93A", "3": "#8FAE47", "4": "#68A64A",
  "5": "#2E9B85", "6": "#2D82A0", "7": "#3E63A0", "8": "#5A4A96" };
const GRADE_ICONS = {
  K: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8z" fill="currentColor"/></svg>',
  "1": '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M12 9c-.5-1.2-1.8-2-3.2-1.8C6.7 7.5 5 9.3 5 12c0 3.9 2.8 7 5.5 8.3.9.4 1.9.4 2.8 0C16 19 18.8 15.9 18.8 12c0-2.6-1.7-4.5-3.8-4.8-1.4-.2-2.7.6-3.2 1.8z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M12 9V6.5M12 6.5c.8-1 2-1.2 3-.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  "2": '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M9 4h4v2a1.5 1.5 0 0 0 3 0V4h2a2 2 0 0 1 2 2v4h-2a1.5 1.5 0 0 0 0 3h2v4a2 2 0 0 1-2 2h-4v-2a1.5 1.5 0 0 0-3 0v2H7a2 2 0 0 1-2-2v-4h2a1.5 1.5 0 0 0 0-3H5V6a2 2 0 0 1 2-2z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  "3": '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M15 9l-2 5-5 2 2-5z" fill="currentColor"/></svg>',
  "4": '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M6 18C6 10 12 5 19 5c0 7-5 13-13 13z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M7 17c3-4 7-7 11-9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  "5": '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 15l13-6 2 4-13 6z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M9 13.5L6 20M17 11l2.5-1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="6.5" cy="12.5" r="1.4" fill="currentColor"/></svg>',
  "6": '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M12 2c2.5 2 4 5.5 4 9 0 2-1 4-1 4H9s-1-2-1-4c0-3.5 1.5-7 4-9z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="12" cy="9" r="1.3" fill="currentColor"/><path d="M9 15l-2.5 4M15 15l2.5 4M10 19h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  "7": '<svg viewBox="0 0 24 24" width="22" height="22"><ellipse cx="12" cy="12" rx="9" ry="3.4" fill="none" stroke="currentColor" stroke-width="1.4" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="3.4" fill="none" stroke="currentColor" stroke-width="1.4" transform="rotate(-60 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="3.4" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/></svg>',
  "8": '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M12 3 2 8l10 5 8-4v5h2V8z" fill="currentColor"/><path d="M6 12v4c0 1.7 2.7 3 6 3s6-1.3 6-3v-4l-6 3z" fill="currentColor"/></svg>',
};
function hexToRgba(hex, a) {
  const h = hex.replace("#", "");
  return "rgba(" + parseInt(h.substr(0, 2), 16) + "," + parseInt(h.substr(2, 2), 16) + "," + parseInt(h.substr(4, 2), 16) + "," + a + ")";
}
function readingBadgeCount(sum) {
  const books = (sum && sum.books) || {};
  return Object.keys(books).filter(id => books[id] && books[id].passed).length;
}
function renderReadingAwardsCard() {
  const n = readingBadgeCount(SUMMARY || {});
  $("#racSub").textContent = n + " " + rt(n === 1 ? "badge_earned_word" : "badges_earned_word");
}
async function openReading() {
  // the shelf language is its own setting (lb_readlang), not the app language: a kid
  // reading in French inside an English-run classroom keeps French across reloads.
  // It seeds from the app language the first time only.
  if (!READLANG) READLANG = localStorage.getItem("lb_readlang") ||
    ((LANG === "fr" || LANG === "es" || LANG === "de") ? LANG : "en");
  show("reading");
  // hub chrome is in the reading language, so its strings must be in hand before
  // the shelves render below
  await loadReadStrings();
  renderReadLangs();
  const sh = $("#bookShelves"); sh.innerHTML = "<p class='muted-note'>" + rt("loading") + "</p>";
  $("#gradeTabBar").innerHTML = ""; $("#activeGradeHead").innerHTML = "";
  let levels;
  try { levels = await (await fetch("/api/books?lang=" + READLANG)).json(); }
  catch (e) { sh.innerHTML = ""; sh.appendChild(el("p", "muted-note", rt("could_not_load_books"))); return; }
  sh.innerHTML = "";
  if (!levels.length) { sh.appendChild(el("p", "muted-note", rt("no_books_lang_yet"))); return; }
  await ensureSummary();
  renderReadingAwardsCard();
  const myGrade = (SUMMARY && SUMMARY.grade) || "";
  if (!ACTIVE_GRADE || !levels.some(lv => lv.grade === ACTIVE_GRADE)) {
    ACTIVE_GRADE = levels.some(lv => lv.grade === myGrade) ? myGrade : levels[0].grade;
  }
  renderGradeTabs(levels);
  renderActiveGrade(levels);
}
function renderGradeTabs(levels) {
  const bar = $("#gradeTabBar"); bar.innerHTML = "";
  levels.forEach(lv => {
    const accent = GRADE_ACCENTS[lv.grade] || "#5A7593", isActive = lv.grade === ACTIVE_GRADE;
    const b = el("button", "grade-tab" + (isActive ? " active" : ""), lv.grade);
    if (isActive) {
      b.style.background = hexToRgba(accent, .16);
      b.style.color = accent;
      b.style.borderColor = hexToRgba(accent, .4);
    }
    b.onclick = () => { ACTIVE_GRADE = lv.grade; renderGradeTabs(levels); renderActiveGrade(levels); };
    bar.appendChild(b);
  });
}
function renderActiveGrade(levels) {
  const lv = levels.find(x => x.grade === ACTIVE_GRADE) || levels[0];
  const accent = GRADE_ACCENTS[lv.grade] || "#5A7593";
  const head = $("#activeGradeHead"); head.innerHTML = "";
  const ic = el("span", "agh-ic"); ic.style.background = hexToRgba(accent, .14); ic.style.color = accent;
  ic.innerHTML = GRADE_ICONS[lv.grade] || BOOK_ICON;
  head.appendChild(ic);
  const txt = el("div");
  txt.appendChild(el("div", "agh-title", gradeLabel(lv.grade, rt) + " " + rt("books_word")));
  const sub = el("div", "agh-sub");
  const subIc = el("span"); subIc.innerHTML = BOOK_ICON; sub.appendChild(subIc);
  sub.appendChild(document.createTextNode(lv.books.length + " " + rt(lv.books.length === 1 ? "book_word" : "books_word")));
  txt.appendChild(sub);
  head.appendChild(txt);
  const grid = $("#bookShelves"); grid.innerHTML = "";
  lv.books.forEach(b => grid.appendChild(bookCard(b)));
}
function bookFallback(b) {
  return el("span", "book-cover-fallback", (b.title || "?").trim().charAt(0).toUpperCase());
}
function bookCard(b) {
  const c = el("button", "book-card");
  const cov = el("div", "book-cover");
  if (b.cover) {
    const img = el("img"); img.src = b.cover; img.loading = "lazy"; img.alt = b.title;
    img.onerror = () => { img.remove(); cov.appendChild(bookFallback(b)); };
    cov.appendChild(img);
  } else {
    cov.appendChild(bookFallback(b));
  }
  cov.appendChild(el("div", "book-cover-spine"));
  cov.appendChild(el("div", "book-cover-sheen"));
  // a bookmarked/in-progress book (saved mid-book, not yet finished) gets a ribbon +
  // "page X of Y" tag instead of the plain page-count tag, so a kid can spot at a
  // glance which cover to tap to pick up right where they left off
  const rec = SUMMARY && SUMMARY.books && SUMMARY.books[b.id];
  const bookmarked = !!(rec && rec.page > 0 && !rec.read);
  if (bookmarked) {
    const ribbon = el("div", "book-cover-bookmark");
    ribbon.innerHTML = BOOKMARK_ICON;
    ribbon.setAttribute("aria-label", rt("continue_reading"));
    cov.appendChild(ribbon);
  }
  if (bookmarked && b.pages) {
    cov.appendChild(el("div", "book-cover-tag on-bookmark", (rec.page + 1) + " / " + (b.pages + 1)));
  } else if (b.pages) {
    cov.appendChild(el("div", "book-cover-tag", b.pages + " " + rt("pages_word")));
  }
  c.appendChild(cov);
  c.appendChild(el("div", "bc-title", b.title));
  // the byline sits in its own fixed-height slot below a fixed-height title, so a
  // one-line title and a wrapped two-line title put their bylines on the same
  // baseline across the grid instead of each card setting its own rhythm
  const auth = el("div", "bc-auth" + (bookmarked ? " bc-continue" : ""));
  if (bookmarked) auth.textContent = rt("continue_reading");
  else if (b.author) auth.textContent = byline(b.author);
  c.appendChild(auth);
  c.onclick = () => openBook(b.id);
  return c;
}

/* ---------- e-book reader ---------- */
let BOOK = null, SPREAD = 0;
async function openBook(bid) {
  let b;
  try { b = await (await fetch("/api/book/" + bid + "?lang=" + READLANG)).json(); } catch (e) { return; }
  if (!b || !b.spreads || !b.spreads.length) return;
  BOOK = b;
  await ensureSummary();
  const saved = SUMMARY && SUMMARY.books && SUMMARY.books[bid] && SUMMARY.books[bid].page;
  SPREAD = typeof saved === "number" ? Math.min(Math.max(saved, 0), b.spreads.length - 1) : 0;
  sendMode("reading", b.id, b.title, false, SPREAD);
  $("#readerTitle").textContent = b.title;
  $("#bookQuiz").classList.add("hidden");
  document.querySelector(".reader-stage").classList.remove("hidden");
  $("#hudName").textContent = getName();
  $("#hudStars").textContent = String(totalStars());
  show("reader");
  renderSpread();
}
function totalStars() {
  let n = 0;
  const v = (SUMMARY && SUMMARY.videos) || {}; Object.keys(v).forEach(id => { if (v[id] && v[id].passed) n++; });
  const b = (SUMMARY && SUMMARY.books) || {}; Object.keys(b).forEach(id => { if (b[id] && b[id].passed) n++; });
  return n;
}
function bumpHudStars() {
  const e = $("#hudStars"); if (!e) return;
  e.textContent = String(totalStars());
  e.classList.add("bump"); setTimeout(() => e.classList.remove("bump"), 320);
}
function playChime() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
    const ctx = new AC(), now = ctx.currentTime;
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => {   // C-E-G-C arpeggio
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "triangle"; o.frequency.value = f;
      const t0 = now + i * 0.12;
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.25, t0 + 0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.35);
      o.connect(g); g.connect(ctx.destination); o.start(t0); o.stop(t0 + 0.4);
    });
    setTimeout(() => { try { ctx.close(); } catch (e) {} }, 1300);
  } catch (e) {}
}
function winAnimation() {
  const ov = $("#winOverlay"); if (!ov) return;
  ov.classList.remove("hidden");
  const star = ov.querySelector(".win-star");
  if (star) { star.style.animation = "none"; void star.offsetWidth; star.style.animation = ""; }
  playChime();
  clearTimeout(window._winT); window._winT = setTimeout(() => ov.classList.add("hidden"), 1800);
}
function creditsHtml(c) {
  const bits = [];
  if (c.author) bits.push("<b>" + esc(rt("credit_story")) + "</b> " + esc(c.author));
  if (c.illustrator) bits.push("<b>" + esc(rt("credit_illustration")) + "</b> " + esc(c.illustrator));
  if (c.translator) bits.push("<b>" + esc(rt("credit_translation")) + "</b> " + esc(c.translator));
  let s = bits.join(" &middot; ");
  const home = c.project_home || c.source_url || "";
  if (c.source || home) s += "<br>" + esc(rt("credit_from")) + " " + (home ? "<a href='" + esc(home) + "' target='_blank' rel='noopener'>" + esc(c.source || home) + "</a>" : esc(c.source));
  if (c.license) s += " &middot; " + (c.license_url ? "<a href='" + esc(c.license_url) + "' target='_blank' rel='noopener'>" + esc(c.license) + "</a>" : esc(c.license));
  return s;
}
function gradeBand(grade) {
  if (grade === "K" || grade === "1" || grade === "2") return "gband-k2";
  if (grade === "3" || grade === "4") return "gband-34";
  return "gband-5plus";
}
/* ---------- typesetting the raw page text ----------
   The Gutenberg chapter books arrive as a plain run of text per page - 39 of Jekyll's
   98 pages carry no paragraph break at all - which renders as a wall. These helpers
   turn that run into something set like a page: a lone short first line becomes a real
   chapter head, and any paragraph long enough to be a wall is broken on sentence
   boundaries into 3-4 sentence chunks. Nothing is rewritten, only re-flowed. */
const CHAPTER_WORD = /^(chapter|chapitre|kapitel|cap[ií]tulo|part|partie|teil|parte|book|livre|buch|libro)\b/i;
// a full stop that belongs to an abbreviation is not the end of a sentence
const ABBREV_END = /(?:^|[\s(])(?:mr|mrs|ms|dr|prof|st|jr|sr|sra|srta|mme|mlle|m|hr|fr|nr|bzw|ca|ggf|usw|etc|vs|no|vol|fig|ch)\.$/i;

function takeHeadLine(text) {
  const nl = text.indexOf("\n");
  if (nl < 1) return null;
  const head = text.slice(0, nl).trim(), rest = text.slice(nl + 1).replace(/^\s+/, "");
  if (!head || !rest || head.length > 72 || /[,;:]$/.test(head)) return null;
  const letters = head.replace(/[^A-Za-zÀ-ÖØ-öø-ÿ]/g, "");
  const caps = letters.length > 1 && head === head.toUpperCase();
  // conservative on purpose: a short line only counts as a heading when it shouts,
  // names a chapter, or is a bare numeral - never merely because it is short
  if (!caps && !CHAPTER_WORD.test(head) && !/^[IVXLCDM]+\.?$/.test(head) && !/^\d+\.?$/.test(head)) return null;
  return { head: head, rest: rest, caps: caps };
}

/* A chapter can open on two heading lines - Jekyll's first page carries the part title
   above the chapter title - so take up to two, and set the second (the more specific
   one) as the main head with the first sitting above it. */
function splitChapterHead(text) {
  const first = takeHeadLine(text);
  if (!first) return null;
  const second = takeHeadLine(first.rest);
  if (!second) return { over: "", head: first.head, caps: first.caps, rest: first.rest };
  return { over: first.head, head: second.head, caps: second.caps, rest: second.rest };
}

function splitSentences(text) {
  const out = []; let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c !== "." && c !== "!" && c !== "?" && c !== "…") continue;
    let j = i + 1;                                     // swallow trailing quotes/brackets
    while (j < text.length && ".!?…)]\"'”’»".indexOf(text[j]) >= 0) j++;
    if (j >= text.length || !/\s/.test(text[j])) { i = j - 1; continue; }
    const piece = text.slice(start, j);
    if (ABBREV_END.test(piece)) { i = j - 1; continue; }
    out.push(piece.trim()); start = j; i = j - 1;
  }
  const tail = text.slice(start).trim();
  if (tail) out.push(tail);
  return out;
}

function reflowPara(para) {
  // leave verse and already-short paragraphs exactly as the book set them
  if (para.length <= 420 || para.indexOf("\n") >= 0) return [para];
  const sents = splitSentences(para);
  if (sents.length < 4) return [para];
  const out = []; let buf = [], len = 0;
  for (let k = 0; k < sents.length; k++) {
    // 3-4 sentences per chunk, but a page of Stevenson-length sentences would still
    // read as a block at four of them, so length closes a chunk early - before the
    // sentence that would overshoot, and again after any chunk that runs long
    if (buf.length >= 2 && len + sents[k].length > 620) { out.push(buf.join(" ")); buf = []; len = 0; }
    buf.push(sents[k]); len += sents[k].length + 1;
    if (buf.length >= 4 || (buf.length >= 3 && len >= 300) || len >= 520) { out.push(buf.join(" ")); buf = []; len = 0; }
  }
  if (buf.length === 1 && out.length) out[out.length - 1] += " " + buf[0];   // no orphan chunk
  else if (buf.length) out.push(buf.join(" "));
  return out;
}

/* line-spark-line ornament, shared by the cover and every chapter head */
function ruleEl() {
  const r = el("div", "r-rule");
  r.appendChild(el("span", "r-rule-line"));
  r.appendChild(el("span", "r-rule-mark", "✦"));
  r.appendChild(el("span", "r-rule-line"));
  return r;
}

function renderSpread() {
  const sp = BOOK.spreads, i = SPREAD, last = sp.length - 1;
  const spread = document.querySelector(".reader-spread");
  const hasImage = !!sp[i].image;
  document.querySelector(".reader-img").classList.toggle("no-image", !hasImage);
  spread.classList.toggle("text-only", !hasImage);
  spread.classList.toggle("cover-page", i === 0);
  if (hasImage) $("#rImg").src = sp[i].image;
  const txt = $("#rText");
  const endDiv = $("#rEndDivider");
  const isLast = i === last;
  if (i === 0) {
    txt.className = "r-text cover"; txt.innerHTML = "";
    txt.appendChild(el("div", "r-cover-t", BOOK.title));
    txt.appendChild(ruleEl());
    // a title page carries the author under the rule, same byline wording as the
    // shelf card so the two surfaces agree
    if (BOOK.author) txt.appendChild(el("div", "r-cover-a", byline(BOOK.author)));
    endDiv.classList.add("hidden");
  } else {
    txt.innerHTML = "";
    // chapter books are set like novels (indented paragraphs, chapter heads, drop cap);
    // picture books keep the spaced setting that suits one thought per spread
    const chap = BOOK.textbook ? splitChapterHead(sp[i].text || "") : null;
    const body = chap ? chap.rest : (sp[i].text || "");
    if (chap) {
      const head = el("header", "r-chapter");
      if (chap.over) head.appendChild(el("div", "r-chapter-over", chap.over));
      head.appendChild(el("h3", "r-chapter-t" + (chap.caps ? " caps" : ""), chap.head));
      head.appendChild(ruleEl());
      txt.appendChild(head);
    }
    const paras = [];
    body.split(/\n{2,}/).forEach(p => { if (p.trim()) reflowPara(p).forEach(c => paras.push(c)); });
    // a drop cap opens a chapter, but only when the first character is a letter -
    // dropping a quotation mark on a chapter that opens on dialogue looks broken
    const drop = !!chap && /^[A-Za-zÀ-ÖØ-öø-ÿ]/.test(paras[0] || "");
    txt.className = "r-text " + gradeBand(BOOK.grade) + (BOOK.textbook ? " indented" : " spaced") + (drop ? " dropcap" : "");
    paras.forEach(p => txt.appendChild(el("p", "r-para", p)));
    endDiv.classList.toggle("hidden", !isLast);
  }
  // replay the page-turn fade/slide animation on every spread change
  spread.style.animation = "none"; void spread.offsetWidth; spread.style.animation = "";
  $("#rPageNumText").textContent = i === 0 ? rt("cover_word")
    : (isLast ? rt("last_page") : (i + 1) + " / " + sp.length);
  const frac = last > 0 ? (i / last) : 1;
  $("#hudFill").style.transform = "scaleX(" + frac + ")";
  $("#hudMark").style.left = (frac * 100) + "%";
  const prog = $("#hudProgress");
  prog.setAttribute("aria-valuemax", String(sp.length));
  prog.setAttribute("aria-valuenow", String(i + 1));
  prog.setAttribute("aria-valuetext", rt("page_word") + " " + (i + 1) + " " + rt("of_word") + " " + sp.length);
  $("#rbPrev").disabled = (i === 0);
  const showCred = (i === 0 || isLast);
  $("#rCredits").classList.toggle("hidden", !showCred);
  if (showCred) $("#rCredits").innerHTML = creditsHtml(BOOK.credits || {});
  $("#rbNext").classList.toggle("hidden", isLast);
  $("#rbQuiz").classList.toggle("hidden", !isLast);
  if (isLast && BOOK && !BOOK._finished) {   // genuinely read to the end -> count it
    BOOK._finished = true;
    sendMode("reading", BOOK.id, BOOK.title, true);
    // mirror server's "read" flag locally so the Reading Hub's bookmark badge
    // (computed from the cached SUMMARY) drops immediately, not after a stale re-fetch
    if (SUMMARY) { SUMMARY.books = SUMMARY.books || {}; (SUMMARY.books[BOOK.id] = SUMMARY.books[BOOK.id] || {}).read = true; }
  }
}

/* ---------- book quiz (3 random from the book's bank) ---------- */
let BQ = null, BQI = 0, BQSCORE = 0;
async function startBookQuiz(retry) {
  if (!BOOK) return;
  document.querySelector(".reader-stage").classList.add("hidden");
  const box = $("#bookQuiz"); box.classList.remove("hidden");
  box.innerHTML = "<div class='qhead'>" + rt("quiz_preparing") + "</div>";   // fresh 3 each time
  let data;
  try { data = await (await fetch("/api/bookquiz/" + BOOK.id + "?lang=" + READLANG)).json(); }
  catch (e) { box.innerHTML = "<div class='qhead'>—</div>"; return; }
  if (!data.questions || !data.questions.length) {
    box.innerHTML = "<div class='qhead'>" + rt("quiz_preparing") + "</div>";   // still generating
    clearTimeout(window._bqprep);
    window._bqprep = setTimeout(() => { if (!$("#reader").classList.contains("hidden")) startBookQuiz(retry); }, 3500);
    return;
  }
  BQ = data; BQI = 0; BQSCORE = 0;
  renderBookQ();
}
function renderBookQ() {
  const box = $("#bookQuiz"); box.innerHTML = "";
  if (BQI >= BQ.questions.length) return finishBookQuiz();
  const item = BQ.questions[BQI];
  box.appendChild(el("div", "qhead", rt("question") + " " + (BQI + 1) + " / " + BQ.questions.length));
  const qc = el("div", "qcard"); qc.appendChild(document.createTextNode(item.q));
  const s = spkBtn(); s.onclick = () => speak(item.q); qc.appendChild(s); box.appendChild(qc);
  item.choices.forEach((ch, i) => { const b = el("button", "choice", ch); b.onclick = () => gradeBookMC(b, i); box.appendChild(b); });
}
async function gradeBookMC(btn, idx) {
  document.querySelectorAll("#bookQuiz .choice").forEach(b => b.disabled = true);
  let d;
  try {
    d = await (await fetch("/api/grade", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookId: BOOK.id, qi: BQ.questions[BQI].qi, answer: idx, session: getSession(), lang: READLANG }) })).json();
  } catch (e) { d = { correct: false, feedback: "" }; }
  if (d.correct) { btn.classList.add("correct"); BQSCORE++; }
  else { btn.classList.add("wrong"); const all = document.querySelectorAll("#bookQuiz .choice"); if (all[d.answerIndex] != null) all[d.answerIndex].classList.add("correct"); }
  const box = $("#bookQuiz");
  const f = el("div", "feedback"); f.textContent = d.feedback || ""; box.appendChild(f); speak(d.feedback);
  const next = el("button", "btn primary", BQI + 1 < BQ.questions.length ? rt("next") : rt("see_stars"));
  next.style.marginTop = "12px"; next.onclick = () => { BQI++; renderBookQ(); }; box.appendChild(next);
}
function finishBookQuiz() {
  const box = $("#bookQuiz"); box.innerHTML = "";
  const total = BQ.questions.length, passed = total >= 1 && BQSCORE * 5 >= total * 3;   // 60%: 2/3 or 3/5
  fetch("/api/book_quiz_done", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: getSession(), bookId: BOOK.id, title: BOOK.title, correct: BQSCORE, total: total }) }).catch(() => {});
  if (SUMMARY) { SUMMARY.books = SUMMARY.books || {}; const r = SUMMARY.books[BOOK.id] = SUMMARY.books[BOOK.id] || {}; r.title = BOOK.title; r.read = true; if (passed) r.passed = true; }
  if (passed) { winAnimation(); bumpHudStars(); }
  const d = el("div", "qresult");
  d.appendChild(el("div", "stars", "★".repeat(BQSCORE) + "☆".repeat(Math.max(0, total - BQSCORE))));
  d.appendChild(el("div", "qscore", rt("you_got") + " " + BQSCORE + " / " + total));
  d.appendChild(el("div", null, passed ? rt("amazing") : rt("book_effort"))); speak(passed ? rt("amazing") : rt("book_effort"), READLANG);
  const actions = el("div", "qresult-actions");
  const retry = el("button", "btn " + (passed ? "ghost" : "primary"), rt("again")); retry.onclick = () => startBookQuiz(true);
  actions.appendChild(retry);
  if (passed) { const star = el("button", "btn primary", rt("reading_awards")); star.onclick = () => openAchievements("reading"); actions.appendChild(star); }
  const back = el("button", "btn ghost", rt("back_to_books")); back.onclick = openReading; actions.appendChild(back);
  d.appendChild(actions);
  box.appendChild(d);
}
function renderHomeHeading(sum) {
  const name = getName();
  const vid = (sum && (sum.last_quiz_video || sum.last_video)) || "";
  const v = vid && CATALOG.find(x => x.id === vid);
  const topic = v ? (v.topic_label || v.title) : "";
  $("#homeEyebrow").textContent = t("home_welcome_back");
  const h = $("#homeHeading"); h.innerHTML = ""; h.textContent = "";
  h.appendChild(document.createTextNode(name + ", " + (topic ? t("home_ready_topic") : t("home_ready_new")) + " "));
  if (topic) { h.appendChild(el("span", "home-hl", topic)); h.appendChild(document.createTextNode("?")); }
}
async function openHome() {
  show("home");
  $("#homeEyebrow").textContent = t("home_welcome_back");
  $("#homeHeading").textContent = getName() + ",";   // instant, refined once summary loads
  $("#nextStep").classList.add("hidden");
  try {
    SUMMARY = await (await fetch("/api/home", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession() }) })).json();
  } catch (e) { SUMMARY = { videos: {} }; }
  ASSIGNED_TESTS = (SUMMARY && SUMMARY.tests) || [];
  updateBell();
  renderHomeHeading(SUMMARY || {});
  renderNextStep(SUMMARY || { videos: {} });
  renderTodoList(SUMMARY || { videos: {} });
}
function renderTodoList(sum) {
  const section = $("#todoSection"), box = $("#todoList");
  box.innerHTML = "";
  const vids = (sum && sum.videos) || {};
  const items = Object.keys(vids).filter(id => vids[id] && vids[id].status === "todo")
    .map(id => CATALOG.find(v => v.id === id)).filter(Boolean);
  section.classList.toggle("hidden", items.length === 0);
  items.forEach(v => {
    const b = el("button", "todo-row");
    const ic = el("span", "todo-ic"); ic.innerHTML = PLAY; b.appendChild(ic);
    const main = el("span", "todo-main");
    main.appendChild(el("span", "todo-title", v.title));
    main.appendChild(el("span", "todo-sub", (v.topic_label || "") + " · " + Math.round(v.duration_min) + " min"));
    b.appendChild(main);
    const dot = el("span", "todo-dot"); dot.appendChild(statusDot(v.id)); b.appendChild(dot);
    b.onclick = () => openLesson(v.id, "home");
    box.appendChild(b);
  });
}
function nextStepFor(sum) {
  if (!CATALOG.length) return null;
  const byId = id => CATALOG.find(v => v.id === id);
  const lq = sum.last_quiz_video, passed = sum.last_quiz_passed;
  if (lq && byId(lq) && passed === false) return { vid: lq, msg: t("ns_redo") };
  if (lq && passed === true) {
    const i = CATALOG.findIndex(v => v.id === lq);
    if (i >= 0 && CATALOG[i + 1]) return { vid: CATALOG[i + 1].id, msg: t("ns_pass") };
  }
  if (sum.last_video && byId(sum.last_video)) return { vid: sum.last_video, msg: t("ns_new") };
  return { vid: CATALOG[0].id, msg: t("ns_new") };
}
function renderNextStep(sum) {
  const box = $("#nextStep"), step = nextStepFor(sum);
  const v = step && CATALOG.find(x => x.id === step.vid);
  if (!v) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden"); box.innerHTML = "";
  box.appendChild(el("div", "ns-head", "★ " + t("ns_title")));
  box.appendChild(el("div", "ns-msg", step.msg));
  const b = el("button", "ns-btn");
  const main = el("div");
  main.appendChild(el("div", "nb-t", v.title));
  main.appendChild(el("div", "nb-s", (v.topic_label || "") + " · " + Math.round(v.duration_min) + " min"));
  b.appendChild(main);
  const play = el("span", "nb-play"); play.innerHTML = PLAY; b.appendChild(play);
  b.onclick = () => openLesson(v.id, "home");
  box.appendChild(b);
}

/* ---------- achievement box ---------- */
let _achReturn = "home", _achScope = "all";
async function openAchievements(scope) {
  _achReturn = (CURRENT_SCREEN && CURRENT_SCREEN !== "achievements") ? CURRENT_SCREEN : "home";
  _achScope = scope || "all";
  try {
    SUMMARY = await (await fetch("/api/home", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession() }) })).json();
  } catch (e) {}
  show("achievements");
  renderAchievements(SUMMARY || { videos: {}, books: {} }, _achScope);
}
function renderAchievements(sum, scope) {
  scope = scope || "all";
  const grid = $("#achGrid"), stats = $("#achStats"), showcase = $("#achShowcase"), vids = sum.videos || {}, books = sum.books || {};
  const byId = id => CATALOG.find(v => v.id === id);
  const vpassed = [], vfin = new Set();   // a video counts as watched only if finished or quiz-passed
  Object.keys(vids).forEach(id => { const v = vids[id] || {}; if (v.finished || v.passed) vfin.add(id); if (v.passed) vpassed.push(id); });
  const bpassed = [], bread = new Set();  // a book counts as read only if genuinely read to the end
  Object.keys(books).forEach(id => { const b = books[id] || {}; if (b.read || b.passed) bread.add(id); if (b.passed) bpassed.push(id); });
  const showMath = scope !== "reading", showRead = scope !== "math";
  $("#achTitle").textContent = scope === "math" ? t("ach_math_title")
    : scope === "reading" ? t("reading_awards") : (getName() + " — " + t("ach_about_me_suffix"));
  stats.innerHTML = "";
  const stat = (n, label) => { const d = el("div", "ach-stat"); d.appendChild(el("div", "num", String(n))); d.appendChild(el("div", "lbl2", label)); return d; };
  if (scope === "all") stats.appendChild(stat(vpassed.length + bpassed.length, t("stat_gold_stars")));
  if (showMath) { stats.appendChild(stat(vpassed.length, t("stat_math_quizzes"))); stats.appendChild(stat(vfin.size, t("stat_videos_watched"))); }
  if (showRead) { stats.appendChild(stat(bpassed.length, t("stat_book_quizzes"))); stats.appendChild(stat(bread.size, t("stat_books_read"))); }
  grid.innerHTML = "";
  const items = [];
  if (showMath) {
    vpassed.forEach(id => { const v = byId(id); items.push({ badge: "⭐", stamp: false, title: v ? v.title : id, tag: t("tag_quiz_passed") }); });
    vfin.forEach(id => { if (vpassed.indexOf(id) < 0) { const v = byId(id); items.push({ badge: "🎬", stamp: true, title: v ? v.title : id, tag: t("tag_watched") }); } });
  }
  if (showRead) {
    bpassed.forEach(id => items.push({ badge: "📖", stamp: false, title: (books[id] || {}).title || id, tag: t("tag_book_quiz_passed") + " ⭐" }));
    bread.forEach(id => { if (bpassed.indexOf(id) < 0) items.push({ badge: "📚", stamp: true, title: (books[id] || {}).title || id, tag: t("tag_read") }); });
  }
  $("#achEmpty").classList.toggle("hidden", items.length > 0);
  items.forEach(it => {
    const card = el("div", "ach-item");
    card.appendChild(el("div", "ach-badge" + (it.stamp ? " stamp" : ""), it.badge));
    card.appendChild(el("div", "ach-name", it.title));
    card.appendChild(el("div", "ach-tag" + (it.stamp ? " watched" : ""), it.tag));
    grid.appendChild(card);
  });
  // showcase: highlight up to 5 gold-star (quiz-passed) awards; fill the rest with empty
  // dashed slots so a brand-new learner sees what they're working toward
  showcase.innerHTML = "";
  const highlights = items.filter(it => !it.stamp).slice(0, 5);
  highlights.forEach(it => showcase.appendChild(el("div", "showcase-slot", it.badge)));
  for (let i = highlights.length; i < 5; i++) showcase.appendChild(el("div", "showcase-slot empty", ""));
  const prevNote = showcase.parentNode.querySelector(".showcase-empty-note");
  if (prevNote) prevNote.remove();
  if (!highlights.length) {
    const note = el("p", "showcase-empty-note", t("showcase_empty"));
    showcase.parentNode.insertBefore(note, showcase.nextSibling);
  }
}

/* ---------- teacher dashboard: classes, access codes, pending requests ---------- */
function esc(s) { return (s || "").replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c])); }

async function loadMyClasses() {
  let res;
  try { res = await fetch("/api/teacher/classes?session=" + encodeURIComponent(getSession())); } catch (e) { return false; }
  if (res.status !== 200) return false;
  const j = await res.json();
  MY_CLASSES = j.classes || [];
  if (!MY_CLASSES.some(c => c.id === CUR_CLASS_ID)) CUR_CLASS_ID = (MY_CLASSES[0] || {}).id || "";
  localStorage.setItem("lb_class_id", CUR_CLASS_ID);
  renderClassSelect();
  return true;
}
function renderClassSelect() {
  const sel = $("#classSelect"); sel.innerHTML = "";
  MY_CLASSES.forEach(c => {
    const o = el("option", null, c.name + " (" + gradeLabel(c.grade) + ")");
    o.value = c.id; if (c.id === CUR_CLASS_ID) o.selected = true; sel.appendChild(o);
  });
  updateCodeDisplay();
}
function updateCodeDisplay() {
  const c = MY_CLASSES.find(x => x.id === CUR_CLASS_ID);
  $("#codeDisplay").classList.toggle("hidden", !c);
  if (c) $("#codeBig").textContent = c.access_code;
}
function onClassChanged() {
  CUR_CLASS_ID = $("#classSelect").value; localStorage.setItem("lb_class_id", CUR_CLASS_ID);
  updateCodeDisplay(); renderDashboard(); loadPending();
}
async function createClassSubmit() {
  const name = $("#newClassName").value.trim(), grade = $("#newClassGrade").value, err = $("#newClassErr");
  err.classList.add("hidden");
  if (!name || !grade) { err.textContent = t("err_class_fields"); err.classList.remove("hidden"); return; }
  let j;
  try {
    j = await (await fetch("/api/teacher/create_class", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), name, grade }) })).json();
  } catch (e) { err.textContent = t("trouble"); err.classList.remove("hidden"); return; }
  if (!j.ok) { err.textContent = t("trouble"); err.classList.remove("hidden"); return; }
  $("#newClassName").value = ""; $("#newClassGrade").value = ""; $("#newClassForm").classList.add("hidden");
  CUR_CLASS_ID = j.class.id;
  await loadMyClasses();
  renderDashboard(); loadPending();
}
async function regenerateCode() {
  if (!CUR_CLASS_ID || !confirm(t("regenerate_confirm"))) return;
  let j;
  try {
    j = await (await fetch("/api/teacher/regenerate_code", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID }) })).json();
  } catch (e) { return; }
  if (j.ok) { const c = MY_CLASSES.find(x => x.id === CUR_CLASS_ID); if (c) c.access_code = j.access_code; updateCodeDisplay(); }
}
async function loadPending() {
  const area = $("#pendingArea");
  if (!CUR_CLASS_ID) { area.innerHTML = ""; return; }
  let j;
  try {
    j = await (await fetch("/api/teacher/pending?session=" + encodeURIComponent(getSession()) +
      "&class_id=" + encodeURIComponent(CUR_CLASS_ID))).json();
  } catch (e) { return; }
  renderPending((j && j.pending) || []);
}
function renderPending(list) {
  const area = $("#pendingArea"); area.innerHTML = "";
  if (!list.length) { area.appendChild(el("p", "muted-note", t("no_pending"))); return; }
  const grid = el("div", "card-grid");
  list.forEach(p => {
    const card = el("div", "sc pending");
    const head = el("div", "sc-head");
    const av = el("span", "sc-av"); av.style.background = avatarColor(p.username); av.textContent = initials(p.username); head.appendChild(av);
    const nm = el("div", "sc-nm"); nm.appendChild(el("div", "sc-name", p.username));
    nm.appendChild(el("div", "pending-at", t("requested_at") + ": " + (p.requested || "")));
    head.appendChild(nm); card.appendChild(head);
    const foot = el("div", "sc-foot");
    const ap = el("span", "sc-link ok", t("approve_btn")); ap.onclick = () => approvePending(p.username); foot.appendChild(ap);
    const rj = el("span", "sc-link danger", t("reject_btn")); rj.onclick = () => rejectPending(p.username); foot.appendChild(rj);
    card.appendChild(foot);
    grid.appendChild(card);
  });
  area.appendChild(grid);
}
async function approvePending(username) {
  try {
    await fetch("/api/teacher/approve", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID, username }) });
  } catch (e) {}
  loadPending(); renderDashboard(); loadMyClasses();
}
async function rejectPending(username) {
  try {
    await fetch("/api/teacher/reject", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID, username }) });
  } catch (e) {}
  loadPending(); loadMyClasses();
}

// derived from GRADE_ORDER so the two can never drift apart; "" is the no-grade-yet bucket
const GRADE_GROUPS = GRADE_ORDER.concat([""]);
const DAILY_GOAL = 5;   // gold-star goal that fills the progress bar (absolute, not relative)
let _dashData = [], _dashSig = "";
async function renderDashboard(silent) {
  const board = $("#board");
  if (!CUR_CLASS_ID) {
    board.innerHTML = ""; if (!silent) board.appendChild(el("p", "muted-note", t("no_classes_yet")));
    $("#classSummary").innerHTML = ""; $("#rosterArea").innerHTML = ""; return;
  }
  if (!silent) board.innerHTML = "<p class='muted-note'>" + t("loading") + "</p>";
  let res;
  try {
    res = await fetch("/api/teacher/class/" + encodeURIComponent(CUR_CLASS_ID) + "/progress_all?session=" + encodeURIComponent(getSession()));
  } catch (e) { return; }
  if (res.status === 403) { stopDashPoll(); clearIdentity(); show("role"); return; }
  if (res.status !== 200) return;
  const payload = await res.json();
  const data = payload.students || [];
  const sig = JSON.stringify(data.map(s => [s.name, s.grade, (s.today || {}).stars, (s.today || {}).tries, s.last_quiz_passed, s.last_quiz_video, s.last_active])) + JSON.stringify(payload.summary || {});
  if (silent && sig === _dashSig) return;       // nothing changed; avoid rebuild/flicker
  _dashSig = sig; _dashData = data;
  renderClassSummary(payload.summary || {});
  renderClassRoster(data);
  if (DASH_VIEW === "tests" && TESTS_TAB === "results") renderTestsArea();
  board.innerHTML = "";
  if (!data.length) { board.appendChild(el("p", "muted-note", t("dash_no_students"))); return; }
  const maxStars = Math.max(1, ...data.map(s => (s.today && s.today.stars) || 0));
  const groups = {}; GRADE_GROUPS.forEach(g => groups[g] = []);
  data.forEach(s => { groups[GRADE_GROUPS.includes(s.grade) ? s.grade : ""].push(s); });
  GRADE_GROUPS.forEach(g => {
    if (!groups[g].length) return;
    const sec = el("div", "grade-section");
    sec.appendChild(el("h3", "grade-head", gradeLabel(g) + " (" + groups[g].length + ")"));
    const list = el("div", "roster-list");
    groups[g].sort((a, b) => ((b.today && b.today.stars) || 0) - ((a.today && a.today.stars) || 0));
    groups[g].forEach(s => list.appendChild(studentRow(s, maxStars)));
    sec.appendChild(list); board.appendChild(sec);
  });
}
function studentRow(s, maxStars) {
  const name = s.name || s.student || "?", today = s.today || {}, stars = today.stars || 0;
  const stuckVid = (s.last_quiz_passed === false) ? s.last_quiz_video : "";
  const tryNum = stuckVid ? ((today.tries || {})[stuckVid] || 0) + 1 : 0;
  const row = el("div", "sc-row" + (stuckVid && tryNum >= 3 ? " stuck" : ""));
  const av = el("span", "sc-av"); av.style.background = avatarColor(name); av.textContent = initials(name); row.appendChild(av);
  const nm = el("div", "sc-nm"); nm.appendChild(el("div", "sc-name", name));
  const gsel = el("select", "sc-grade");
  GRADE_GROUPS.forEach(val => {
    const o = el("option", null, gradeLabel(val)); o.value = val; if ((s.grade || "") === val) o.selected = true; gsel.appendChild(o);
  });
  gsel.onchange = () => setGrade(name, gsel.value);
  nm.appendChild(gsel); row.appendChild(nm);
  const mid = el("div", "sc-mid");
  if (stuckVid) mid.appendChild(el("span", "sc-retry" + (tryNum >= 3 ? " red" : ""), "Try #" + tryNum));
  if (stuckVid) {
    const lt = (CATALOG.find(v => v.id === stuckVid) || {}).title || stuckVid;
    mid.appendChild(el("div", "sc-stuckon", "Stuck on: " + lt));
  }
  if (s.mode) {
    const reading = s.mode === "reading";
    const m = el("div", "sc-mode " + (reading ? "reading" : "math"));
    let label = reading ? "Reading Mode" : "Math Mode";
    if (reading && s.current_book && s.current_book.title) label += " · " + s.current_book.title;
    m.textContent = label;
    mid.appendChild(m);
  }
  const prog = el("div", "sc-prog");
  const bar = el("div", "sc-bar"); const fill = el("div", "sc-fill");
  fill.style.transform = "scaleX(" + Math.min(1, stars / DAILY_GOAL) + ")";
  bar.appendChild(fill); prog.appendChild(bar);
  prog.appendChild(el("div", "sc-stars", "★ " + stars + " / " + DAILY_GOAL + " today"));
  mid.appendChild(prog);
  row.appendChild(mid);
  const foot = el("div", "sc-foot");
  const reset = el("span", "sc-link", "reset"); reset.onclick = () => resetPassword(name); foot.appendChild(reset);
  const rm = el("span", "sc-link danger", "remove"); rm.onclick = () => removeStudent(name); foot.appendChild(rm);
  row.appendChild(foot);
  return row;
}
function renderClassSummary(sum) {
  const box = $("#classSummary"); box.innerHTML = "";

  const act = el("div", "cs-active stat-card dark");
  act.appendChild(el("div", "cs-num", String(sum.active || 0)));
  act.appendChild(el("div", "cs-lbl", t("dash_students_active_now")));
  box.appendChild(act);

  const topCard = el("div", "cs-card stat-card cream");
  topCard.appendChild(el("div", "cs-h", t("dash_top_passed_today")));
  const tp = sum.top_passed || [];
  if (!tp.length) topCard.appendChild(el("div", "cs-empty", t("dash_no_passes_today")));
  else tp.forEach((x, n) => {
    const row = el("div", "cs-row" + (n === 0 ? " top1" : ""));
    row.appendChild(el("span", "cs-rank", "#" + (n + 1)));
    row.appendChild(el("span", "cs-nm", x.title));
    row.appendChild(el("span", "cs-cnt ok", "✓" + x.count));
    topCard.appendChild(row);
  });
  box.appendChild(topCard);

  const failCard = el("div", "cs-card stat-card default");
  failCard.appendChild(el("div", "cs-h", t("dash_most_failed_today")));
  if (sum.most_failed) {
    const row = el("div", "cs-row");
    row.appendChild(el("span", "cs-nm", sum.most_failed.title));
    row.appendChild(el("span", "cs-cnt bad", "✗" + sum.most_failed.count));
    failCard.appendChild(row);
  } else failCard.appendChild(el("div", "cs-empty", t("dash_no_fails_today")));
  box.appendChild(failCard);
}
// Lightweight roster summary for the Class Overview view - reuses the same data
// renderDashboard() already fetched (no new request), unlike the detailed #board
// table (studentRow) which keeps its grade-edit/reset/remove management controls.
function renderClassRoster(data) {
  const area = $("#rosterArea"), countEl = $("#rosterCount");
  area.innerHTML = "";
  if (countEl) countEl.textContent = String(data.length);
  if (!data.length) { area.appendChild(el("p", "muted-note", t("dash_no_students"))); return; }
  data.forEach(s => {
    const name = s.name || s.student || "?", stars = (s.today && s.today.stars) || 0;
    const row = el("div", "ov-roster-row");
    const av = el("span", "sc-av"); av.style.background = avatarColor(name); av.textContent = initials(name);
    row.appendChild(av);
    row.appendChild(el("div", "ov-roster-name", name));
    row.appendChild(el("div", "ov-roster-grade", gradeLabel(s.grade)));
    const bar = el("div", "ov-roster-bar"); const fill = el("div", "ov-roster-bar-fill");
    fill.style.width = (Math.min(1, stars / DAILY_GOAL) * 100) + "%";
    bar.appendChild(fill); row.appendChild(bar);
    const btn = el("button", "btn ghost sm", t("view_progress_btn"));
    btn.onclick = () => showDashView("progress");
    row.appendChild(btn);
    area.appendChild(row);
  });
}
async function setGrade(name, grade) {
  try {
    await fetch("/api/teacher/set_grade", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID, username: name, grade }) });
  } catch (e) {}
  renderDashboard();
}

/* ---------- teacher: custom test builder + grading (embedded in the dashboard) ---------- */
function fmtDue(due) { return (due || "").replace("T", " "); }
/* EDIT_TEST is null when the builder is creating, or the full test object when editing
   one that already exists. The same form serves both - only the heading, the warning
   banner, and where Save posts differ. */
let EDIT_TEST = null;
function startEditTest(test, subCount) {
  EDIT_TEST = test; EDIT_TEST._subs = subCount || 0;
  showDashView("tests"); showTestsTab("create");
}
function renderTestBuilder() {
  const b = $("#testBuilder"); b.innerHTML = "";
  b.classList.remove("hidden");
  const ed = EDIT_TEST;
  b.appendChild(el("h3", "add-title", ed ? t("edit_test") : t("build_test")));
  // non-blocking warning, not a modal gate: the teacher is allowed to proceed, they just
  // shouldn't be surprised afterwards
  if (ed && ed._subs) {
    const warn = el("div", "tb-warn");
    warn.appendChild(el("div", "tb-warn-t", t("edit_heads_up")));
    warn.appendChild(el("div", "tb-warn-m", t("edit_warn_subs").replace("{n}", ed._subs)));
    b.appendChild(warn);
  }
  const title = el("input", "field tb-title"); title.id = "tbTitle"; title.placeholder = t("test_title_ph");
  if (ed) title.value = ed.title || "";
  b.appendChild(title);
  b.appendChild(Object.assign(el("div"), { id: "tbQs" }));
  const qb = el("div", "tb-btns");
  const mc = el("button", "btn secondary", t("add_mc")); mc.type = "button"; mc.onclick = () => addBuilderQuestion("mc");
  const tx = el("button", "btn secondary", t("add_text")); tx.type = "button"; tx.onclick = () => addBuilderQuestion("text");
  qb.appendChild(mc); qb.appendChild(tx); b.appendChild(qb);
  // assignment: due date/time + grades AND/OR individuals, all in one bounded card,
  // visually separate from the question cards above (per the dashboard mockup)
  const asg = el("div", "card tb-block");
  asg.appendChild(el("div", "add-title", t("assignment_title")));
  const due = el("div");
  due.appendChild(el("div", "tb-h", t("due_label")));
  const drow = el("div", "tb-due-row");
  const dd = el("input", "field"); dd.id = "tbDate"; dd.type = "date";
  const tt = el("input", "field"); tt.id = "tbTime"; tt.type = "time";
  drow.appendChild(dd); drow.appendChild(tt); due.appendChild(drow); asg.appendChild(due);
  asg.appendChild(el("div", "tb-h", t("assign_grades")));
  const grow = el("div", "tb-checks");
  // was a hardcoded K-3 list, so a teacher could not assign a test to grades 4-8 even
  // though students and lessons exist there. Derived from GRADE_ORDER now, with the
  // already-translated grade_* labels instead of hardcoded English.
  GRADE_ORDER.forEach(v => {
    const l = el("label", "tb-chk"); const c = document.createElement("input");
    c.type = "checkbox"; c.className = "tbGrade"; c.value = v;
    l.appendChild(c); l.appendChild(el("span", null, gradeLabel(v))); grow.appendChild(l);
  });
  asg.appendChild(grow);
  asg.appendChild(el("div", "tb-h", t("assign_students")));
  const srow = el("div", "tb-checks");
  const names = (_dashData || []).map(s => s.name || s.student).filter(Boolean);
  if (names.length) names.forEach(n => {
    const l = el("label", "tb-chk"); const c = document.createElement("input");
    c.type = "checkbox"; c.className = "tbStudent"; c.value = n;
    l.appendChild(c); l.appendChild(el("span", null, n)); srow.appendChild(l);
  });
  else srow.appendChild(el("span", "muted-note", t("tb_no_students")));
  asg.appendChild(srow); b.appendChild(asg);
  const actions = el("div", "tb-actions");
  const create = el("button", "btn primary tb-create", ed ? t("save_changes") : t("create_test_btn"));
  create.onclick = collectAndCreateTest;
  actions.appendChild(create);
  if (ed) {
    const cancel = el("button", "btn ghost", t("cancel_edit"));
    cancel.onclick = () => { const id = ed.id; EDIT_TEST = null; renderTestBuilder();
      showTestsTab("results"); openTestDetail(id); };
    actions.appendChild(cancel);
  }
  b.appendChild(actions);
  b.appendChild(Object.assign(el("span", "tb-msg"), { id: "tbMsg" }));
  // pre-fill: rebuild each stored question in the same widgets the creation flow uses,
  // so editing and creating can never drift apart
  if (ed && (ed.questions || []).length) {
    (ed.questions || []).forEach(q => {
      addBuilderQuestion(q.type === "mc" ? "mc" : "text");
      const w = $("#tbQs").lastChild;
      w.querySelector(".tbQText").value = q.q || "";
      if (q.type === "mc") {
        const box = w.querySelector(".tbChoices");
        box.innerHTML = "";
        (q.choices || []).forEach(() => addBuilderChoice(box));
        [...box.querySelectorAll(".tb-choice")].forEach((row, i) => {
          row.querySelector(".tbCText").value = q.choices[i] || "";
          if (i === q.answer) row.querySelector("input[type=radio]").checked = true;
        });
      }
    });
    const cur = (ed.due || "").split("T");
    if (cur[0]) $("#tbDate").value = cur[0];
    if (cur[1]) $("#tbTime").value = cur[1];
    const gs = (ed.assign && ed.assign.grades) || [];
    document.querySelectorAll(".tbGrade").forEach(c => { c.checked = gs.includes(c.value); });
    const ss = (ed.assign && ed.assign.students) || [];
    document.querySelectorAll(".tbStudent").forEach(c => { c.checked = ss.includes(c.value); });
  } else {
    addBuilderQuestion("mc");
  }
}
function addBuilderQuestion(type) {
  const wrap = el("div", "tb-q"); wrap.dataset.type = type;
  wrap.dataset.qid = Math.random().toString(36).slice(2);
  wrap.appendChild(el("div", "tb-qtag", type === "mc" ? t("add_mc_tag") : t("add_text_tag")));
  const q = el("input", "field tbQText"); q.placeholder = t("question_ph"); wrap.appendChild(q);
  if (type === "mc") {
    const ch = el("div", "tbChoices"); wrap.appendChild(ch);
    const addC = el("button", "btn ghost sm", t("add_choice")); addC.type = "button";
    addC.onclick = () => addBuilderChoice(ch); wrap.appendChild(addC);
    wrap.appendChild(el("div", "tb-hint", t("tick_correct")));
  } else {
    wrap.appendChild(el("div", "tb-hint", t("free_response_hint")));
  }
  const del = el("button", "btn ghost tb-small danger", t("del_q")); del.type = "button";
  del.onclick = () => wrap.remove(); wrap.appendChild(del);
  $("#tbQs").appendChild(wrap);
  if (type === "mc") { const c = wrap.querySelector(".tbChoices"); addBuilderChoice(c); addBuilderChoice(c); }
}
function addBuilderChoice(container) {
  const qwrap = container.closest(".tb-q");
  const gname = "c_" + qwrap.dataset.qid;
  const idx = container.querySelectorAll(".tb-choice").length;
  const row = el("div", "tb-choice");
  const r = document.createElement("input"); r.type = "radio"; r.name = gname;
  const lab = el("label", "tb-correct"); lab.appendChild(r); lab.appendChild(el("span", null, t("correct_lbl")));
  const ci = el("input", "field tbCText"); ci.placeholder = t("choice_ph") + " " + (idx + 1);
  row.appendChild(lab); row.appendChild(ci); container.appendChild(row);
}
async function collectAndCreateTest() {
  const title = $("#tbTitle").value.trim();
  const questions = []; let err = "";
  document.querySelectorAll("#tbQs .tb-q").forEach(w => {
    const qt = w.querySelector(".tbQText").value.trim(); if (!qt) return;
    if (w.dataset.type === "mc") {
      const rows = [...w.querySelectorAll(".tb-choice")];
      const choices = rows.map(r => r.querySelector(".tbCText").value.trim()).filter(Boolean);
      const answer = rows.findIndex(r => r.querySelector("input[type=radio]").checked);
      if (choices.length < 2) { err = t("err_choices"); return; }
      if (answer < 0) { err = t("err_correct"); return; }
      questions.push({ type: "mc", q: qt, choices, answer });
    } else questions.push({ type: "text", q: qt });
  });
  const grades = [...document.querySelectorAll(".tbGrade:checked")].map(c => c.value);
  const students = [...document.querySelectorAll(".tbStudent:checked")].map(c => c.value);
  const date = $("#tbDate").value, time = $("#tbTime").value;
  const due = date ? (date + (time ? ("T" + time) : "")) : "";
  const msg = $("#tbMsg"); const fail = m => { msg.textContent = m; msg.style.color = "#C0392B"; };
  if (!title) return fail(t("err_title"));
  if (err) return fail(err);                 // surface the real per-question problem first
  if (!questions.length) return fail(t("err_noq"));
  if (!grades.length && !students.length) return fail(t("err_assign"));
  const editing = EDIT_TEST;
  const body = { session: getSession(), title, questions, grades, students, due };
  if (editing) body.id = editing.id;
  const r = await fetch(editing ? "/api/teacher/update_test" : "/api/teacher/create_test",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) return fail(j.error || t("err_create"));
  if (editing) {
    // land back on the test just edited, where the "edited after submission" flags on
    // any existing answers are immediately visible
    EDIT_TEST = null;
    renderTestBuilder();
    showTestsTab("results");
    return openTestDetail(editing.id);
  }
  $("#testBuilder").classList.add("hidden");
  renderTestsArea();
}
/* ---------- teacher notifications ----------
   Events live server-side (see notifications.json) so they survive sign-out; this only
   renders them and reports read/dismiss back. Messages are stored as a translation key
   plus params rather than a finished sentence, so switching dashboard language
   re-renders history in the new language instead of freezing it in whatever language
   was active when the event happened. */
let NOTIFS = [], NOTIF_UNREAD = 0, _notifPoll = null;

function notifMsg(e) {
  let s = t(e.key || "");
  Object.keys(e.params || {}).forEach(k => {
    s = s.split("{" + k + "}").join(e.params[k] == null ? "" : String(e.params[k]));
  });
  return s;
}
/* "2026-08-01 09:14" -> a coarse relative label. Deliberately coarse: a classroom feed
   doesn't need second-level precision, and the exact stamp is in the title attribute. */
function relTime(stamp) {
  const s = String(stamp || "").replace(" ", "T");
  const then = new Date(s), now = new Date();
  if (isNaN(then)) return stamp || "";
  const mins = Math.floor((now - then) / 60000);
  if (mins < 1) return t("just_now");
  if (mins < 60) return t("mins_ago").replace("{n}", mins);
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t("hours_ago").replace("{n}", hrs);
  return t("days_ago").replace("{n}", Math.floor(hrs / 24));
}
async function loadNotifications() {
  if (ME.role !== "teacher" || !getSession()) return;
  let j;
  try {
    j = await (await fetch("/api/teacher/notifications?session=" +
      encodeURIComponent(getSession()))).json();
  } catch (e) { return; }
  if (!j || !j.notifications) return;
  const hadUnread = NOTIF_UNREAD;
  NOTIFS = j.notifications; NOTIF_UNREAD = j.unread || 0;
  renderNotifications();
  // a brand-new submission changes the results the teacher is looking at, so refresh
  // the open Tests view too - this is what makes the class average recalculate without
  // anyone pressing refresh
  if (NOTIF_UNREAD > hadUnread && CURRENT_SCREEN === "dashboard" &&
      DASH_VIEW === "tests" && TESTS_TAB === "results") renderTestsArea();
}
function renderNotifications() {
  const wrap = $("#notifWrap"); if (!wrap) return;
  const count = $("#notifCount");
  count.textContent = NOTIF_UNREAD > 9 ? "9+" : String(NOTIF_UNREAD);
  count.classList.toggle("hidden", !NOTIF_UNREAD);
  $("#notifBell").classList.toggle("has-unread", !!NOTIF_UNREAD);
  const list = $("#notifList"); list.innerHTML = "";
  if (!NOTIFS.length) {
    list.appendChild(el("div", "notif-empty", t("no_notifications")));
    return;
  }
  NOTIFS.forEach(e => {
    const row = el("div", "notif-item" + (e.unread ? " unread" : ""));
    row.appendChild(el("span", "notif-dot"));
    const body = el("div", "notif-body");
    body.appendChild(el("div", "notif-msg", notifMsg(e)));
    const when = el("div", "notif-when", relTime(e.at));
    when.title = e.at || "";
    body.appendChild(when);
    row.appendChild(body);
    const x = el("button", "notif-x", "✕");
    x.setAttribute("aria-label", t("notif_dismiss"));
    x.onclick = ev => { ev.stopPropagation(); markNotifs({ dismiss: [e.id] }); };
    row.appendChild(x);
    // clicking the row marks it read and, when the event points at a test, jumps there
    row.onclick = () => {
      if (e.unread) markNotifs({ ids: [e.id] });
      if (e.test_id) {
        closeNotifPanel();
        showDashView("tests"); showTestsTab("results"); openTestDetail(e.test_id);
      }
    };
    list.appendChild(row);
  });
}
async function markNotifs(payload) {
  try {
    const j = await (await fetch("/api/teacher/notifications_read", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ session: getSession() }, payload))
    })).json();
    if (j && j.notifications) { NOTIFS = j.notifications; NOTIF_UNREAD = j.unread || 0; renderNotifications(); }
  } catch (e) {}
}
function openNotifPanel() {
  $("#notifPanel").classList.remove("hidden");
  $("#notifBell").setAttribute("aria-expanded", "true");
}
function closeNotifPanel() {
  $("#notifPanel").classList.add("hidden");
  $("#notifBell").setAttribute("aria-expanded", "false");
}
function toggleNotifPanel() {
  $("#notifPanel").classList.contains("hidden") ? openNotifPanel() : closeNotifPanel();
}
/* Poll while a teacher screen is open. 25s (not the dashboard's 8s) because this box is
   CPU-only and shares itself with llama.cpp; pausing on a hidden tab keeps a forgotten
   background tab from polling all day for nothing. */
function startNotifPoll() {
  if (_notifPoll || ME.role !== "teacher") return;
  loadNotifications();
  _notifPoll = setInterval(() => {
    if (!document.hidden) loadNotifications();
  }, 25000);
}
function stopNotifPoll() { if (_notifPoll) { clearInterval(_notifPoll); _notifPoll = null; } }

/* ---------- extend due date ---------- */
let EXT_MODE = "whole", EXT_TEST = null;
function openExtendModal() {
  if (!TD || !TD.test) return;
  EXT_TEST = TD.test; EXT_MODE = "whole";
  $("#extendErr").classList.add("hidden");
  renderExtendModal();
  $("#extendOverlay").classList.remove("hidden");
}
function closeExtendModal() { $("#extendOverlay").classList.add("hidden"); }
function renderExtendModal() {
  const body = $("#extendBody"); body.innerHTML = "";
  const modes = el("div", "ext-modes");
  [["whole", "extend_whole"], ["students", "extend_selected"]].forEach(([m, k]) => {
    const b = el("button", "btn " + (EXT_MODE === m ? "secondary" : "ghost") + " sm", t(k));
    b.type = "button";
    b.onclick = () => { EXT_MODE = m; renderExtendModal(); };
    modes.appendChild(b);
  });
  body.appendChild(modes);
  body.appendChild(el("div", "ext-current", EXT_TEST.due
    ? t("extend_current").replace("{due}", fmtDue(EXT_TEST.due)) : t("extend_no_due")));
  body.appendChild(el("label", "lbl", t("extend_new_due")));
  const row = el("div", "tb-due-row");
  const d = el("input", "field"); d.id = "extDate"; d.type = "date";
  const tm = el("input", "field"); tm.id = "extTime"; tm.type = "time";
  const cur = (EXT_TEST.due || "").split("T");
  if (cur[0]) d.value = cur[0];
  if (cur[1]) tm.value = cur[1];
  row.appendChild(d); row.appendChild(tm); body.appendChild(row);
  if (EXT_MODE === "students") {
    body.appendChild(el("label", "lbl", t("extend_pick_students")));
    const box = el("div", "ext-students");
    const overrides = EXT_TEST.student_due || {};
    (TD.stats.roster || []).forEach(n => {
      const l = el("label", "tb-chk");
      const c = document.createElement("input");
      c.type = "checkbox"; c.className = "extStudent"; c.value = n;
      if (overrides[n]) c.checked = true;
      l.appendChild(c); l.appendChild(el("span", null, n));
      if (overrides[n]) l.appendChild(el("span", "badge gold ext-chk-badge", t("extended_badge")));
      box.appendChild(l);
    });
    body.appendChild(box);
    body.appendChild(el("div", "ext-hint", t("extend_clear_hint")));
  }
}
async function saveExtend() {
  const err = $("#extendErr"); err.classList.add("hidden");
  const date = $("#extDate").value, time = $("#extTime").value;
  const due = date ? (date + (time ? "T" + time : "")) : "";
  const payload = { session: getSession(), id: EXT_TEST.id, due };
  if (EXT_MODE === "students") {
    const picked = [...document.querySelectorAll(".extStudent:checked")].map(c => c.value);
    // unticked students are sent too, with the override cleared, so this dialog can undo
    // an extension as well as grant one
    const all = TD.stats.roster || [];
    if (!picked.length && !all.some(n => (EXT_TEST.student_due || {})[n])) {
      err.textContent = t("extend_err_students"); err.classList.remove("hidden"); return;
    }
    if (picked.length && !due) { err.textContent = t("extend_err_date"); err.classList.remove("hidden"); return; }
    const cleared = all.filter(n => !picked.includes(n) && (EXT_TEST.student_due || {})[n]);
    if (picked.length) await postExtend(Object.assign({}, payload, { students: picked }));
    if (cleared.length) await postExtend(Object.assign({}, payload, { students: cleared, due: "" }));
  } else {
    if (!due) { err.textContent = t("extend_err_date"); err.classList.remove("hidden"); return; }
    await postExtend(payload);
  }
  closeExtendModal();
  renderTestDetail();
}
async function postExtend(payload) {
  try {
    await fetch("/api/teacher/extend_due", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } catch (e) {}
}

/* ---------- tests: list view -> per-test detail view ----------
   The old layout expanded every test's answers inline in one flat column, which stopped
   being readable past a couple of tests. Now the list is one scannable row per test and
   everything else - class average, per-question breakdown, per-student answers, the
   sort/filter controls - lives in a detail view fetched on demand from
   /api/teacher/test/<id>. Readiness and the average itself are decided SERVER-side (see
   test_stats in server.py); this code only renders what it is told, so changing the
   device clock can't reveal an average that isn't finalised yet. */
let TEST_DETAIL_ID = null, TD = null;
let TD_SORT = "newest", TD_SHOW = "all", TD_STUDENT = "";

async function renderTestsArea() {
  return TEST_DETAIL_ID ? renderTestDetail() : renderTestList();
}
function openTestDetail(id) {
  TEST_DETAIL_ID = id; TD = null;
  TD_SORT = "newest"; TD_SHOW = "all"; TD_STUDENT = "";
  renderTestsArea();
}
function closeTestDetail() { TEST_DETAIL_ID = null; TD = null; renderTestsArea(); }

const GRADE_TONE = { K: "gold", "1": "info", "2": "success", "3": "navy" };
function testStatus(x) {
  if (x.total && x.sub_count >= x.total) return { k: "status_complete", tone: "success" };
  if (x.due_passed) return { k: "status_past_due", tone: "warning" };
  return { k: "test_status_open", tone: "info" };
}
function assignBadges(assign) {
  const gs = (assign && assign.grades) || (assign && assign.grade ? [assign.grade] : []);
  return gs.map(g => el("span", "badge " + (GRADE_TONE[g] || "neutral"), gradeLabel(g)));
}
const ICON_CHECK = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 12.5l2.5 2.5L16 9.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const ICON_X = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 9l6 6M15 9l-6 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
const ICON_DOT = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8.5 12h7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
function svgSpan(cls, markup) { const s = el("span", cls); s.innerHTML = markup; return s; }

async function renderTestList() {
  const area = $("#testsArea");
  let tests = [];
  try {
    tests = ((await (await fetch("/api/teacher/tests?session=" +
      encodeURIComponent(getSession()))).json()).tests) || [];
  } catch (e) { return; }
  area.innerHTML = "";
  if (!tests.length) { area.appendChild(el("p", "muted-note", t("no_tests_list"))); return; }
  const head = el("div", "tl-head");
  [["col_title", ""], ["col_status", ""], ["col_due", ""], ["col_submissions", "num"], ["", ""]]
    .forEach(([k, c]) => head.appendChild(el("span", c, k ? t(k) : "")));
  area.appendChild(head);
  const list = el("div", "tl-list");
  tests.forEach(x => {
    const row = el("div", "card tl-row");
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    const nameCell = el("div", "tl-name");
    nameCell.appendChild(el("div", "tl-title", x.title));
    const badges = el("div", "tl-badges");
    assignBadges(x.assign).forEach(b => badges.appendChild(b));
    const named = ((x.assign && x.assign.students) || []).length;
    if (named) badges.appendChild(el("span", "badge neutral",
      t("students_count_badge").replace("{n}", named)));
    nameCell.appendChild(badges);
    row.appendChild(nameCell);
    const st = testStatus(x);
    row.appendChild(el("span", "badge " + st.tone, t(st.k)));
    row.appendChild(el("span", "tl-due", x.due ? fmtDue(x.due) : t("no_due_date")));
    row.appendChild(el("span", "tl-count", x.sub_count + "/" + (x.total || 0)));
    row.appendChild(svgSpan("tl-chev",
      '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'));
    const go = () => openTestDetail(x.id);
    row.onclick = go;
    row.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
    list.appendChild(row);
  });
  area.appendChild(list);
}

async function renderTestDetail() {
  const area = $("#testsArea");
  try {
    TD = await (await fetch("/api/teacher/test/" + encodeURIComponent(TEST_DETAIL_ID) +
      "?session=" + encodeURIComponent(getSession()))).json();
  } catch (e) { return; }
  if (!TD || !TD.test) return closeTestDetail();
  const test = TD.test, stats = TD.stats;
  area.innerHTML = "";

  const back = el("button", "td-back");
  back.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  back.appendChild(el("span", null, t("all_tests_back")));
  back.onclick = closeTestDetail;
  area.appendChild(back);

  const head = el("div", "td-head");
  const titleRow = el("div", "td-title-row");
  titleRow.appendChild(el("h2", "td-title", test.title));
  const st = testStatus({ total: stats.total, sub_count: stats.sub_count, due_passed: stats.due_passed });
  titleRow.appendChild(el("span", "badge " + st.tone, t(st.k)));
  assignBadges(test.assign).forEach(b => titleRow.appendChild(b));
  head.appendChild(titleRow);
  head.appendChild(el("div", "td-meta",
    (test.due ? t("due_word") + " " + fmtDue(test.due) + " · " : "") +
    stats.sub_count + "/" + stats.total + " " + t("submitted_word") + " · " +
    (test.questions || []).length + " " + t("questions_word")));
  const acts = el("div", "td-actions");
  const ext = el("button", "btn ghost sm");
  ext.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M3 9.5h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>';
  ext.appendChild(el("span", null, t("extend_due")));
  ext.onclick = openExtendModal;
  acts.appendChild(ext);
  const edit = el("button", "btn ghost sm");
  edit.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M4 20l1-4.5L15.5 5 19 8.5 8.5 19 4 20z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M13.5 6.5L17.5 10.5" stroke="currentColor" stroke-width="1.9"/></svg>';
  edit.appendChild(el("span", null, t("edit_test")));
  edit.onclick = () => startEditTest(test, stats.sub_count);
  acts.appendChild(edit);
  const del = el("button", "btn ghost sm danger", t("del_test"));
  del.onclick = () => deleteTest(test.id);
  acts.appendChild(del);
  head.appendChild(acts);
  area.appendChild(head);

  area.appendChild(renderAverageBanner(test, stats));
  area.appendChild(renderDetailFilters(stats));

  const rows = filterSortRows(TD.rows);
  if (!rows.length) { area.appendChild(el("p", "muted-note", t("no_match_filters"))); return; }
  rows.forEach(r => area.appendChild(renderSubmissionRow(r)));
}

function renderAverageBanner(test, stats) {
  // Not-ready is a first-class state, not a blank space: the teacher should be able to
  // tell "nobody has finished yet" apart from "this test has no average".
  if (!stats.ready) {
    const c = el("div", "card td-avg-wait");
    c.appendChild(svgSpan("td-avg-clock",
      '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5.2l3.2 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'));
    const txt = el("div");
    txt.appendChild(el("div", "td-avg-wait-t", t("avg_not_ready")));
    txt.appendChild(el("div", "td-avg-wait-s", test.due
      ? t("avg_awaiting").replace("{due}", fmtDue(test.due)).replace("{n}", stats.total)
      : t("avg_awaiting_nodue").replace("{n}", stats.total)));
    c.appendChild(txt);
    return c;
  }
  const c = el("div", "card td-avg");
  const statBox = el("div", "td-avg-stat");
  statBox.appendChild(el("div", "td-avg-num", (stats.average == null ? "—" : stats.average + "%")));
  statBox.appendChild(el("div", "td-avg-lbl", t("class_average")));
  c.appendChild(statBox);
  const bars = el("div", "td-avg-bars");
  (stats.per_question || []).forEach((q, i) => {
    const rowEl = el("div", "td-qbar");
    rowEl.appendChild(el("div", "td-qbar-lbl", (i + 1) + ". " + q.q));
    if (q.pct == null) {
      rowEl.appendChild(el("div", "td-qbar-none", t("avg_ungraded")));
    } else {
      const track = el("div", "td-qbar-track");
      const fill = el("div", "td-qbar-fill"); fill.style.width = q.pct + "%";
      track.appendChild(fill); rowEl.appendChild(track);
      rowEl.appendChild(el("div", "td-qbar-pct", q.pct + t("avg_pct_correct")));
    }
    bars.appendChild(rowEl);
  });
  c.appendChild(bars);
  return c;
}

function renderDetailFilters(stats) {
  const bar = el("div", "td-filters");
  const mk = (labelKey, value, opts, onChange) => {
    const wrap = el("label", "td-filter");
    wrap.appendChild(el("span", "td-filter-lbl", t(labelKey)));
    const sel = el("select", "field select-pill");
    opts.forEach(([v, lab]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = lab; if (v === value) o.selected = true;
      sel.appendChild(o);
    });
    sel.onchange = () => { onChange(sel.value); renderTestDetail(); };
    wrap.appendChild(sel);
    return wrap;
  };
  bar.appendChild(mk("sort_by", TD_SORT, [
    ["newest", t("sort_newest")], ["oldest", t("sort_oldest")], ["name", t("sort_name")]
  ], v => TD_SORT = v));
  bar.appendChild(mk("filter_show", TD_SHOW, [
    ["all", t("filter_all")], ["incorrect", t("filter_incorrect")],
    ["submitted", t("filter_submitted")], ["pending", t("filter_pending")]
  ], v => TD_SHOW = v));
  bar.appendChild(mk("filter_student", TD_STUDENT,
    [["", t("filter_all_students")]].concat((stats.roster || []).map(n => [n, n])),
    v => TD_STUDENT = v));
  return bar;
}

function filterSortRows(rows) {
  let out = (rows || []).slice();
  if (TD_STUDENT) out = out.filter(r => r.student === TD_STUDENT);
  if (TD_SHOW === "submitted") out = out.filter(r => r.submitted);
  else if (TD_SHOW === "pending") out = out.filter(r => !r.submitted);
  else if (TD_SHOW === "incorrect")
    out = out.filter(r => r.submitted && (r.answers || []).some(a => a.correct === false));
  if (TD_SORT === "name") out.sort((a, b) => a.student.localeCompare(b.student));
  else {
    // unsubmitted rows have no timestamp - keep them last in both time orders rather
    // than letting "" sort to one end and bury the real submissions
    out.sort((a, b) => {
      if (!a.at && !b.at) return a.student.localeCompare(b.student);
      if (!a.at) return 1;
      if (!b.at) return -1;
      return TD_SORT === "oldest" ? a.at.localeCompare(b.at) : b.at.localeCompare(a.at);
    });
  }
  return out;
}

function renderSubmissionRow(r) {
  const card = el("div", "card td-sub" + (r.submitted ? "" : " flat"));
  const head = el("div", "td-sub-head");
  const av = el("span", "sc-av td-av", (r.student || "?")[0].toUpperCase());
  av.style.background = avatarColor(r.student || "?");
  head.appendChild(av);
  const who = el("div", "td-sub-who");
  who.appendChild(el("div", "td-sub-name", r.student));
  let meta = r.submitted ? t("submitted_at") + " " + fmtDue(r.at) : t("not_submitted");
  if (r.extended) meta += " · " + t("extended_to") + " " + fmtDue(r.due);
  who.appendChild(el("div", "td-sub-meta", meta));
  head.appendChild(who);
  if (r.extended) head.appendChild(el("span", "badge gold", t("extended_badge")));
  card.appendChild(head);

  if (!r.submitted) return card;
  const showOnlyBad = TD_SHOW === "incorrect";
  (r.answers || []).forEach((a, i) => {
    if (showOnlyBad && a.correct !== false) return;
    const tone = a.correct === true ? "ok" : a.correct === false ? "bad" : "na";
    const qrow = el("div", "td-ans " + tone);
    qrow.appendChild(svgSpan("td-ans-icon",
      a.correct === true ? ICON_CHECK : a.correct === false ? ICON_X : ICON_DOT));
    const body = el("div", "td-ans-body");
    body.appendChild(el("div", "td-ans-q", (i + 1) + ". " + a.q));
    const ansLine = el("div", "td-ans-line");
    ansLine.appendChild(el("span", "td-ans-lbl", t("answered_lbl") + " "));
    ansLine.appendChild(el("b", null,
      (a.answer_text === undefined || a.answer_text === null || a.answer_text === "")
        ? t("no_answer_word") : String(a.answer_text)));
    if (a.correct === false && a.correct_text) {
      ansLine.appendChild(el("span", "td-ans-corr",
        " — " + t("correct_answer_lbl") + " "));
      ansLine.appendChild(el("b", "td-ans-corr", String(a.correct_text)));
    }
    body.appendChild(ansLine);
    if (a.edited) body.appendChild(renderEditedNote(a));
    qrow.appendChild(body);
    card.appendChild(qrow);
  });
  return card;
}

/* A question edited after this student answered it. The snapshot stored at submission
   time (server: submit_test -> "asked") is what makes this visible instead of silently
   regrading an answer against wording the student never saw. */
function renderEditedNote(a) {
  const n = el("div", "td-edited");
  n.appendChild(el("span", "badge warning", t("edited_after_sub")));
  if (a.asked_q) n.appendChild(el("div", "td-edited-was",
    t("student_saw") + " " + '"' + a.asked_q + '"'));
  if (a.was_correct === true) n.appendChild(el("div", "td-edited-was", t("was_correct_then")));
  return n;
}
async function deleteTest(id) {
  if (!confirm(t("confirm_del_test"))) return;
  try {
    await fetch("/api/teacher/delete_test", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), id }) });
  } catch (e) {}
  // deleting the test currently open in the detail view has to fall back to the list,
  // or the next render fetches an id that no longer exists
  if (TEST_DETAIL_ID === id) return closeTestDetail();
  renderTestsArea();
}

/* ---------- past history logs: month calendar (scoped to the selected class) ----------
   One batched fetch per visible month (HIST_CACHE keyed by "year-month") backs every day
   cell and the detail panel - switching months or clicking a day never issues a fresh
   per-day request, and the student filter is applied client-side over that same cache. */
function histMonthName(m) { return t("hist_month_" + m); }
const CHEV_DOWN = '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function pad2(n) { return n < 10 ? "0" + n : "" + n; }
function histKey(y, m, d) { return y + "-" + pad2(m) + "-" + pad2(d); }
let HIST_YEAR = null, HIST_MONTH = null, HIST_SELECTED = null, HIST_FILTER = "";
let HIST_CACHE = {}, HIST_EXPANDED = new Set();
function histUrl(qs) {
  return "/api/teacher/class/" + encodeURIComponent(CUR_CLASS_ID) + "/history?" + qs + "&session=" + encodeURIComponent(getSession());
}
const HIST_WEEKDAY_KEYS = ["hist_sun", "hist_mon", "hist_tue", "hist_wed", "hist_thu", "hist_fri", "hist_sat"];
function renderHistWeekdays() {
  const box = $("#histWeekdays"); box.innerHTML = "";
  HIST_WEEKDAY_KEYS.forEach(k => box.appendChild(el("span", null, t(k))));
}
async function openHistory() {
  show("history");
  const now = new Date();
  HIST_YEAR = now.getFullYear(); HIST_MONTH = now.getMonth() + 1;
  HIST_SELECTED = null; HIST_FILTER = ""; HIST_CACHE = {};
  $("#histSelect").value = ""; $("#histDetail").classList.add("hidden");
  $("#histFilterBanner").classList.add("hidden");
  $("#histGrid").innerHTML = "";
  renderHistWeekdays();
  if (!CUR_CLASS_ID) return;
  await histLoadStudents();
  await histLoadMonth(HIST_YEAR, HIST_MONTH);
  renderHistCalendar();
}
async function histLoadStudents() {
  const sel = $("#histSelect"); sel.innerHTML = "";
  const allOpt = el("option", null, t("hist_all_students")); allOpt.value = ""; sel.appendChild(allOpt);
  let meta;
  try { meta = await (await fetch(histUrl("meta=1"))).json(); } catch (e) { return; }
  (meta.students || []).forEach(n => { const o = el("option", null, n); o.value = n; sel.appendChild(o); });
}
async function histLoadMonth(y, m) {
  const key = y + "-" + m;
  if (HIST_CACHE[key]) return HIST_CACHE[key];
  let data = { days: {} };
  if (CUR_CLASS_ID) {
    try { data = await (await fetch(histUrl("month=" + y + "-" + m))).json(); } catch (e) {}
  }
  HIST_CACHE[key] = data;
  return data;
}
async function histChangeMonth(delta) {
  let m = HIST_MONTH + delta, y = HIST_YEAR;
  if (m < 1) { m = 12; y--; } else if (m > 12) { m = 1; y++; }
  HIST_YEAR = y; HIST_MONTH = m; HIST_SELECTED = null;
  $("#histDetail").classList.add("hidden");
  await histLoadMonth(y, m);
  renderHistCalendar();
}
async function histGoToday() {
  const now = new Date();
  HIST_YEAR = now.getFullYear(); HIST_MONTH = now.getMonth() + 1;
  await histLoadMonth(HIST_YEAR, HIST_MONTH);
  renderHistCalendar();
  histSelectDay(histKey(HIST_YEAR, HIST_MONTH, now.getDate()));
}
function onHistFilterChange() {
  HIST_FILTER = $("#histSelect").value || "";
  const banner = $("#histFilterBanner");
  if (HIST_FILTER) {
    banner.classList.remove("hidden");
    $("#histFilterBannerText").textContent = t("hist_showing_activity_for") + " " + HIST_FILTER + " " + t("hist_only_suffix");
  } else banner.classList.add("hidden");
  renderHistCalendar();
  if (HIST_SELECTED) renderHistDetail(HIST_SELECTED);
}
function histFilteredDayRows(dateKey) {
  const monthData = HIST_CACHE[HIST_YEAR + "-" + HIST_MONTH] || { days: {} };
  let rows = (monthData.days && monthData.days[dateKey]) || [];
  if (HIST_FILTER) rows = rows.filter(r => r.name === HIST_FILTER);
  return rows;
}
function histDayCount(rows) {
  return rows.reduce((n, r) => n + (r.watched ? r.watched.length : 0) +
    (r.quizzes ? r.quizzes.length : 0) + (r.book_quizzes ? r.book_quizzes.length : 0), 0);
}
function histTier(count) {
  if (count <= 0) return 0;
  if (count <= 2) return 1;
  if (count <= 5) return 2;
  return 3;
}
function renderHistCalendar() {
  const label = histMonthName(HIST_MONTH) + " " + HIST_YEAR;
  $("#histMonthLabel").textContent = label;
  $("#histPrintTitle").textContent = label + " — " + t("hist_activity_report_suffix");
  const grid = $("#histGrid"); grid.innerHTML = "";
  const firstDow = new Date(HIST_YEAR, HIST_MONTH - 1, 1).getDay();
  const daysInMonth = new Date(HIST_YEAR, HIST_MONTH, 0).getDate();
  const now = new Date();
  const todayKey = histKey(now.getFullYear(), now.getMonth() + 1, now.getDate());
  const totalCells = Math.ceil((firstDow + daysInMonth) / 7) * 7;
  for (let i = 0; i < totalCells; i++) {
    const dayNum = i - firstDow + 1;
    if (dayNum < 1 || dayNum > daysInMonth) { grid.appendChild(el("div", "hist-day empty")); continue; }
    const dateKey = histKey(HIST_YEAR, HIST_MONTH, dayNum);
    const rows = histFilteredDayRows(dateKey);
    const count = histDayCount(rows);
    const tier = histTier(count);
    const isToday = dateKey === todayKey, isSelected = dateKey === HIST_SELECTED;
    const cell = el("div", "hist-day clickable" + (tier ? " t" + tier : "") +
      (isToday ? " today-cell" : "") + (isSelected ? " selected" : ""));
    cell.appendChild(el("div", "hd-num", String(dayNum)));
    if (isToday) cell.appendChild(el("div", "hd-today-badge", t("hist_today")));
    if (count > 0) {
      const act = el("div", "hd-activity");
      act.appendChild(el("span", "hd-dot"));
      act.appendChild(el("span", "hd-count", count + " " + (count === 1 ? t("hist_log_word") : t("hist_logs_word"))));
      cell.appendChild(act);
    }
    cell.onclick = () => histSelectDay(dateKey);
    grid.appendChild(cell);
  }
}
function histSelectDay(dateKey) {
  if (!dateKey) return;
  if (HIST_SELECTED === dateKey) { HIST_SELECTED = null; $("#histDetail").classList.add("hidden"); renderHistCalendar(); return; }
  HIST_SELECTED = dateKey; HIST_EXPANDED = new Set();
  renderHistCalendar();
  renderHistDetail(dateKey);
}
function histFormatDate(dateKey) {
  const parts = dateKey.split("-").map(Number);
  const dt = new Date(parts[0], parts[1] - 1, parts[2]);
  return dt.toLocaleDateString(SPEECH[LANG] || "en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}
function histInitials(name) {
  return (name || "?").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
}
function histActivityRow(title, badgeText, badgeClass) {
  const row = el("div", "hsr-activity");
  row.appendChild(el("span", null, title));
  row.appendChild(el("span", "hq-chip " + badgeClass, badgeText));
  return row;
}
function histStudentRow(r) {
  const totalActivities = (r.watched ? r.watched.length : 0) + (r.quizzes ? r.quizzes.length : 0) + (r.book_quizzes ? r.book_quizzes.length : 0);
  const stars = r.stars || 0;
  const pct = Math.min(100, Math.round((stars / DAILY_GOAL) * 100));
  const open = HIST_EXPANDED.has(r.name);
  const wrap = el("div", "hsr" + (open ? " open" : ""));
  const row = el("div", "hsr-row");
  row.appendChild(el("div", "hsr-avatar", histInitials(r.name)));
  const mid = el("div");
  mid.appendChild(el("div", "hsr-name", r.name));
  mid.appendChild(el("div", "hsr-sub", totalActivities + " " + (totalActivities === 1 ? t("hist_activity_word") : t("hist_activities_word"))));
  row.appendChild(mid);
  const barWrap = el("div", "hsr-bar-track"); const fill = el("div", "hsr-bar-fill");
  fill.style.width = pct + "%"; barWrap.appendChild(fill);
  row.appendChild(barWrap);
  row.appendChild(el("div", "hsr-status", stars + " " + (stars === 1 ? t("hist_star_word") : t("hist_stars_word"))));
  const chev = el("span", "hsr-chevron"); chev.innerHTML = CHEV_DOWN; row.appendChild(chev);
  wrap.appendChild(row);
  wrap.onclick = () => {
    if (HIST_EXPANDED.has(r.name)) HIST_EXPANDED.delete(r.name); else HIST_EXPANDED.add(r.name);
    renderHistDetail(HIST_SELECTED);
  };
  if (open) {
    const list = el("div", "hsr-activities");
    (r.watched || []).forEach(v => list.appendChild(histActivityRow(v.title, t("hist_video_word"), "neutral")));
    (r.quizzes || []).forEach(qz => list.appendChild(histActivityRow(qz.title + " " + t("hist_math_quiz_suffix"),
      (qz.score != null ? qz.score + "/" + qz.total : "—"), qz.passed ? "ok" : "bad")));
    (r.book_quizzes || []).forEach(qz => list.appendChild(histActivityRow(qz.title + " " + t("hist_book_quiz_suffix"),
      (qz.score != null ? qz.score + "/" + qz.total : "—"), qz.passed ? "ok" : "bad")));
    if (!list.children.length) list.appendChild(el("div", "hist-empty-day", t("hist_no_individual_activities")));
    wrap.appendChild(list);
  }
  return wrap;
}
function renderHistDetail(dateKey) {
  const rows = histFilteredDayRows(dateKey);
  $("#histDetail").classList.remove("hidden");
  $("#histDetailDate").textContent = histFormatDate(dateKey);
  const body = $("#histDetailBody"); body.innerHTML = "";
  if (!rows.length) { body.appendChild(el("div", "hist-empty-day", t("hist_no_activity_day"))); return; }
  rows.forEach(r => body.appendChild(histStudentRow(r)));
}

/* ---------- print / export report (asks for a duration, then downloads a CSV) ---------- */
function openExportModal() { $("#exportModal").classList.remove("hidden"); $("#exportStatus").classList.add("hidden"); }
function closeExportModal() { $("#exportModal").classList.add("hidden"); }
function csvEscape(v) {
  const s = String(v == null ? "" : v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
async function runHistExport() {
  const checked = document.querySelector("input[name='exportDur']:checked");
  const dur = checked ? checked.value : "this_month";
  const btn = $("#exportDownloadBtn"); btn.disabled = true;
  const status = $("#exportStatus"); status.classList.remove("hidden"); status.textContent = t("hist_building_report");
  let months = [[HIST_YEAR, HIST_MONTH]];
  if (dur !== "this_month") {
    const n = parseInt(dur, 10); months = [];
    let y = HIST_YEAR, m = HIST_MONTH;
    for (let i = 0; i < n; i++) { months.unshift([y, m]); m--; if (m < 1) { m = 12; y--; } }
  }
  const rowsOut = [[t("hist_csv_date"), t("hist_csv_student"), t("hist_csv_stars"), t("hist_csv_videos_watched"),
                    t("hist_csv_math_passed"), t("hist_csv_math_total"), t("hist_csv_book_passed"), t("hist_csv_book_total")]];
  for (const [y, m] of months) {
    const data = await histLoadMonth(y, m);
    const days = (data && data.days) || {};
    Object.keys(days).sort().forEach(dateKey => {
      days[dateKey].forEach(r => {
        const qPass = (r.quizzes || []).filter(q => q.passed).length;
        const bqPass = (r.book_quizzes || []).filter(q => q.passed).length;
        rowsOut.push([dateKey, r.name, r.stars || 0, (r.watched || []).length,
                      qPass, (r.quizzes || []).length, bqPass, (r.book_quizzes || []).length]);
      });
    });
  }
  const csv = rowsOut.map(row => row.map(csvEscape).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const label = dur === "this_month" ? (HIST_YEAR + "-" + pad2(HIST_MONTH)) : ("last_" + dur + "_months");
  a.href = url; a.download = "lightbox_activity_" + label + ".csv";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  status.textContent = t("hist_downloaded");
  btn.disabled = false;
  setTimeout(closeExportModal, 700);
}
async function addStudent() {
  const name = $("#newName").value.trim(), pw = $("#newPin").value.trim(), grade = $("#newGrade").value;
  const err = $("#addErr"); err.classList.add("hidden");
  if (!name) { flash($("#newName")); return; }
  if (!CUR_CLASS_ID) { err.textContent = t("no_classes_yet"); err.classList.remove("hidden"); return; }
  try {
    const r = await fetch("/api/teacher/add_student", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID, username: name, password: pw, grade }) });
    const d = await r.json();
    if (!d.ok) {
      err.textContent = d.status === "need_password"
        ? t("need_password_msg")
        : t("could_not_add_student");
      err.classList.remove("hidden"); flash($("#newPin")); return;
    }
    $("#newName").value = ""; $("#newPin").value = ""; $("#newGrade").value = ""; $("#newName").focus();
    renderDashboard(); loadMyClasses();
  } catch (e) { err.textContent = t("could_not_add_student"); err.classList.remove("hidden"); }
}
async function removeStudent(name) {
  if (!confirm("Remove " + name + " from this class? Their account and progress history are kept.")) return;
  try {
    await fetch("/api/teacher/remove_student", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID, username: name }) });
  } catch (e) {}
  renderDashboard(); loadMyClasses();
}
async function resetPassword(name) {
  const pw = prompt("Set a new password for " + name + " (min 4 characters):");
  if (pw === null) return;
  if (pw.trim().length < 4) { alert("Password must be at least 4 characters."); return; }
  try {
    await fetch("/api/teacher/add_student", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: getSession(), class_id: CUR_CLASS_ID, username: name, password: pw.trim() }) });
  } catch (e) {}
  renderDashboard();
}

/* ---------- screen + navigation ---------- */
let _dashPoll = null;
function startDashPoll() { if (!_dashPoll) _dashPoll = setInterval(() => { if (!$("#dashboard").classList.contains("hidden")) renderDashboard(true); }, 8000); }
function stopDashPoll() { if (_dashPoll) { clearInterval(_dashPoll); _dashPoll = null; } }
function show(screen) {
  CURRENT_SCREEN = screen;
  SCREENS.forEach(s => $("#" + s).classList.toggle("hidden", s !== screen));
  // The helper sizes itself to the viewport and scrolls its own message list, so the
  // page behind it must not scroll as well - otherwise there is empty background to
  // scroll down into. Cleared again on every other screen.
  document.body.classList.toggle("screen-locked", screen === "helper");
  // teachers don't get a back arrow - Sign Out (with its own confirm) is the only
  // way off the dashboard, so there's no "go back" state to support
  $("#backBtn").classList.toggle("hidden", screen === "role" || screen === "welcome" || screen === "login" || screen === "dashboard" || screen === "history");
  const nm = getName(), studentScreen = ["subjects", "home", "reading", "reader", "browse", "helper", "lesson", "achievements", "test"].includes(screen);
  const showProfile = studentScreen && nm;
  $("#profName").textContent = nm;
  $("#profileWrap").classList.toggle("hidden", !showProfile);
  if (!showProfile) $("#profileMenu").classList.add("hidden");
  // once a student is signed in, language lives in the profile menu ("Change Language")
  // instead of duplicating a picker in the top bar
  $("#lang").classList.toggle("hidden", showProfile);
  updateBell();
  if (screen !== "lesson") speechSynthesis && speechSynthesis.cancel();
  // real-time dashboard refresh for the teacher
  if (screen === "dashboard") startDashPoll(); else stopDashPoll();
  // stop watching for class-join approval once the student has left the join screen
  if (screen !== "joincode") stopJoinPoll();
  // teacher-only topbar label ("Teacher dashboard") shown on dashboard + history
  const teacherScreen = screen === "dashboard" || screen === "history";
  $("#topbarTeacherLabel").classList.toggle("hidden", !teacherScreen);
  $("#topbarDivider").classList.toggle("hidden", !teacherScreen);
  // the notification bell rides the shared top bar, so it is present on both teacher
  // screens; polling only runs while one of them is open
  const showBell = teacherScreen && ME.role === "teacher";
  $("#notifWrap").classList.toggle("hidden", !showBell);
  if (!showBell) { closeNotifPanel(); stopNotifPoll(); } else startNotifPoll();
  renderSidebarActive();
  // reading HUD replaces the global top bar while inside a book
  $("#topbar").classList.toggle("reading-hidden", screen === "reader" || screen === "welcome");
}

/* ---------- teacher dashboard: sidebar-navigated views (Overview/Tests/Progress), History Logs stays its own screen ---------- */
const DASH_VIEWS = ["overview", "tests", "progress"];
let DASH_VIEW = "overview", TESTS_TAB = "create";
function capFirst(s) { return s[0].toUpperCase() + s.slice(1); }
function showDashView(view) {
  // navigating in from History (or anywhere else): switch screens, but don't
  // re-fetch - renderDashboard() already ran when the dashboard was first entered
  // and _dashData is still cached, so callers of showDashView never need to
  // call renderDashboard() again themselves.
  if (CURRENT_SCREEN !== "dashboard") show("dashboard");
  DASH_VIEW = view;
  DASH_VIEWS.forEach(v => $("#dashView" + capFirst(v)).classList.toggle("hidden", v !== view));
  renderSidebarActive();
  if (view === "tests") showTestsTab(TESTS_TAB);
}
function showTestsTab(tab) {
  TESTS_TAB = tab;
  $("#testsPaneCreate").classList.toggle("hidden", tab !== "create");
  $("#testsPaneResults").classList.toggle("hidden", tab !== "results");
  $("#testsTabCreate").classList.toggle("active", tab === "create");
  $("#testsTabResults").classList.toggle("active", tab === "results");
  if (tab === "create") renderTestBuilder(); else renderTestsArea();
}
function renderSidebarActive() {
  document.querySelectorAll(".dash-nav-item[data-view]").forEach(b => {
    const v = b.dataset.view;
    const active = v === "history" ? CURRENT_SCREEN === "history" : (CURRENT_SCREEN === "dashboard" && v === DASH_VIEW);
    b.classList.toggle("active", active);
  });
}
// Navigate to the signed-in user's home screen. Does NOT sign anyone out - the
// session stays alive until logout() runs (e.g. the profile menu's Sign Out).
function goHome() {
  if (SESSION && ME.username) {
    if (ME.role === "teacher") { showDashView("overview"); show("dashboard"); renderDashboard(); loadPending(); startDashPoll(); archiveSweep(); }
    else openSubjects();
  } else {
    show("role");
  }
}
function logout() { apiLogout(); clearIdentity(); resetIdentity(); show("role"); }
function confirmSignOut() {
  const box = $("#confirmSignOut");
  box.classList.remove("hidden");
  const cleanup = () => { box.classList.add("hidden"); $("#confirmSignOutYes").onclick = null; $("#confirmSignOutCancel").onclick = null; };
  $("#confirmSignOutCancel").onclick = cleanup;
  $("#confirmSignOutYes").onclick = () => { cleanup(); logout(); };
}
function goBack() {
  const vis = id => !$("#" + id).classList.contains("hidden");
  if (vis("welcome")) return;                 // first-run setup: stay put (never skip setup or leave)
  if (vis("helper")) { show(HELPER_MODE === "math" ? "home" : "subjects"); return; }
  if (vis("test")) { openSubjects(); return; }
  if (vis("achievements")) { if (_achReturn === "reading") openReading(); else show(_achReturn || "home"); return; }
  if (vis("reader")) { openReading(); return; }
  if (vis("reading")) { show("subjects"); return; }
  // signed-in root screen: nothing further back to go, so "back" means sign out -
  // ask first, since kids can hit this by accident and lose their place
  if (vis("subjects")) { confirmSignOut(); return; }
  if (vis("dashboard")) { confirmSignOut(); return; }   // unreachable via click - back arrow is hidden for teachers - kept as a safety net
  if (vis("history")) { showDashView("overview"); show("dashboard"); renderDashboard(); return; }
  if (vis("lesson")) {
    if (LESSON_RETURN === "home") { openHome(); return; }
    show("browse"); renderBrowse(); return;
  }
  if (vis("browse")) {
    if (nav.topic) { nav.topic = null; renderBrowse(); }
    else if (nav.grade) { nav.grade = null; renderBrowse(); }
    else show("home");
    return;
  }
  if (vis("home")) { show("subjects"); return; }
  if (vis("login") || vis("signup") || vis("joincode")) { show("role"); return; }
  show("role");
}

const CHEV = '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const PLAY = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>';
const BOOK_ICON = '<svg viewBox="0 0 24 24" width="15" height="15"><path d="M12 6c-1.5-1.2-3.6-2-6-2v13c2.4 0 4.5.8 6 2 1.5-1.2 3.6-2 6-2V4c-2.4 0-4.5.8-6 2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 6v13" stroke="currentColor" stroke-width="1.8"/></svg>';
const BOOKMARK_ICON = '<svg viewBox="0 0 24 24" width="14" height="14"><path d="M6 3h12v18l-6-4.2L6 21V3z" fill="currentColor"/></svg>';
const GRADE_ICON = '<svg viewBox="0 0 24 24" width="22" height="22"><rect x="5" y="3" width="14" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><line x1="8" y1="7" x2="16" y2="7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8.5" cy="12.3" r="1" fill="currentColor"/><circle cx="12" cy="12.3" r="1" fill="currentColor"/><circle cx="15.5" cy="12.3" r="1" fill="currentColor"/><circle cx="8.5" cy="16.3" r="1" fill="currentColor"/><circle cx="12" cy="16.3" r="1" fill="currentColor"/><circle cx="15.5" cy="16.3" r="1" fill="currentColor"/></svg>';
const TOPIC_ICON = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M4 19V10M12 19V5M20 19v-7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
const PLAY_CIRCLE_ICON = '<svg viewBox="0 0 24 24" width="14" height="14"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 8.5v7l6-3.5z" fill="currentColor"/></svg>';
const CIRCLE_ICON = '<svg viewBox="0 0 24 24" width="14" height="14"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
// the LightBox mark itself - same geometry as the topbar logo in index.html, inlined
// so the helper's avatar is the logo rather than a generic dot
const LOGO_ICON = '<svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="49" fill="#16233B"/><circle cx="50" cy="43" r="25" fill="#F3EAC2"/><path d="M50 24 L67 50 L50 80 L33 50 Z" fill="#FCC419"/></svg>';
const SPEAKER_ICON = '<svg viewBox="0 0 24 24" width="15" height="15"><path d="M4 9v6h4l5 5V4L8 9H4z" fill="currentColor"/><path d="M15.5 8.8a4 4 0 0 1 0 6.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
function spkBtn() {
  const b = el("button", "spk"); b.innerHTML = SPEAKER_ICON;
  // icon-only control: without a label a screen reader announces just "button"
  b.type = "button"; b.setAttribute("aria-label", t("read_aloud")); b.title = t("read_aloud");
  return b;
}
function pill(label, sub, icon, onclick, cls, extra) {
  const b = el("button", "navpill" + (cls ? " " + cls : ""));
  const main = el("div", "pill-main");
  main.appendChild(el("div", "pill-label", label));
  if (sub) main.appendChild(el("div", "pill-sub", sub));
  b.appendChild(main);
  const right = el("span", "pill-right");
  const ic = el("span", "pill-ic"); ic.innerHTML = icon; right.appendChild(ic);
  if (extra) right.appendChild(extra);
  b.appendChild(right);
  b.onclick = onclick; return b;
}
function vidDone(v) { const s = SUMMARY && SUMMARY.videos && SUMMARY.videos[v.id]; return !!(s && (s.finished || s.passed)); }
function vidMastered(v) { const s = SUMMARY && SUMMARY.videos && SUMMARY.videos[v.id]; return !!(s && s.passed); }
function courseCard(gradeCode, items) {
  const done = items.filter(vidDone).length, pct = Math.round((done / items.length) * 100);
  const started = pct > 0;
  const accent = GRADE_ACCENTS[gradeCode] || "#5A7593";
  const b = el("button", "course-card");
  b.style.borderTopColor = accent;
  const ic = el("span", "cc-icon"); ic.style.background = hexToRgba(accent, .14); ic.style.color = accent;
  ic.innerHTML = GRADE_ICONS[gradeCode] || GRADE_ICON;
  b.appendChild(ic);
  const head = el("div");
  head.appendChild(el("div", "cc-title", t("grade_" + gradeCode)));
  head.appendChild(el("div", "cc-sub", items.length + " " + t("videos")));
  b.appendChild(head);
  const prog = el("div");
  const bar = el("div", "cc-bar");
  const fill = el("div", "cc-fill"); const barPct = started ? Math.max(pct, 4) : 0;
  fill.style.width = barPct + "%"; fill.style.background = accent;
  bar.appendChild(fill);
  const dot = el("div", "cc-dot"); dot.style.left = barPct + "%"; dot.style.background = accent;
  bar.appendChild(dot);
  prog.appendChild(bar);
  const status = el("div", "cc-status" + (started ? "" : " zero"));
  if (started) { status.style.color = accent; status.innerHTML = PLAY_CIRCLE_ICON; }
  else { status.innerHTML = CIRCLE_ICON; }
  status.appendChild(document.createTextNode(started ? (pct + "% " + t("watched_word")) : t("not_started")));
  prog.appendChild(status);
  b.appendChild(prog);
  b.onclick = () => { nav.grade = gradeCode; renderBrowse(); };
  return b;
}
function topicRow(label, items) {
  const mastered = items.filter(vidMastered).length, done = items.filter(vidDone).length;
  const pct = Math.round((mastered / items.length) * 100);
  const b = el("button", "topic-row");
  const ic = el("span", "tr-ic"); ic.innerHTML = TOPIC_ICON; b.appendChild(ic);
  const main = el("div", "tr-main");
  main.appendChild(el("div", "tr-title", label));
  main.appendChild(el("div", "tr-sub" + (pct ? "" : " zero"),
    pct ? (pct + "% Mastered") : (done ? (done + " / " + items.length + " watched") : (items.length + " " + t("videos")))));
  b.appendChild(main);
  const bar = el("div", "tr-bar"); const fill = el("div", "tr-fill"); fill.style.width = pct + "%"; bar.appendChild(fill);
  b.appendChild(bar);
  const chev = el("span", "tr-chev"); chev.innerHTML = CHEV; b.appendChild(chev);
  return b;
}
function renderResume(gradeItems) {
  const box = el("div", "resume-section");
  box.appendChild(el("h3", "side-h", "Resume Learning"));
  const list = el("div", "thumb-list");
  const unfinished = gradeItems.filter(v => !vidDone(v));
  const picks = (unfinished.length ? unfinished : gradeItems).slice(0, 5);
  if (!picks.length) return null;
  picks.forEach(v => list.appendChild(thumbCard(v)));
  box.appendChild(list);
  return box;
}
async function renderBrowse() {
  // wait for progress data before the first paint - rendering with SUMMARY still null
  // shows every grade/topic as 0%/"Not started" until a later re-render corrects it,
  // which reads as "the menu didn't load" the first time a screen is opened
  if (!SUMMARY) { showLoading(true); await ensureSummary(); showLoading(false); }
  if ($("#browse").classList.contains("hidden")) return;   // navigated away while we waited
  const folders = $("#folders"); folders.innerHTML = ""; folders.className = "";
  const crumbs = $("#crumbs"); crumbs.innerHTML = "";
  const addCrumb = (label, fn, last) => {
    if (last) crumbs.appendChild(el("span", null, label));
    else { const a = el("a", null, label); a.onclick = fn; crumbs.appendChild(a);
      crumbs.appendChild(el("span", "sep", "›")); }
  };
  addCrumb(t("home"), goHome, false);

  if (!nav.grade) {
    $("#browseTitle").textContent = t("choose_grade");
    addCrumb(t("choose_grade"), null, true);
    folders.className = "course-grid";
    GRADE_ORDER.forEach(g => {
      const items = CATALOG.filter(v => v.grade === g);
      if (!items.length) return;
      folders.appendChild(courseCard(g, items));
    });
    return;
  }
  addCrumb(t("grade_" + nav.grade), () => { nav.grade = null; nav.topic = null; renderBrowse(); }, !nav.topic);

  if (!nav.topic) {
    $("#browseTitle").textContent = t("grade_" + nav.grade);
    folders.className = "topic-panel";
    const gradeItems = CATALOG.filter(v => v.grade === nav.grade);
    const seen = {}, order = [];
    gradeItems.forEach(v => {
      const k = topicKey(v.id);
      if (seen[k]) seen[k].items.push(v); else { seen[k] = { label: v.topic_label, items: [v] }; order.push(k); }
    });
    const card = el("div", "card topic-card");
    order.forEach(k => {
      const row = topicRow(seen[k].label, seen[k].items);
      row.onclick = () => { nav.topic = k; renderBrowse(); };
      card.appendChild(row);
    });
    folders.appendChild(card);
    const resume = renderResume(gradeItems);
    if (resume) folders.appendChild(resume);
    return;
  }
  const list = CATALOG.filter(v => v.grade === nav.grade && topicKey(v.id) === nav.topic);
  $("#browseTitle").textContent = list.length ? list[0].topic_label : t("lessons");
  addCrumb(list.length ? list[0].topic_label : t("lessons"), null, true);
  folders.className = "pill-list";
  list.forEach(v => {
    folders.appendChild(pill(v.title, v.id + "  ·  " + Math.round(v.duration_min) + " min", PLAY,
      () => openLesson(v.id, "browse"), "lesson", statusDot(v.id)));
  });
}

/* ---------- lesson ---------- */
const UNFINISHED_THRESHOLD = 0.9;
// Only the Next Videos thumbnails (inside the lesson/video screen) gate on an unfinished
// video - browsing to a lesson from the topic list, code entry, etc. never prompts.
function openNextVideo(id) {
  if (CUR && CUR.id !== id && watchedFrac < UNFINISHED_THRESHOLD) {
    confirmLeaveVideo(() => openLesson(id));
    return;
  }
  openLesson(id);
}
function confirmLeaveVideo(onConfirm) {
  const box = $("#confirmLeave");
  box.classList.remove("hidden");
  const cleanup = () => { box.classList.add("hidden"); $("#confirmStayBtn").onclick = null; $("#confirmGoBtn").onclick = null; };
  $("#confirmStayBtn").onclick = cleanup;
  $("#confirmGoBtn").onclick = () => { cleanup(); onConfirm(); };
}
/* Where Back should go from the lesson screen. openLesson() sets nav.grade/nav.topic
   from the video so the browse hierarchy is correct if you DO go there, but a lesson
   opened from the home screen (Next step, To-do, a lesson code) should return home
   rather than dropping the student into the grade/topic list they never went through. */
let LESSON_RETURN = "browse";
function openLesson(id, from) {
  const v = CATALOG.find(x => x.id === id);
  if (!v) { flash($("#code")); alert(t("cant_find") + " (" + id + ")"); return; }
  // Opening a "Next video" from inside a lesson passes no `from` and inherits the
  // current target, so a chain of videos still returns where the chain began. The
  // language-switch re-render (refreshScreenTexts) relies on this too.
  if (from) LESSON_RETURN = from;
  else if (CURRENT_SCREEN !== "lesson") LESSON_RETURN = "browse";
  CUR = v; HISTORY = [];
  if (v.grade) { nav.grade = v.grade; nav.topic = topicKey(v.id); }
  show("lesson");
  $("#ltitle").textContent = v.title;
  $("#ltopic").textContent = v.topic_label || "";
  $("#ldesc").textContent = v.note || "";
  const vid = $("#vid"); vid.innerHTML = ""; vid.src = "/api/video/" + v.id;
  loadTrack(); vid.load(); resetPlayer();
  // warm the model's prompt cache with this video's transcript while the child watches,
  // so the first question answers quickly (debounced ~6s so browsing past lessons doesn't trigger it)
  clearTimeout(WARM_TIMER);
  WARM_TIMER = setTimeout(() => {
    fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: v.id, lang: LANG, warm: true, session: getSession() }) }).catch(() => {});
  }, 6000);
  $("#chat").innerHTML = ""; botMsg(t("welcome")); switchTab("ask");
  renderStatusButtons(v.id);
  ensureSummary().then(() => { renderStatusButtons(v.id); renderNextRelated(v); });
  renderNextRelated(v);
}
function renderStatusButtons(vid) {
  const st = videoStatus(vid);
  $("#markComplete").classList.toggle("on", st === "complete");
  $("#markTodo").classList.toggle("on", st === "todo");
}
function thumbCard(v) {
  const c = el("button", "thumb-card");
  const cov = el("div", "thumb-cover");
  const img = el("img", "thumb-img"); img.src = "/api/thumb/" + v.id; img.alt = "";
  img.onerror = () => img.remove();   // no frame could be extracted - fall back to the plain tile
  cov.appendChild(img);
  const play = el("span", "thumb-play"); play.innerHTML = PLAY; cov.appendChild(play);
  const dur = el("span", "thumb-dur", Math.round(v.duration_min) + " min"); cov.appendChild(dur);
  const status = el("span", "thumb-status"); status.appendChild(statusDot(v.id)); cov.appendChild(status);
  c.appendChild(cov);
  c.appendChild(el("div", "thumb-title", v.title));
  c.onclick = () => openNextVideo(v.id);
  return c;
}
function renderNextRelated(v) {
  const topic = topicKey(v.id);
  const idx = CATALOG.findIndex(x => x.id === v.id);
  const next = CATALOG.filter((x, i) => x.grade === v.grade && topicKey(x.id) === topic && i > idx).slice(0, 2);

  const nextBox = $("#nextVideos"); nextBox.innerHTML = "";
  if (!next.length) nextBox.appendChild(el("p", "thumb-empty", t("topic_finished")));
  else next.forEach(n => nextBox.appendChild(thumbCard(n)));
}
function switchTab(which) {
  $("#tabAsk").classList.toggle("on", which === "ask");
  $("#tabQuiz").classList.toggle("on", which === "quiz");
  $("#ask").classList.toggle("hidden", which !== "ask");
  $("#quiz").classList.toggle("hidden", which !== "quiz");
  if (which === "quiz") startQuiz();
}
/* ---- markdown + streaming chat rendering (shared) ---- */
function escapeHtml(s) { return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function inlineMd(s) {
  return s.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/^#{1,4}\s+(.*)$/, "<strong>$1</strong>");
}
function mdToHtml(text) {
  const lines = escapeHtml(text || "").split(/\n/);
  let out = "", para = [], list = null;   // list = { ordered, items: [] }
  const flushPara = () => { if (para.length) { out += "<p>" + para.map(inlineMd).join("<br>") + "</p>"; para = []; } };
  const flushList = () => {
    if (list) {
      out += (list.ordered ? "<ol>" : "<ul>") + list.items.map(i => "<li>" + inlineMd(i) + "</li>").join("") + (list.ordered ? "</ol>" : "</ul>");
      list = null;
    }
  };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { flushPara(); flushList(); continue; }       // blank line ends a block
    const h = line.match(/^\s*#{1,6}\s+(.*)$/);
    if (h) { flushPara(); flushList(); out += "<p><strong>" + inlineMd(h[1]) + "</strong></p>"; continue; }
    const m = line.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/);
    if (m) {                                                        // a list item (groups consecutive items)
      flushPara();
      const ordered = /\d/.test(m[1]);
      if (!list || list.ordered !== ordered) { flushList(); list = { ordered: ordered, items: [] }; }
      list.items.push(m[2]);
      continue;
    }
    flushList();
    para.push(line);
  }
  flushPara(); flushList();
  return out || "<p></p>";
}
/* The homework helper shows each bubble with an avatar and a speaker label; the
   in-lesson Q&A chat stays the plain bubble stack it has always been. Both use the
   same `.msg` element and the same streaming path - only the helper wraps it in a
   row - so nothing about how a message is sent or rendered changes here. */
function isHelperChat(container) { return container && container.id === "hchat"; }
function addMsg(container, m, mine) {
  if (!isHelperChat(container)) { container.appendChild(m); return m; }
  const row = el("div", "hrow " + (mine ? "me" : "ai"));
  const av = el("div", "havatar" + (mine ? " me" : ""));
  // the AI wears the LightBox mark (gold dot on navy); the student wears their initial
  if (mine) av.textContent = (getName() || "?").trim().charAt(0).toUpperCase();
  else av.innerHTML = LOGO_ICON;
  av.setAttribute("aria-hidden", "true");
  const col = el("div", "hcol");
  col.appendChild(el("div", "hwho", mine ? t("helper_you") : BOT_NAME));
  col.appendChild(m);
  row.appendChild(av); row.appendChild(col);
  container.appendChild(row);
  return m;
}
function botBubble(container, text) {
  const m = el("div", "msg bot");
  const c = el("div", "md"); c.innerHTML = mdToHtml(text); m.appendChild(c);
  const s = spkBtn(); s.onclick = () => speak(text); m.appendChild(s);
  addMsg(container, m, false); container.scrollTop = container.scrollHeight; return m;
}
function userBubble(container, text) {
  const m = el("div", "msg me", text);
  addMsg(container, m, true); container.scrollTop = container.scrollHeight;
}
// removes a bubble together with its helper row wrapper, so a pending "thinking"
// indicator does not leave an empty avatar behind
function dropMsg(m) { if (!m) return; const r = m.closest(".hrow"); (r || m).remove(); }
// three CSS-animated dots - no library, no GIF, nothing to download - because this
// runs on the same 2-core box that is busy generating the answer
function thinkingEl(container) {
  if (!isHelperChat(container)) return el("div", "msg thinking", t("thinking"));
  const m = el("div", "msg thinking dots");
  const d = el("span", "tdots");
  d.appendChild(el("i")); d.appendChild(el("i")); d.appendChild(el("i"));
  m.appendChild(d); m.appendChild(el("span", "tlabel", t("thinking")));
  return m;
}
async function streamAsk(endpoint, payload, container, history) {
  const wait = thinkingEl(container);
  addMsg(container, wait, false); container.scrollTop = container.scrollHeight;
  let acc = "", m = null, c = null;
  const atBottom = () => container.scrollHeight - container.scrollTop - container.clientHeight < 60;
  try {
    const resp = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!resp.body || !resp.body.getReader) { dropMsg(wait); botBubble(container, t("trouble")); return; }
    const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const evt = buf.slice(0, i); buf = buf.slice(i + 2);
        const dl = evt.split("\n").find(l => l.startsWith("data:")); if (!dl) continue;
        let o; try { o = JSON.parse(dl.slice(5).trim()); } catch (e) { continue; }
        if (o.t) {
          const stick = atBottom();
          if (!m) { dropMsg(wait); m = el("div", "msg bot"); c = el("div", "md"); m.appendChild(c); addMsg(container, m, false); }
          acc += o.t; c.innerHTML = mdToHtml(acc);
          if (stick) container.scrollTop = container.scrollHeight;
        } else if (o.error && !m) { dropMsg(wait); botBubble(container, o.error); }
      }
    }
    dropMsg(wait);
    if (m && acc) {
      const s = spkBtn(); s.onclick = () => speak(acc); m.appendChild(s);
      history.push({ role: "assistant", content: acc }); speak(acc);
    } else if (!m) botBubble(container, t("trouble"));
  } catch (e) { dropMsg(wait); if (!m) botBubble(container, t("trouble")); }
}
function botMsg(text) { return botBubble($("#chat"), text); }
function meMsg(text) { userBubble($("#chat"), text); }
async function ask() {
  const q = $("#q").value.trim(); if (!q || !CUR) return;
  $("#q").value = ""; meMsg(q); HISTORY.push({ role: "user", content: q });
  await streamAsk("/api/ask", { id: CUR.id, question: q, history: HISTORY, lang: LANG, session: getSession() }, $("#chat"), HISTORY);
}

/* ---------- homework helper ---------- */
// The helper introduces itself by name. It is a brand name like LightBox, so it is
// substituted into the translated sentence rather than being part of it - otherwise
// LibreTranslate would happily "translate" it.
const BOT_NAME = "LightBot";
let HHISTORY = [];
let HELPER_MODE = "general";
/* Helper session state. All three ride along with every message and are turned into a
   single system prompt server-side (helper_system in server.py), so they change how the
   model answers rather than just labelling the chat. They survive the whole
   conversation and reset only on "New question" or an explicit change.
   The student's profile grade is offered as the suggested chip, but never assumed:
   HGRADE is only ever set by a tap, so "grade 3" in the summary is always something the
   child actually confirmed. */
let HSUBJECT = "", HGRADE = "", HLANG = "";
/* Which question LightBot is currently asking. "subject" -> "grade" -> "chat"; the
   picker below the conversation and the input bar are both driven by this one value,
   so they can never disagree about which step we are on. */
let HSTEP = "subject";
// strings in the ANSWER language, used for the assistant's own opening line. The
// screen chrome stays in the app language (STR); only what LightBot "says" follows
// the language the student picked for answers.
let HSTR = {}, HSTR_LANG = "";
/* Languages VERIFIED for AI answers. Measured 2026-08-11 against Qwen2.5-3B-Q4 on the
   box, same question in each language:
     en  correct ("4 tens and 12 ones ... take away 8 from 12")
     fr  wrong maths ("partager une piece de 10 ... pour totaliser 52"); a writing
         answer also opened with a repetition glitch ("Chou, commen commen commencer")
     es  wrong maths ("8 menos 2 es 6"); called chlorophyll "chlorina" in a science answer
     de  invented the word "Einsteinstrelle" (there is no such word - Einerstelle) and
         rendered "borrow" as "bauen" (to build)
   The surface language is fluent in all three; it is the reasoning and the technical
   vocabulary that break, which is exactly the failure a child cannot catch. So the app
   is translated into four languages but LightBot answers only in English for now.
   Re-enabling is this one line - but generate-in-English-then-LibreTranslate (the path
   the rest of the app already uses) is the safer way to add them. */
const HELPER_LANGS = ["en"];
function helperDefaults() {
  if (!HLANG) HLANG = HELPER_LANGS.indexOf(LANG) >= 0 ? LANG : "en";
}
// The grade we already know for this child (set by their teacher, and the same value
// the reading hub and the browse screen use). It is a SUGGESTION for the grade step,
// never the answer: it is pre-selected and marked, but still has to be tapped.
function suggestedGrade() {
  const g = (SUMMARY && SUMMARY.grade) || "";
  return GRADE_ORDER.indexOf(g) >= 0 ? g : "";
}
function fillSel(sel, items, current) {
  sel.innerHTML = "";
  items.forEach(it => {
    const o = el("option", null, it.label);
    o.value = it.value;
    if (it.value === current) o.selected = true;
    sel.appendChild(o);
  });
}
/* Only the answer language is still a control. Subject and grade are asked for in the
   conversation itself (renderHelperPicker) - a child who has to fill in a form before
   they are allowed to talk is being handed a form, not a helper. */
function renderHelperOpts() {
  helperDefaults();
  const lng = $("#hLang");
  if (!lng) return;
  // the app's own language list, not a second one that could drift out of step
  const langOpts = Object.keys(LANGS).filter(c => HELPER_LANGS.indexOf(c) >= 0);
  fillSel(lng, langOpts.map(c => ({ value: c, label: LANGS[c] })), HLANG);
  // only offer the control when there is more than one verified answer language
  const langWrap = lng.closest(".hopt");
  if (langWrap) langWrap.classList.toggle("hidden", langOpts.length < 2);
  // changing the answer language mid-conversation also re-greets in that language, so
  // the change is visible immediately rather than only on the next reply
  lng.onchange = async e => {
    HLANG = e.target.value;
    await loadHelperStrings();
    // only safe to restart while nothing has been asked yet; mid-conversation this
    // would wipe the child's history just to restate a greeting
    if (HHISTORY.length === 0) startHelperFlow();
  };
}
// the opening line comes from the string table like everything else, and follows the
// answer language rather than the app language - it is the assistant speaking
async function loadHelperStrings() {
  const lang = HLANG || "en";
  if (HSTR_LANG === lang) return;
  if (lang === LANG) { HSTR = STR; HSTR_LANG = lang; return; }   // already in memory
  try { HSTR = await (await fetch("/api/i18n?lang=" + lang)).json(); HSTR_LANG = lang; }
  catch (e) { HSTR = {}; HSTR_LANG = ""; }                        // fall back to app language
}
// what LightBot SAYS follows the answer language (HSTR); screen chrome around it stays
// in the app language. Every line the assistant speaks goes through this, so none of
// them can be a hardcoded English string.
function hsay(k) { return (HSTR && HSTR[k]) || t(k); }
function helperWelcome() {
  return hsay(HELPER_MODE === "math" ? "math_helper_welcome" : "helper_welcome");
}
/* Subject cards: a blank text box is the hardest thing to answer, so the conversation
   opens by asking which subject. Tapping one is a turn in the chat, not a form entry.
   Icons are inline SVG (the app ships no icon library and has no network to fetch one
   from). Accents reuse the grade palette. */
const HELPER_SUBJECTS = [
  { key: "math", color: "#2D82A0",
    icon: '<svg viewBox="0 0 24 24" width="21" height="21"><rect x="4" y="3" width="16" height="18" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M7.5 8h9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M8 12.5h1.6M11.2 12.5h1.6M14.4 12.5h1.6M8 16.5h1.6M11.2 16.5h1.6M14.4 16.5h1.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>' },
  { key: "reading", color: "#68A64A",
    icon: '<svg viewBox="0 0 24 24" width="21" height="21"><path d="M12 6c-1.5-1.2-3.6-2-6-2v13c2.4 0 4.5.8 6 2 1.5-1.2 3.6-2 6-2V4c-2.4 0-4.5.8-6 2z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 6v13" stroke="currentColor" stroke-width="1.8"/></svg>' },
  { key: "science", color: "#C2664A",
    icon: '<svg viewBox="0 0 24 24" width="21" height="21"><path d="M10 3h4M10.5 3v6.2L5.6 17.4A2 2 0 0 0 7.3 20.5h9.4a2 2 0 0 0 1.7-3.1L13.5 9.2V3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8.3 14.5h7.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>' },
  { key: "writing", color: "#D19A1E",
    icon: '<svg viewBox="0 0 24 24" width="21" height="21"><path d="M15.5 4.5l4 4L8 20H4v-4z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M13.4 6.6l4 4" stroke="currentColor" stroke-width="1.8"/></svg>' }
];
// one card, whichever step we are on: same size, same icon tile, same hover/press, so
// picking a grade feels like the second half of picking a subject rather than a
// different screen that happens to appear underneath
function pickCard(accent, iconHtml, label, onPick) {
  const b = el("button", "hsubj");
  b.type = "button";
  b.style.setProperty("--subj", accent);
  const ic = el("span", "hsubj-ic"); ic.innerHTML = iconHtml;
  b.appendChild(ic);
  b.appendChild(el("span", "hsubj-lbl", label));
  b.onclick = onPick;
  return b;
}
/* The picker under the conversation renders whichever question LightBot just asked.
   It is one function and one container for both steps precisely so the two steps
   cannot drift apart visually. When HSTEP is "chat" it disappears and the input bar
   takes its place. */
function renderHelperPicker() {
  const box = $("#hsubjects"), bar = $("#hbar");
  if (!box) return;
  const asking = HSTEP === "subject" || HSTEP === "grade";
  box.classList.toggle("hidden", !asking);
  // while a question is on screen the card gives the cards priority over the message
  // list: #helper is a fixed-height, overflow:hidden column, so without this the last
  // row of grades is cut off the bottom of the card and cannot be reached at all
  const cardEl = box.closest(".helper-card");
  if (cardEl) cardEl.classList.toggle("picking", asking);
  // the list just changed height under the question that was scrolled to the bottom of
  // it, so put the newest message back in view instead of leaving it cut in half. On
  // the next frame as well as now: the flex re-layout the class above triggers has not
  // happened yet on this one, so scrolling only now lands on the old scrollHeight.
  const chat = $("#hchat");
  if (chat) {
    chat.scrollTop = chat.scrollHeight;
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
  }
  // a text box while LightBot is still asking a question invites a child to answer in
  // the wrong place, so it is hidden rather than merely disabled
  if (bar) bar.classList.toggle("hidden", asking);
  box.innerHTML = "";
  if (!asking) return;
  box.appendChild(el("div", "hsubj-head", HSTEP === "subject" ? t("subject_prompt") : t("choose_grade")));
  const grid = el("div", "hsubj-grid" + (HSTEP === "grade" ? " grades" : ""));
  if (HSTEP === "subject") {
    HELPER_SUBJECTS.forEach(s => {
      grid.appendChild(pickCard(s.color, s.icon, t("subj_" + s.key), () => chooseSubject(s.key)));
    });
  } else {
    const sug = suggestedGrade();
    GRADE_ORDER.forEach(g => {
      const c = pickCard(GRADE_ACCENTS[g] || "#5A7593", GRADE_ICONS[g] || "", gradeLabel(g), () => chooseGrade(g));
      if (g === sug) {
        // the grade their teacher already recorded: marked, easiest to reach, still a tap
        c.classList.add("sug");
        c.appendChild(el("span", "hsubj-tag", t("your_grade")));
      }
      grid.appendChild(c);
    });
  }
  box.appendChild(grid);
}
/* Two arrows, not a pencil: the action swaps one pick for another rather than editing
   any text, and a pencil here would be the Writing subject's own icon sitting right
   beside the Writing chip in a quarter of all sessions. */
const SWAP_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9h13M13.6 5.6 17 9l-3.4 3.4"/><path d="M20 15H7M10.4 11.6 7 15l3.4 3.4"/></svg>';
/* One chip: the same icon and the same accent colour as the card the child tapped to
   set this, shrunk. The word ("Subject", "Grade") is carried for screen readers only -
   sighted children already know which chip is which from the icon they just chose, and
   printing the word turns a status strip back into a sentence. */
function hsumChip(accent, iconHtml, label, srLabel) {
  const c = el("span", "hsum-chip");
  c.style.setProperty("--chip", accent);
  const ic = el("span", "hsum-chip-ic"); ic.innerHTML = iconHtml;
  c.appendChild(ic);
  c.appendChild(el("span", "sr-only", srLabel + ": "));
  c.appendChild(el("span", "hsum-chip-lbl", label));
  return c;
}
/* The pinned summary: what was chosen, and a way to change it. Deliberately not the
   old selects - tapping "Change" re-asks the question in the chat instead of dropping
   a form on the child. Rendered as two chips on a light strip rather than a sentence
   in a cream pill: the cream belongs to the chat bubbles directly underneath, and two
   cream blocks stacked read as one more message from LightBot instead of a header. */
function renderHelperSummary() {
  const box = $("#hsummary"); if (!box) return;
  const has = !!(HSUBJECT || HGRADE);
  box.classList.toggle("hidden", !has);
  box.innerHTML = "";
  if (!has) return;
  const line = el("div", "hsum-line");
  const subj = HELPER_SUBJECTS.find(s => s.key === HSUBJECT);
  line.appendChild(hsumChip(
    subj ? subj.color : "#5A7593",
    subj ? subj.icon : TOPIC_ICON,
    HSUBJECT ? t("subj_" + HSUBJECT) : t("subj_general"),
    t("subject_word")));
  line.appendChild(el("span", "hsum-div"));
  line.appendChild(hsumChip(
    GRADE_ACCENTS[HGRADE] || "#5A7593",
    GRADE_ICONS[HGRADE] || GRADE_ICON,
    gradeLabel(HGRADE),
    t("grade_word")));
  const ch = el("button", "hsum-change");
  ch.type = "button";
  const ci = el("span", "hsum-change-ic"); ci.innerHTML = SWAP_ICON;
  ch.appendChild(ci);
  ch.appendChild(el("span", "hsum-change-lbl", t("helper_change")));
  ch.setAttribute("aria-label", t("helper_change_aria"));
  ch.onclick = restartHelperPicks;
  line.appendChild(ch);
  box.appendChild(line);
}
// step 1. Also the "New question" state, and where "Change" sends the child back to.
function startHelperFlow() {
  HSUBJECT = ""; HGRADE = ""; HSTEP = "subject";
  $("#hchat").innerHTML = "";
  hbot(helperWelcome());
  renderHelperSummary();
  renderHelperPicker();
}
// Re-asking mid-conversation. The chat and HHISTORY are left exactly as they are -
// fixing a wrong grade must not cost a child the answer they were reading.
function restartHelperPicks() {
  HSTEP = "subject";
  hbot(hsay("helper_subject_again"));
  renderHelperPicker();
}
function chooseSubject(key) {
  HSUBJECT = key;
  // the tap reads back as the student's own turn, so the transcript stays a conversation
  userBubble($("#hchat"), t("subj_" + key));
  HSTEP = "grade";
  hbot(hsay("helper_grade_prompt"));
  renderHelperSummary();
  renderHelperPicker();
}
function chooseGrade(g) {
  HGRADE = g;
  userBubble($("#hchat"), gradeLabel(g));
  HSTEP = "chat";
  // built by concatenation, not from a "{subject}, grade {n}" template: LibreTranslate
  // translates or drops placeholders, so a sentence with holes in it cannot survive
  // the fr/de/es cache build (same reason the "by {name}" byline is matched loosely)
  hbot(hsay("helper_got_it") + " " + hsay("subj_" + (HSUBJECT || "general")) + ", " +
       gradeLabel(g, hsay) + ". " + hsay("helper_what_help"));
  renderHelperSummary();
  renderHelperPicker();
  setTimeout(() => { const q = $("#hq"); if (q) q.focus(); }, 60);
}
async function openHelper(mode) {
  HELPER_MODE = (mode === "math") ? "math" : "general";
  HHISTORY = []; show("helper");
  const ttl = $("#helper .screen-title");
  if (ttl) ttl.textContent = HELPER_MODE === "math" ? t("math_helper") : t("helper_title");
  // the suggested grade comes from the student's profile, so it has to be loaded before
  // the grade step can mark it - otherwise a child with a known grade is asked blind
  await ensureSummary();
  renderHelperOpts();
  await loadHelperStrings();
  startHelperFlow();
}
function hbot(text) { return botBubble($("#hchat"), text); }
// `preset` lets a caller send a question through exactly the same path a typed one
// takes - same endpoint, same history, same streaming
async function askHelper(preset) {
  // nothing typed while LightBot is still asking for subject/grade can be a question
  if (HSTEP !== "chat") return;
  const q = (preset || $("#hq").value).trim(); if (!q) return;
  $("#hq").value = ""; userBubble($("#hchat"), q); HHISTORY.push({ role: "user", content: q });
  // subject/grade/language travel with every message; the server composes them into
  // one system prompt rather than trusting a client-supplied prompt
  await streamAsk("/api/chat", { question: q, history: HHISTORY, lang: HLANG || LANG,
    subject: HSUBJECT, grade: HGRADE, session: getSession(), mode: HELPER_MODE }, $("#hchat"), HHISTORY);
}

/* ---------- quiz (bank-based, anti-memorization) ---------- */
let QUIZ = null, QI = 0, SCORE = 0, QSEEN = [];
async function startQuiz(retry) {
  if (!CUR) return;
  $("#qbox").innerHTML = "<div class='qhead'>" + t(retry ? "quiz_newset" : "loading") + "</div>";
  if (!retry) QSEEN = [];
  let data;
  try {
    data = await (await fetch("/api/quiz/" + CUR.id + "?lang=" + LANG + "&seen=" + encodeURIComponent(QSEEN.join(",")))).json();
  } catch (e) { $("#qbox").textContent = "—"; return; }
  if (!data || !data.questions || !data.questions.length) {
    $("#qbox").innerHTML = "<div class='qhead'>" + t("quiz_preparing") + "</div>";   // no questions yet
    clearTimeout(window._qprep);
    window._qprep = setTimeout(() => { if (!$("#lesson").classList.contains("hidden")) startQuiz(retry); }, 4000);
    return;
  }
  QUIZ = data; QSEEN = QSEEN.concat(data.questions.map(q => q.bankIdx));
  QI = 0; SCORE = 0;
  renderQ();
}
function renderQ() {
  const box = $("#qbox"); box.innerHTML = "";
  if (QI >= QUIZ.questions.length) return finishQuiz();
  const item = QUIZ.questions[QI];
  box.appendChild(el("div", "qhead", t("question") + " " + (QI + 1) + " / " + QUIZ.questions.length));
  const qc = el("div", "qcard"); qc.appendChild(document.createTextNode(item.q));
  const s = spkBtn(); s.onclick = () => speak(item.q); qc.appendChild(s); box.appendChild(qc);
  if (item.type === "mc") {
    item.choices.forEach((ch, i) => { const b = el("button", "choice", ch); b.onclick = () => gradeMC(b, i); box.appendChild(b); });
  } else {
    const inp = el("input", "field"); inp.placeholder = t("type_answer"); box.appendChild(inp);
    const b = el("button", "btn primary", t("check")); b.style.marginTop = "12px";
    b.onclick = () => gradeOpen(inp.value, b); box.appendChild(b);
  }
}
async function grade(payload) {
  const r = await fetch("/api/grade", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ id: CUR.id, bankIdx: QUIZ.questions[QI].bankIdx, session: getSession(), lang: LANG }, payload)) });
  return r.json();
}
async function gradeMC(btn, idx) {
  document.querySelectorAll(".choice").forEach(b => b.disabled = true);
  const d = await grade({ answer: idx });
  if (d.correct) { btn.classList.add("correct"); SCORE++; }
  else { btn.classList.add("wrong"); const all = document.querySelectorAll(".choice"); if (all[d.answerIndex]) all[d.answerIndex].classList.add("correct"); }
  showFeedback(d.feedback);
}
async function gradeOpen(text, btn) {
  if (!text.trim()) return;
  btn.disabled = true; btn.textContent = t("thinking");
  const d = await grade({ answer: text }); if (d.correct) SCORE++; showFeedback(d.feedback);
}
function showFeedback(fb) {
  const box = $("#qbox");
  const f = el("div", "feedback"); const fc = el("div", "md"); fc.innerHTML = mdToHtml(fb || ""); f.appendChild(fc);
  const s = spkBtn(); s.onclick = () => speak(fb); f.appendChild(s); box.appendChild(f); speak(fb);
  const next = el("button", "btn primary", QI + 1 < QUIZ.questions.length ? t("next") : t("see_stars"));
  next.style.marginTop = "12px"; next.onclick = () => { QI++; renderQ(); }; box.appendChild(next);
}
function finishQuiz() {
  const box = $("#qbox"); box.innerHTML = "";
  const total = QUIZ.questions.length, passed = total >= 1 && SCORE * 3 >= total * 2;   // >= 2 of 3
  fetch("/api/quiz_done", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: getSession(), id: CUR.id, correct: SCORE, total }) }).catch(() => {});
  if (SUMMARY && SUMMARY.videos) { const vv = SUMMARY.videos[CUR.id] = SUMMARY.videos[CUR.id] || {}; vv.finished = true; if (passed) vv.passed = true; }
  const d = el("div", "qresult");
  d.appendChild(el("div", "stars", "★".repeat(SCORE) + "☆".repeat(Math.max(0, total - SCORE))));
  d.appendChild(el("div", "qscore", t("you_got") + " " + SCORE + " / " + total));
  d.appendChild(el("div", null, passed ? t("amazing") : t("effort"))); speak(passed ? t("amazing") : t("effort"));
  const retry = el("button", "btn " + (passed ? "ghost" : "primary"), t("again"));
  retry.style.marginTop = "14px"; retry.onclick = () => startQuiz(true);   // retry pulls a NEW random set
  d.appendChild(retry);
  if (passed) {
    const star = el("button", "btn primary", "My Math Awards"); star.style.marginTop = "10px";
    star.onclick = () => openAchievements("math");
    d.appendChild(star);
  }
  box.appendChild(d);
}

/* ---------- custom video player ---------- */
let _seeking = false;
function setupPlayer() {
  const v = $("#vid"), player = $("#player");
  const TOUCH = ("ontouchstart" in window) || (navigator.maxTouchPoints > 0);
  const toggle = () => { if (v.paused) v.play(); else v.pause(); };
  $("#playBtn").onclick = toggle;
  $("#bigplay").onclick = toggle;
  // On touch devices a tap on the video just reveals the controls (so kids can reach the
  // playback/caption settings) instead of instantly toggling play. The play button still toggles.
  v.addEventListener("click", () => { if (TOUCH) { player.classList.add("show"); kickHide(); } else toggle(); });
  v.addEventListener("play", () => { player.classList.add("playing", "show"); setPlayIcon(true); kickHide(); });
  v.addEventListener("pause", () => { player.classList.remove("playing"); player.classList.add("show"); setPlayIcon(false); });
  v.addEventListener("ended", () => {
    player.classList.remove("playing"); setPlayIcon(false);
    watchedFrac = 1;
    if (CUR) {
      fetch("/api/event", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: getSession(), id: CUR.id, kind: "finish" }) }).catch(() => {});
      // watching a video to the end marks it complete automatically - no manual click needed
      setVideoStatus(CUR.id, "complete");
      renderStatusButtons(CUR.id);
    }
  });
  v.addEventListener("timeupdate", updateProg);
  v.addEventListener("loadedmetadata", () => { $("#dur").textContent = fmt(v.duration); updateProg(); });
  v.addEventListener("volumechange", setMuteIcon);
  const seek = $("#seek");
  seek.addEventListener("pointerdown", e => { _seeking = true; try { seek.setPointerCapture(e.pointerId); } catch (x) {} doSeek(e); });
  seek.addEventListener("pointermove", e => { if (_seeking) doSeek(e); });
  seek.addEventListener("pointerup", () => { _seeking = false; });
  $("#muteBtn").onclick = () => { v.muted = !v.muted; };
  $("#ccBtn").onclick = toggleCC;
  $("#fsBtn").onclick = toggleFs;
  let hideT;
  // keep controls up much longer on touch, and never auto-hide while the settings popover is open
  function kickHide() {
    clearTimeout(hideT);
    hideT = setTimeout(() => {
      if (!v.paused && $("#settings").classList.contains("hidden")) player.classList.remove("show");
    }, TOUCH ? 6000 : 2500);
  }
  player.addEventListener("mousemove", () => { player.classList.add("show"); kickHide(); });
  player.addEventListener("touchstart", () => { player.classList.add("show"); kickHide(); }, { passive: true });
  player.addEventListener("mouseleave", () => { if (!v.paused) player.classList.remove("show"); });
  document.addEventListener("keydown", e => {
    if ($("#lesson").classList.contains("hidden")) return;
    if (e.target && e.target.tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); toggle(); }
  });
  // caption settings popover
  $("#setBtn").onclick = e => { e.stopPropagation(); $("#settings").classList.toggle("hidden"); };
  document.addEventListener("click", e => {
    const s = $("#settings");
    if (!s.classList.contains("hidden") && !s.contains(e.target) && !$("#setBtn").contains(e.target))
      s.classList.add("hidden");
  });
  const cl = $("#capLang"); cl.innerHTML = "";
  Object.keys(LANGS).forEach(c => { const o = el("option", null, LANGS[c]); o.value = c; if (c === captionLang) o.selected = true; cl.appendChild(o); });
  cl.onchange = e => setCaptionLang(e.target.value);
  document.querySelectorAll(".sizebtn").forEach(b => b.onclick = () => {
    cueSize = b.dataset.size; localStorage.setItem("cap_size", cueSize); applyCueSize();
  });
  applyCueSize();
}
function resetPlayer() {
  watchedFrac = 0;
  $("#player").classList.remove("playing", "show"); setPlayIcon(false);
  $("#prog").style.width = "0%"; $("#knob").style.left = "0%";
  $("#cur").textContent = "0:00"; $("#dur").textContent = "0:00";
  $("#ccBtn").classList.toggle("on", ccOn);
  // clear any caption left over from the previous video - we own this element now, so
  // nothing else wipes it when the source changes
  const cap = $("#capOverlay");
  if (cap) { cap.textContent = ""; cap.classList.add("hidden"); }
}
function setPlayIcon(playing) {
  $("#playBtn").innerHTML = playing
    ? '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M7 5h3.4v14H7zM13.6 5H17v14h-3.4z" fill="currentColor"/></svg>'
    : '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>';
}
function setMuteIcon() {
  const v = $("#vid");
  $("#muteBtn").innerHTML = (v.muted || v.volume === 0)
    ? '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 9v6h4l5 5V4L8 9H4z" fill="currentColor"/><path d="M16.5 9.5l4 5M20.5 9.5l-4 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
    : '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 9v6h4l5 5V4L8 9H4z" fill="currentColor"/><path d="M15.5 8.8a4 4 0 0 1 0 6.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
}
function updateProg() {
  const v = $("#vid"); const p = v.duration ? v.currentTime / v.duration : 0;
  if (p > watchedFrac) watchedFrac = p;
  $("#prog").style.width = (p * 100) + "%"; $("#knob").style.left = (p * 100) + "%";
  $("#cur").textContent = fmt(v.currentTime);
}
function doSeek(e) {
  const v = $("#vid"); const r = $("#seek").getBoundingClientRect();
  let x = (e.clientX - r.left) / r.width; x = Math.max(0, Math.min(1, x));
  if (v.duration) { v.currentTime = x * v.duration; updateProg(); }
}
function fmt(s) { s = Math.floor(s || 0); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
/* ---------- captions ----------
   We paint captions ourselves into #capOverlay instead of letting the browser render the
   text track, for three reasons the native path could not solve:
     - Chrome does not reliably honour an author `::cue { font-size }`, so the size
       control did nothing (captions stayed at the UA default regardless of the setting).
     - Native cues are painted at the very bottom of the video box, underneath our custom
       control bar, so the text collided with the scrubber.
     - Sizing is now driven by the PLAYER'S OWN WIDTH via container-query units in CSS
       (see .cap-overlay), so it scales on a phone, a tablet, a laptop and a projector
       alike, and is immune to the vh/zoom trap that bites viewport units in this app.
   track.mode = "hidden" is the key: it keeps the cues parsed and keeps `cuechange`
   firing, while suppressing the browser's own rendering. */
function stripVtt(s) {
  // cue payloads can carry voice/style tags (<v Narrator>, <i>, <c.loud>) and entities
  return String(s || "")
    .replace(/<[^>]*>/g, "")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ")
    .trim();
}
function renderCue() {
  const box = $("#capOverlay"); if (!box) return;
  const tt = $("#vid").textTracks[0];
  if (!ccOn || !tt) { box.textContent = ""; box.classList.add("hidden"); return; }
  const cues = tt.activeCues;
  const text = cues && cues.length
    ? [].slice.call(cues).map(c => stripVtt(c.text)).filter(Boolean).join("\n") : "";
  box.textContent = text;
  box.classList.toggle("hidden", !text);
}
function toggleCC() {
  ccOn = !ccOn;
  const tt = $("#vid").textTracks[0];
  if (tt) tt.mode = ccOn ? "hidden" : "disabled";   // "hidden" = parsed but not UA-drawn
  $("#ccBtn").classList.toggle("on", ccOn);
  renderCue();
}
function loadTrack() {
  const v = $("#vid");
  [].slice.call(v.querySelectorAll("track")).forEach(tr => tr.remove());
  const tr = document.createElement("track");
  tr.kind = "subtitles"; tr.srclang = captionLang; tr.label = LANGS[captionLang] || "CC";
  tr.src = "/api/subs/" + CUR.id + "?lang=" + captionLang; tr.default = true;
  v.appendChild(tr);
  renderCue();
  setTimeout(() => {
    const tt = v.textTracks[0];
    if (!tt) return;
    tt.mode = ccOn ? "hidden" : "disabled";
    tt.oncuechange = renderCue;
    renderCue();
  }, 350);
}
function setCaptionLang(l) {
  captionLang = l; localStorage.setItem("cap_lang", l);
  if (CUR) loadTrack();
}
/* Size is a CSS-side multiplier now (see .player[data-cap]); this only records the
   choice and reflects it on the picker buttons. */
function applyCueSize() {
  const p = $("#player"); if (p) p.dataset.cap = cueSize;
  document.querySelectorAll(".sizebtn").forEach(b => b.classList.toggle("on", b.dataset.size === cueSize));
}
function toggleFs() {
  const p = $("#player");
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    (document.exitFullscreen || document.webkitExitFullscreen).call(document);
  } else if (p.requestFullscreen) { p.requestFullscreen(); }
  else if (p.webkitRequestFullscreen) { p.webkitRequestFullscreen(); }
  else if ($("#vid").webkitEnterFullscreen) { $("#vid").webkitEnterFullscreen(); }
}

init();
