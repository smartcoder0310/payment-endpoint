"""Entry point for `flask run` and for a WSGI server."""

from dotenv import load_dotenv

from app import create_app

load_dotenv()

app = create_app()
