"""官方 CDN 来源插件：TCP 握手 → hash CSV → 差分下载。

协议参考 nobbyfix/AzurLane-AssetDownloader（MIT），自行实现。
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from core.events import bus
from core.registry import SourcePlugin

from .cdn_proto import p10min_pb_pb2 as pb

# 各服务器客户端配置（参考官方实现）
CLIENTS = {
    "CN": ("line1-login-bili-blhx.bilibiligame.net", 80, "https://line3-patch-blhx.bilibiligame.net"),
    "JP": ("blhxjploginapi.azurlane.jp", 80, "https://blhxstatic.yo-star.com"),
    "EN": ("blhxusgate.yo-star.com", 80, "https://blhxusstatic.yo-star.com"),
}

HEADER_LEN = 7
NOID_LEN = 5


def serialize_command(command_id: int, payload: bytes) -> bytes:
    size = (len(payload) + NOID_LEN).to_bytes(2, "big")
    cmd = command_id.to_bytes(2, "big")
    idx = (0).to_bytes(2, "big")
    return bytes([size[0], size[1], 0, cmd[0], cmd[1], idx[0], idx[1]]) + payload


def parse_version_string(raw: str) -> tuple[str, str] | None:
    """解析 "$TYPE$version$vhash" 形式的版本串 → (类型, vhash)。"""
    parts = raw.split("$")
    if len(parts) < 4:
        return None
    name = parts[1]
    if name == "azhash":
        vhash = parts[-1]
    else:
        vhash = parts[3] if len(parts) > 3 else parts[-1]
    return name, vhash


@dataclass
class VersionInfo:
    versions: dict[str, str] = field(default_factory=dict)  # hashname -> vhash
    raw_strings: dict[str, str] = field(default_factory=dict)  # hashname -> 原始版本串
    cdn: str = ""


class CdnSource(SourcePlugin):
    id = "cdn"
    name = "官方 CDN 下载器"

    def __init__(self) -> None:
        self.proxy: str | None = None

    # ---- 握手 ----
    def handshake(self, client: str = "CN", timeout: int = 15) -> VersionInfo:
        gateip, gateport, cdn = CLIENTS.get(client, CLIENTS["CN"])
        info = VersionInfo(cdn=cdn)
        with socket.create_connection((gateip, gateport), timeout=timeout) as s:
            req = pb.cs_10800()
            req.state = 21
            req.platform = "0"
            s.sendall(serialize_command(10800, req.SerializeToString()))
            header = self._recv_bytes(s, HEADER_LEN)
            payload_size = (header[0] << 8 | header[1]) - NOID_LEN
            payload = self._recv_bytes(s, payload_size)
        resp = pb.sc_10801()
        resp.ParseFromString(payload)
        for v in resp.version:
            parsed = parse_version_string(v)
            if parsed:
                info.versions[parsed[0]] = parsed[1]
                info.raw_strings[parsed[0]] = v
        return info

    @staticmethod
    def _recv_bytes(sock, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                break
            data += chunk
        return data

    # ---- hash 清单 ----
    def fetch_hash_csv(self, cdn: str, raw_version: str) -> str:
        import urllib.parse

        url = f"{cdn}/android/hash/{urllib.parse.quote(raw_version, safe='')}"
        return self._get(url).text

    def _get(self, url: str) -> requests.Response:
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        last: Exception | None = None
        for attempt in range(3):
            try:
                return requests.get(url, proxies=proxies, timeout=30)
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < 2:
                    time.sleep(1 + attempt)
        raise last or RuntimeError("request failed")

    # ---- 下载 ----
    def download_asset(
        self,
        cdn: str,
        md5: str,
        dest: Path,
        size: int,
        attempts: int = 3,
        cancel_event=None,
    ) -> bool:
        url = f"{cdn}/android/resource/{md5}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size == size:
            part = dest.with_suffix(dest.suffix + ".part")
            if part.exists():
                part.unlink(missing_ok=True)
            return True
        part = dest.with_suffix(dest.suffix + ".part")
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        for attempt in range(attempts):
            if cancel_event is not None and cancel_event.is_set():
                part.unlink(missing_ok=True)
                return False
            headers = {}
            if part.exists() and part.stat().st_size > 0:
                headers["Range"] = f"bytes={part.stat().st_size}-"
            try:
                with requests.get(url, proxies=proxies, headers=headers, stream=True, timeout=60) as r:
                    if r.status_code == 416:
                        if part.exists():
                            os.replace(part, dest)
                        return True
                    if r.status_code not in (200, 206):
                        if attempt < attempts - 1:
                            time.sleep(1 + attempt)
                            continue
                        return False
                    mode = "ab" if r.status_code == 206 else "wb"
                    with open(part, mode) as f:
                        for chunk in r.iter_content(1 << 16):
                            if cancel_event is not None and cancel_event.is_set():
                                f.close()
                                part.unlink(missing_ok=True)
                                return False
                            f.write(chunk)
            except Exception:  # noqa: BLE001
                if attempt < attempts - 1:
                    time.sleep(1 + attempt)
                    continue
                return False
            if part.stat().st_size == size:
                os.replace(part, dest)
                return True
        return False

    # ---- 全流程 ----
    def sync(self, folders: list[str], out_dir: Path, client: str = "CN") -> dict:
        """握手 → 拉取相关 hash 清单 → 差分下载指定目录的 bundle。"""
        out_dir = Path(out_dir)
        info = self.handshake(client)
        bus.emit("cdn.versions", versions=info.versions)
        # 目录 -> 所属 hash 清单
        folder_to_hash = {
            "spinepainting": "azhash",
            "dependencies": "azhash",
            "live2d": "l2dhash",
            "painting": "paintinghash",
        }
        csvs: dict[str, str] = {}
        for folder in folders:
            hname = folder_to_hash.get(folder)
            if not hname or hname in csvs:
                continue
            try:
                csvs[hname] = self.fetch_hash_csv(info.cdn, info.raw_strings[hname])
            except Exception as e:  # noqa: BLE001
                print(f"[cdn] hash 下载失败 {hname}: {e}")
        downloaded = 0
        failed = 0
        seen = set()
        for csv in csvs.values():
            for row in (l.split(",") for l in csv.splitlines() if l.strip()):
                if len(row) < 3:
                    continue
                path, size, md5 = row[0], int(row[1]), row[2]
                folder = path.split("/", 1)[0]
                if folder not in folders or path in seen:
                    continue
                seen.add(path)
                dest = out_dir / path
                if dest.exists() and dest.stat().st_size == size:
                    continue  # 差分：已存在且大小一致则跳过
                bus.emit("cdn.progress", path=path, size=size)
                ok = self.download_asset(info.cdn, md5, dest, size)
                if ok:
                    downloaded += 1
                else:
                    failed += 1
                    print(f"[cdn] 下载失败 {path}")
        return {"downloaded": downloaded, "failed": failed, "total": len(seen)}
