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

PROJECT_DIR = Path(r"C:\Users\Yash\Desktop\Data Science").resolve()

# Wait this many seconds after the LAST detected change.
DEBOUNCE_SECONDS = 45

# Only these file types trigger an automatic backup.
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

# File extensions that commonly contain private keys/certificates.
SENSITIVE_EXTENSIONS = {
    ".pem",
    ".key",
}


# ============================================================
# GLOBAL STATE
# ============================================================

timer = None
timer_lock = threading.Lock()

# Prevent two backup operations from running at the same time.
backup_lock = threading.Lock()


# ============================================================
# PATH / FILE HELPERS
# ============================================================

def normalize_path(path):
    """
    Convert a watchdog event path into a pathlib.Path object.

    Watchdog normally gives us strings on Windows, while the
    rest of this script uses pathlib.Path.
    """
    return Path(path).resolve()


def is_ignored(path) -> bool:
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


def is_watched_file(path) -> bool:
    """
    Return True only for .py and .ipynb files that are not
    inside an ignored directory.
    """

    path = normalize_path(path)

    if is_ignored(path):
        return False

    return path.suffix.lower() in WATCHED_EXTENSIONS


# ============================================================
# SECURITY CHECK
# ============================================================

def contains_sensitive_file():
    """
    Search the project for obvious sensitive files.

    This is an additional safety layer.
    .gitignore remains the primary protection.
    """

    for root, dirs, files in os.walk(PROJECT_DIR):

        # Don't walk through directories that should be ignored.
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in IGNORED_DIRECTORIES
        ]

        for filename in files:

            file_path = Path(root) / filename

            # Check exact sensitive filenames.
            if filename in SENSITIVE_FILE_NAMES:
                return True, file_path

            # Check sensitive extensions.
            if file_path.suffix.lower() in SENSITIVE_EXTENSIONS:
                return True, file_path

    return False, None


# ============================================================
# GIT FUNCTIONS
# ============================================================

def run_git_command(args):
    """
    Run a Git command inside the project directory.

    Returns the subprocess result.
    """

    command_display = "git " + " ".join(args)

    print(f"\n> {command_display}")

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

        print("ERROR: Git command timed out.")

        return None

    except FileNotFoundError:

        print(
            "ERROR: Git was not found."
            "\nMake sure Git is installed and available in PATH."
        )

        return None

    if result.stdout.strip():
        print(result.stdout.strip())

    if result.stderr.strip():
        print(result.stderr.strip())

    return result


# ============================================================
# BACKUP OPERATION
# ============================================================

