FROM ubuntu:latest

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy your project
WORKDIR /app
COPY . .

# Install requirements
RUN pip install --break-system-packages -r requirements.txt

EXPOSE 8000
CMD ["uvicorn", "feed.wsgi:application", "--host", "0.0.0.0", "--port", "8000"]

