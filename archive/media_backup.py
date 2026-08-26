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
    skipped_count: int
    manifest: tuple[dict, ...]


def create_media_backup(cutoff_date):
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

    return MediaBackupResult(
        archive_path=archive_path,
        file_count=len(archived_paths),
        skipped_count=skipped_count,
        manifest=tuple(manifest),
    )


def load_media_backup_result(archive_path, file_count=0, skipped_count=0):
    archive_path = Path(archive_path)
    with ZipFile(archive_path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
    return MediaBackupResult(
        archive_path=archive_path,
        file_count=file_count,
        skipped_count=skipped_count,
        manifest=tuple(manifest),
    )


def delete_archived_originals(result):
    """Delete only files represented in a successfully created and sent archive."""
    if not result.archive_path.is_file():
        raise FileNotFoundError("The backup ZIP no longer exists; originals were not deleted.")

    media_root = Path(settings.MEDIA_ROOT).resolve()
    deleted_paths = set()
    cleared_message_ids = []
    for item in result.manifest:
        source = (media_root / item["path"]).resolve()
        try:
            source.relative_to(media_root)
        except ValueError:
            continue

        if source not in deleted_paths:
            try:
                source.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                continue
            deleted_paths.add(source)
        cleared_message_ids.append(item["message_pk"])

    if cleared_message_ids:
        with transaction.atomic():
            Message.objects.filter(pk__in=cleared_message_ids).update(media_path=None)

    return len(deleted_paths)
