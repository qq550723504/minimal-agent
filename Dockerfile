FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY src /app/src
COPY plugins /app/plugins
COPY demos /app/demos
EXPOSE 8000
ENV AGENT_ENABLE_MEMORY=true
ENV VECTOR_MEMORY_PATH=/app/vector_memory.json
CMD ["uvicorn", "src.agent.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
