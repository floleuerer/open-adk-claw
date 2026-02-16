FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn playwright
RUN playwright install chromium

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
