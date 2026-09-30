FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements-minimal.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
COPY frontend /app/frontend
ENV PYTHONPATH=/app
EXPOSE 3000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "3000"]
