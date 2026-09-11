"""Decides which of a batch of emails are worth telling the user about. Batches
all candidates into one Groq call rather than one call per email -- classifying
10 emails individually would be 10x the latency and token cost for the same
decision.
"""
import logging
import re

from llm.groq_client import ask_groq, CLASSIFICATION_MODEL

logger = logging.getLogger(__name__)

IMPORTANCE_CRITERIA = (
    "genuine job hiring, recruiting, interview invitations or scheduling, job "
    "offers, or real follow-up related to a job application the user actually made"
)

# Job-scam spam is extremely common and easily mistaken for a genuine opportunity
# on subject/snippet alone -- explicitly telling the model what a scam looks like
# performs much better than just trusting it to know, given how close "important"
# and "obvious scam" both sit here from the same three fields (sender/subject/snippet).
SCAM_EXCLUSION_HINT = (
    "Exclude anything that looks like a scam or spam job posting, even if it mentions "
    "hiring or an offer. Signs of a scam: urgent/pressuring language ('immediate action "
    "needed', 'act now', 'limited slots'), a vague or unverifiable company name, "
    "unrealistic pay for minimal effort, generic mass-recruitment phrasing with no "
    "reference to an application the user actually made, requests for money or "
    "personal/financial details, or a sender email domain that doesn't match the "
    "company it claims to represent (e.g. claiming to be Amazon but sent from an "
    "unrelated or generic address).\n\n"
    "Also exclude automated job-board alert/digest emails -- these are mass "
    "recommendation emails, not personal outreach, EVEN IF they name a specific real "
    "company or role. Recognize these by the sender: LinkedIn Job Alerts, Indeed, "
    "Jobsora, Internshala, Wellfound, Naukri, Glassdoor, or any similar job "
    "board/aggregator platform, especially from a noreply/donotreply-style address. "
    "'Full Stack Engineer role at Accenture' sent FROM LinkedIn's automated alert "
    "system is a digest, not Accenture contacting the user, and must be excluded. "
    "Only include a message if it is a DIRECT, personal communication from an actual "
    "employer, recruiter, or hiring platform's own application-tracking system about "
    "the user's specific application, interview, or offer -- not a recommendation feed."
)


BATCH_PREVIEW_CHARS = 400  # per email -- a batch call classifies many at once, so
# each gets a longer look than the old 150-char snippet without letting the
# whole prompt balloon to N x MAX_BODY_CHARS.


def _summarize_for_prompt(emails: list[dict]) -> str:
    lines = []
    for i, email in enumerate(emails):
        preview = (email.get("body") or email.get("snippet", ""))[:BATCH_PREVIEW_CHARS]
        lines.append(
            f"{i + 1}. From: {email['sender']} | Subject: {email['subject']} | "
            f"Preview: {preview}"
        )
    return "\n".join(lines)


def classify_important_emails(emails: list[dict]) -> list[dict]:
    """Returns the subset of `emails` that look important by IMPORTANCE_CRITERIA,
    in the same order they were given. Empty input or an unreachable LLM both
    just return an empty list -- callers treat "couldn't check" and "nothing
    important" identically, since guessing wrong here means either an unnecessary
    interruption or a missed one, and erring toward silence is the safer default
    for a background process the user hasn't directly asked to run."""
    if not emails:
        return []

    prompt = (
        f"You are screening a user's email inbox for anything important related to: "
        f"{IMPORTANCE_CRITERIA}.\n\n"
        f"{SCAM_EXCLUSION_HINT}\n\n"
        f"EMAILS:\n{_summarize_for_prompt(emails)}\n\n"
        "Respond with ONLY a comma-separated list of the numbers that qualify as "
        "important AND genuine by that criteria (e.g. '1,3'), or the word NONE if "
        "none do. No other text."
    )

    reply, _ = ask_groq(prompt, model=CLASSIFICATION_MODEL)
    reply = reply.strip().upper()

    if "NONE" in reply or not reply:
        return []

    indices = [int(n) - 1 for n in re.findall(r"\d+", reply)]
    return [emails[i] for i in indices if 0 <= i < len(emails)]


def describe_important_emails(important_emails: list[dict]) -> str:
    if not important_emails:
        return ""
    parts = [f"an email from {e['sender'].split('<')[0].strip()} about \"{e['subject']}\"" for e in important_emails]
    return "; ".join(parts)


def describe_recent_emails(emails: list[dict]) -> str:
    """Same voice-friendly format as describe_important_emails, but for a plain,
    unfiltered list -- used when the user directly asks 'check my mail', which
    should read out what's actually in the inbox, not run it through the
    importance classifier the background poller uses to decide what's worth an
    unprompted interruption."""
    if not emails:
        return ""
    parts = [f"an email from {e['sender'].split('<')[0].strip()} about \"{e['subject']}\"" for e in emails]
    return "; ".join(parts)


def extract_application_update(email: dict) -> dict | None:
    """Pulls structured company/role/status out of an email already classified
    as important, for the job application tracker (memory/job_tracker.py).
    Returns None if a company name genuinely can't be determined -- better to
    skip tracking one email than to log a garbage/empty company name."""
    content = email.get("body") or email.get("snippet", "")
    prompt = (
        "This email was flagged as job/hiring related. Extract the company name, "
        "the role/position if mentioned, and the application status it reflects.\n\n"
        f"From: {email['sender']}\nSubject: {email['subject']}\nContent: {content}\n\n"
        "Status must be exactly one of: applied, interviewing, offer, rejected, other.\n"
        "- applied: confirms an application was received/submitted\n"
        "- interviewing: an interview is being scheduled, confirmed, or has happened\n"
        "- offer: a job offer\n"
        "- rejected: application was not successful\n"
        "- other: genuinely application-related but doesn't clearly fit the above\n\n"
        "Respond with EXACTLY this format on one line, nothing else:\n"
        "company: <name> | role: <role, or NONE if not mentioned> | status: <status>\n"
        "If you cannot determine a company name at all, respond with exactly: SKIP"
    )
    reply, _ = ask_groq(prompt, model=CLASSIFICATION_MODEL)
    reply = reply.strip()
    if not reply or reply.upper() == "SKIP":
        return None

    match = re.search(r"company:\s*(.+?)\s*\|\s*role:\s*(.+?)\s*\|\s*status:\s*(\w+)", reply, re.IGNORECASE)
    if not match:
        logger.warning("Could not parse application details from LLM reply: %r", reply)
        return None

    company, role, status = match.groups()
    company = company.strip()
    if not company:
        return None
    role = None if role.strip().upper() == "NONE" else role.strip()
    return {"company": company, "role": role, "status": status.strip().lower()}


def _track_applications(important_emails: list[dict]) -> None:
    """Best-effort: a failure here must never break the actual email check --
    the user announcement matters far more than the tracker staying current."""
    from memory.job_tracker import is_email_processed, mark_email_processed, upsert_application

    for email in important_emails:
        email_id = email.get("id")
        if email_id and is_email_processed(email_id):
            continue
        try:
            details = extract_application_update(email)
            if details:
                upsert_application(details["company"], details["role"], details["status"])
        except Exception as e:
            logger.warning("Failed to track application from email %r: %s", email_id, e)
        if email_id:
            mark_email_processed(email_id)


def check_for_important_emails(max_results: int = 10) -> list[dict]:
    """Shared by the on-demand tool, the background poller, and the morning alarm
    integration: fetch recent unread mail and return the subset worth surfacing."""
    from systems.gmail_client import fetch_recent_emails

    emails = fetch_recent_emails(max_results=max_results, unread_only=True)
    important = classify_important_emails(emails)
    _track_applications(important)
    return important
