"""
FULL DISCLOSURE: This file has been adapted from Hermes Agent.
See https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/signal.py
License: MIT (https://github.com/NousResearch/hermes-agent/blob/main/LICENSE)

Refactored using Claude.

Connects to a running signal-cli daemon in HTTP mode and exposes a simple,
Pythonic API for sending and receiving messages, images, files, and typing
indicators.

Requirements:
    pip install httpx

Setup:
    signal-cli daemon --http 127.0.0.1:8080

Usage:
    import asyncio
    from signal_client import SignalClient, SignalMessage

    client = SignalClient(url="http://127.0.0.1:8080", account="+49123456789")

    @client.on_message
    async def handle(msg: SignalMessage):
        await client.send_typing(msg.chat_id)
        await client.send(msg.chat_id, f"Echo: {msg.text}")

    asyncio.run(client.run())
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SSE_RETRY_INITIAL = 2.0  # seconds before first reconnect attempt
_SSE_RETRY_MAX = 60.0  # maximum backoff between reconnects
_MAX_ATTACHMENT = 100 * 1024 * 1024  # 100 MB hard cap per Signal spec


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class SignalMessage:
    """A received Signal message, normalised for easy consumption."""

    chat_id: str  # recipient (phone/UUID) or "group:<id>"
    sender: str  # sender phone number or UUID
    text: str  # message body (mention markers expanded)
    timestamp: int  # Unix timestamp in milliseconds
    is_group: bool = False
    group_id: Optional[str] = None
    attachments: List[str] = field(default_factory=list)  # local file paths


MessageHandler = Callable[[SignalMessage], Awaitable[None]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guess_ext(data: bytes) -> str:
    """Infer a file extension from magic bytes."""
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] == b"%PDF":
        return ".pdf"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return ".mp4"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:2] in (b"ID3", b"\xff\xfb"):
        return ".mp3"
    return ".bin"


def _render_mentions(text: str, mentions: list) -> str:
    """Replace Signal's Unicode object-replacement placeholders with @identifiers."""
    if not mentions or "\ufffc" not in text:
        return text
    for mention in sorted(
        mentions, key=lambda m: m.get("start", 0), reverse=True
    ):
        start = mention.get("start", 0)
        length = mention.get("length", 1)
        ident = mention.get("number") or mention.get("uuid") or "user"
        text = text[:start] + f"@{ident}" + text[start + length :]
    return text


def _utf16_len(s: str) -> int:
    """Length of *s* measured in UTF-16 code units (Signal's unit for bodyRanges)."""
    return len(s.encode("utf-16-le")) // 2


# ---------------------------------------------------------------------------
# Markdown → Signal bodyRanges converter
# ---------------------------------------------------------------------------


