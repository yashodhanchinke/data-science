import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_DIR = Path(
    r"C:\Users\Yash\Desktop\Data Science"
).resolve()

# Wait this many seconds after the LAST detected save.
DEBOUNCE_SECONDS = 45

# Only these file types trigger automatic backup.
WATCHED_EXTENSIONS = {
    ".py",
    ".ipynb",
}

# Directories that should never trigger the watcher.
IGNORED_DIRECTORIES = {
    ".git",
    ".ipynb_checkpoints",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "ENV",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# Jupyter/editor temporary files.
TEMP_FILE_PREFIXES = (
    ".~",
)

TEMP_FILE_SUFFIXES = (
    "~",
    ".tmp",
    ".temp",
    ".swp",
    ".swo",
)

# Files that should never be automatically committed.
SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
    "secrets.json",
    "credentials.yaml",
    "credentials.yml",
    "secrets.yaml",
    "secrets.yml",
}

# File extensions that commonly contain private keys.
SENSITIVE_EXTENSIONS = {
    ".pem",
    ".key",
}


# ============================================================
# GLOBAL STATE
# ============================================================

timer = None
timer_lock = threading.Lock()

# Prevent overlapping Git operations.
backup_lock = threading.Lock()


# ============================================================
# PATH HELPERS
# ============================================================

def normalize_path(path):
    """
    Convert watchdog's path into pathlib.Path.
    """

    return Path(path).resolve()


def is_ignored_directory(path):
    """
    Return True if the path is inside an ignored directory.
    """

    path = normalize_path(path)

    try:
        relative_path = path.relative_to(PROJECT_DIR)

    except ValueError:
        return True

    for part in relative_path.parts:

        if part in IGNORED_DIRECTORIES:
            return True

    return False


def is_temporary_file(path):
    """
    Ignore temporary files created by Jupyter/editors.
    """

    path = normalize_path(path)

    filename = path.name

    # Example:
    # .~Python_Fundamentals.ipynb
    for prefix in TEMP_FILE_PREFIXES:

        if filename.startswith(prefix):
            return True

    # Examples:
    # Python_Fundamentals.ipynb~
    # Python_Fundamentals.ipynb.tmp
    for suffix in TEMP_FILE_SUFFIXES:

        if filename.endswith(suffix):
            return True

    return False


def is_watched_file(path):
    """
    Return True only for real .py and .ipynb files.
    """

    path = normalize_path(path)

    if is_ignored_directory(path):
        return False

    if is_temporary_file(path):
        return False

    return path.suffix.lower() in WATCHED_EXTENSIONS


# ============================================================
# SECURITY
# ============================================================

def contains_sensitive_file():
    """
    Check the project for obvious sensitive files.

    This is an additional safety layer.
    .gitignore remains the primary protection.
    """

    for root, dirs, files in os.walk(PROJECT_DIR):

        # Don't enter ignored directories.
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in IGNORED_DIRECTORIES
        ]

        for filename in files:

            file_path = Path(root) / filename

            if filename in SENSITIVE_FILE_NAMES:

                return True, file_path

            if file_path.suffix.lower() in SENSITIVE_EXTENSIONS:

                return True, file_path

    return False, None


# ============================================================
# GIT
# ============================================================

