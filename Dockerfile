FROM python:3.12-slim-bookworm

WORKDIR /app

RUN useradd --create-home appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY resources/ ./resources/

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:5000/')" || exit 1

CMD ["python", "-m", "src.app"]
