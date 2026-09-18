#!/usr/bin/env python3
"""
Entry point — interactive chatbot.

    python run_chatbot.py

Run from the project root so imports resolve.
"""

from dotenv import load_dotenv

load_dotenv()

from agent.chatbot import main  # noqa: E402

if __name__ == "__main__":
    main()