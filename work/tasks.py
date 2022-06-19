from remote.celery import app
from celery import shared_task

@shared_task
@app.task
def add(x, y):
    return x + y

