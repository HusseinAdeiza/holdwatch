#!/usr/bin/env bash
# assemble.sh — cut the recorded footage and the drawn cards into the final
# 60-90s demo, with the TTS voiceover laid against it.
#
# The timeline is built from the MEASURED duration of each voiceover clip, not
# from the estimates in the script — an early pass came out at 99.3s, over the
# 90s ceiling, and the VO was re-recorded faster rather than the visuals being
# rushed or the video padded.
set -euo pipefail

FF=/root/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg
V=/root/web3alphatester/paypal/video
C=$V/cards
O=$V/vo
W=$V/out
mkdir -p "$W"

UI=$V/clips/holdwatch_ui.mp4
UI_HOLD=$W/ui_hold.mp4
UI_SLOW=$W/ui_slow.mp4

echo "── durations (seconds) ──"
# Two bugs fixed here, both from `set -e`:
#   1. the awk program was single-quoted inside the function, so quotes closed
#      early and awk exited non-zero — replaced with a python one-liner.
#   2. `ffmpeg -i file` with no output ALWAYS exits 32 ("at least one output
#      file must be specified"), even on success. Under set -e that killed the
#      script on the very first probe. Hence the explicit `|| true`.
FFPROBE=$FF
dur() {
  $FFPROBE -hide_banner -i "$1" 2>&1 | grep -m1 Duration | sed 's/.*Duration: //;s/,.*//' \
  | python3 -c "import sys;h,m,s=sys.stdin.read().strip().split(':');print(f'{int(h)*3600+int(m)*60+float(s):.2f}')" || true
}
B1=$(dur "$O/beat1.ogg"); B2=$(dur "$O/beat2.ogg"); B3=$(dur "$O/beat3.ogg")
B4=$(dur "$O/beat4.ogg"); B5=$(dur "$O/beat5.ogg"); B6=$(dur "$O/beat6.ogg")
for n in B1 B2 B3 B4 B5 B6; do
  printf "  %s = %ss\n" "$n" "${!n}"
done
python3 -c "print(f'  VO total = {$B1+$B2+$B3+$B4+$B5+$B6:.2f}s')"

echo
echo "── preparing footage segments ──"

# Beat 3 needs a longer look at the order card + the unknown-cause badge.
# Slow to 0.85x so a judge can actually read the fields; the VO drives timing.
$FF -hide_banner -loglevel error -y -ss 2 -t "$B3" -i "$UI" \
  -vf "scale=1920:1080,fps=25,setpts=PTS/0.85" -an -c:v libx264 -crf 20 \
  -pix_fmt yuv420p "$UI_HOLD"

# Beat 4 is the architecture section — reuse the scroll, slower still.
$FF -hide_banner -loglevel error -y -ss 12 -t "$B4" -i "$UI" \
  -vf "scale=1920:1080,fps=25,setpts=PTS/0.8" -an -c:v libx264 -crf 20 \
  -pix_fmt yuv420p "$UI_SLOW"

echo "  beat3 segment: $(dur "$UI_HOLD")s"
echo "  beat4 segment: $(dur "$UI_SLOW")s"

echo
echo "── beat 1 (persona) — four drawn stages ──"
# Stage weights: the freeze card is held longest because it is the hook.
B1A=$(python3 -c "print(round($B1*0.05,2))"); B1B=$(python3 -c "print(round($B1*0.20,2))")
B1C=$(python3 -c "print(round($B1*0.30,2))"); B1D=$(python3 -c "print(round($B1*0.45,2))")
printf "  stages: %s %s %s %s = %ss\n" "$B1A" "$B1B" "$B1C" "$B1D" "$B1"

$FF -hide_banner -loglevel error -y \
  -loop 1 -t "$B1A" -i "$C/beat1_0.png" \
  -loop 1 -t "$B1B" -i "$C/beat1_1.png" \
  -loop 1 -t "$B1C" -i "$C/beat1_2.png" \
  -loop 1 -t "$B1D" -i "$C/beat1_3.png" \
  -filter_complex "[0][1][2][3]concat=n=4:v=1:a=0,fps=25,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 20 "$W/beat1.mp4"

