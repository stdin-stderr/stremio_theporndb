FROM python:3.13-alpine
RUN apk add --no-cache gcc musl-dev libffi-dev
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
CMD ["uvicorn", "src.addon:app", "--host", "0.0.0.0", "--port", "7000"]
