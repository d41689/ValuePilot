FROM python:3.11-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 9000

# Exec-form CMD: uvicorn is PID 1 and receives SIGTERM directly on `docker
# stop` — a clean shutdown, no shell swallowing the signal.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
