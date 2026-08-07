FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
ENV AGENT_ENABLE_MEMORY=true
ENV VECTOR_MEMORY_PATH=/app/vector_memory.json
CMD ["uvicorn", "src.agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
