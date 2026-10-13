FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --uid 1000 --create-home bot && mkdir -p /app/data && chown -R bot:bot /app
USER bot

CMD ["python", "bot.py"]
