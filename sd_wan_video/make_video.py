#!/usr/bin/env python3
"""Render a 120-second animated explainer video about SD-WAN.

Requirements: Pillow, ffmpeg, espeak-ng (+ optional mbrola-us2 voice).
Usage:  python3 make_video.py [output.mp4]
"""
import math
import os
import subprocess
import sys
import tempfile
import wave

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "sd_wan_120s.mp4")
FONT_DIR = "/usr/share/fonts/opentype/inter/"


def font(weight, size):
    try:
        return ImageFont.truetype(FONT_DIR + f"Inter-{weight}.otf", size)
    except OSError:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


F = {k: font(w, s) for k, (w, s) in {
    "huge": ("ExtraBold", 84), "title": ("Bold", 46), "sub": ("Medium", 28),
    "body": ("Regular", 26), "label": ("SemiBold", 21), "small": ("Medium", 17),
    "cap": ("Medium", 24), "tag": ("Bold", 18),
}.items()}

BG = (11, 18, 38)
PANEL = (22, 33, 62)
FG = (236, 241, 250)
MUTED = (140, 155, 185)
CYAN = (56, 189, 248)
ORANGE = (251, 146, 60)
GREEN = (52, 211, 153)
RED = (248, 113, 113)
PURPLE = (167, 139, 250)
YELLOW = (250, 204, 21)

# ----------------------------------------------------------------- script
SCENES = [
    (9, "title", "S D WAN, explained in two minutes."),
    (15, "problem",
     "Traditional WANs connect every branch back to headquarters over private M P L S circuits. "
     "Cloud and internet traffic gets backhauled through the data center. That is slow, rigid, and expensive."),
    (15, "overlay",
     "S D WAN, a software defined wide area network, builds a secure overlay on top of any transport. "
     "M P L S, broadband internet, and L T E or 5 G, all used together, as one logical network."),
    (20, "arch",
     "It separates the network into three planes. The management plane, an orchestrator, gives one dashboard for the whole WAN. "
     "The control plane, a controller, distributes routes and policy. "
     "And the data plane, the edge routers at each site, forward the actual traffic through encrypted tunnels."),
    (19, "aar",
     "The key feature is application aware routing. Edges constantly measure latency, jitter, and packet loss on every path. "
     "If the M P L S link degrades, voice and video are moved to the healthy path in under a second, before users notice."),
    (16, "security",
     "Every tunnel is encrypted with I P sec. Traffic is segmented, so guests never touch payment systems. "
     "And branches can break out directly to trusted cloud apps, often through a cloud security service, known as SASE."),
    (15, "benefits",
     "The result: lower circuit costs, zero touch deployment of new sites, better application performance, "
     "and end to end visibility from a single pane of glass."),
    (11, "recap",
     "S D WAN. Any transport, centrally managed, application aware, and secure by design."),
]
assert sum(s[0] for s in SCENES) == 120


# ----------------------------------------------------------------- helpers
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def mix(c, a, base=BG):
    a = clamp(a)
    return tuple(int(base[i] + (c[i] - base[i]) * a) for i in range(3))


def appear(t, start, dur=0.6):
    return ease((t - start) / dur)


def text(d, xy, s, f, c, a=1.0, anchor="la", base=BG):
    if a <= 0:
        return
    d.text(xy, s, font=f, fill=mix(c, a, base), anchor=anchor)


def node(d, cx, cy, w, h, label, color, a, sub=None, r=14):
    if a <= 0:
        return
    s = 0.85 + 0.15 * a
    w2, h2 = w * s / 2, h * s / 2
    d.rounded_rectangle([cx - w2, cy - h2, cx + w2, cy + h2], r, fill=mix(PANEL, a), outline=mix(color, a), width=3)
    if sub:
        text(d, (cx, cy - 10), label, F["label"], FG, a, "mm", PANEL)
        text(d, (cx, cy + 14), sub, F["small"], color, a, "mm", PANEL)
    else:
        text(d, (cx, cy), label, F["label"], FG, a, "mm", PANEL)


