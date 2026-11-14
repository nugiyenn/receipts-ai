#!/usr/bin/env python3
"""Record the 3:00 demo video from the built walkthrough (local only, localhost only).

Follows docs/VIDEO_SCRIPT.md timings. Burns in a small caption bar (bottom-left) and a visible cursor,
because Playwright's video does not draw the pointer. The name and risk text typed in the
receipt step are scripted demo text for a REHEARSAL receipt, not a real person's decision.

Run:  PLAYWRIGHT_BROWSERS_PATH=.venv/pw-browsers .venv/bin/python scripts/record_final.py [--out docs/media/demo.webm]
After recording it also writes docs/media/demo.mp4 (no audio) and demo-with-draft-voice.mp4 (macOS say, Samantha),
using the ffmpeg binary from imageio-ffmpeg. Use --no-post to skip that, or --post-only --offset SECONDS to redo it.
Needs web/ served on http://localhost:8765/ (python3 -m http.server 8765 in web/).
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".venv" / "pw-browsers"))
from playwright.sync_api import sync_playwright

URL = "http://localhost:8765/index.html"
RISK = ("I accept that the blanket location filter may hide a diagnostic nobody has exercised yet, "
        "so I will open a follow-up issue and watch the next release for any regression here.")

OVERLAY_JS = r"""
(() => {
  if (document.getElementById('__cap')) return;
  const st = document.createElement('style');
  st.textContent = `
   #__cap{position:fixed;left:0;right:0;bottom:0;height:38px;background:#172B4D;color:#fff;font:14px/38px -apple-system,'Segoe UI',Roboto,sans-serif;padding:0 20px;z-index:99998;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
   #__cur{position:fixed;left:0;top:0;width:18px;height:18px;z-index:99999;pointer-events:none;transform:translate(-100px,-100px)}
   #__card{position:fixed;inset:0 0 38px 0;background:#F7F8F9;z-index:99990;display:none;align-items:center;justify-content:center;flex-direction:column;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;color:#172B4D;text-align:center;padding:40px}
   #__card h1{font-size:40px;margin:0 0 18px;font-weight:600} #__card p{font-size:20px;margin:6px 0;color:#44546F}
   #__card table{border-collapse:collapse;margin-top:18px;font-size:18px} #__card td,#__card th{padding:8px 22px;border-bottom:1px solid #DCDFE4;text-align:left}
   body{padding-bottom:44px}`;
  document.head.appendChild(st);
  const c = document.createElement('div'); c.id='__cap'; document.body.appendChild(c);
  const k = document.createElement('div'); k.id='__cur';
  k.innerHTML = '<svg width="18" height="18" viewBox="0 0 18 18"><path d="M2 1 L2 14 L5.5 11 L8 16.5 L10.2 15.5 L7.8 10.3 L12.5 10 Z" fill="#fff" stroke="#172B4D" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  document.body.appendChild(k);
  const d = document.createElement('div'); d.id='__card'; document.body.appendChild(d);
  window.__cap = t => { c.textContent = t; };
  window.__cur = (x,y) => { k.style.transform = `translate(${x}px,${y}px)`; };
  window.__card = h => { d.style.display = h ? 'flex' : 'none'; if (h) d.innerHTML = h; };
})();
"""

BASELINE_CARD = ("<h1>Why not just ask a model to review it?</h1>"
                 "<p>Plain review prompt, four changes, 16 findings we confirmed.</p>"
                 "<table><tr><th></th><th>Mentioned</th><th>False claims</th><th>Approved</th></tr>"
                 "<tr><td>Claude, no tools</td><td>6 yes, 3 partly</td><td>3</td><td>0 of 4</td></tr>"
                 "<tr><td>Gemini</td><td>4 yes</td><td>4</td><td>2 of 4</td></tr></table>"
                 "<p style='margin-top:22px'>It sounds equally sure when it is right and when it is wrong.</p>")
CLOSE_CARD = ("<h1>AI reviews. Humans stay accountable.</h1>"
              "<p>Receipts. Every number traces to a file in runs/ or data/.</p>")
# Draft voice: (timeline second at which the line starts, text). Text equals the quotes in docs/VIDEO_SCRIPT.md.
VOICE = [
    (1.9, "Receipts reviews agent-written pull requests by checking claims against a requirement and running evidence, so a named engineer can sign for a change without reading every line. This change has 228 lines. Receipts says read 90."),
    (20, "The agent wrote three tests. On the old code they fail with the exact exception from the bug report, and we check that signature, not just that they failed. On the new code they pass. Only now do they count as evidence."),
    (50, "We revert each piece of the fix and rerun the tests. One hunk can be removed and nothing fails. That is the code the owner reads. It does not mean a bug is there, only that nothing checks it."),
    (75, "Four questions the reviewer refused to decide. The owner answers them, writes the accepted risk in their own words, and signs. That is a record of who decided. It does not make the change safe."),
    (98, "We also asked two models to review the same four changes with a plain prompt. They mentioned 6 and 4 of our 16 findings, and one approved two changes that fail silently. Neither could show a log."),
    (114, "We tested our own reviewer on eleven bugs we wrote, and on six that Gemini wrote after we froze it. On ours, all signals caught eleven and tests plus rules caught seven."),
    (125, "On Gemini's, all signals caught five and tests plus rules caught two. A weakened test assertion got past everything."),
    (141, "The chart is synthetic."),
    (142.6, "On four real regressions, our evidence found the defect in two."),
    (148.8, "Another change: four of eight new tests pass on the old code."),
    (152.5, "A script checked 220 of 222 snapshots."),
    (157.2, "A 1043-line public API change gets a full read."),
    (161.6, "AI reviews. Humans stay accountable. Whatever trust we ask for comes with a receipt."),
]
RATE = 170   # words per minute for macOS say


def post(webm, offset):
    """Convert to mp4 (no audio) and build the DRAFT scratch voice track with macOS say (Samantha)."""
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    media = webm.parent
    mp4 = media / "demo.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(webm), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-r", "30", "-movflags", "+faststart", str(mp4)], check=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="receipts-voice-"))
    segs, report = [], []
    for i, (start, text) in enumerate(VOICE):
        aiff, wav = work / f"v{i}.aiff", work / f"v{i}.wav"
        subprocess.run(["say", "-v", "Samantha", "-r", str(RATE), "-o", str(aiff), text], check=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "44100", "-ac", "1", str(wav)], check=True)
        info = subprocess.run([ff, "-i", str(wav)], capture_output=True, text=True).stderr.split("Duration: ")[1].split(",")[0]
        h_, m_, s_ = info.split(":")
        dur = int(h_) * 3600 + int(m_) * 60 + float(s_)
        nxt = VOICE[i + 1][0] if i + 1 < len(VOICE) else 171
        report.append((i, start, round(dur, 1), round(nxt - start, 1), dur <= nxt - start))
        segs.append((wav, start + offset))
    for r in report:
        print(f"voice line {r[0]:2d}: starts {r[1]:6.1f}s, length {r[2]:5.1f}s, window {r[3]:5.1f}s, {'fits' if r[4] else 'OVERRUNS'}")
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(mp4)]
    for wav, _ in segs:
        cmd += ["-i", str(wav)]
    fc = ";".join(f"[{i+1}:a]adelay={int(t*1000)}|{int(t*1000)}[a{i}]" for i, (_, t) in enumerate(segs))
    fc += ";" + "".join(f"[a{i}]" for i in range(len(segs))) + f"amix=inputs={len(segs)}:normalize=0[aout]"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            str(media / "demo-with-draft-voice.mp4")]
    subprocess.run(cmd, check=True)
    shutil.rmtree(work, ignore_errors=True)
    print(f"wrote {mp4.name} and demo-with-draft-voice.mp4 in {media}")


def held_out_card():
    """Caption card for the Drill beat. The web Drill tab does not show the held_out block, so build it from data/drill.json."""
    d = json.loads((ROOT / "data" / "drill.json").read_text())
    o, h = d["overall"], d["held_out"]
    ours = (o["caught"], o["planted"], o["recall_no_llm"]["caught"])
    theirs = (h["caught_by_union"], h["planted"], h["recall_no_llm"]["caught"])
    miss = h["per_canary"][h["missed"][0]]["description"] if h.get("missed") else ""
    return ("<h1>Did we test the reviewer on bugs we did not write?</h1>"
            "<table><tr><th></th><th>Our 11 bugs</th><th>Gemini's 6 bugs</th></tr>"
            f"<tr><td>All signals together</td><td>{ours[0]} of {ours[1]}</td><td>{theirs[0]} of {theirs[1]}</td></tr>"
            f"<tr><td>Tests and rules, no model</td><td>{ours[2]} of {ours[1]}</td><td>{theirs[2]} of {theirs[1]}</td></tr></table>"
            "<p style='margin-top:22px'>Missed: a test helper where <code>&gt;= Warning</code> became <code>&gt; Warning</code>. "
            "No test, rule or review flagged it.</p>"
            "<p style='font-size:16px'>Gemini wrote these bugs and is also one of the reviewers. Six bugs, one run. Source: data/drill.json (held_out)</p>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "media" / "demo.webm"))
    ap.add_argument("--speed", type=float, default=1.0, help="timeline speed, 1.0 = real time (rehearsal: 4)")
    ap.add_argument("--no-post", action="store_true", help="skip mp4 conversion and the draft voice track")
    ap.add_argument("--post-only", action="store_true", help="skip recording; redo mp4 and voice from --out")
    ap.add_argument("--offset", type=float, default=0.8, help="seconds from video start to the timeline start (used with --post-only)")
    a = ap.parse_args()
    if a.post_only:
        post(pathlib.Path(a.out), a.offset)
        return
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="receipts-final-"))
    spd = a.speed

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp),
                            record_video_size={"width": 1280, "height": 720})
        t_page = time.monotonic()
        pg = ctx.new_page()
        t0 = [0.0]
        pos = [640, 360]

        def at(sec):
            """sleep until `sec` seconds into the timeline"""
            d = sec / spd - (time.monotonic() - t0[0])
            if d > 0:
                pg.wait_for_timeout(int(d * 1000))

        def cap(t):
            pg.evaluate("t => window.__cap && window.__cap(t)", t)

        def move(x, y, steps=10):
            x0, y0 = pos
            for i in range(1, steps + 1):
                nx, ny = x0 + (x - x0) * i / steps, y0 + (y - y0) * i / steps
                pg.mouse.move(nx, ny)
                pg.evaluate("([x,y]) => window.__cur && window.__cur(x,y)", [nx, ny])
                pg.wait_for_timeout(int(10 / spd))
            pos[0], pos[1] = x, y

        def click(loc, pause=250):
            loc.scroll_into_view_if_needed()
            pg.wait_for_timeout(int(120 / spd))
            bb = loc.bounding_box()
            if bb:
                move(bb["x"] + min(bb["width"] / 2, 120), bb["y"] + bb["height"] / 2)
            loc.click()
            pg.wait_for_timeout(int(pause / spd))

        def jump(sec_id):
            click(pg.locator(f"[data-act=jump][data-id='{sec_id}'], [data-act=jump][data-t='{sec_id}']").first)

        def tab(name):
            click(pg.locator(f"[data-act=tab]", has_text=name).first)

        def choose_change(v):
            pg.select_option("#chsel", v)
            pg.wait_for_timeout(int(900 / spd))
            pg.evaluate("window.scrollTo(0,0)")

        pg.goto(URL)
        t0[0] = time.monotonic()
        pg.wait_for_timeout(int(1900 / spd))             # short intro
        pg.evaluate(OVERLAY_JS)
        pg.evaluate("window.scrollTo(0,0)")

        # 0:00 verdict
        cap("An agent wrote 228 lines. Read 90.")
        move(640, 190)
        at(20)
        # 0:20 Time Machine
        cap("Old code fails with the issue's exception. New code passes.")
        jump("s-tm"); move(430, 380)
        at(50)
        # 0:50 X-Ray
        cap("One hunk: covered by 0 of 59 tests.")
        jump("s-xray"); at(54)
        click(pg.locator("[data-act=tgrun]").first)
        at(66)
        click(pg.locator("[data-act=tgmode]", has_text="Base").first)
        pg.wait_for_timeout(int(900 / spd))
        click(pg.locator("[data-act=tgmode]", has_text="Head").first)
        at(75)
        # 1:15 refusals and receipt
        cap("A record of who decided.")
        jump("s-refusals")
        n = pg.locator("[data-act=refusal]").count()
        for i in range(n):
            click(pg.locator("[data-act=refusal]").nth(i), pause=350)
            opt = pg.locator("#drawer .opt").first
            if opt.count():
                click(opt, pause=250)
            click(pg.locator("[data-act=closedrawer]").first, pause=150)
        at(88)
        jump("s-receipt")
        pg.locator("#owner").scroll_into_view_if_needed()
        click(pg.locator("#owner")); pg.locator("#owner").fill("Rehearsal Owner")
        click(pg.locator("#risk")); pg.locator("#risk").type(RISK, delay=int(14 / spd))
        pg.wait_for_timeout(int(500 / spd))
        sign = pg.locator("#signbtn")
        if sign.is_enabled():
            click(sign, pause=1600)
        at(98)
        # 1:40 baseline card (static summary of data/baseline.json)
        cap("Plain review prompt: 6 and 4 of our 16 findings. Source: data/baseline.json")
        pg.evaluate("h => window.__card(h)", BASELINE_CARD)
        at(114)
        pg.evaluate("() => window.__card(null)")
        # 1:55 drill: our 11 canaries on the Drill tab, then the held-out round as a card
        cap("Our 11 bugs: 11 caught by all signals, 7 by tests and rules alone.")
        tab("Drill"); move(640, 330)
        at(125)
        cap("Gemini wrote 6 more bugs we had not seen: 5 caught, 1 missed.")
        pg.evaluate("h => window.__card(h)", held_out_card())
        at(141)
        pg.evaluate("() => window.__card(null)")
        # 2:20 ledger escape table
        cap("The chart is synthetic data.")
        tab("Ledger"); move(640, 380)
        at(144)
        cap("Real regressions: our evidence pointed at the defect in 2 of 4.")
        pg.mouse.wheel(0, 700); pg.wait_for_timeout(int(700 / spd))
        at(149)
        cap("4 of 8 new tests also pass on the old code.")
        tab("Review"); choose_change("2234")
        pg.wait_for_timeout(int(2000 / spd))
        pg.evaluate("document.querySelector('#s-tm').scrollIntoView()")
        at(152.5)
        cap("220 of 222 snapshots checked by script.")
        choose_change("2297")
        pg.wait_for_timeout(int(2600 / spd))
        try:
            tab("Scale")
        except Exception:
            pass
        at(157.2)
        cap("1043 of 1043 lines read: a public API change gets a full read.")
        choose_change("2129")
        at(161.5)
        # 2:45 close
        cap("AI reviews. Humans stay accountable.")
        pg.evaluate("h => window.__card(h)", CLOSE_CARD)
        at(171)
        offset = t0[0] - t_page
        vid = pg.video
        ctx.close()
        path = vid.path()
        b.close()
    shutil.move(path, out)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB), page-to-timeline offset {offset:.2f} s")
    if not a.no_post:
        post(out, offset)


if __name__ == "__main__":
    main()
