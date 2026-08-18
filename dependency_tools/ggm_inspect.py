#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "dnfile==0.18.0",
#   "pefile==2024.8.26",
# ]
# ///

"""Check, download, unpack, and inspect the current beanfun GGM launcher.

The installer is never executed. It is unpacked with innoextract or innounp.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

import dnfile
import pefile


DEFAULT_INDEX_URL = "https://tw.beanfun.com/ggm/index.aspx"
DEFAULT_VERSION_URL = "https://tw.beanfun.com/generic_handlers/CheckVersion.ashx"
DEFAULT_USER_AGENT = "ggm-inspect/1.0 (+interoperability version check)"
VERSION_RE = re.compile(r"GGMSetup[_-]([0-9]+(?:\.[0-9]+)+)\.exe", re.I)
ABSOLUTE_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
HEX_ALPHABET = frozenset(b"0123456789abcdef")


class GgmInspectError(RuntimeError):
    pass


def request(url: str, *, range_probe: bool = False) -> Any:
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"}
    if range_probe:
        headers["Range"] = "bytes=0-0"
    return urlopen(Request(url, headers=headers), timeout=60)


def fetch_text(url: str) -> tuple[str, str]:
    try:
        with request(url) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), response.geturl()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise GgmInspectError(f"failed to fetch {url}: {exc}") from exc


def candidate_download_urls(page: str, page_url: str) -> list[str]:
    decoded = html.unescape(page)
    candidates: list[str] = []

    for match in ABSOLUTE_URL_RE.finditer(decoded):
        candidates.append(match.group(0).rstrip("),;"))

    for match in re.finditer(r"(?:href|src)\s*=\s*[\"']([^\"']+)", decoded, re.I):
        candidates.append(urljoin(page_url, match.group(1)))

    unique = list(dict.fromkeys(candidates))
    preferred = [
        url
        for url in unique
        if VERSION_RE.search(unquote(urlparse(url).path))
        or "redirect.aspx" in url.lower()
        or "ggmsetup" in url.lower()
    ]
    preferred.sort(
        key=lambda url: (
            0 if VERSION_RE.search(unquote(urlparse(url).path)) else 1,
            0 if "ggmsetup" in url.lower() else 1,
        )
    )
    return preferred


def resolve_download(index_url: str, version_url: str | None = DEFAULT_VERSION_URL) -> dict[str, str]:
    """Resolve the official installer, preferring the version endpoint."""
    if version_url:
        try:
            return resolve_download_from_api(version_url)
        except (GgmInspectError, HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            print(
                f"note: {version_url} unusable ({exc}); falling back to the index page",
                file=sys.stderr,
            )
    return resolve_download_from_index(index_url)


def resolve_download_from_api(version_url: str) -> dict[str, str]:
    """Read the JSON the launcher itself polls: {"url": ..., "version": ...}."""
    payload, final_url = fetch_text(version_url)
    data = json.loads(payload)
    download_url = data["url"]
    filename = Path(unquote(urlparse(download_url).path)).name
    return {
        "index_url": final_url,
        "link_url": download_url,
        "download_url": download_url,
        "version": data["version"],
        "filename": filename,
        "source": "CheckVersion.ashx",
    }


def resolve_download_from_index(index_url: str) -> dict[str, str]:
    page, final_index_url = fetch_text(index_url)
    candidates = candidate_download_urls(page, final_index_url)
    if not candidates:
        raise GgmInspectError("no GGM installer or redirect link found on the index page")

    failures: list[str] = []
    for candidate in candidates:
        try:
            with request(candidate, range_probe=True) as response:
                final_url = response.geturl()
                disposition = response.headers.get("Content-Disposition", "")
        except (HTTPError, URLError, TimeoutError) as exc:
            failures.append(f"{candidate}: {exc}")
            continue

        names = [unquote(urlparse(final_url).path), disposition]
        version_match = next((VERSION_RE.search(name) for name in names if VERSION_RE.search(name)), None)
        if version_match:
            return {
                "index_url": final_index_url,
                "link_url": candidate,
                "download_url": final_url,
                "version": version_match.group(1),
                "filename": Path(unquote(urlparse(final_url).path)).name,
                "source": "index page",
            }

    detail = "; ".join(failures[:3])
    raise GgmInspectError(f"download link did not resolve to a versioned GGMSetup exe: {detail}")


def normalize_version(value: str) -> str:
    value = value.strip().lower().removeprefix("v")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", value):
        raise GgmInspectError(f"invalid version: {value!r}")
    return ".".join(str(int(part)) for part in value.split("."))


def file_version_from_name(path: Path) -> str | None:
    match = VERSION_RE.search(path.name)
    return normalize_version(match.group(1)) if match else None


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    try:
        with request(url) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if temporary.stat().st_size == 0:
            raise GgmInspectError("downloaded installer is empty")
        os.replace(temporary, destination)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise GgmInspectError(f"failed to download {url}: {exc}") from exc


def resolve_program(explicit: str | None, default: str) -> str | None:
    candidate = explicit or default
    return shutil.which(candidate) or (str(Path(candidate)) if Path(candidate).is_file() else None)


def find_named_file(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob("*") if path.is_file() and path.name.lower() == name.lower()]
    if not matches:
        raise GgmInspectError(f"{name} was not found in the extracted installer")
    matches.sort(key=lambda path: (len(path.parts), str(path)))
    return matches[0]


def machine_architecture(path: Path) -> str:
    pe = pefile.PE(str(path), fast_load=True)
    try:
        machine = pe.FILE_HEADER.Machine
    finally:
        pe.close()
    return {
        pefile.MACHINE_TYPE["IMAGE_FILE_MACHINE_AMD64"]: "x64",
        pefile.MACHINE_TYPE["IMAGE_FILE_MACHINE_I386"]: "x86",
        pefile.MACHINE_TYPE.get("IMAGE_FILE_MACHINE_ARM64", 0xAA64): "arm64",
    }.get(machine, f"unknown-0x{machine:04x}")


def find_launcher_binary(root: Path, suffix: str, arch: str) -> Path:
    pattern = re.compile(rf"^GGMWebStart(?:,\d+)?\.{re.escape(suffix)}$", re.I)
    matches = [path for path in root.rglob("*") if path.is_file() and pattern.match(path.name)]
    if not matches:
        raise GgmInspectError(f"GGMWebStart.{suffix} was not found in the extracted installer")

    matching_arch: list[Path] = []
    for path in matches:
        try:
            if machine_architecture(path) == arch:
                matching_arch.append(path)
        except pefile.PEFormatError:
            continue
    if not matching_arch:
        available = ", ".join(f"{path.name}:{machine_architecture(path)}" for path in matches)
        raise GgmInspectError(f"no {arch} GGMWebStart.{suffix} found; available: {available}")
    matching_arch.sort(key=lambda path: (len(path.parts), str(path)))
    return matching_arch[0]


def run_extractor(command: list[str]) -> tuple[bool, str]:
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode == 0, result.stdout.strip()


def unpack_installer(
    setup: Path,
    artifact_dir: Path,
    *,
    arch: str,
    innoextract: str | None,
    innounp: str | None,
    wine: str | None,
) -> tuple[Path, Path, str]:
    if not setup.is_file():
        raise GgmInspectError(f"installer does not exist: {setup}")

    with setup.open("rb") as source:
        if b"MZ" != source.read(2):
            raise GgmInspectError(f"installer is not a PE executable: {setup}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ggm-inno-") as temporary:
        extract_dir = Path(temporary)
        errors: list[str] = []
        backend: str | None = None

        if innoextract:
            command = [innoextract, "--extract", "--silent", "--output-dir", str(extract_dir), str(setup)]
            ok, output = run_extractor(command)
            if ok:
                backend = "innoextract"
            else:
                errors.append(f"innoextract:\n{output}")
                shutil.rmtree(extract_dir)
                extract_dir.mkdir()

        if backend is None and innounp:
            executable = [innounp]
            if os.name != "nt" and Path(innounp).suffix.lower() == ".exe":
                if not wine:
                    errors.append("innounp: a Windows innounp.exe requires wine on this platform")
                    executable = []
                else:
                    executable = [wine, innounp]
            if executable:
                command = executable + ["-x", "-b", "-q", f"-d{extract_dir}", str(setup)]
                ok, output = run_extractor(command)
                if ok:
                    backend = "innounp"
                else:
                    errors.append(f"innounp:\n{output}")

        if backend is None:
            if not innoextract and not innounp:
                errors.append(
                    "no extractor found; pass a current innoextract build or `--innounp innounp.exe` "
                    "(with `--wine wine` on Linux)"
                )
            raise GgmInspectError("all installer extractors failed:\n" + "\n\n".join(errors))

        source_dll = find_launcher_binary(extract_dir, "dll", arch)
        target_dll = artifact_dir / "GGMWebStart.dll"
        shutil.copy2(source_dll, target_dll)

        source_exe = find_launcher_binary(extract_dir, "exe", arch)
        target_exe = artifact_dir / "GGMWebStart.exe"
        shutil.copy2(source_exe, target_exe)

    return target_dll, target_exe, backend


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assembly_version(dotnet_pe: dnfile.dnPE) -> str:
    table = dotnet_pe.net.mdtables.Assembly
    if not table or not table.rows:
        raise GgmInspectError("the DLL does not contain an Assembly metadata row")
    row = table.rows[0]
    return f"{row.MajorVersion}.{row.MinorVersion}.{row.BuildNumber}.{row.RevisionNumber}"


def section_bytes_from_rva(dotnet_pe: dnfile.dnPE, rva: int) -> bytes:
    section = dotnet_pe.get_section_by_rva(rva)
    if section is None:
        return b""
    section_end = section.VirtualAddress + max(section.Misc_VirtualSize, section.SizeOfRawData)
    return dotnet_pe.get_data(rva, max(0, section_end - rva))


def table_runs(decoded: bytes) -> Iterable[tuple[int, list[str]]]:
    for start in range(0, max(0, len(decoded) - 15)):
        tables: list[str] = []
        offset = start
        while offset + 16 <= len(decoded):
            chunk = decoded[offset : offset + 16]
            if len(set(chunk)) != 16 or frozenset(chunk) != HEX_ALPHABET:
                break
            tables.append(chunk.decode("ascii"))
            offset += 16
        if len(tables) >= 4:
            yield start, tables


def extract_substitution_tables(dotnet_pe: dnfile.dnPE) -> dict[str, Any]:
    table = dotnet_pe.net.mdtables.FieldRva
    if not table or not table.rows:
        raise GgmInspectError("the DLL has no FieldRVA data to inspect")

    best: tuple[int, int, list[str], str] | None = None
    for row in table.rows:
        encrypted = section_bytes_from_rva(dotnet_pe, row.Rva)
        decoded = bytes(value ^ (index & 0xFF) ^ 0xAA for index, value in enumerate(encrypted))
        field_name = str(row.Field.row.Name)
        for offset, tables in table_runs(decoded):
            candidate = (len(tables), offset, tables, field_name)
            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        raise GgmInspectError(
            "no hard-coded hex substitution tables were found; the launcher obfuscation may have changed"
        )

    count, offset, tables, field_name = best
    return {
        "field_name": field_name,
        "decoded_blob_offset": offset,
        "all_tables": tables,
        "data_decode_tables": tables[:4],
        "table_count": count,
        "blob_decode": "decoded[i] = field_rva[i] XOR (i & 0xff) XOR 0xaa",
    }


def pe_architecture(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return machine_architecture(path)


def inspect_dll(dll: Path, launcher_exe: Path | None) -> dict[str, Any]:
    try:
        managed = dnfile.dnPE(str(dll))
    except Exception as exc:
        raise GgmInspectError(f"failed to parse .NET assembly {dll}: {exc}") from exc
    if not managed.net:
        raise GgmInspectError(f"not a managed .NET assembly: {dll}")

    try:
        tables = extract_substitution_tables(managed)
        version = assembly_version(managed)
    finally:
        managed.close()

    return {
        "dll": str(dll.resolve()),
        "cv": version,
        "hash": sha256_file(dll),
        "hash_algorithm": "sha256(GGMWebStart.dll)",
        "arch": pe_architecture(launcher_exe),
        "arch_source": str(launcher_exe.resolve()) if launcher_exe else None,
        "substitution_tables": tables,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-version", help="currently supported version, e.g. 1.5.0.2")
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument(
        "--version-url",
        default=DEFAULT_VERSION_URL,
        help="JSON version endpoint; pass an empty value to only use the index page",
    )
    parser.add_argument("--setup", type=Path, help="analyze this local GGMSetup exe")
    parser.add_argument("--dll", type=Path, help="analyze an already extracted GGMWebStart.dll")
    parser.add_argument("--launcher-exe", type=Path, help="native GGMWebStart.exe used to determine arch")
    parser.add_argument("--output-dir", type=Path, default=Path("ggm-artifacts"))
    parser.add_argument("--innoextract", help="innoextract executable or path")
    parser.add_argument("--innounp", help="innounp.exe path; on Linux it is invoked through Wine")
    parser.add_argument("--wine", help="Wine executable/path for running innounp.exe on Linux")
    parser.add_argument("--arch", choices=("x64", "x86"), default="x64")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="only resolve and compare the official version")
    parser.add_argument("--write-json", type=Path, help="also save the result as JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, Any] = {}

    remote = resolve_download(args.index_url, args.version_url)
    result["official"] = remote

    current = normalize_version(args.current_version) if args.current_version else None
    remote_version = normalize_version(remote["version"])
    changed = current is not None and current != remote_version
    result["version_check"] = {
        "current": current,
        "official": remote_version,
        "changed": changed,
    }

    if args.check_only:
        emit_result(result, args.write_json)
        return 2 if changed else 0

    setup = args.setup
    if args.force_download or changed or (current is None and setup is None and args.dll is None):
        setup = args.output_dir / remote_version / remote["filename"]
        if args.force_download or not setup.is_file():
            download_file(remote["download_url"], setup)
        result["downloaded_setup"] = str(setup.resolve())

    if setup is None and args.dll is None:
        emit_result(result, args.write_json)
        return 0

    if args.dll:
        dll = args.dll
        launcher_exe = args.launcher_exe
    else:
        if setup is None:
            raise GgmInspectError("nothing to analyze; pass --setup or --dll")
        setup_version = file_version_from_name(setup)
        artifact_version = setup_version or remote_version
        artifact_dir = args.output_dir / artifact_version
        innoextract = resolve_program(args.innoextract, "innoextract")
        innounp = resolve_program(args.innounp, "innounp")
        wine = resolve_program(args.wine, "wine") if os.name != "nt" else None
        dll, launcher_exe, backend = unpack_installer(
            setup,
            artifact_dir,
            arch=args.arch,
            innoextract=innoextract,
            innounp=innounp,
            wine=wine,
        )
        result["setup"] = {
            "path": str(setup.resolve()),
            "sha256": sha256_file(setup),
            "version_from_filename": setup_version,
            "extractor": backend,
            "selected_arch": args.arch,
        }

    result["launcher"] = inspect_dll(dll, launcher_exe)
    emit_result(result, args.write_json)
    return 0


def emit_result(result: dict[str, Any], path: Path | None) -> None:
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GgmInspectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
