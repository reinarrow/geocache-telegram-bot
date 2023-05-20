FROM python:3.8-slim-buster

WORKDIR /app

# Copy only the requirements.txt first, for separate dependency resolving and downloading
COPY app/requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code into the container
COPY app .

# Start the bot using the command you normally use
CMD ["python", "GeocacheAlcalaBot.py"]