# Welcome to LlamaMXD
<img width="1920" height="800" alt="LlamaMXD Banner" src="https://github.com/user-attachments/assets/6b2aa305-6030-4561-ac29-018cdce36470" />
LlamaMXD is a friendly, easy to use media multiplexer, transcoder and downloader for Windows that utilizes [ffmpeg](https://ffmpeg.org) and the [yt-dlp project](https://github.com/yt-dlp).


## Setup
Setup is very simple. First download the latest installer from [Releases](https://github.com/YezanSmadi/LlamaMXD/releases). Next, run the setup wizard and choose your install 
location and whether you'd like a desktop/start menu shortcut or not, and you're done! LlamaMXD is ready for work!

### What LlamaMXD Does
---
LlamaMXD comes with a User's Manual that details everything you need to know about using the program, including what each feature does and cheatsheets for 
setting parameters. The manual is easily accessible in **Settings -> About -> User Manual**.
<p align="center">
<img width="443" height="506.5" alt="LlamaMXD User Manual" src="https://github.com/user-attachments/assets/3c550d32-585b-4f97-a922-cff13b0de921" />
</p>

### Muxing
---
<p align="center">
<img width="896" height="540"alt="muxing-video" src="https://github.com/user-attachments/assets/6a71d835-1fa5-4dbe-af0b-5c94861e30ef" />
</p>

In the Muxing (Multiplexing) tab, you can combine and package/repackage video, audio, subtitles, and chapters into one file without re-encoding. It's completely 
lossless; video/audio/subtitle/chapter streams are simply copied and not manipulated.

### Encoding
---
<p align="center">
<img width="896" height="540" alt="encoding-video" src="https://github.com/user-attachments/assets/126ea353-8ba4-4bf9-90fb-2d9ed90b6a4a" />
</p>

In the Encoding tab, you can package/repackage video, audio, subtitle, and chapter streams into a compressed file, which allows for better size and quality management but isn't 
a lossless process; every encode loses a little quality. The amount of quality sacrificed can be tweaked here.
<table>
  <tr>
    <td align="center"><b>HDR (original)</b></td>
    <td align="center"><b>SDR (tonemapped)</b></td>
  </tr>
  <tr>
    <td><img width="424" height="239.5" alt="encoding-video-hdr" src="https://github.com/user-attachments/assets/e240c577-83d7-4b28-a2b8-c6d7b3caab6c" /></td>
    <td><img width="424" height="239.5" alt="encoding-video-sdr" src="https://github.com/user-attachments/assets/bdc8fff3-7845-41ff-ac6c-5d6d96e3fbee" /></td>
  </tr>
</table>

Encoding also comes with an HDR to SDR converter that can be switched on and off. The converter utilizes the BT.2390 color curve (the most color accurate tonemap curve) 
to tonemap HDR images to SDR.

### Downloader
---
<p align="center">
<img width="896" height="540" alt="downloader" src="https://github.com/user-attachments/assets/50106497-7170-4fd5-99c7-19a943631490" />
</p>

The LlamaMXD Downloader utilizes the power of the [yt-dlp](https://github.com/yt-dlp) to fetch and download video/audio from the web for download.

### Reporting problems
---
Found a bug or have a suggestion? Please open an issue on the
[Issue Tracker](https://github.com/YezanSmadi/LlamaMXD/issues). If something went wrong
with a job or the app crashed, attach the log files to your report. You can find them in
LlamaMXD under **Settings -> Performance -> LlamaLog -> Open Log Folder**. They show what
the app was doing when the problem happened and make it much easier to track down.

### License and credits
---
LlamaMXD is free software, released under the
[GNU General Public License v3.0 or later](LICENSE.txt). You can use, change and share it
under those terms.

LlamaMXD bundles [ffmpeg](https://ffmpeg.org), [yt-dlp](https://github.com/yt-dlp/yt-dlp)
and [Deno](https://deno.com), along with other libraries and fonts. Each of these is
covered by its own license, not by LlamaMXD's. Their license texts and source links are
in the [`licenses/`](licenses/) folder.

LlamaMXD™ and Pak the Llama™ are trademarks of Yezan Smadi. Logo and brand assets Copyright © 2026 Yezan Smadi, all rights reserved. 
They are not covered by the GPL. If you fork or redistribute LlamaMXD, please use your own name
and artwork.

### Building from source
---
LlamaMXD runs on Windows with Python 3.13.

```
pip install -r requirements.txt
python main.py
```

The `dependables/` folder is not part of this repository, because the files are too large
for GitHub. Create it in the project root and put `ffmpeg.exe`, `ffprobe.exe`,
`yt-dlp.exe` and `deno.exe` inside it before running the app.

