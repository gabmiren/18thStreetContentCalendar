"""Mix and finish a reel: voice after the title, music under everything, effects, loudness, and the video.
usage: python3 -I mix.py --video page.mp4 --vo vo.mp3 --off 2.5 --sfx sfx.wav --out final.mp4
       [--music assets/lofi-technology.mp3] [--music-db -23] [--vo-fade .35] [--tail 2.2]
- The voice starts at --off (the end of the title) and fades in over --vo-fade so it never starts abruptly.
- The music runs from 0 under everything at --music-db (-23 dB on the lofi technology track, the balance of the approved retail sales reel) and fades out over the last --tail seconds.
- Two-pass loudness to -14 LUFS with true peak -2 dB, then muxed onto the silent video (AAC 192k).
Writes final.mp4 and final.wav (the mix), and prints the measured loudness."""
import sys, json, subprocess, argparse
p = argparse.ArgumentParser()
p.add_argument('--video', required=True); p.add_argument('--vo', required=True); p.add_argument('--off', type=float, default=2.5)
p.add_argument('--sfx'); p.add_argument('--out', required=True); p.add_argument('--music', default='assets/lofi-technology.mp3')
p.add_argument('--music-db', type=float, default=-23); p.add_argument('--vo-fade', type=float, default=.35); p.add_argument('--tail', type=float, default=2.2)
o = p.parse_args()
D = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', o.video], capture_output=True, text=True).stdout)
ms = int(o.off * 1000); raw = o.out.rsplit('.', 1)[0] + '_raw.wav'; wav = o.out.rsplit('.', 1)[0] + '.wav'
ins = ['-i', o.vo, '-i', o.music] + (['-i', o.sfx] if o.sfx else [])
fc = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,afade=t=in:st=0:d={o.vo_fade},adelay={ms}|{ms},apad[v];"
      f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{D},asetpts=PTS-STARTPTS,volume={o.music_db}dB,afade=t=out:st={max(0, D-o.tail)}:d={o.tail}[m];")
if o.sfx: fc += "[2:a]aresample=48000,aformat=channel_layouts=stereo,apad[s];[v][m][s]amix=inputs=3:normalize=0:duration=longest[x];[x]atrim=0:%s[y]" % D
else: fc += "[v][m]amix=inputs=2:normalize=0:duration=longest[x];[x]atrim=0:%s[y]" % D
subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + ins + ['-filter_complex', fc, '-map', '[y]', '-ar', '48000', raw], check=True)
ln = 'loudnorm=I=-14:TP=-2:LRA=11'
m = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', raw, '-af', ln + ':print_format=json', '-f', 'null', '-'], capture_output=True, text=True).stderr
j = json.loads(m[m.rindex('{'):m.rindex('}') + 1])
ln2 = f"{ln}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true"
subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', raw, '-af', ln2 + ',aresample=192000,alimiter=limit=0.74:attack=1:release=60:level=disabled,aresample=48000', '-ar', '48000', wav], check=True)   # the limiter catches true peaks loudnorm misses
subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', o.video, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', o.out], check=True)
r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', o.out, '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
I = r[r.rindex('I:'):].split()[1]; TP = r[r.rindex('Peak:'):].split()[1]
print(f'{o.out}: {D:.2f}s, {I} LUFS, true peak {TP} dBTP (target -14 LUFS, -2 dBTP or lower)')
