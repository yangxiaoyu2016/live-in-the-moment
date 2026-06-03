# Live in the Moment by Yang&Codex

人只活一些瞬间

Archive your own WeChat Moments text and locally cached images into portable files.

This project is for personal data recovery and archiving on your own Windows machine. It does not bypass WeChat account login, does not fetch private data from remote services, and must only be used on data you own or are authorized to process.

## Download the Windows app

For the fastest start, download the ready-to-run Windows executable:

[Download LiveInTheMoment.exe](https://github.com/yangxiaoyu2016/live-in-the-moment/releases/latest/download/LiveInTheMoment.exe)

Then log in to WeChat for Windows, keep it running, open the app, and click `One-click export all Moments`.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

## Features

- Export Moments date and text from `moments_extracted.json` into JSON, CSV, Markdown, and TXT.
- Build a local personal HTML report from `moments_text.txt`.
- Decode locally cached WeChat V1/V2 image cache files when you provide the V2 image cache AES key.
- Build a local, openable HTML gallery with Markdown and media manifest outputs.
- Remove duplicate images and keep the clearest copy by pixel count.
- Optional Windows-only helper to probe a running `Weixin.exe` process for the V2 image cache key.

## Install

### Downloadable Windows app

For most users, download [LiveInTheMoment.exe](https://github.com/yangxiaoyu2016/live-in-the-moment/releases/latest/download/LiveInTheMoment.exe) and double-click it.

In the app:

1. Log in to WeChat for Windows and keep it running.
2. Open `LiveInTheMoment.exe`.
3. Let the app auto-detect the WeChat data folder, or choose `xwechat_files` manually.
4. Choose an output folder.
5. Click `One-click export all Moments`.

The executable is not code-signed, so Windows SmartScreen may show a warning on first run.

Image export is automatic when the image cache key is available in the running WeChat process. If the app exports text but skips images, open Moments or any Moment photo in WeChat, then run the export again.

### Python CLI

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

## Usage

Export text:

```powershell
limm export-text `
  --input examples\moments_extracted.sample.json `
  --output-dir out\text
```

Build a local personal HTML report from exported text:

```powershell
limm report-from-txt `
  --input out\text\moments_text.txt
```

One-click export from the currently logged-in Windows WeChat:

```powershell
limm one-click `
  --output-dir out\one-click
```

Build a local gallery from an extracted Moments JSON and your WeChat account cache folder:

```powershell
limm build-gallery `
  --input path\to\moments_extracted.json `
  --account-root path\to\xwechat_files\wxid_example `
  --output-dir out\gallery `
  --v2-aes-key 0123456789abcdef `
  --v2-xor-key 5
```

Probe the V2 image cache key from a running WeChat process:

```powershell
limm probe-v2-key `
  --sample path\to\one\encrypted\Sns\Img\cache_file `
  --pid 12345
```

If `--pid` is omitted, the tool tries to find `Weixin.exe` automatically.

## Inputs

`moments_extracted.json` should be a JSON list. Each row may contain:

- `create_time`: Unix timestamp
- `create_time_iso`: ISO datetime string
- `content_desc`: Moments text
- `media_urls`, `thumb_urls`, `media_md5`: optional media references
- `post_id`, `tid`: optional identifiers

The sample in `examples/` is fake data.

## Outputs

`export-text` writes:

- `moments_text.json`
- `moments_text.csv`
- `moments_text.md`
- `moments_text.txt`

`report-from-txt` writes:

- `moments_report.html`

`build-gallery` writes:

- `openable_moments_gallery.html`
- `openable_moments_gallery.md`
- `openable_media_manifest.csv`
- `openable_media_manifest.json`
- `media_by_month/`

Do not publish generated outputs unless you have reviewed them for private text, photos, local paths, and account identifiers.

## Safety

This tool can process sensitive personal data. Before publishing a repository, always search for:

- your local username
- real `wxid_...` values
- real AES keys
- real Moments text
- real photos, videos, database files, and export outputs

The memory probing helper reads a local process you specify or own. Use it only on your own machine and your own WeChat session.

## License

MIT