def link(d, p, q, color, a, width=4, dash=False, prog=1.0):
    if a <= 0 or prog <= 0:
        return
    x = p[0] + (q[0] - p[0]) * prog
    y = p[1] + (q[1] - p[1]) * prog
    c = mix(color, a)
    if not dash:
        d.line([p, (x, y)], fill=c, width=width)
        return
    L = math.dist(p, (x, y))
    n = int(L // 18)
    for i in range(n + 1):
        t0, t1 = i * 18 / max(L, 1), min((i * 18 + 10) / max(L, 1), 1)
        if t0 >= 1:
            break
        d.line([(p[0] + (x - p[0]) * t0, p[1] + (y - p[1]) * t0),
                (p[0] + (x - p[0]) * t1, p[1] + (y - p[1]) * t1)], fill=c, width=width)


def along(path, f):
    """Point at fraction f along polyline."""
    segs = [math.dist(path[i], path[i + 1]) for i in range(len(path) - 1)]
    total = sum(segs)
    dist = (f % 1.0) * total
    for i, s in enumerate(segs):
        if dist <= s:
            k = dist / s if s else 0
            return (path[i][0] + (path[i + 1][0] - path[i][0]) * k,
                    path[i][1] + (path[i + 1][1] - path[i][1]) * k)
        dist -= s
    return path[-1]


def packets(d, path, t, color, a, n=3, speed=0.35, r=7, offset=0.0):
    if a <= 0:
        return
    for i in range(n):
        x, y = along(path, t * speed + i / n + offset)
        d.ellipse([x - r, y - r, x + r, y + r], fill=mix(color, a))


def header(d, t, title, kicker):
    a = appear(t, 0.1)
    text(d, (70, 52), kicker.upper(), F["tag"], CYAN, a)
    text(d, (70 - 20 * (1 - a), 80), title, F["title"], FG, a)


def cloud(d, cx, cy, label, color, a, sc=1.0):
    if a <= 0:
        return
    c = mix(PANEL, a)
    o = mix(color, a)
    for dx, dy, r in [(-55, 10, 38), (-15, -15, 48), (35, -5, 42), (65, 15, 30), (5, 22, 40)]:
        d.ellipse([cx + dx * sc - r * sc, cy + dy * sc - r * sc, cx + dx * sc + r * sc, cy + dy * sc + r * sc],
                  fill=c, outline=o, width=3)
    for dx, dy, r in [(-55, 10, 36), (-15, -15, 46), (35, -5, 40), (65, 15, 28), (5, 22, 38)]:
        d.ellipse([cx + dx * sc - r * sc, cy + dy * sc - r * sc, cx + dx * sc + r * sc, cy + dy * sc + r * sc], fill=c)
    text(d, (cx + 5 * sc, cy + 5 * sc), label, F["label"], FG, a, "mm", PANEL)


def check(d, x, y, a, color=GREEN):
    if a <= 0:
        return
    d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=mix(color, a))
    d.line([(x - 8, y), (x - 2, y + 7), (x + 9, y - 7)], fill=mix(BG, a, color), width=4)


# ----------------------------------------------------------------- scenes
def s_title(d, t, D):
    for i in range(14):  # drifting network dots
        x = (i * 97 + t * 25 * (1 + i % 3)) % (W + 100) - 50
        y = 120 + (i * 53) % 480
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=mix(CYAN, 0.35))
    a = appear(t, 0.3, 0.9)
    text(d, (W / 2, 300 + 20 * (1 - a)), "SD-WAN", F["huge"], FG, a, "mm")
    text(d, (W / 2, 375), "Software-Defined Wide Area Network", F["sub"], CYAN, appear(t, 1.0), "mm")
    b = appear(t, 1.8)
    d.rounded_rectangle([W / 2 - 110, 425, W / 2 + 110, 465], 20, fill=mix(ORANGE, b))
    text(d, (W / 2, 445), "IN 120 SECONDS", F["tag"], BG, b, "mm", ORANGE)


