# RepliCut AI — Windows MVP

A beginner-friendly desktop prototype for reference-guided video assembly.

## What this first build does
- Choose one reference video and multiple raw clips.
- Detect approximate scene changes in the reference.
- Rebuild a vertical 2K (1440×2560) or horizontal 2K (2560×1440) video using the detected scene durations and uploaded raw clips.
- Optionally use the reference video's audio as the soundtrack.
- Export an MP4 file.

## Important limitations
This is a functional first-stage editor, **not** an exact AI clone of a reference edit. It does not yet understand semantic shot matching, identify licensed songs, or recreate complex transitions/effects perfectly. Scene detection is heuristic and raw clips are currently selected in upload order. Review the exported video before publishing.

## Download the Windows app
Open the repository's **Actions** tab, select **Build RepliCut AI for Windows**, and download the `RepliCut-AI-Windows` artifact from a successful run. The artifact contains the packaged app.

## Run from source (optional)
Python 3.11+ is required:
```powershell
py -m pip install -r requirements.txt
py app.py
``

The GitHub Actions workflow builds a Windows executable and bundles FFmpeg. You do not need Python or FFmpeg installed to run the packaged app.
