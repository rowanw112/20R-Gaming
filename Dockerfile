# Use a lightweight Python image
FROM python:3.11-slim

# Install git so the bot can pull its own updates
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first (to cache the installation step)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your bot's code
COPY . .

# Command to start the bot (change main.py if your entry file is named differently)
CMD ["python", "main.py"]