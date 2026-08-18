# GGM inspector

`ggm_inspect.py` performs four operations without running the Windows installer:

1. Reads `generic_handlers/CheckVersion.ashx`, the JSON endpoint the launcher itself polls,
   which reports the current version and installer URL directly. If that endpoint is
   unavailable, falls back to reading the GGM page and following its redirect. Pass an
   empty `--version-url` to only use the page.
2. Compares the official version with `--current-version`.
3. Downloads and unpacks the Setup only when the version changed, when no current version was supplied, or when `--force-download` is used.
4. Extracts `GGMWebStart.dll` metadata, SHA-256, launcher architecture, and the hard-coded substitution tables.

Python dependencies are declared in the script with PEP 723, so `uv` installs them automatically.

## Version check only

When the version is unchanged, this does not download the Setup:

```bash
uv run ggm_inspect.py --current-version 1.5.0.2
```

Use `--check-only` when exit status `2` should mean that an update is available:

```bash
uv run ggm_inspect.py --current-version 1.5.0.2 --check-only
```

## Analyze a local Setup

The Setup currently uses Inno Setup 6.3.0. Use a current `innoextract` build that supports this format:

```bash
uv run ggm_inspect.py \
  --current-version 1.5.0.2 \
  --setup ./GGMSetup_1.5.0.2.exe \
  --innoextract /usr/local/bin/innoextract \
  --output-dir ./ggm-artifacts
```

The old released `innoextract 1.9` binary cannot parse this particular Setup. A tested fallback is `innounp 2.70.1`; on Linux, run the extractor through Wine. This executes the unpacker, not `GGMSetup.exe`:

```bash
uv run ggm_inspect.py \
  --current-version 1.5.0.2 \
  --setup ./GGMSetup_1.5.0.2.exe \
  --innounp ./innounp.exe \
  --wine wine \
  --output-dir ./ggm-artifacts
```

For a 32-bit launcher, add `--arch x86`. The default is `--arch x64`.

## Automatic update path

If the supplied version differs from the official version, the script downloads the new Setup and analyzes it:

```bash
uv run ggm_inspect.py \
  --current-version 1.4.0.0 \
  --innounp ./innounp.exe \
  --wine wine \
  --output-dir ./ggm-artifacts \
  --write-json ./ggm-artifacts/result.json
```

The selected DLL and native launcher are saved under:

```text
ggm-artifacts/<version>/GGMWebStart.dll
ggm-artifacts/<version>/GGMWebStart.exe
```

The JSON output includes:

- resolved official download URL and version comparison;
- Setup and DLL SHA-256 values;
- `CV` from .NET Assembly metadata;
- `arch` from the native PE machine type;
- all detected substitution tables and the four tables used by the current `Data` decoder.

