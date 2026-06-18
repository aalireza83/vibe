# Generated manually after switching full-text search to the simple config.

from django.db import migrations


REBUILD_SEARCH_VECTOR = """
UPDATE archive_message
SET search_vector =
    setweight(to_tsvector('simple', coalesce(text, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(transcription, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(poll_question, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(audio_title, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(contact_name, '')), 'C') ||
    setweight(to_tsvector('simple', coalesce(file_name, '')), 'C');
"""


class Migration(migrations.Migration):

    dependencies = [
        ("archive", "0003_bookmark"),
    ]

    operations = [
        migrations.RunSQL(REBUILD_SEARCH_VECTOR, reverse_sql=migrations.RunSQL.noop),
    ]
