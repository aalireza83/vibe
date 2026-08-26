"""Parallel Telethon uploads adapted from painor's fast transfer gist.

Source: https://gist.github.com/painor/7e74de80ae0c819d3e9abcf9989a8dd6
The implementation intentionally covers uploads only, which is all the backup queue needs.
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from telethon import helpers, utils
from telethon.network import MTProtoSender
from telethon.tl.functions.upload import SaveBigFilePartRequest, SaveFilePartRequest
from telethon.tl.types import InputFile, InputFileBig

logger = logging.getLogger(__name__)


class _UploadSender:
    def __init__(self, client, sender, file_id, part_count, is_big, index, stride):
        self.client = client
        self.sender = sender
        self.stride = stride
        self.previous = None
        request_type = SaveBigFilePartRequest if is_big else SaveFilePartRequest
        if is_big:
            self.request = request_type(file_id, index, part_count, b"")
        else:
            self.request = request_type(file_id, index, b"")

    async def send(self, data):
        if self.previous is not None:
            await self.previous
        self.previous = asyncio.create_task(self._send(data))

    async def _send(self, data):
        self.request.bytes = data
        await self.client._call(self.sender, self.request)
        self.request.file_part += self.stride

    async def disconnect(self):
        upload_error = None
        try:
            if self.previous is not None:
                await self.previous
        except Exception as exc:
            upload_error = exc
        finally:
            await self.sender.disconnect()
        if upload_error is not None:
            raise upload_error


class _ParallelUploader:
    def __init__(self, client, file_id, part_count, is_big, connection_count):
        self.client = client
        self.file_id = file_id
        self.part_count = part_count
        self.is_big = is_big
        self.connection_count = connection_count
        self.senders = []
        self.ticker = 0

    async def connect(self):
        dc = await self.client._get_dc(self.client.session.dc_id)

        async def create_sender(index):
            sender = MTProtoSender(self.client.session.auth_key, loggers=self.client._log)
            await sender.connect(
                self.client._connection(
                    dc.ip_address,
                    dc.port,
                    dc.id,
                    loggers=self.client._log,
                    proxy=self.client._proxy,
                )
            )
            return _UploadSender(
                self.client,
                sender,
                self.file_id,
                self.part_count,
                self.is_big,
                index,
                self.connection_count,
            )

        results = await asyncio.gather(
            *(create_sender(index) for index in range(self.connection_count)),
            return_exceptions=True,
        )
        self.senders = [result for result in results if not isinstance(result, Exception)]
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            await self.disconnect()
            raise errors[0]

    async def send(self, data):
        await self.senders[self.ticker].send(data)
        self.ticker = (self.ticker + 1) % len(self.senders)

    async def disconnect(self):
        if self.senders:
            results = await asyncio.gather(
                *(sender.disconnect() for sender in self.senders),
                return_exceptions=True,
            )
            self.senders = []
            for result in results:
                if isinstance(result, Exception):
                    raise result


async def upload_file_parallel(client, file_path, connection_count=8, progress_callback=None):
    """Upload a local file through several MTProto senders and return its handle."""
    file_path = Path(file_path)
    file_size = file_path.stat().st_size
    part_size = utils.get_appropriated_part_size(file_size) * 1024
    part_count = (file_size + part_size - 1) // part_size
    is_big = file_size > 10 * 1024 * 1024
    connection_count = max(1, min(int(connection_count), 20, part_count))
    file_id = helpers.generate_random_long()
    md5 = hashlib.md5()

    logger.info(
        "Starting parallel Telegram upload: %s, %.1f MB, %d connections",
        file_path.name,
        file_size / (1024 * 1024),
        connection_count,
    )

    uploader = _ParallelUploader(
        client, file_id, part_count, is_big, connection_count
    )
    await uploader.connect()
    sent = 0
    try:
        with file_path.open("rb") as source:
            while True:
                part = source.read(part_size)
                if not part:
                    break
                if not is_big:
                    md5.update(part)
                await uploader.send(part)
                sent += len(part)
                if progress_callback is not None:
                    result = progress_callback(sent, file_size)
                    if asyncio.iscoroutine(result):
                        await result
    finally:
        await uploader.disconnect()

    if is_big:
        return InputFileBig(file_id, part_count, file_path.name)
    return InputFile(file_id, part_count, file_path.name, md5.hexdigest())
