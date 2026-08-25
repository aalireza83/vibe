from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("archive", "0005_appsettings_archive_bot_chats"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramchat",
            name="is_hidden",
            field=models.BooleanField(
                default=False,
                help_text="Keep this chat in the database but hide it from the web interface",
                verbose_name="Hidden",
            ),
        ),
    ]
