"""Captions for a reel page, timed from the voice audio and the script.
usage: python3 -I caps.py vo.mp3 script.txt [--keys "gap,flat,holding"] [--tr tr.json] [--max-words 4] > caps.js
- vo.mp3: the voice alone (voice time 0 = the start of the file).
- script.txt: the words exactly as they should read on screen (8:30, 0.8%, it's). Write numbers the way they are spoken
  ("plus 0.2%" if the voice says "plus").
- How it times words: it finds the pauses in the voice, shares the script's words out over the stretches of speech
  (sentence and comma breaks prefer to land on pauses), then spaces words inside each stretch by their spoken length.
  Whisper's own word times drift after long pauses, so they are only used as a cross-check (--tr).
- Key words (accent colour): every word with a digit, plus --keys. Aim for one or two per sentence.
Prints `CAPS=[...];` to paste into the page; the report goes to stderr. Listen to any word it flags."""
import sys, json, re, subprocess
import numpy as np

a = sys.argv[1:]
if len(a) < 2: sys.exit(__doc__)
vo, sc = a[0], a[1]; keys = set(); MAXW = 4; MAXC = 24; trf = None
i = 2
while i < len(a):
    if a[i] == '--keys': keys = {re.sub(r'\W', '', k.lower()) for k in a[i+1].split(',')}; i += 2
    elif a[i] == '--max-words': MAXW = int(a[i+1]); i += 2
    elif a[i] == '--tr': trf = a[i+1]; i += 2
    else: sys.exit('unknown option ' + a[i])

# ---- speech stretches from the audio
SR = 16000
x = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', vo, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True, check=True).stdout, np.float32)
hop = 160; n = len(x) // hop
db = 20 * np.log10(np.sqrt((x[:n*hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
thr = max(np.percentile(db, 95) - 30, -50); sp = db > thr
segs = []; k = 0
while k < n:
    if sp[k]:
        j = k
        while j < n and (sp[j] or (j + 16 < n and sp[j:j+16].any())): j += 1   # pauses shorter than 160 ms stay inside a stretch
        if j - k >= 6: segs.append([k * hop / SR, j * hop / SR])
        k = j
    else: k += 1

# ---- spoken length of each word (a rough syllable proxy)
S = open(sc).read().split()
def spoken(w):
    w = w.lower(); n = 0
    for ch in w:
        if ch.isdigit(): n += 4
        elif ch == '%': n += 7
        elif ch == ':': n += 1
        elif ch.isalpha(): n += 1
    if re.search(r'\d\.\d', w): n += 5          # "point"
    return max(n, 2) + 2
Ls = np.array([spoken(w) for w in S], float)
brk = [bool(re.search(r'[.,?!:;]$', w)) for w in S]

# ---- share words over stretches: dynamic programming, each stretch gets a run of words whose spoken length fits its duration
N, M = len(S), len(segs)
dur = np.array([b - a for a, b in segs]); rate = Ls.sum() / dur.sum()
cum = np.concatenate([[0], np.cumsum(Ls)])
INF = 1e18; D = np.full((M + 1, N + 1), INF); D[0, 0] = 0; BK = np.zeros((M + 1, N + 1), int)
for m in range(1, M + 1):
    want = dur[m-1] * rate
    for j in range(1, N + 1):
        best, arg = INF, 0
        for i0 in range(max(0, j - 25), j):
            if D[m-1, i0] >= INF: continue
            got = cum[j] - cum[i0]
            c = D[m-1, i0] + ((got - want) / max(want, 6)) ** 2 + (0 if brk[j-1] else 1.5)
            if c < best: best, arg = c, i0
        D[m, j] = best; BK[m, j] = arg
if D[M, N] >= INF: sys.exit('could not fit the script to the audio: check the script matches the voice')
cuts = [N]
for m in range(M, 0, -1): cuts.append(BK[m, cuts[-1]])
cuts = cuts[::-1]
st = np.zeros(N); en = np.zeros(N)
for m in range(M):
    i0, i1 = cuts[m], cuts[m+1]; a0, b0 = segs[m]; tot = Ls[i0:i1].sum(); t = a0
    for k in range(i0, i1): st[k] = t if k == i0 else t - .06; t += (b0 - a0) * Ls[k] / tot; en[k] = t   # words inside a stretch start a touch early: the vowel carries the length

# ---- caption chunks: break at punctuation, at a pause, at 4 words or 24 characters
chunks, cur = [], []
for k, w in enumerate(S):
    cur.append(k); last = k == N - 1
    gap = st[k+1] - en[k] if not last else 9
    chars = sum(len(S[j]) + 1 for j in cur); nxt = len(S[k+1]) + 1 if not last else 0
    if last or brk[k] or gap > .2 or len(cur) >= MAXW or chars + nxt > MAXC: chunks.append(cur); cur = []
out = []
for c_i, c in enumerate(chunks):
    a0 = max(0, st[c[0]] - .06)
    nx = st[chunks[c_i+1][0]] - .06 if c_i + 1 < len(chunks) else None
    b0 = nx if nx is not None and nx - en[c[-1]] < .7 else en[c[-1]] + .3
    ws = [f"['{S[k].replace(chr(39), '’')}',{st[k]:.2f}" + (",1]" if re.search(r'\d', S[k]) or re.sub(r'\W', '', S[k].lower()) in keys else "]") for k in c]
    out.append(f"[{a0:.2f},{b0:.2f},[{','.join(ws)}]]")
print('CAPS=[' + ',\n'.join(out) + '];')
print(f'{len(chunks)} caption chunks, {N} words over {M} stretches of speech ({x.size/SR:.2f}s of audio).', file=sys.stderr)
if trf:
    import difflib
    W = [w for s in json.load(open(trf))['segments'] for w in s['words']]
    nm = lambda w: re.sub(r'[^a-z0-9]', '', w.lower())
    sm = difflib.SequenceMatcher(None, [nm(w) for w in S], [nm(w['w']) for w in W], autojunk=False)
    far = [f"{S[i1+k]} ({st[i1+k]:.2f} vs whisper {W[j1+k]['s']:.2f})" for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag == 'equal' for k in range(i2 - i1) if abs(st[i1+k] - W[j1+k]['s']) > .45]
    if far: print('Differs from whisper by more than 0.45 s, listen to these: ' + '; '.join(far), file=sys.stderr)
