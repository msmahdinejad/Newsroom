"""Telegram bot command handlers for newsroom.

These handlers process commands from the configured allowlist.
Only news-report functionality - no technical/engineering commands.
"""

import json
import os
import subprocess
import sys
import time

# Project paths
PROJECT_DIR = r"[REDACTED]\OneDrive\Desktop\newsroom"
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))

# Pipeline lock file
LOCK_FILE = os.path.join(PROJECT_DIR, ".pipeline.lock")

# Cooldown: 10 minutes between manual reports
COOLDOWN_SECONDS = 600
COOLDOWN_FILE = os.path.join(PROJECT_DIR, ".manual_cooldown")


def acquire_lock():
    """Try to acquire pipeline lock. Returns True if acquired."""
    if os.path.exists(LOCK_FILE):
        # Check if lock is stale (older than 5 minutes)
        try:
            mtime = os.path.getmtime(LOCK_FILE)
            if time.time() - mtime > 300:
                os.remove(LOCK_FILE)
            else:
                return False
        except OSError:
            return False
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except OSError:
        return False


def release_lock():
    """Release the pipeline lock."""
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def check_cooldown():
    """Check if manual report is in cooldown. Returns (can_run, remaining_seconds)."""
    if not os.path.exists(COOLDOWN_FILE):
        return True, 0
    try:
        mtime = os.path.getmtime(COOLDOWN_FILE)
        elapsed = time.time() - mtime
        if elapsed >= COOLDOWN_SECONDS:
            return True, 0
        return False, int(COOLDOWN_SECONDS - elapsed)
    except OSError:
        return True, 0


def set_cooldown():
    """Set the manual report cooldown."""
    try:
        with open(COOLDOWN_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def run_pipeline_and_deliver():
    """Run the full pipeline and deliver to Telegram."""
    if not acquire_lock():
        return "خطا: خط لوله در حال اجراست. لطفاً کمی بعد تلاش کنید."

    try:
        result = subprocess.run(
            [sys.executable, os.path.join(PROJECT_DIR, "scripts", "run_pipeline.py")],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=PROJECT_DIR,
            env={**os.environ, "NEWSROOM_JOB_ID": "manual"},
        )

        if result.returncode != 0:
            return "خطا در اجرای خط لوله. لطفاً دوباره تلاش کنید."

        # Parse output
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line.strip().startswith("{") and '"status"' in line:
                data = json.loads(line.strip())
                if data.get("status") == "ok_empty":
                    return "خبر جدیدی در این دوره یافت نشد."
                if data.get("status") == "ok":
                    digest_id = data.get("report_id")
                    if digest_id:
                        set_cooldown()
                        return f"گزارش شماره {digest_id} تولید و ارسال شد."
        return "گزارش با موفقیت ارسال شد."
    except subprocess.TimeoutExpired:
        return "خطا: زمان اجرای خط لوله به پایان رسید."
    except Exception:
        return "خطا در تولید گزارش."
    finally:
        release_lock()


def get_latest_digest():
    """Get the latest delivered digest content."""
    from sqlalchemy.orm import Session

    from newsroom.storage.database import engine
    from newsroom.storage.models import Digest

    session = Session(engine)
    try:
        digest = session.query(Digest).filter_by(delivered=True).order_by(
            Digest.id.desc()
        ).first()
        if digest:
            return digest.content_fa
        return "هیچ گزارشی هنوز تولید نشده است."
    finally:
        session.close()


def handle_report():
    """Handle /report command - generate report since last scheduled run."""
    can_run, remaining = check_cooldown()
    if not can_run:
        mins = remaining // 60
        secs = remaining % 60
        return f"لطفاً {mins} دقیقه و {secs} ثانیه صبر کنید."

    ack = "در حال تولید گزارش فوری..."
    result = run_pipeline_and_deliver()
    return f"{ack}\n\n{result}"


def handle_report_new():
    """Handle /report new - only genuinely new material."""
    can_run, remaining = check_cooldown()
    if not can_run:
        mins = remaining // 60
        secs = remaining % 60
        return f"لطفاً {mins} دقیقه و {secs} ثانیه صبر کنید."

    result = run_pipeline_and_deliver()
    return result


def handle_report_comprehensive():
    """Handle /report comprehensive - broad briefing."""
    can_run, remaining = check_cooldown()
    if not can_run:
        mins = remaining // 60
        secs = remaining % 60
        return f"لطفاً {mins} دقیقه و {secs} ثانیه صبر کنید."

    result = run_pipeline_and_deliver()
    return f"گزارش جامع:\n\n{result}"


def handle_latest():
    """Handle /latest - return latest successful report."""
    return get_latest_digest()


def handle_help():
    """Handle /help - show available commands."""
    return (
        "راهنمای گزارش‌های خبری\n\n"
        "/report - گزارش فوری از آخرین اخبار\n"
        "/report new - فقط اخبار کاملاً جدید\n"
        "/report comprehensive - گزارش جامع فعلی\n"
        "/latest - آخرین گزارش تولید شده\n"
        "/help - این راهنما\n\n"
        "زمان‌بندی خودکار:\n"
        "صبح: ۰۹:۰۰\n"
        "عصر: ۱۵:۰۰\n"
        "شب: ۲۱:۰۰\n"
        "(همه به وقت تهران)"
    )
