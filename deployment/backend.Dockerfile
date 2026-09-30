FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements-minimal.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
COPY ml /app/ml
COPY frontend /app/frontend
COPY demo /app/demo
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
