# Sanitization / privacy check

This packaged project contains only synthetic demo names and synthetic programming questions.

Before packaging, the repository was checked for common personal-data and secret patterns, including:

- personal names previously associated with the requester
- email addresses and local user-home paths
- populated `.env` files
- API-key-like strings and private-key headers
- SQLite/database artifacts containing runtime student data

Only `.env.example` is included, and its `GEMINI_API_KEY` value is blank. Runtime database files are ignored by `.gitignore` and are not included in the ZIP.
