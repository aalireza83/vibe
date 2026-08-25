import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Message


@dataclass(frozen=True)
class MediaBackupResult:
    archive_path: Path
    file_count: int
    deleted_count: int
    skipped_count: int


def create_media_backup(cutoff_date, delete_originals=False):
    """Archive local media belonging to messages through the selected local date."""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    backup_dir = media_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    next_day = cutoff_date + timedelta(days=1)
    cutoff = timezone.make_aware(
        datetime.combine(next_day, time.min),
        timezone.get_current_timezone(),
    )
    messages = list(
        Message.objects.filter(date__lt=cutoff, media_path__isnull=False)
        .exclude(media_path="")
        .select_related("chat")
        .order_by("date", "pk")
    )

    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S-%f")
    archive_path = backup_dir / f"media-through-{cutoff_date.isoformat()}-{timestamp}.zip"
    manifest = []
    archived_paths = set()
    skipped_count = 0

    try:
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for message in messages:
                source = Path(message.media_path)
                if not source.is_absolute():
                    source = media_root / source

                try:
                    source = source.resolve(strict=True)
                    relative_path = source.relative_to(media_root)
                except (FileNotFoundError, ValueError, OSError):
                    skipped_count += 1
                    continue

                if not source.is_file():
                    skipped_count += 1
                    continue

                # Never include a previously generated backup in another backup.
                if relative_path.parts and relative_path.parts[0] == "backups":
                    skipped_count += 1
                    continue

                if source not in archived_paths:
                    archive.write(source, arcname=relative_path.as_posix())
                    archived_paths.add(source)

                manifest.append({
                    "message_pk": message.pk,
                    "message_id": message.message_id,
                    "chat_id": message.chat.chat_id,
                    "message_date": message.date.isoformat(),
                    "path": relative_path.as_posix(),
                })

            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    deleted_ids = []
    deleted_paths = set()
    if delete_originals and manifest:
        for item in manifest:
            source = media_root / item["path"]
            if source not in deleted_paths:
                try:
                    source.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
                deleted_paths.add(source)
            deleted_ids.append(item["message_pk"])

        if deleted_ids:
            with transaction.atomic():
                Message.objects.filter(pk__in=deleted_ids).update(media_path=None)

    return MediaBackupResult(
        archive_path=archive_path,
        file_count=len(archived_paths),
        deleted_count=len(deleted_paths),
        skipped_count=skipped_count,
    )
