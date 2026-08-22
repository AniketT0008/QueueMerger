"""Streamlit Community Cloud default entrypoint.

Cloud often defaults to streamlit_app.py — keep this thin wrapper so either
main-file setting works.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "ui_streamlit.py"), run_name="__main__")
