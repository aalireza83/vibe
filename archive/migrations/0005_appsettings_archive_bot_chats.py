from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("archive", "0004_rebuild_search_vector_simple"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="archive_bot_chats",
            field=models.BooleanField(
                default=True,
                help_text="Save messages exchanged with Telegram bots",
                verbose_name="Archive bot chats",
            ),
        ),
    ]