def run_git(args):
    """
    Run a Git command inside the project directory.
    """

    print(
        "\n> git " + " ".join(args)
    )

    try:

        result = subprocess.run(
            ["git"] + args,
            cwd=PROJECT_DIR,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

    except subprocess.TimeoutExpired:

        print(
            "ERROR: Git command timed out."
        )

        return None

    except FileNotFoundError:

        print(
            "ERROR: Git was not found in PATH."
        )

        return None

    if result.stdout.strip():

        print(
            result.stdout.strip()
        )

    if result.stderr.strip():

        print(
            result.stderr.strip()
        )

    return result


# ============================================================
# BACKUP OPERATION
# ============================================================

def perform_backup():

    global timer

    with timer_lock:

        timer = None

    # Don't run two backups simultaneously.
    if not backup_lock.acquire(
        blocking=False
    ):

        print(
            "\nBackup already running."
        )

        return

    try:

        print(
            "\n" + "=" * 60
        )

        print(
            "PREPARING AUTOMATIC GIT BACKUP"
        )

        print(
            "=" * 60
        )

        # ----------------------------------------------------
        # SECURITY CHECK
        # ----------------------------------------------------

        sensitive_found, sensitive_path = (
            contains_sensitive_file()
        )

        if sensitive_found:

            print(
                "\n" + "!" * 60
            )

            print(
                "SECURITY STOP"
            )

            print(
                "!" * 60
            )

            print(
                "\nPotentially sensitive file found:"
            )

            print(
                f"  {sensitive_path}"
            )

            print(
                "\nAutomatic commit cancelled."
            )

            print(
                "Check your .gitignore before continuing."
            )

            print(
                "!" * 60
            )

            return

        # ----------------------------------------------------
        # CHECK GIT STATUS
        # ----------------------------------------------------

        status = run_git(
            [
                "status",
                "--porcelain",
            ]
        )

        if status is None:
            return

        if status.returncode != 0:

            print(
                "\nERROR: git status failed."
            )

            return

        if not status.stdout.strip():

            print(
                "\nNo Git changes found."
            )

            return

        # ----------------------------------------------------
        # FIND RELEVANT CHANGED FILES
        # ----------------------------------------------------

        changed_files = []

        for line in status.stdout.splitlines():

            if len(line) < 4:
                continue

            filename = line[3:].strip()

            # Handle Git rename output:
            #
            # old.py -> new.py
            #
            if " -> " in filename:

                filename = filename.split(
                    " -> "
                )[-1]

            file_path = (
                PROJECT_DIR / filename
            ).resolve()

            if is_watched_file(file_path):

                changed_files.append(
                    filename
                )

        if not changed_files:

            print(
                "\nNo .py or .ipynb changes "
                "require an automatic backup."
            )

            return

        print(
            "\nRelevant changed files:"
        )

        for filename in changed_files:

            print(
                f"  - {filename}"
            )

        # ----------------------------------------------------
        # STAGE ONLY RELEVANT FILES
        # ----------------------------------------------------

        print(
            "\nStaging relevant files..."
        )

        add_result = run_git(
            [
                "add",
                "--",
                *changed_files,
            ]
        )

        if add_result is None:

            return

        if add_result.returncode != 0:

            print(
                "\nERROR: git add failed."
            )

            return

        # ----------------------------------------------------
        # CHECK STAGED FILES
        # ----------------------------------------------------

        staged = run_git(
            [
                "diff",
                "--cached",
                "--name-only",
            ]
        )

        if staged is None:
            return

        if staged.returncode != 0:

            print(
                "\nERROR: Could not inspect staged changes."
            )

            return

        staged_files = [
            line.strip()
            for line in staged.stdout.splitlines()
            if line.strip()
        ]

        if not staged_files:

            print(
                "\nNothing was staged."
            )

            return

        print(
            "\nFiles staged:"
        )

        for filename in staged_files:

            print(
                f"  + {filename}"
            )

        # ----------------------------------------------------
        # COMMIT
        # ----------------------------------------------------

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        commit_message = (
            f"Auto-save: {timestamp}"
        )

        print(
            "\nCreating commit:"
        )

        print(
            f"  {commit_message}"
        )

        commit_result = run_git(
            [
                "commit",
                "-m",
                commit_message,
            ]
        )

        if commit_result is None:
            return

        if commit_result.returncode != 0:

            print(
                "\nERROR: Git commit failed."
            )

            print(
                "Run 'git status' to inspect the repository."
            )

            return

        # ----------------------------------------------------
        # PUSH
        # ----------------------------------------------------

        print(
            "\nPushing commit to GitHub..."
        )

        push_result = run_git(
            [
                "push",
            ]
        )

        if push_result is None:

            print(
                "\nCommit exists locally."
            )

            return

        if push_result.returncode != 0:

            print(
                "\n" + "!" * 60
            )

            print(
                "PUSH FAILED"
            )

            print(
                "!" * 60
            )

            print(
                "\nThe commit exists locally,"
            )

            print(
                "but it may not be on GitHub."
            )

            print(
                "\nYou can retry later with:"
            )

            print(
                "  git push"
            )

            print(
                "!" * 60
            )

            return

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print(
            "\n" + "=" * 60
        )

        print(
            "AUTOMATIC GIT BACKUP SUCCESSFUL"
        )

        print(
            "=" * 60
        )

        print(
            f"\nCommit:"
            f"\n  {commit_message}"
        )

        print(
            "\nPushed successfully to GitHub."
        )

        print(
            "=" * 60
        )

    finally:

        backup_lock.release()


# ============================================================
# FILE EVENT HANDLER
# ============================================================

class ChangeHandler(
    FileSystemEventHandler
):

    def schedule_backup(self, path):

        path = normalize_path(path)

        # Ignore everything except real .py/.ipynb files.
        if not is_watched_file(path):

            return

        try:

            relative_path = (
                path.relative_to(
                    PROJECT_DIR
                )
            )

        except ValueError:

            return

        print(
            "\nDetected save:"
        )

        print(
            f"  {relative_path}"
        )

        global timer

        with timer_lock:

            # Reset the previous timer.
            if timer is not None:

                timer.cancel()

            timer = threading.Timer(
                DEBOUNCE_SECONDS,
                perform_backup,
            )

            timer.daemon = True

            timer.start()

        print(
            f"Backup scheduled in "
            f"{DEBOUNCE_SECONDS} seconds "
            f"after the last save."
        )

    def on_modified(self, event):

        if not event.is_directory:

            self.schedule_backup(
                event.src_path
            )

    def on_created(self, event):

        if not event.is_directory:

            self.schedule_backup(
                event.src_path
            )

    def on_moved(self, event):

        if not event.is_directory:

            self.schedule_backup(
                event.dest_path
            )


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # Check project directory
    # --------------------------------------------------------

    if not PROJECT_DIR.exists():

        print(
            "ERROR: Project directory does not exist:"
        )

        print(
            PROJECT_DIR
        )

        return

    # --------------------------------------------------------
    # Check Git repository
    # --------------------------------------------------------

    if not (
        PROJECT_DIR / ".git"
    ).exists():

        print(
            "ERROR: Git repository not found."
        )

        print(
            PROJECT_DIR
        )

        return

    # --------------------------------------------------------
    # Startup information
    # --------------------------------------------------------

    print(
        "=" * 60
    )

    print(
        "DATA SCIENCE GIT AUTO-BACKUP WATCHER"
    )

    print(
        "=" * 60
    )

    print(
        f"Project:"
        f"\n  {PROJECT_DIR}"
    )

    print(
        f"\nDebounce:"
        f"\n  {DEBOUNCE_SECONDS} seconds"
    )

    print(
        "\nWatching:"
        "\n  .py"
        "\n  .ipynb"
    )

    print(
        "\nIgnoring:"
        "\n  .git"
        "\n  .ipynb_checkpoints"
        "\n  __pycache__"
        "\n  virtual environments"
        "\n  IDE files"
        "\n  Jupyter temporary files"
    )

    print(
        "\nPress Ctrl+C to stop the watcher."
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # Start watchdog
    # --------------------------------------------------------

    event_handler = ChangeHandler()

    observer = Observer()

    observer.schedule(
        event_handler,
        str(PROJECT_DIR),
        recursive=True,
    )

    observer.start()

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        print(
            "\n\nStopping watcher..."
        )

        observer.stop()

        with timer_lock:

            if timer is not None:

                timer.cancel()

                timer = None

    finally:

        observer.join()

        print(
            "Watcher stopped."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()