def s_problem(d, t, D):
    header(d, t, "The problem with traditional WAN", "Before SD-WAN")
    hq = (640, 260)
    branches = [(230, 520), (640, 560), (1050, 520)]
    for i, b in enumerate(branches):
        a = appear(t, 1.0 + i * 0.3)
        link(d, b, hq, ORANGE, a, 5, prog=ease((t - 1.0 - i * 0.3) / 0.8))
    a = appear(t, 5.0)
    link(d, (750, 250), (990, 240), CYAN, a, 3, dash=True)
    path = [branches[0], hq, (990, 240)]
    packets(d, path, t, CYAN, appear(t, 6.0), n=4, speed=0.25)
    node(d, *hq, 220, 80, "HQ Data Center", PURPLE, appear(t, 0.5), "firewall + internet")
    for i, b in enumerate(branches):
        node(d, *b, 160, 64, f"Branch {i + 1}", ORANGE, appear(t, 1.0 + i * 0.3))
    text(d, (430, 400), "MPLS", F["label"], ORANGE, appear(t, 2.0))
    cloud(d, 1060, 240, "SaaS / Cloud", CYAN, a, 0.9)
    text(d, (300, 300), "Backhaul / hairpin", F["label"], RED, appear(t, 6.5))
    for i, (lbl, st) in enumerate([("Slow", 9.5), ("Rigid", 10.5), ("Expensive", 11.5)]):
        a = appear(t, st)
        x = 70
        y = 180 + i * 48
        d.rounded_rectangle([x, y, x + 150, y + 36], 18, fill=mix(RED, a * 0.25), outline=mix(RED, a), width=2)
        text(d, (x + 75, y + 18), lbl, F["label"], RED, a, "mm")


def s_overlay(d, t, D):
    header(d, t, "One virtual network over any transport", "What is SD-WAN?")
    left, right = (190, 400), (1090, 400)
    node(d, *left, 170, 90, "Branch", ORANGE, appear(t, 0.4), "SD-WAN edge")
    node(d, *right, 170, 90, "HQ / DC", PURPLE, appear(t, 0.4), "SD-WAN edge")
    rows = [("MPLS", ORANGE, 260), ("Broadband Internet", CYAN, 400), ("LTE / 5G", GREEN, 540)]
    for i, (lbl, col, y) in enumerate(rows):
        a = appear(t, 1.5 + i * 1.2)
        p, q = (275, 400), (1005, 400)
        path = [p, (380, y), (900, y), q]
        for j in range(3):
            link(d, path[j], path[j + 1], col, a, 4)
        packets(d, path, t + i, col, appear(t, 5.5), n=2, speed=0.3)
        d.rounded_rectangle([530, y - 20, 750, y + 20], 20, fill=mix(BG, a), outline=mix(col, a), width=2)
        text(d, (640, y), lbl, F["label"], col, a, "mm")
    a = appear(t, 8.0)
    d.rounded_rectangle([340, 200 - 8, 940, 600 + 8], 30, outline=mix(YELLOW, a), width=3)
    text(d, (640, 170), "SECURE OVERLAY  -  managed as one logical WAN", F["tag"], YELLOW, a, "mm")
    text(d, (640, 650), "Transport independent: mix and match circuits", F["body"], MUTED, appear(t, 10), "mm")


def s_arch(d, t, D):
    header(d, t, "Three planes, clearly separated", "Architecture")
    layers = [
        ("Management plane", "Orchestrator / Manager", "Single dashboard, templates, monitoring", PURPLE, 200, 0.6),
        ("Control plane", "Controller", "Distributes routes, keys & policy", CYAN, 330, 6.0),
        ("Data plane", "Edge routers", "Forward traffic over IPsec tunnels", GREEN, 470, 11.0),
    ]
    for name, comp, desc, col, y, st in layers:
        a = appear(t, st, 0.8)
        d.rounded_rectangle([70, y - 56, 500, y + 56], 16, fill=mix(PANEL, a), outline=mix(col, a), width=3)
        text(d, (95, y - 40), name.upper(), F["tag"], col, a, base=PANEL)
        text(d, (95, y - 14), comp, F["label"], FG, a, base=PANEL)
        text(d, (95, y + 16), desc, F["small"], MUTED, a, base=PANEL)
    # right-side diagram
    mgr, ctl = (850, 170), (850, 290)
    edges = [(650, 440), (850, 570), (1050, 440)]
    a1, a2, a3 = appear(t, 1.0), appear(t, 6.5), appear(t, 11.5)
    link(d, mgr, ctl, PURPLE, a2, 3, dash=True)
    for e in edges:
        link(d, ctl, e, CYAN, a3, 3, dash=True)
    for i in range(3):
        link(d, edges[i], edges[(i + 1) % 3], GREEN, appear(t, 13), 5)
    tri = [edges[0], edges[1], edges[2], edges[0]]
    packets(d, tri, t, YELLOW, appear(t, 14), n=4, speed=0.18, r=6)
    node(d, *mgr, 230, 66, "Orchestrator", PURPLE, a1)
    node(d, *ctl, 230, 66, "Controller", CYAN, a2)
    for i, e in enumerate(edges):
        node(d, *e, 130, 56, f"Edge {i + 1}", GREEN, a3)
    text(d, (850, 622), "Overlay tunnels between edges", F["small"], GREEN, appear(t, 14), "mm")


