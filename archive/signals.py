from django.contrib.postgres.search import SearchVector
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Message


@receiver(post_save, sender=Message)
def update_search_vector(sender, instance, **kwargs):
    # Avoid recursion: update through a queryset, not save().
    vector = SearchVector("text", weight="A", config=settings.SEARCH_CONFIG)

    if instance.transcription:
        vector = vector + SearchVector("transcription", weight="B", config=settings.SEARCH_CONFIG)

    if instance.poll_question:
        vector = vector + SearchVector("poll_question", weight="A", config=settings.SEARCH_CONFIG)

    if instance.audio_title:
        vector = vector + SearchVector("audio_title", weight="B", config=settings.SEARCH_CONFIG)

    if instance.contact_name:
        vector = vector + SearchVector("contact_name", weight="C", config=settings.SEARCH_CONFIG)

    if instance.file_name:
        vector = vector + SearchVector("file_name", weight="C", config=settings.SEARCH_CONFIG)

    Message.objects.filter(pk=instance.pk).update(search_vector=vector)
