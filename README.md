# Bilibili Downloader Tool

A command-line tool that downloads a Bilibili video, extracts an **instrumental BGM** (vocals/dialogue removed via AI source separation), and converts subtitles/danmaku to **SRT** format.

## Outputs

| File | Description |
|------|-------------|
| `<title>.mp4` | Original video (best available quality) |
| `<title>_BGM_instrumental.mp3` | Clean instrumental background music (no voices/dialogue/SFX) |
| `<title>.srt` | Subtitles/danmaku converted to SRT format |
| `<title>.jpg` | Video thumbnail |
| `<title>.danmaku.xml` | Raw Bilibili danmaku XML (source for SRT) |

## Requirements

| Tool | Purpose | Install |
|------|---------|---------|
| **yt-dlp** | Video & subtitle download | `winget install yt-dlp.yt-dlp` |
| **ffmpeg** | Audio extraction, subtitle transcoding | `winget install FFmpeg` |
| **Python + demucs** | AI vocal/instrumental separation | `pip install demucs` |

## Usage

```powershell
# Full download: video + instrumental BGM + SRT subtitles
python bilibili_tool.py "https://www.bilibili.com/video/BV1ujWb6tE2t/" -o ./my_downloads

# Skip video (use existing file in output dir)
python bilibili_tool.py "URL" --no-video

# Skip BGM extraction (faster if you only need video + subs)
python bilibili_tool.py "URL" --no-bgm

# Skip subtitle processing
python bilibili_tool.py "URL" --no-subs

# Keep temporary files for debugging
python bilibili_tool.py "URL" -o ./out --keep-temp
```

## How It Works

1. **Download** – `yt-dlp` fetches the video, thumbnail, and any available subtitles/danmaku from Bilibili.
2. **Audio extraction** – `ffmpeg` pulls the audio track from the video.
3. **Source separation** – `Demucs` (`--two-stems vocals`) runs AI source separation to isolate vocals from the music. The `no_vocals` stem is saved as the instrumental BGM.
4. **Subtitle conversion** – Bilibili danmaku XML (`<d p="time,...">content</d>`) is parsed and converted to SRT format. Other subtitle formats (VTT, ASS, SSA) are transcoded via `ffmpeg`.

## Notes

- The yt-dlp post-processing warning about danmaku embedding is non-fatal; the video still downloads correctly.
- The instrumental BGM quality depends on Demucs separation; some residual vocals or SFX may remain in complex mixes.
- On Windows, `PYTHONIOENCODING=utf-8` is set automatically when invoking Demucs to avoid console encoding errors with non-ASCII filenames.

## Example Output

```
Finished!
  Video      : E:\zest\test_output\没有骑士的王，是没有故乡的人（合集）【AI全民制作人】.mp4
  BGM (inst) : E:\zest\test_output\没有骑士的王，是没有故乡的人（合集）【AI全民制作人】_BGM_instrumental.mp3
  Subtitle   : E:\zest\test_output\没有骑士的王，是没有故乡的人（合集）【AI全民制作人】.srt