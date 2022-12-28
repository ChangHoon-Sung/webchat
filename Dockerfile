FROM python:3.10

# Install dependencies
COPY ./requirements.txt /app/requirements.txt

WORKDIR /app

RUN pip install -r requirements.txt

COPY ./server /app

COPY ./index.html /app

# Run the application
CMD ["python", "app.py"]