def s_aar(d, t, D):
    header(d, t, "Application-aware routing", "Key feature")
    a0 = appear(t, 0.4)
    b, h = (170, 400), (1110, 400)
    node(d, *b, 150, 80, "Branch", ORANGE, a0, "edge")
    node(d, *h, 150, 80, "HQ", PURPLE, a0, "edge")
    fail = 9.0  # MPLS degrades
    deg = ease((t - fail) / 0.8)
    top = [(245, 400), (360, 260), (920, 260), (1035, 400)]
    bot = [(245, 400), (360, 540), (920, 540), (1035, 400)]
    mcol = mix(RED, deg, ORANGE)
    for j in range(3):
        link(d, top[j], top[j + 1], mcol, a0, 5, dash=deg > 0.5)
        link(d, bot[j], bot[j + 1], CYAN, a0, 5)
    # SLA panels
    def stats(x, y, lbl, col, lat, jit, loss, a, bad=False):
        if a <= 0:
            return
        d.rounded_rectangle([x - 150, y - 46, x + 150, y + 46], 14, fill=mix(PANEL, a), outline=mix(col, a), width=2)
        text(d, (x, y - 26), lbl, F["label"], col, a, "mm", PANEL)
        vc = RED if bad else GREEN
        text(d, (x, y + 14), f"{lat} ms   {jit} ms jitter   {loss}% loss", F["small"], vc, a, "mm", PANEL)
    a1 = appear(t, 3.0)
    lat = int(18 + deg * 220)
    stats(640, 200, "MPLS", mcol, lat, int(2 + deg * 40), round(0.0 + deg * 6.5, 1), a1, deg > 0.5)
    stats(640, 600, "Internet", CYAN, 24, 3, 0.1, a1)
    # voice packets
    pa = appear(t, 5.5)
    switch = fail + 1.8
    if t < switch:
        packets(d, top, t, YELLOW, pa, n=4, speed=0.3)
    else:
        packets(d, bot, t, YELLOW, pa, n=4, speed=0.3)
    packets(d, bot, t + 0.5, GREEN, appear(t, 5.5) * 0.7, n=2, speed=0.22, r=5)
    text(d, (640, 330), "Voice / video (SLA: <150 ms, <1% loss)", F["small"], YELLOW, pa, "mm")
    if t > fail:
        text(d, (640, 300), "SLA VIOLATED", F["tag"], RED, appear(t, fail + 0.3), "mm")
    if t > switch:
        a = appear(t, switch)
        d.rounded_rectangle([450, 440, 830, 482], 21, fill=mix(GREEN, a))
        text(d, (640, 461), "Rerouted in < 1 second", F["tag"], BG, a, "mm", GREEN)


