"""Bounded Settings capabilities. No scheduler, installer, SEC fetch, or credential access."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager, ExitStack
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StrictStr, Field

from version import read_version
from fact_lake_store import _snapshot_identity, _snapshot_descriptor_matches, _is_link_or_reparse

REPOSITORY = "guilaile95/Vibe-Research"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
MAX_BODY = 262144
SCHEMA = "platform_settings.v1"
_LOCK = threading.Lock()
_CHECK_LOCK = threading.Lock()
_UPDATE = None
_TAG = re.compile(r"v?(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})", re.ASCII)
_CONTACT = re.compile(r"[A-Za-z][A-Za-z .'-]{0,99} [A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", re.ASCII)


def normalize_contact(value):
    if type(value) is not str or len(value) > 200 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError("联系方式需为 200 字符以内的英文姓名和邮箱，不含控制字符")
    value = " ".join(value.strip().split(" "))
    # Collapse spaces without accepting header-control characters.
    value = re.sub(" +", " ", value)
    if value and not _CONTACT.fullmatch(value):
        raise ValueError("格式需为英文姓名、空格、邮箱；此处仅校验格式")
    return value


def _path():
    return Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research") / "private" / "platform_settings.json"


@contextmanager
def _windows_handle(path, *, directory):
    """Hold a non-following handle; parent handles deny rename/delete while in use."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    handle = kernel.CreateFileW(str(path), 0x80 if directory else 0x80000000,
                                3 if directory else 1, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError("settings path unavailable")
    class AttributeTag(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]
    try:
        info = AttributeTag()
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or info.attributes & 0x400:
            raise OSError("settings reparse path refused")
        yield handle
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def _parent(path, *, create=False):
    """Anchor every parent; no path resolution through symlinks or junctions."""
    path = Path(os.path.abspath(path))
    with ExitStack() as stack:
        identities = []
        current = Path(path.anchor)
        parent_fd = None
        for part in (None, *path.parent.parts[1:]):
            if part is not None:
                current = current / part
            if create and part is not None:
                try:
                    if os.name == "nt":
                        current.mkdir(mode=0o700)
                    else:
                        os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
            info = current.lstat()
            if _is_link_or_reparse(current, info) or not stat.S_ISDIR(info.st_mode):
                raise OSError("settings parent refused")
            if os.name == "nt":
                stack.enter_context(_windows_handle(current, directory=True))
                opened = current.lstat()
            else:
                fd = os.open(str(current) if part is None else part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             **({} if part is None else {"dir_fd": parent_fd}))
                stack.callback(os.close, fd)
                opened = os.fstat(fd)
                parent_fd = fd
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError("settings parent changed")
            identities.append((current, info.st_dev, info.st_ino))
        yield path, parent_fd, identities


def _assert_parents(identities):
    for path, device, inode in identities:
        info = path.lstat()
        if _is_link_or_reparse(path, info) or (info.st_dev, info.st_ino) != (device, inode):
            raise OSError("settings parent changed")


def _file_identity(path, parent_fd):
    try:
        info = path.lstat() if parent_fd is None else os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if _is_link_or_reparse(path, info) or not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise OSError("settings file refused")
    return _snapshot_identity(info)


def _read_in(path, parent_fd):
    before = _file_identity(path, parent_fd)
    if before is None:
        return {"schema": SCHEMA, "revision": "absent", "contact": ""}, None
    with ExitStack() as stack:
        if os.name == "nt":
            import msvcrt
            # Duplicate the held handle: the context remains its sole native owner.
            import ctypes
            from ctypes import wintypes
            handle = stack.enter_context(_windows_handle(path, directory=False))
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            duplicate = wintypes.HANDLE()
            process = kernel.GetCurrentProcess()
            if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
                raise OSError("settings read unavailable")
            try:
                fd = msvcrt.open_osfhandle(duplicate.value, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(duplicate)
                raise
        else:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        with os.fdopen(fd, "rb") as handle:
            opened = _snapshot_identity(os.fstat(handle.fileno()))
            if not _snapshot_descriptor_matches(before, opened):
                raise OSError("settings file changed")
            raw = handle.read(4097)
            if _snapshot_identity(os.fstat(handle.fileno())) != opened:
                raise OSError("settings file changed")
    if _file_identity(path, parent_fd) != before or len(raw) > 4096:
        raise OSError("settings file changed")
    data = json.loads(raw)
    if (type(data) is not dict or set(data) != {"schema", "revision", "contact"}
            or data["schema"] != SCHEMA or type(data["revision"]) is not str
            or not re.fullmatch("[a-f0-9]{32}", data["revision"])):
        raise ValueError()
    data["contact"] = normalize_contact(data["contact"])
    return data, before


def _read():
    entered = False
    try:
        with _parent(_path()) as (path, parent_fd, identities):
            entered = True
            result, _ = _read_in(path, parent_fd)
            _assert_parents(identities)
            return result
    except FileNotFoundError:
        if entered:
            raise HTTPException(503, "本地设置读取失败；未覆盖原文件") from None
        return {"schema": SCHEMA, "revision": "absent", "contact": ""}
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "本地设置读取失败；未覆盖原文件") from None


