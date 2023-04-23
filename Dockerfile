FROM python:3.8-slim-buster

WORKDIR /app

# Copy the requirements file and install the dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the source code into the container
COPY . .

# Start the bot using the command you normally use
CMD ["python", "GeocacheAlcalaBot.py"]