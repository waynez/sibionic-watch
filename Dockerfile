FROM python:3.12
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt --progress-bar off
CMD ["python", "./process.py"]
