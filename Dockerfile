# One image definition, two lightweight serving targets.
#   docker build --target api       -t planalyst-api .
#   docker build --target dashboard -t planalyst-dashboard .
# The API healthcheck calls /ready, so "healthy" means the database is reachable too.
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY planalyst planalyst
COPY streamlit_app streamlit_app
COPY .streamlit .streamlit
COPY docs docs

FROM base AS api
RUN pip install ".[api]"
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/ready')"
CMD ["uvicorn", "planalyst.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS dashboard
RUN pip install ".[dashboard]"
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "streamlit_app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
