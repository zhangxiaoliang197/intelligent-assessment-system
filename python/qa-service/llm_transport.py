"""LLM HTTP transport with a Windows curl fallback."""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any


_STATUS_MARKER = "__LLM_HTTP_STATUS__:"


class LlmTransportError(RuntimeError):
    pass


def _curl_executable() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl")


def _use_curl(url: str) -> bool:
    return os.name == "nt" and url.lower().startswith("https://") and _curl_executable() is not None


def _curl_args(url: str, api_key: str, timeout: int, stream: bool) -> list[str]:
    executable = _curl_executable()
    if not executable:
        raise LlmTransportError("系统未找到 curl，无法建立大模型 HTTPS 连接")
    args = [
        executable, "--tlsv1.2", "--http1.1", "-sS",
        "--max-time", str(timeout),
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {api_key}",
        "--data-binary", "@-",
        "--write-out", f"\n{_STATUS_MARKER}%{{http_code}}\n",
    ]
    if stream:
        args.append("--no-buffer")
    args.append(url)
    return args


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _split_status(raw: str) -> tuple[str, int | None]:
    marker_index = raw.rfind(_STATUS_MARKER)
    if marker_index < 0:
        return raw, None
    body = raw[:marker_index].rstrip()
    status_text = raw[marker_index + len(_STATUS_MARKER):].strip().splitlines()[0]
    try:
        return body, int(status_text)
    except ValueError:
        return body, None


def _error_message(body: str, fallback: str) -> str:
    try:
        data = json.loads(body)
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or fallback)
        if error:
            return str(error)
    except (json.JSONDecodeError, TypeError):
        pass
    return body[:500] if body else fallback


def _curl_post_json(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        _curl_args(url, api_key, timeout, stream=False),
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout + 5,
        creationflags=_creation_flags(),
        check=False,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    body, status = _split_status(stdout)
    if status is not None and status >= 400:
        raise LlmTransportError(f"HTTP {status}: {_error_message(body, stderr)}")
    if completed.returncode != 0:
        raise LlmTransportError(stderr or f"curl 退出码 {completed.returncode}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LlmTransportError("大模型返回了无法解析的 JSON") from exc


def _urllib_post_json(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LlmTransportError(f"HTTP {exc.code}: {_error_message(error_body, str(exc))}") from exc


def post_chat_json(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    if _use_curl(url):
        return _curl_post_json(url, api_key, payload, timeout)
    return _urllib_post_json(url, api_key, payload, timeout)


def _curl_stream_lines(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> Generator[str, None, None]:
    process = subprocess.Popen(
        _curl_args(url, api_key, timeout, stream=True),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_creation_flags(),
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    process.stdin.close()

    non_stream_parts: list[str] = []
    status: int | None = None
    for raw_line in process.stdout:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if line.startswith(_STATUS_MARKER):
            try:
                status = int(line[len(_STATUS_MARKER):])
            except ValueError:
                status = None
        elif line.startswith("data: "):
            yield line
        elif line:
            non_stream_parts.append(line)

    return_code = process.wait(timeout=timeout + 5)
    stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
    body = "\n".join(non_stream_parts)
    if status is not None and status >= 400:
        raise LlmTransportError(f"HTTP {status}: {_error_message(body, stderr)}")
    if return_code != 0:
        raise LlmTransportError(stderr or f"curl 退出码 {return_code}")


def _urllib_stream_lines(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> Generator[str, None, None]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line.startswith("data: "):
                    yield line
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LlmTransportError(f"HTTP {exc.code}: {_error_message(error_body, str(exc))}") from exc


def stream_chat_lines(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> Generator[str, None, None]:
    if _use_curl(url):
        yield from _curl_stream_lines(url, api_key, payload, timeout)
        return
    yield from _urllib_stream_lines(url, api_key, payload, timeout)