def s_security(d, t, D):
    header(d, t, "Secure by design", "Security & cloud")
    cards = [
        ("IPsec encryption", "Every overlay tunnel is encrypted end to end", CYAN, 0.5),
        ("Segmentation", "Separate VPNs: corporate, guest, PCI payments", PURPLE, 4.5),
        ("Direct cloud access", "Local internet breakout to trusted SaaS", GREEN, 8.5),
        ("SASE integration", "Cloud firewall, SWG and ZTNA in the path", ORANGE, 12.0),
    ]
    for i, (ttl, desc, col, st) in enumerate(cards):
        a = appear(t, st, 0.7)
        x = 70 + (i % 2) * 580
        y = 170 + (i // 2) * 250
        x += 30 * (1 - a)
        d.rounded_rectangle([x, y, x + 560, y + 220], 20, fill=mix(PANEL, a), outline=mix(col, a), width=3)
        d.rounded_rectangle([x + 28, y + 30, x + 92, y + 94], 14, fill=mix(col, a, PANEL))
        text(d, (x + 60, y + 62), str(i + 1), F["title"], BG, a, "mm", col)
        text(d, (x + 115, y + 42), ttl, F["sub"], FG, a, base=PANEL)
        text(d, (x + 115, y + 84), desc, F["small"], MUTED, a, base=PANEL)
        # mini visual
        if i == 0:
            link(d, (x + 40, y + 160), (x + 520, y + 160), CYAN, a * 0.4, 18)
            packets(d, [(x + 40, y + 160), (x + 520, y + 160)], t, YELLOW, a, n=5, speed=0.4, r=6)
        elif i == 1:
            for k, c in enumerate([CYAN, YELLOW, RED]):
                d.rounded_rectangle([x + 40 + k * 165, y + 140, x + 190 + k * 165, y + 180], 12, outline=mix(c, a, PANEL), width=2)
                text(d, (x + 115 + k * 165, y + 160), ["Corp", "Guest", "PCI"][k], F["small"], c, a, "mm", PANEL)
        elif i == 2:
            packets(d, [(x + 60, y + 160), (x + 500, y + 160)], t, GREEN, a, n=3, speed=0.5, r=6)
            text(d, (x + 280, y + 192), "Branch  ->  Microsoft 365 / AWS / Google", F["small"], GREEN, a, "mm", PANEL)
        else:
            text(d, (x + 280, y + 160), "Branch -> SSE cloud -> Internet", F["small"], ORANGE, a, "mm", PANEL)


def s_benefits(d, t, D):
    header(d, t, "Why organizations adopt SD-WAN", "Benefits")
    items = [
        ("Lower cost", "Use affordable broadband alongside MPLS", 0.6),
        ("Zero-touch provisioning", "Ship a box, plug it in, it configures itself", 2.6),
        ("Better app performance", "Real-time path selection per application", 5.0),
        ("Visibility & control", "One pane of glass for the entire WAN", 8.5),
    ]
    for i, (ttl, desc, st) in enumerate(items):
        a = appear(t, st)
        y = 200 + i * 110
        check(d, 110, y + 20, a)
        text(d, (150 - 20 * (1 - a), y), ttl, F["sub"], FG, a)
        text(d, (150 - 20 * (1 - a), y + 38), desc, F["body"], MUTED, a)
    # cost bar chart
    a = appear(t, 1.0)
    bx, by = 860, 600
    text(d, (980, 200), "WAN cost (illustrative)", F["small"], MUTED, a, "mm")
    for k, (lbl, val, col) in enumerate([("MPLS only", 1.0, ORANGE), ("SD-WAN hybrid", 0.55, GREEN)]):
        g = ease((t - 1.5 - k * 0.8) / 1.2) * val
        x0 = bx + k * 160
        d.rectangle([x0, by - 340 * g, x0 + 100, by], fill=mix(col, a))
        text(d, (x0 + 50, by + 24), lbl, F["small"], FG, a, "mm")
    d.line([(bx - 20, by), (bx + 300, by)], fill=mix(MUTED, a), width=2)


def s_recap(d, t, D):
    a = appear(t, 0.2)
    text(d, (W / 2, 150), "SD-WAN IN ONE LINE", F["tag"], CYAN, a, "mm")
    words = [("Any transport", ORANGE), ("Centrally managed", PURPLE), ("Application-aware", CYAN), ("Secure by design", GREEN)]
    for i, (w, c) in enumerate(words):
        b = appear(t, 0.8 + i * 1.4)
        x = W / 2
        y = 250 + i * 85
        d.rounded_rectangle([x - 260, y - 32, x + 260, y + 32], 32, fill=mix(PANEL, b), outline=mix(c, b), width=3)
        text(d, (x, y), w, F["sub"], FG, b, "mm", PANEL)
    text(d, (W / 2, 640), "Thanks for watching", F["body"], MUTED, appear(t, 7.5), "mm")


DRAW = {"title": s_title, "problem": s_problem, "overlay": s_overlay, "arch": s_arch,
        "aar": s_aar, "security": s_security, "benefits": s_benefits, "recap": s_recap}


# ----------------------------------------------------------------- audio
def tts(txt, path, rate):
    for voice in ("mb-us2", "en-us"):
        r = subprocess.run(["espeak-ng", "-v", voice, "-s", str(rate), "-p", "45", "-w", path, txt],
                           capture_output=True)
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 1000:
            return
    raise RuntimeError("espeak-ng failed")


def wav_info(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate(), w.getframerate(), w.readframes(w.getnframes())


def build_audio(tmp):
    rate_hz = None
    track = bytearray()
    spans = []  # (scene_start, speech_dur) for captions
    t0 = 0.0
    for i, (dur, _, narr) in enumerate(SCENES):
        p = os.path.join(tmp, f"n{i}.wav")
        rate = 160
        while True:
            tts(narr, p, rate)
            sec, sr, frames = wav_info(p)
            if sec <= dur - 0.9 or rate >= 230:
                break
            rate += 8
        rate_hz = rate_hz or sr
        lead = 0.4
        pad = int(lead * sr) * 2
        body = frames[: int((dur - lead) * sr) * 2]
        seg = b"\x00" * pad + body
        seg += b"\x00" * (int(dur * sr) * 2 - len(seg))
        track += seg
        spans.append((t0 + lead, sec))
        print(f"scene {i}: {sec:.1f}s speech @ {rate} wpm in {dur}s slot")
        t0 += dur
    out = os.path.join(tmp, "narration.wav")
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate_hz)
        w.writeframes(bytes(track))
    return out, spans


def caption_chunks(narr, start, speech):
    """Split narration into ~10-word chunks timed by character count."""
    shown = narr.replace("S D WAN", "SD-WAN").replace("M P L S", "MPLS").replace("L T E", "LTE") \
        .replace("5 G", "5G").replace("I P sec", "IPsec")
    words = shown.split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 9 or w.endswith((".", ",")) and len(cur) >= 5:
            chunks.append(" ".join(cur)); cur = []
    if cur:
        chunks.append(" ".join(cur))
    total = sum(len(c) for c in chunks)
    out, t = [], start
    for c in chunks:
        dt = speech * len(c) / total
        out.append((t, t + dt, c))
        t += dt
    return out


# ----------------------------------------------------------------- main
def main():
    tmp = tempfile.mkdtemp()
    audio, spans = build_audio(tmp)
    caps = []
    for (dur, _, narr), (st, sp) in zip(SCENES, spans):
        caps += caption_chunks(narr, st, sp)

    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", audio,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-af", "loudnorm=I=-16", "-shortest", "-movflags", "+faststart", OUT,
    ], stdin=subprocess.PIPE)

    total = sum(s[0] for s in SCENES)
    starts, acc = [], 0
    for s in SCENES:
        starts.append(acc); acc += s[0]
    for f in range(int(total * FPS)):
        T = f / FPS
        idx = max(i for i, s in enumerate(starts) if s <= T)
        dur, key, _ = SCENES[idx]
        t = T - starts[idx]
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        DRAW[key](d, t, dur)
        # scene fade in/out
        fade = min(ease(t / 0.35), ease((dur - t) / 0.35))
        if idx == 0:
            fade = ease((dur - t) / 0.35)
        if fade < 1:
            img = Image.blend(Image.new("RGB", (W, H), BG), img, fade)
            d = ImageDraw.Draw(img)
        # progress bar
        d.rectangle([0, H - 5, W * T / total, H], fill=CYAN)
        # caption
        for a, b, c in caps:
            if a <= T < b:
                bb = d.textbbox((W / 2, H - 42), c, font=F["cap"], anchor="mm")
                d.rounded_rectangle([bb[0] - 18, bb[1] - 10, bb[2] + 18, bb[3] + 10], 10, fill=(0, 0, 0))
                d.text((W / 2, H - 42), c, font=F["cap"], fill=FG, anchor="mm")
                break
        ff.stdin.write(img.tobytes())
    ff.stdin.close()
    ff.wait()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