def perform_backup():

    global timer

    with timer_lock:
        timer = None

    # Prevent overlapping backup operations.
    if not backup_lock.acquire(blocking=False):

        print(
            "\nA backup operation is already running."
            "\nSkipping this backup trigger."
        )

        return

    try:

        print("\n" + "=" * 60)
        print("CHANGE DETECTED")
        print("Preparing automatic Git backup...")
        print("=" * 60)

        # ----------------------------------------------------
        # SECURITY CHECK
        # ----------------------------------------------------

        sensitive_found, sensitive_path = contains_sensitive_file()

        if sensitive_found:

            print("\n" + "!" * 60)
            print("SECURITY STOP")
            print("!" * 60)

            print(
                "\nA potentially sensitive file was found:"
            )

            print(f"  {sensitive_path}")

            print(
                "\nAutomatic commit has been cancelled."
            )

            print(
                "Check your .gitignore and remove/move the "
                "sensitive file if necessary."
            )

            print("!" * 60)

            return

        # ----------------------------------------------------
        # CHECK GIT STATUS
        # ----------------------------------------------------

        status = run_git_command(
            ["status", "--porcelain"]
        )

        if status is None:
            print("ERROR: Git status could not be executed.")
            return

        if status.returncode != 0:

            print(
                "\nERROR: Git status returned an error."
            )

            return

        # No changes means there is nothing to commit.
        if not status.stdout.strip():

            print(
                "\nNo Git changes found."
                "\nNothing to commit."
            )

            return

        # ----------------------------------------------------
        # STAGE CHANGES
        # ----------------------------------------------------

        print("\nStaging changes...")

        add_result = run_git_command(
            ["add", "."]
        )

        if add_result is None:

            print("ERROR: git add could not be executed.")

            return

        if add_result.returncode != 0:

            print(
                "\nERROR: git add failed."
            )

            return

        # ----------------------------------------------------
        # CHECK STAGED FILES
        # ----------------------------------------------------

        staged = run_git_command(
            [
                "diff",
                "--cached",
                "--name-only",
            ]
        )

        if staged is None:

            print(
                "ERROR: Could not inspect staged changes."
            )

            return

        if staged.returncode != 0:

            print(
                "ERROR: Git could not inspect staged changes."
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
                "\nNo commit will be created."
            )

            return

        print(
            "\nFiles staged for automatic backup:"
        )

        for filename in staged_files:

            print(f"  + {filename}")

        # ----------------------------------------------------
        # CREATE COMMIT
        # ----------------------------------------------------

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        commit_message = (
            f"Auto-save: {timestamp}"
        )

        print(
            f"\nCreating commit:"
            f"\n{commit_message}"
        )

        commit_result = run_git_command(
            [
                "commit",
                "-m",
                commit_message,
            ]
        )

        if commit_result is None:

            print(
                "ERROR: git commit could not be executed."
            )

            return

        if commit_result.returncode != 0:

            print(
                "\nERROR: git commit failed."
            )

            print(
                "\nYour changes may still be staged."
            )

            print(
                "Run 'git status' to inspect them."
            )

            return

        # ----------------------------------------------------
        # PUSH TO GITHUB
        # ----------------------------------------------------

        print(
            "\nPushing commit to GitHub..."
        )

        push_result = run_git_command(
            ["push"]
        )

        if push_result is None:

            print(
                "\nERROR: git push could not be executed."
            )

            print(
                "The commit exists locally."
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
                "\nbut it may not be on GitHub."
            )

            print(
                "\nRun:"
            )

            print(
                "  git status"
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

        print("\n" + "=" * 60)
        print("AUTOMATIC GIT BACKUP SUCCESSFUL")
        print("=" * 60)

        print(
            f"\nCommit:"
            f"\n  {commit_message}"
        )

        print(
            "\nChanges have been pushed to GitHub."
        )

        print("=" * 60)

    finally:

        backup_lock.release()


# ============================================================
# FILE EVENT HANDLER
# ============================================================

class ChangeHandler(FileSystemEventHandler):

    def schedule_backup(self, path):

        path = normalize_path(path)

        # Ignore everything except .py and .ipynb files.
        if not is_watched_file(path):
            return

        try:

            relative_path = path.relative_to(
                PROJECT_DIR
            )

        except ValueError:

            return

        print(
            f"\nDetected change:"
            f"\n  {relative_path}"
        )

        global timer

        with timer_lock:

            # Cancel the previous timer.
            if timer is not None:
                timer.cancel()

            # Start a fresh debounce timer.
            timer = threading.Timer(
                DEBOUNCE_SECONDS,
                perform_backup
            )

            timer.daemon = True

            timer.start()

        print(
            f"Backup scheduled in "
            f"{DEBOUNCE_SECONDS} seconds "
            f"after the last change."
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
    # Verify project directory
    # --------------------------------------------------------

    if not PROJECT_DIR.exists():

        print(
            "ERROR: Project directory does not exist:"
        )

        print(PROJECT_DIR)

        return

    # --------------------------------------------------------
    # Verify Git repository
    # --------------------------------------------------------

    git_directory = PROJECT_DIR / ".git"

    if not git_directory.exists():

        print(
            "ERROR: This folder is not a Git repository:"
        )

        print(PROJECT_DIR)

        print(
            "\nRun 'git init' first."
        )

        return

    # --------------------------------------------------------
    # Startup information
    # --------------------------------------------------------

    print("=" * 60)

    print(
        "DATA SCIENCE GIT AUTO-BACKUP WATCHER"
    )

    print("=" * 60)

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
        "\n  IDE folders"
    )

    print(
        "\nPress Ctrl+C to stop the watcher."
    )

    print("=" * 60)

    # --------------------------------------------------------
    # Start watchdog observer
    # --------------------------------------------------------

    event_handler = ChangeHandler()

    observer = Observer()

    observer.schedule(
        event_handler,
        str(PROJECT_DIR),
        recursive=True
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

        # Cancel pending debounce timer.
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
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()