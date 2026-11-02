# SOLVENT Localization MCP server — stdlib-only Python, no pip installs.
FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY data/ ./data/
# The translation backend is the SOLVENT free-LLM pool CLI (ask.py). In a
# container deployment, mount or bake the pool at ASK_PY, or set ASK_PY to a
# compatible CLI path. Glossary-only mode works with no backend at all.
ENV ASK_PY=/app/ask.py
EXPOSE 8787
CMD ["python3", "server.py", "--transport", "stdio"]
