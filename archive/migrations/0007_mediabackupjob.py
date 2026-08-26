from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("archive", "0006_telegramchat_is_hidden"),
    ]

    operations = [
        migrations.CreateModel(
            name="MediaBackupJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cutoff_date", models.DateField(verbose_name="Media through date")),
                ("archive_path", models.CharField(blank=True, max_length=500, verbose_name="ZIP path")),
                ("delete_originals", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("uploading", "Uploading"), ("completed", "Completed"), ("failed", "Failed")], db_index=True, default="pending", max_length=20)),
                ("file_count", models.PositiveIntegerField(default=0)),
                ("skipped_count", models.PositiveIntegerField(default=0)),
                ("deleted_count", models.PositiveIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Media backup job",
                "verbose_name_plural": "Media backup jobs",
                "ordering": ["-created_at"],
            },
        ),
    ]
