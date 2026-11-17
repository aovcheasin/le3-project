#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bilibili Downloader Tool
========================
Downloads a Bilibili video, extracts an instrumental BGM (vocals removed via
Demucs AI source separation), and converts subtitles/danmaku to SRT format.

Requirements (system tools):
    - yt-dlp   : https://github.com/yt-dlp/yt-dlp
    - ffmpeg   : https://ffmpeg.org/
    - demucs   : https://github.com/facebookresearch/demucs  (Python package)

Usage:
    python bilibili_tool.py "https://www.bilibili.com/video/BV1ujWb6tE2t/" -o ./output

Examples:
    # Download everything (video + instrumental BGM + SRT subtitles)
    python bilibili_tool.py "URL" -o ./my_downloads

    # Skip video, only extract BGM + subs from an already-downloaded video
    python bilibili_tool.py "URL" --no-video

    # Keep temp files for debugging
    python bilibili_tool.py "URL" -o ./out --keep-temp
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path
from typing import List, Optional, Tuple


def find_executable(name: str) -> Optional[str]:
    """Locate an executable in PATH or common Windows install locations."""
    result = shutil.which(name)
    if result:
        return result
    if sys.platform == "win32":
        for directory in [r"C:\WINDOWS\system32", r"C:\Program Files\ffmpeg\bin",
                          r"C:\Program Files (x86)\ffmpeg\bin"]:
            candidate = os.path.join(directory, name if name.endswith(".exe") else name + ".exe")
            if os.path.isfile(candidate):
                return candidate
    return None


def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp: HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def normalize_bilibili_url(url: str) -> str:
    """Clean a Bilibili URL by removing language prefixes and tracking params.

    Bilibili URLs often contain /zh-Hans/, /zh-CN/, or tracking parameters
    (trackid, spm_id_from, vd_source, etc.) that can cause yt-dlp to receive
    an HTML consent/login page instead of the video manifest.
    """
    try:
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parsed = urlparse(url)

        # Remove language prefix from path (e.g. /zh-Hans/video/... -> /video/...)
        path = parsed.path
        parts = [p for p in path.split("/") if p]
        lang_prefixes = {"zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "en", "ja", "ko"}
        if parts and parts[0] in lang_prefixes:
            parts = parts[1:]
        path = "/" + "/".join(parts)

        # Drop tracking/query parameters that often trigger consent pages
        keep_params = {}  # intentionally empty — Bilibili video page works without them
        query = urlencode(keep_params, doseq=True)

        return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, query, parsed.fragment))
    except Exception:
        # If parsing fails, return the URL unchanged
        return url


