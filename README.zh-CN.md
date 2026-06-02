# Live in the moment（微信朋友圈导出工具）

把你自己的微信朋友圈文字和本地缓存图片整理成可长期保存、可本地打开的归档文件。

本项目用于个人数据恢复和归档，只应在你自己的 Windows 电脑上处理你本人拥有或已获授权的数据。它不会绕过微信账号登录，不会从远程服务抓取他人的私密数据。

## 功能

- 从 `moments_extracted.json` 导出朋友圈发表时间和文字，输出 JSON、CSV、Markdown、TXT。
- 在你提供 V2 图片缓存 AES key 后，解密微信本地 V1/V2 图片缓存。
- 生成本地可打开的 HTML 图文归档、Markdown 和 media manifest。
- 对重复图片去重，保留像素更高、更清晰的版本。
- 提供 Windows 专用的 `Weixin.exe` 进程探测辅助命令，用来寻找 V2 图片缓存 key。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

## 使用

导出文字：

```powershell
limm export-text `
  --input examples\moments_extracted.sample.json `
  --output-dir out\text
```

从朋友圈 JSON 和微信本地缓存目录生成图文归档：

```powershell
limm build-gallery `
  --input path\to\moments_extracted.json `
  --account-root path\to\xwechat_files\wxid_example `
  --output-dir out\gallery `
  --v2-aes-key 0123456789abcdef `
  --v2-xor-key 5
```

从正在运行的微信进程探测 V2 图片缓存 key：

```powershell
limm probe-v2-key `
  --sample path\to\one\encrypted\Sns\Img\cache_file `
  --pid 12345
```

如果不传 `--pid`，工具会尝试自动查找 `Weixin.exe`。

## 输入格式

`moments_extracted.json` 应该是一个 JSON 数组。每条记录可以包含：

- `create_time`：Unix 时间戳
- `create_time_iso`：ISO 时间字符串
- `content_desc`：朋友圈文字
- `media_urls`、`thumb_urls`、`media_md5`：可选媒体引用
- `post_id`、`tid`：可选标识符

`examples/` 里的样例是完全虚构的脱敏数据。

## 输出文件

`export-text` 会生成：

- `moments_text.json`
- `moments_text.csv`
- `moments_text.md`
- `moments_text.txt`

`build-gallery` 会生成：

- `openable_moments_gallery.html`
- `openable_moments_gallery.md`
- `openable_media_manifest.csv`
- `openable_media_manifest.json`
- `media_by_month/`

不要把生成的真实导出结果直接发布到 GitHub。发布前必须检查其中是否包含真实文字、照片、本地路径、微信账号 ID 或密钥。

## 安全边界

这个工具会处理高度敏感的个人数据。开源或分享任何目录前，请至少搜索：

- 你的本地用户名
- 真实 `wxid_...`
- 真实 AES key
- 真实朋友圈文字
- 真实照片、视频、数据库和导出结果

`probe-v2-key` 会读取你指定或自动发现的本地微信进程内存。只应在你自己的电脑、自己的微信会话上使用。

## License

MIT