def _write(contact, revision):
    try:
        with _parent(_path(), create=True) as (path, parent_fd, identities):
            previous, identity = _read_in(path, parent_fd)
            if previous["revision"] != revision:
                raise HTTPException(409, "设置已改变，请重新读取；草稿未保存")
            data = {"schema": SCHEMA, "revision": secrets.token_hex(16), "contact": contact}
            tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
            args = {} if parent_fd is None else {"dir_fd": parent_fd}
            name = str(tmp) if parent_fd is None else tmp.name
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, **args)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary_identity = _snapshot_identity(os.fstat(handle.fileno()))
                _assert_parents(identities)
                temp_identity = _file_identity(tmp, parent_fd)
                if temp_identity is None or not _snapshot_descriptor_matches(temp_identity, temporary_identity):
                    raise OSError("settings temporary file changed")
                if _file_identity(path, parent_fd) != identity:
                    raise OSError("settings changed before replacement")
                if parent_fd is None:
                    os.replace(tmp, path)
                else:
                    os.replace(tmp.name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            finally:
                try:
                    os.unlink(name, **args)
                except FileNotFoundError:
                    pass
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "保存未确认，请重新读取设置；草稿保留") from None


def _local(request):
    # No proxy-header trust. A remote client must not choose the owner's identity.
    def loopback(host):
        return host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
    try:
        origin = request.headers.get("origin")
        return bool(request.client and loopback(request.client.host) and loopback(request.url.hostname)
                    and (not origin or loopback(urlsplit(origin).hostname)))
    except ValueError:
        return False


def contact_status(request):
    env = os.environ.get("VR_SEC_CONTACT", "")
    if env:
        try:
            valid = bool(normalize_contact(env))
        except ValueError:
            valid = False
        return {"source": "environment", "configured": valid, "revision": "environment", "editable": False}
    data = _read()
    return {"source": "saved" if data["contact"] else "none", "configured": bool(data["contact"]),
            "revision": data["revision"], "editable": _local(request)}


def save_contact(request, contact, revision):
    if not _local(request) or os.environ.get("VR_SEC_CONTACT", ""):
        raise HTTPException(403, "仅本机可修改；环境变量配置不可在页面覆盖")
    try:
        normalized = normalize_contact(contact)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    with _LOCK:
        _write(normalized, revision)
        return contact_status(request)


def version_tuple(value):
    match = _TAG.fullmatch(value) if type(value) is str else None
    return tuple(map(int, match.groups())) if match else None


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _current_version():
    value = read_version()
    parsed = version_tuple(value)
    return ".".join(map(str, parsed)) if parsed else "unknown"


def update_status():
    # Only fixed public metadata, never disk paths, contact or provider settings.
    return {"repository": REPOSITORY, "current": _current_version(), "mode": "manual_only",
            "status": "not_checked", "checked_at": None, "latest": None} if _UPDATE is None else dict(_UPDATE)


def check_update(*, client_factory=httpx.Client, now=None):
    now = now or _now()
    current = _current_version()
    result = {"repository": REPOSITORY, "current": current, "mode": "manual_only",
              "status": "unavailable", "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "latest": None}
    started = time.monotonic()
    try:
        with client_factory(timeout=5.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", RELEASES_API, headers={"Accept": "application/vnd.github+json", "Accept-Encoding": "identity",
                    "User-Agent": "Vibe-Research-Manual-Update-Check", "X-GitHub-Api-Version": "2022-11-28"}) as response:
                if response.status_code == 404:
                    result["status"] = "release_not_found"
                    return result
                if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                    return result
                raw = bytearray()
                for chunk in response.iter_raw():
                    if len(raw) + len(chunk) > MAX_BODY or time.monotonic() - started > 5:
                        return result
                    raw.extend(chunk)
                body = json.loads(raw)
        if type(body) is not dict or body.get("draft") is not False or body.get("prerelease") is not False:
            return result
        tag = body.get("tag_name")
        latest = version_tuple(tag)
        published = body.get("published_at")
        if latest is None or type(published) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", published):
            return result
        published_dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if published_dt > now:
            return result
        result["latest"] = {"version": ".".join(map(str, latest)), "url": f"{RELEASES_PAGE}/tag/{tag}", "published_at": published}
        ours = version_tuple(current)
        result["status"] = "current_unknown" if ours is None else "update_available" if latest > ours else "current" if latest == ours else "ahead"
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        pass  # Never return external response/error text, URLs, paths or environment values.
    return result


class ContactWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact: StrictStr = Field(max_length=200)
    revision: StrictStr = Field(max_length=32)


router = APIRouter(prefix="/api/settings/platform", tags=["settings"])


@router.get("")
def capabilities(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"data": {"schema": SCHEMA, "sec_contact": contact_status(request), "update": update_status(),
            "platforms": {"windows": "existing_launcher", "linux": "existing_user_space_launcher", "macos": "unsupported_launcher"},
            "sec_provider": "not_connected", "can_check_update": _local(request)}}


@router.put("/sec-contact")
def put_contact(payload: ContactWrite, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"data": save_contact(request, payload.contact, payload.revision)}


@router.post("/check-update")
def post_check(request: Request, response: Response):
    global _UPDATE
    if not _local(request):
        raise HTTPException(403, "仅本机可手动检查更新")
    response.headers["Cache-Control"] = "no-store"
    if not _CHECK_LOCK.acquire(blocking=False):
        raise HTTPException(409, "更新检查正在进行")
    try:
        _UPDATE = check_update()
        return {"data": dict(_UPDATE)}
    finally:
        _CHECK_LOCK.release()
