#!/usr/bin/env python3
"""
Entry point — scoring.

    python run_grader.py --quick     fast subset, for iterating
    python run_grader.py --full      everything; the only mode that can unlock

Run from the project root so imports resolve.
"""

from dotenv import load_dotenv

load_dotenv()

from grader.grade import main  # noqa: E402

if __name__ == "__main__":
    main()
