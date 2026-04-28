FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY app.py .
COPY cleaner.py .
COPY sheets.py .

# Streamlit config
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV STREAMLIT_THEME_BASE=dark

# Mount point for credentials (local) — override with env var in cloud
VOLUME ["/app/credentials"]

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.headless=true"]