echo "  beat1 built: $(dur "$W/beat1.mp4")s"

echo
echo "── beat 2 (reveal) ──"
$FF -hide_banner -loglevel error -y -loop 1 -t "$B2" -i "$C/title.png" \
  -filter_complex "[0]fade=t=in:st=0:d=0.4,fade=t=out:st=$(python3 -c "print($B2-0.3)"):d=0.3,fps=25,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 20 "$W/beat2.mp4"
echo "  beat2 built: $(dur "$W/beat2.mp4")s"

echo
echo "── beat 5 (montage) — fast cuts over the dashboard ──"
C5=$(python3 -c "print(round($B5/3,2))")
printf "  3 cuts of %ss each\n" "$C5"
$FF -hide_banner -loglevel error -y -ss 0  -t "$C5" -i "$UI" \
  -ss 8  -t "$C5" -i "$UI" \
  -ss 16 -t "$C5" -i "$UI" \
  -filter_complex "[0]trim,fps=25[a];[1]trim,fps=25[b];[2]trim,fps=25[c];[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 20 "$W/beat5.mp4"
echo "  beat5 built: $(dur "$W/beat5.mp4")s"

echo
echo "── beat 6 (end card) ──"
$FF -hide_banner -loglevel error -y -loop 1 -t "$B6" -i "$C/end_card.png" \
  -filter_complex "[0]fade=t=in:st=0:d=0.5,fade=t=out:st=$(python3 -c "print($B6-1.2)"):d=1.2,fps=25,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 20 "$W/beat6.mp4"
echo "  beat6 built: $(dur "$W/beat6.mp4")s"

echo
echo "── concatenating picture ──"
$FF -hide_banner -loglevel error -y \
  -i "$W/beat1.mp4" -i "$W/beat2.mp4" -i "$UI_HOLD" -i "$UI_SLOW" \
  -i "$W/beat5.mp4" -i "$W/beat6.mp4" \
  -filter_complex "[0][1][2][3][4][5]concat=n=6:v=1:a=0,fps=25,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 20 -preset medium "$W/picture.mp4"
echo "  picture: $(dur "$W/picture.mp4")s"

echo
echo "── laying the voiceover ──"
$FF -hide_banner -loglevel error -y -i "$W/picture.mp4" \
  -i "$O/beat1.ogg" -i "$O/beat2.ogg" -i "$O/beat3.ogg" \
  -i "$O/beat4.ogg" -i "$O/beat5.ogg" -i "$O/beat6.ogg" \
  -filter_complex "[0:v]copy[v];
    [1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];
    [2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a2];
    [3:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a3];
    [4:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a4];
    [5:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a5];
    [6:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a6];
    [a1][a2][a3][a4][a5][a6]concat=n=6:v=0:a=1[ao]" \
  -map "[v]" -map "[ao]" \
  -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 192k \
  -movflags +faststart "$W/HoldWatch_DEMO.mp4"

echo
echo "── final ──"
$FF -hide_banner -i "$W/HoldWatch_DEMO.mp4" 2>&1 | grep -E "Duration|Stream"
ls -la "$W/HoldWatch_DEMO.mp4" | awk '{printf "  size: %.1f MB\n", $5/1048576}'
python3 -c "
import subprocess,re
o=subprocess.run(['$FF','-hide_banner','-i','$W/HoldWatch_DEMO.mp4'],capture_output=True,text=True).stderr
d=re.search(r'Duration: (\d+):(\d+):([\d.]+)',o)
t=int(d.group(1))*3600+int(d.group(2))*60+float(d.group(3))
print(f'  DURATION: {t:.2f}s  ->  {\"UNDER the 3-min limit\" if t<180 else \"OVER\"}  |  {\"within our 90s target\" if t<=90 else \"over our 90s target\"}')
"