def run_command(cmd: List[str], cwd: Optional[str] = None,
                timeout: Optional[int] = None,
                env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Run a shell command, return (returncode, stdout, stderr)."""
    merged_env = None
    if env:
        merged_env = os.environ.copy()
        merged_env.update(env)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=merged_env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return -1, stdout, f"Command timed out after {timeout}s: {exc}"
    except Exception as exc:
        return -1, "", str(exc)
class BilibiliDownloader:
    """Orchestrates yt-dlp, ffmpeg and Demucs to produce video + instrumental BGM + SRT."""

    def __init__(self, output_dir: str = "./bilibili_downloads", keep_temp: bool = False,
                 cookies_from_browser: Optional[str] = None):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.keep_temp = keep_temp
        self.temp_dir = Path(tempfile.mkdtemp(prefix="bilibili_dl_"))
        self.cookies_from_browser = cookies_from_browser

        self.yt_dlp = find_executable("yt-dlp")
        self.ffmpeg = find_executable("ffmpeg")
        self.python = shutil.which("python") or shutil.which("python3")
        self.demucs_bin = find_executable("demucs")

        missing = []
        if not self.yt_dlp:
            missing.append("yt-dlp")
        if not self.ffmpeg:
            missing.append("ffmpeg")
        if not self.python:
            missing.append("python (needed for demucs)")
        if missing:
            raise RuntimeError(
                "Missing required tools: " + ", ".join(missing) +
                ". Install yt-dlp & ffmpeg, and Python with demucs."
            )

    def __del__(self):
        if not self.keep_temp and hasattr(self, "temp_dir"):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def download_video(self, url: str) -> Optional[Path]:
        """Download video (+ thumbnail + subtitles) via yt-dlp."""
        print("[1/4] Downloading video with yt-dlp ...")
        out_template = str(self.output_dir / "%(title)s.%(ext)s")

        # Normalize URL: strip language prefix and tracking parameters
        clean_url = normalize_bilibili_url(url)
        if clean_url != url:
            print(f"  Normalized URL: {clean_url}")

        cmd = [
            self.yt_dlp,
            "-o", out_template,
            "--write-thumbnail",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "all",
            "--embed-subs",
            "--no-playlist",
        ]

        # Add cookies from browser if specified (helps with Bilibili auth walls)
        if self.cookies_from_browser:
            cmd.extend(["--cookies-from-browser", self.cookies_from_browser])
            print(f"  Using cookies from browser: {self.cookies_from_browser}")

        cmd.append(clean_url)
        rc, _out, err = run_command(cmd, timeout=600)

        if rc != 0:
            err_tail = err[-800:] if err else ""
            print(f"  WARNING: yt-dlp exited {rc} (non-fatal if video was saved).")
            if err_tail:
                print(f"  yt-dlp notes: {err_tail}")

        # Check for video file regardless of exit code — yt-dlp may exit non-zero
        # due to post-processing (e.g. subtitle embedding) while the video itself
        # was already downloaded successfully.
        video_extensions = (".mp4", ".mkv", ".webm", ".mov", ".flv")
        video_files = [
            p for p in self.output_dir.iterdir()
            if p.is_file() and p.suffix.lower() in video_extensions
        ]
        if not video_files:
            print("  ERROR: No video file found after download.")
            if "unusual" in err_tail or "html" in err_tail.lower():
                print("  HINT: Bilibili returned an HTML page instead of a video.")
                print("        Try: --cookies-from-browser edge  (or chrome, firefox)")
                print("        Or the video may require login / be region-locked.")
            return None
        video_file = max(video_files, key=lambda p: p.stat().st_size)
        print(f"  Video saved: {video_file.name}")
        return video_file

    def extract_audio(self, video_path: Path) -> Optional[Path]:
        """Extract audio from video using ffmpeg (copy when possible, else transcode)."""
        print("[2/4] Extracting audio from video ...")
        audio_path = self.temp_dir / f"{video_path.stem}_audio.aac"
        cmd = [self.ffmpeg, "-y", "-i", str(video_path), "-vn", "-acodec", "copy", str(audio_path)]
        rc, _out, err = run_command(cmd, timeout=120)

        if rc != 0 or not audio_path.exists():
            audio_path = self.temp_dir / f"{video_path.stem}_audio.mp3"
            cmd = [
                self.ffmpeg, "-y", "-i", str(video_path),
                "-vn", "-ab", "192k", "-ar", "44100", str(audio_path),
            ]
            rc, _out, err = run_command(cmd, timeout=120)
            if rc != 0 or not audio_path.exists():
                print(f"  ERROR: Audio extraction failed: {err[-300:] if err else ''}")
                return None

        print(f"  Audio extracted: {audio_path.name}")
        return audio_path

    def separate_instrumental(self, audio_path: Path, output_name: str) -> Optional[Path]:
        """Use Demucs (--two-stems vocals) to isolate instrumental BGM."""
        print("[3/4] Separating instrumental BGM from vocals (Demucs) ...")

        demucs_output = self.temp_dir / "demucs_out"
        demucs_output.mkdir(exist_ok=True)

        if self.demucs_bin:
            demucs_cmd = [self.demucs_bin]
        elif self.python:
            demucs_cmd = [self.python, "-m", "demucs.separate"]
        else:
            print("  ERROR: No Demucs executable or Python found.")
            return None

        cmd = demucs_cmd + [
            "--two-stems", "vocals",
            "--out", str(demucs_output),
            "--mp3", "--mp3-bitrate", "192",
            str(audio_path),
        ]
        print("  Running Demucs source separation (may take several minutes) ...")
        # PYTHONIOENCODING=utf-8 avoids Windows cp1252 crashes on non-ASCII filenames
        rc, _out, err = run_command(cmd, timeout=1800,
                                    env={"PYTHONIOENCODING": "utf-8"})
        if rc != 0:
            print(f"  ERROR: Demucs failed: {err[-500:] if err else ''}")
            return None

        no_vocals = list(demucs_output.rglob("no_vocals.mp3"))
        if not no_vocals:
            print("  ERROR: 'no_vocals.mp3' not found in Demucs output.")
            return None

        instrumental_src = no_vocals[0]
        instrumental_dst = self.output_dir / f"{output_name}_BGM_instrumental.mp3"
        shutil.copy2(instrumental_src, instrumental_dst)
        print(f"  Instrumental BGM saved: {instrumental_dst.name}")
        return instrumental_dst
    # -- subtitle handling --------------------------------------------------

    def convert_subtitles_to_srt(self, video_path: Optional[Path]) -> List[Path]:
        """Find downloaded subtitle/danmaku files and convert them to SRT."""
        print("[4/4] Processing subtitles ...")
        srt_files: List[Path] = []

        candidates: List[Path] = []
        for pattern in ["*.vtt", "*.srt", "*.ass", "*.ssa", "*.xml", "*.json", "*.danmaku.xml"]:
            candidates.extend(self.output_dir.glob(pattern))

        seen = set()
        unique: List[Path] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)

        if not unique:
            print("  No subtitle/danmaku files found in output directory.")
            return []

        for sub_file in unique:
            try:
                if "danmaku" in sub_file.name.lower() and sub_file.suffix.lower() == ".xml":
                    srt_path = self._convert_danmaku_to_srt(sub_file)
                else:
                    srt_path = self._convert_generic_subtitle_to_srt(sub_file)
                if srt_path and srt_path.exists():
                    srt_files.append(srt_path)
                    print(f"  SRT created: {srt_path.name}")
            except Exception as exc:
                print(f"  WARNING: Could not convert {sub_file.name}: {exc}")

        return srt_files

    def _convert_danmaku_to_srt(self, xml_path: Path) -> Optional[Path]:
        """Convert Bilibili danmaku XML to SRT."""
        srt_path = xml_path.with_suffix(".srt")
        if ".danmaku" in srt_path.name:
            srt_path = Path(str(srt_path).replace(".danmaku", ""))

        tree = ET.parse(str(xml_path))
        root = tree.getroot()

        entries: List[Tuple[float, str]] = []

        # Format A: <d p="time,mode,fontsize,color,date,pool,uid,rowid">content</d>
        for d_elem in root.iter("d"):
            p_attr = d_elem.get("p", "")
            content = (d_elem.text or "").strip()
            if not content or not p_attr:
                continue
            parts = p_attr.split(",")
            try:
                time_sec = float(parts[0])
            except (ValueError, IndexError):
                continue
            entries.append((time_sec, content))

        # Format B: <i><content>...</content><ctime>...</ctime></i>
        if not entries:
            for i_elem in root.iter("i"):
                content_elem = i_elem.find("content")
                time_elem = i_elem.find("ctime")
                if content_elem is None or time_elem is None:
                    continue
                content = (content_elem.text or "").strip()
                try:
                    time_sec = float(time_elem.text or 0)
                except ValueError:
                    continue
                if content:
                    entries.append((time_sec, content))

        if not entries:
            return None

        entries.sort(key=lambda x: x[0])
        default_duration = 4.0

        with open(srt_path, "w", encoding="utf-8") as f:
            for idx, (start_sec, text) in enumerate(entries, 1):
                if idx < len(entries):
                    end_sec = min(start_sec + default_duration, entries[idx][0])
                else:
                    end_sec = start_sec + default_duration
                if end_sec <= start_sec:
                    end_sec = start_sec + default_duration
                f.write(f"{idx}\n")
                f.write(f"{format_srt_timestamp(start_sec)} --> {format_srt_timestamp(end_sec)}\n")
                f.write(f"{text}\n\n")

        return srt_path

    def _convert_generic_subtitle_to_srt(self, sub_file: Path) -> Optional[Path]:
        """Pass-through for .srt, or transcode VTT/ASS/SSA via ffmpeg."""
        if sub_file.suffix.lower() == ".srt":
            return sub_file

        srt_path = sub_file.with_suffix(".srt")
        cmd = [self.ffmpeg, "-y", "-i", str(sub_file), str(srt_path)]
        rc, _out, err = run_command(cmd, timeout=60)
        if rc == 0 and srt_path.exists():
            return srt_path
        return None


    # -- orchestration ------------------------------------------------------

    def process(
        self,
        url: str,
        skip_video: bool = False,
        skip_bgm: bool = False,
        skip_subs: bool = False,
    ) -> dict:
        """Run the full pipeline and return a dict of produced files."""
        print("=" * 60)
        print("Bilibili Downloader Tool")
        print(f"URL : {url}")
        print(f"Out : {self.output_dir}")
        print("=" * 60)

        results: dict = {"video": None, "bgm_instrumental": None, "subtitles": []}

        # --- Step 1: video (yt-dlp also grabs subtitles/danmaku) ---
        if skip_video:
            videos = [p for p in self.output_dir.iterdir()
                      if p.is_file() and p.suffix.lower() in (".mp4", ".mkv", ".webm")]
            video_path = max(videos, key=lambda p: p.stat().st_size) if videos else None
        else:
            video_path = self.download_video(url)
        results["video"] = video_path

        # --- Step 2 & 3: audio extraction + Demucs instrumental separation ---
        if not skip_bgm and video_path:
            audio_path = self.extract_audio(video_path)
            if audio_path:
                instrumental = self.separate_instrumental(audio_path, video_path.stem)
                results["bgm_instrumental"] = instrumental

        # --- Step 4: subtitles ---
        if not skip_subs:
            subs = self.convert_subtitles_to_srt(video_path)
            results["subtitles"] = subs

        # --- Summary ---
        print("=" * 60)
        print("Finished!")
        if results["video"]:
            print(f"  Video      : {results['video']}")
        if results["bgm_instrumental"]:
            print(f"  BGM (inst) : {results['bgm_instrumental']}")
        for srt in results["subtitles"]:
            print(f"  Subtitle   : {srt}")
        print("=" * 60)
        return results

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a Bilibili video, extract instrumental BGM (vocals removed), and convert subtitles to SRT.",
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument("-o", "--output", default="./bilibili_downloads",
                        help="Output directory (default: ./bilibili_downloads)")
    parser.add_argument("--keep-temp", action="store_true",
                        help="Keep temporary working files (for debugging)")
    parser.add_argument("--no-video", action="store_true",
                        help="Skip video download (use existing file in output dir)")
    parser.add_argument("--no-bgm", action="store_true",
                        help="Skip instrumental BGM extraction")
    parser.add_argument("--no-subs", action="store_true",
                        help="Skip subtitle/danmaku processing")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="Load cookies from browser (edge, chrome, firefox, etc.) " +
                             "to bypass Bilibili auth walls")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        downloader = BilibiliDownloader(
            output_dir=args.output,
            keep_temp=args.keep_temp,
            cookies_from_browser=args.cookies_from_browser,
        )
        downloader.process(
            url=args.url,
            skip_video=args.no_video,
            skip_bgm=args.no_bgm,
            skip_subs=args.no_subs,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()