def _markdown_to_signal(text: str) -> tuple[str, list[str]]:
    """Convert a Markdown string to a (plain_text, textStyles) pair.

    Signal does not render Markdown.  Instead it uses ``bodyRanges``
    (``textStyle`` / ``textStyles`` params in signal-cli) encoded as
    ``"start:length:STYLE"`` strings, where offsets are measured in
    UTF-16 code units.

    Supported mappings
    ------------------
    ``**bold**`` / ``__bold__``  →  BOLD
    ``*italic*``  / ``_italic_`` →  ITALIC
    ``~~strike~~``               →  STRIKETHROUGH
    `` `code` `` / ````` ```block``` `````  →  MONOSPACE
    ``# Heading``                →  BOLD  (marker stripped)

    Returns
    -------
    plain_text : str
        The original text with all Markdown markers removed.
    styles : list[str]
        Zero or more ``"start:length:STYLE"`` strings ready to pass to
        signal-cli's ``textStyle`` / ``textStyles`` params.
    """
    # Normalise excessive blank lines; trim leading/trailing whitespace.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    styles: list[tuple[int, int, str]] = []  # (cp_start, cp_len, STYLE)

    # --- Pass 1: fenced code blocks  ```lang\n...\n``` → MONOSPACE ----------
    _CB = re.compile(r"```[a-zA-Z0-9_+\-]*\n?(.*?)```", re.DOTALL)
    while m := _CB.search(text):
        inner = m.group(1).rstrip("\n")
        styles.append((m.start(), len(inner), "MONOSPACE"))
        text = text[: m.start()] + inner + text[m.end() :]

    # --- Pass 2: ATX headings  # Heading → Heading (BOLD) -------------------
    _HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
    out, last = "", 0
    for m in _HEADING.finditer(text):
        out += text[last : m.start()]
        last = m.end()
        eol = text.find("\n", m.end())
        if eol == -1:
            eol = len(text)
        heading_text = text[m.end() : eol]
        styles.append((len(out), len(heading_text), "BOLD"))
        out += heading_text
        last = eol
    text = out + text[last:]

    # --- Pass 3: inline patterns — collect all matches before stripping ------
    # Process in a single pass so stripping markers in one pattern does not
    # shift the offsets recorded for another.
    _PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), "BOLD"),
        (re.compile(r"__(.+?)__", re.DOTALL), "BOLD"),
        (re.compile(r"~~(.+?)~~", re.DOTALL), "STRIKETHROUGH"),
        (re.compile(r"`(.+?)`"), "MONOSPACE"),
        (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), "ITALIC"),
        (re.compile(r"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)"), "ITALIC"),
    ]

    # Collect non-overlapping matches (first-listed pattern wins on ties).
    all_matches: list[tuple[int, int, int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for pat, style in _PATTERNS:
        for m in pat.finditer(text):
            ms, me = m.start(), m.end()
            if not any(ms < oe and me > os for os, oe in occupied):
                all_matches.append((ms, me, m.start(1), m.end(1), style))
                occupied.append((ms, me))
    all_matches.sort()

    # Build a list of (position, length) removals so we can shift the Pass
    # 1/2 styles' code-point positions after the inline markers are stripped.
    removals: list[tuple[int, int]] = []
    for ms, me, g1s, g1e, _ in all_matches:
        if g1s > ms:
            removals.append((ms, g1s - ms))
        if me > g1e:
            removals.append((g1e, me - g1e))
    removals.sort()

    def _shift(pos: int) -> int:
        shift = 0
        for rp, rl in removals:
            if rp < pos:
                shift += min(rl, pos - rp)
        return pos - shift

    # Adjust Pass 1/2 styles for the upcoming marker deletions.
    adjusted: list[tuple[int, int, str]] = []
    for s, l, st in styles:
        ns, ne = _shift(s), _shift(s + l)
        if ne > ns:
            adjusted.append((ns, ne - ns, st))

    # Strip inline markers in one pass → inline style positions are exact.
    result, last, inline_styles = "", 0, []
    for ms, me, g1s, g1e, sty in all_matches:
        result += text[last:ms]
        pos = len(result)
        inner = text[g1s:g1e]
        result += inner
        inline_styles.append((pos, len(inner), sty))
        last = me
    result += text[last:]
    text = result
    styles = adjusted + inline_styles

    # --- Convert code-point offsets → UTF-16 code-unit offsets --------------
    style_strings: list[str] = []
    for cp_start, cp_len, stype in sorted(styles):
        if cp_start < 0 or cp_start + cp_len > len(text):
            continue
        u16_start = _utf16_len(text[:cp_start])
        u16_len = _utf16_len(text[cp_start : cp_start + cp_len])
        style_strings.append(f"{u16_start}:{u16_len}:{stype}")

    return text, style_strings


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------


class SignalClient:
    """Minimal async Signal client backed by a signal-cli HTTP daemon.

    Parameters
    ----------
    url :
        Base URL of the signal-cli HTTP daemon, e.g. ``"http://127.0.0.1:8080"``.
    account :
        The E.164 phone number registered with signal-cli, e.g. ``"+49123456789"``.
    attachment_dir :
        Directory where received attachments are saved.  Defaults to a
        ``signal_attachments/`` folder next to the script.

    Quick-start
    -----------
    .. code-block:: python

        client = SignalClient(url="http://127.0.0.1:8080", account="+49123456789")

        @client.on_message
        async def handle(msg: SignalMessage):
            await client.send(msg.chat_id, f"You said: {msg.text}")

        asyncio.run(client.run())
    """

    def __init__(
        self,
        url: str,
        account: str,
        *,
        attachment_dir: str | Path = "signal_attachments",
    ) -> None:
        self.url = url.rstrip("/")
        self.account = account.strip()
        self.attachment_dir = Path(attachment_dir)
        self.attachment_dir.mkdir(parents=True, exist_ok=True)

        self._http: Optional[httpx.AsyncClient] = None
        self._handler: Optional[MessageHandler] = None
        self._running = False
        self._sse_task: Optional[asyncio.Task] = None

        # Typing-indicator state (per chat_id)
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._typing_failures: dict[str, int] = {}
        self._typing_skip_until: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Decorator for registering the message handler
    # ------------------------------------------------------------------

    def on_message(self, fn: MessageHandler) -> MessageHandler:
        """Register an async function to be called for every incoming message.

        Can be used as a decorator::

            @client.on_message
            async def handle(msg: SignalMessage): ...

        Or called directly::

            client.on_message(handle)
        """
        self._handler = fn
        return fn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the HTTP connection and verify the daemon is reachable."""
        self._http = httpx.AsyncClient(timeout=30.0)
        try:
            resp = await self._http.get(
                f"{self.url}/api/v1/check", timeout=10.0
            )
            resp.raise_for_status()
        except Exception as exc:
            await self._http.aclose()
            self._http = None
            raise RuntimeError(
                f"Cannot reach signal-cli at {self.url}: {exc}"
            ) from exc
        logger.info(
            "SignalClient: connected to %s (account %s)",
            self.url,
            self.account,
        )

    async def disconnect(self) -> None:
        """Stop the SSE listener, cancel typing tasks, and close the HTTP client."""
        self._running = False

        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass

        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()

        if self._http:
            await self._http.aclose()
            self._http = None

        logger.info("SignalClient: disconnected")

    async def run(self) -> None:
        """Connect and listen for messages until interrupted.

        This is the main entry point for simple scripts.  It blocks until
        a ``KeyboardInterrupt`` or ``asyncio.CancelledError`` is raised.
        """
        await self.connect()
        self._running = True
        self._sse_task = asyncio.create_task(self._sse_listener())
        try:
            await self._sse_task
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await self.disconnect()

    # ------------------------------------------------------------------
    # SSE listener (inbound messages)
    # ------------------------------------------------------------------

    async def _sse_listener(self) -> None:
        """Stream Server-Sent Events from signal-cli and dispatch messages."""

        if self._http is None:
            raise RuntimeError("SSE listener started before HTTP client was initialized")

        url = (
            f"{self.url}/api/v1/events?account={quote(self.account, safe='')}"
        )
        backoff = _SSE_RETRY_INITIAL

        while self._running:
            try:
                async with self._http.stream(
                    "GET",
                    url,
                    headers={"Accept": "text/event-stream"},
                    timeout=None,
                ) as resp:
                    backoff = _SSE_RETRY_INITIAL  # reset on successful connect
                    logger.info("SignalClient SSE: connected")
                    buffer = ""

                    async for chunk in resp.aiter_text():
                        if not self._running:
                            return
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith("data:"):
                                raw = line[5:].strip()
                                if raw:
                                    try:
                                        await self._handle_envelope(
                                            json.loads(raw)
                                        )
                                    except json.JSONDecodeError:
                                        logger.debug(
                                            "SSE: invalid JSON: %.80s", raw
                                        )
                                    except Exception:
                                        logger.exception(
                                            "SSE: error handling event"
                                        )

            except asyncio.CancelledError:
                return
            except httpx.HTTPError as exc:
                if self._running:
                    logger.warning(
                        "SSE disconnected: %s — reconnecting in %.0fs",
                        exc,
                        backoff,
                    )

            if self._running:
                jitter = backoff * 0.2 * random.random()
                await asyncio.sleep(backoff + jitter)
                backoff = min(backoff * 2, _SSE_RETRY_MAX)

    async def _handle_envelope(self, envelope: dict) -> None:
        """Parse a signal-cli envelope and invoke the message handler."""
        data = envelope.get("envelope", envelope)

        sender = (
            data.get("sourceNumber")
            or data.get("sourceUuid")
            or data.get("source")
        )
        sender_uuid = data.get("sourceUuid", "")

        if not sender or sender == self.account:
            return

        data_msg = data.get("dataMessage") or (
            data.get("editMessage") or {}
        ).get("dataMessage")
        if not data_msg:
            return

        group_info = data_msg.get("groupInfo") or {}
        group_id = group_info.get("groupId")
        is_group = bool(group_id)
        chat_id = f"group:{group_id}" if is_group else sender

        text = data_msg.get("message", "") or ""
        mentions = data_msg.get("mentions", [])
        if text and mentions:
            text = _render_mentions(text, mentions)

        ts_ms = data.get("timestamp", 0)

        # Download attachments to local files
        att_paths: list[str] = []
        for att in data_msg.get("attachments", []):
            att_id = att.get("id")
            if not att_id:
                continue
            path = await self._fetch_attachment(att_id)
            if path:
                att_paths.append(path)

        if not text.strip() and not att_paths:
            return  # skip contentless envelopes (profile key updates, etc.)

        msg = SignalMessage(
            chat_id=chat_id,
            sender=sender_uuid or sender,
            text=text,
            timestamp=ts_ms,
            is_group=is_group,
            group_id=group_id,
            attachments=att_paths,
        )

        if self._handler:
            try:
                await self._handler(msg)
            except Exception:
                logger.exception("Message handler raised an exception")

    # ------------------------------------------------------------------
    # Attachment download
    # ------------------------------------------------------------------

    async def _fetch_attachment(self, attachment_id: str) -> Optional[str]:
        """Download an attachment from signal-cli and return its local path."""
        result = await self._rpc(
            "getAttachment",
            {
                "account": self.account,
                "id": attachment_id,
            },
        )
        if not result:
            return None

        raw_b64 = result.get("data") if isinstance(result, dict) else result
        if not raw_b64:
            return None

        raw = base64.b64decode(raw_b64)
        ext = _guess_ext(raw)
        path = self.attachment_dir / f"{attachment_id}{ext}"
        path.write_bytes(raw)
        logger.debug("Saved attachment: %s", path)
        return str(path)

    # ------------------------------------------------------------------
    # JSON-RPC helper
    # ------------------------------------------------------------------

    async def _rpc(
        self, method: str, params: dict, *, timeout: float = 30.0
    ) -> Optional[dict]:
        """Send a JSON-RPC 2.0 request and return the ``result`` field."""
        if not self._http:
            logger.error("RPC called before connect()")
            return None

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": f"{method}_{uuid.uuid4().hex[:8]}",
        }
        try:
            resp = await self._http.post(
                f"{self.url}/api/v1/rpc",
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                logger.warning("RPC %s error: %s", method, body["error"])
                return None
            return body.get("result")
        except Exception as exc:
            logger.warning("RPC %s failed: %s", method, exc)
            return None

    # ------------------------------------------------------------------
    # Recipient resolution (phone number → UUID when available)
    # ------------------------------------------------------------------

    async def _resolve_recipient(self, chat_id: str) -> str:
        """Best-effort: upgrade a phone number to its Signal UUID."""
        if chat_id.startswith("group:") or not chat_id.startswith("+"):
            return chat_id
        contacts = await self._rpc(
            "listContacts",
            {
                "account": self.account,
                "allRecipients": True,
            },
        )
        if isinstance(contacts, list):
            for c in contacts:
                if not isinstance(c, dict):
                    continue
                if c.get("number") != chat_id:
                    continue
                sid = c.get("uuid") or c.get("serviceId")
                if sid:
                    return sid
        return chat_id

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, text: str) -> bool:
        """Send a text message with Markdown converted to Signal formatting.

        Supports ``**bold**``, ``_italic_``, `` `code` ``, ``~~strike~~``,
        fenced code blocks, and ATX headings.

        Parameters
        ----------
        chat_id : Phone number / UUID for DMs, or ``"group:<id>"`` for groups.
        text :    Message body (Markdown is converted automatically).

        Returns ``True`` on success.
        """
        plain, styles = _markdown_to_signal(text)

        params: dict = {
            "account": self.account,
            "message": plain,
        }
        if styles:
            params["textStyles" if len(styles) > 1 else "textStyle"] = (
                styles if len(styles) > 1 else styles[0]
            )

        if chat_id.startswith("group:"):
            params["groupId"] = chat_id[6:]
        else:
            params["recipient"] = [await self._resolve_recipient(chat_id)]

        result = await self._rpc("send", params)
        return result is not None

    async def send_file(
        self,
        chat_id: str,
        file_path: str | Path,
        caption: str = "",
    ) -> bool:
        """Send any local file (image, audio, video, document) as an attachment.

        Parameters
        ----------
        chat_id :   Recipient chat ID.
        file_path : Absolute or relative path to the file to send.
        caption :   Optional text caption shown alongside the attachment.

        Returns ``True`` on success.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.stat().st_size > _MAX_ATTACHMENT:
            raise ValueError(
                f"File exceeds Signal's 100 MB attachment limit: {path}"
            )

        params: dict = {
            "account": self.account,
            "message": caption,
            "attachments": [str(path.resolve())],
        }
        if chat_id.startswith("group:"):
            params["groupId"] = chat_id[6:]
        else:
            params["recipient"] = [await self._resolve_recipient(chat_id)]

        result = await self._rpc("send", params, timeout=60.0)
        return result is not None

    async def send_image(
        self,
        chat_id: str,
        file_path: str | Path,
        caption: str = "",
    ) -> bool:
        """Convenience wrapper around :meth:`send_file` for images.

        Identical behaviour — Signal treats all attachments the same way;
        the distinction is only cosmetic in the API.
        """
        return await self.send_file(chat_id, file_path, caption)

    # ------------------------------------------------------------------
    # Typing indicators
    # ------------------------------------------------------------------

    async def send_typing(self, chat_id: str) -> None:
        """Start a typing indicator that refreshes automatically.

        The indicator is refreshed every 8 seconds (Signal's display
        timeout) until :meth:`stop_typing` is called or a message is sent.

        Consecutive failures (e.g. recipient offline) are silenced after
        the first occurrence and the RPC is skipped during an exponential
        back-off window to avoid flooding signal-cli.
        """
        # Cancel any existing indicator for this chat first
        await self.stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(
            self._typing_loop(chat_id)
        )

    async def stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for *chat_id*, if one is running."""
        task = self._typing_tasks.pop(chat_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._typing_failures.pop(chat_id, None)
        self._typing_skip_until.pop(chat_id, None)

    async def _typing_loop(self, chat_id: str) -> None:
        """Internal: keep sending ``sendTyping`` every 8 s with backoff on failure."""
        _REFRESH_INTERVAL = (
            8.0  # seconds; matches Signal's typing-indicator TTL
        )

        while True:
            now = time.monotonic()
            skip_until = self._typing_skip_until.get(chat_id, 0.0)

            if now >= skip_until:
                params: dict = {"account": self.account}
                if chat_id.startswith("group:"):
                    params["groupId"] = chat_id[6:]
                else:
                    params["recipient"] = [
                        await self._resolve_recipient(chat_id)
                    ]

                fails = self._typing_failures.get(chat_id, 0)
                result = await self._rpc("sendTyping", params)

                if result is None:
                    fails += 1
                    self._typing_failures[chat_id] = fails
                    # After 3 failures back off exponentially (cap: 60 s)
                    if fails >= 3:
                        backoff = min(60.0, 16.0 * (2 ** (fails - 3)))
                        self._typing_skip_until[chat_id] = (
                            time.monotonic() + backoff
                        )
                        logger.debug(
                            "Typing RPC failed %d times for %s; backing off %.0fs",
                            fails,
                            chat_id,
                            backoff,
                        )
                else:
                    self._typing_failures.pop(chat_id, None)
                    self._typing_skip_until.pop(chat_id, None)

            await asyncio.sleep(_REFRESH_INTERVAL)
