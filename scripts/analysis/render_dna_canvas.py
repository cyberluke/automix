"""Apply the malugi mix-show DNA recipe to the duplicated-vocal canvas.

Builds the canvas (vocal 0-16 x2 + bar 24-64) and MATCHING stems (bass/vocals
duplicated identically), then applies the recipe steps:
  1 rewind stab ending at bar 16 (0:26)
  2 MS-20 filter sweep on bars 16-18
  3 jumpstyle vocal + L/R stereo delay at bar 16.1, tail cut after 2 beats
  4 bomb_sfx (low-cut) at bar 18
  5 bass_solo moment at bar 18
  6 juggle signature_dj at bar 22

Run in .venv-hypermix. Stems come from the spr-malugi-v15 demucs? NO — the
canvas is from the FULL track, so we demucs-separate the canvas? That's the
.venv-stems boundary. For bass_solo we need a bass stem. We approximate: run
the DNA with stems=None except we need bass. We separate the canvas bass in
.venv-stems first (subprocess), OR pass stems=None and bass_solo no-ops.

Simplest correct path: this script runs in .venv-hypermix; it calls the
demucs helper (subprocess into .venv-stems) to get bass+vocals of the CANVAS,
duplicates them to match the canvas layout, then applies the recipe.
"""
import sys, subprocess, json, tempfile
sys.path.insert(0, '.')
from pathlib import Path
import numpy as np
import soundfile as sf

from src.hypermix.canonicalize import Canonicalizer
from src.hypermix.config import DEFAULT_CONFIG
from src.hypermix.audio_io import read_wav
from src.hypermix.analysis.automix_analyzer import AutomixAnalyzer

TRACK = Path('music/Malugi MCYL - Knees Break.mp4')
OUTDIR = Path('renders/malugi-phrases')
OUTDIR.mkdir(parents=True, exist_ok=True)
START_BAR = 103
VOCAL_BARS = 16
REST_START_BAR = 24
XFADE_MS = 60

c = Canonicalizer(DEFAULT_CONFIG)
res = c.canonicalize(TRACK, c.default_private_root())
audio = read_wav(res.canonical_path)
a = AutomixAnalyzer(DEFAULT_CONFIG).analyze(audio, DEFAULT_CONFIG.phrase_bars)
sr = audio.sample_rate
bars = a.bars


def bar_range(b0, b1):
    s = bars[START_BAR + b0]
    e = bars[START_BAR + b1] if START_BAR + b1 < len(bars) else audio.n_samples
    return audio.samples[s:e]


def xfade_join(a_seg, b_seg, ms):
    n = int(sr * ms / 1000.0); n = min(n, len(a_seg), len(b_seg))
    t = np.linspace(0, np.pi, n, dtype=np.float32)
    fo = (0.5 * (1 + np.cos(t)))[:, None]; fi = (0.5 * (1 - np.cos(t)))[:, None]
    ov = a_seg[-n:] * fo + b_seg[:n] * fi
    return np.concatenate([a_seg[:-n], ov, b_seg[n:]])


vocal = bar_range(0, VOCAL_BARS)
rest = bar_range(REST_START_BAR, 64)
canvas = xfade_join(vocal, vocal.copy(), XFADE_MS)
canvas = xfade_join(canvas, rest, XFADE_MS)
peak = np.abs(canvas).max()
if peak > 0.98:
    canvas *= 0.98 / peak

# --- stems: demucs-separate the canvas (subprocess into .venv-stems) ---
def separate_bass_vocals(wav_path):
    helper = (
        "import sys; sys.path.insert(0,'.');"
        "import soundfile as sf, numpy as np;"
        "from src.hypermix.spr.isolate import demucs_all_stems;"
        "y,sr=sf.read(sys.argv[1],dtype='float32',always_2d=True);"
        "st=demucs_all_stems(y,sr);"
        "sf.write(sys.argv[2],st['bass'],sr); sf.write(sys.argv[3],st['vocals'],sr)"
    )
    import shutil
    py = '.venv-stems/Scripts/python.exe'
    subprocess.run([py, '-W', 'ignore', '-c', helper,
                    str(wav_path), str(wav_path)+'.bass.wav',
                    str(wav_path)+'.vocals.wav'], check=True)

# Only bass_solo needs stems, and it only reads a short window around bar 26.
# Slice an 8-bar window around it, demucs THAT (fast), and embed the stems back
# into full-canvas-length zero buffers so the operator sees the right timeline.
BASS_SOLO_BAR = 18.0
WIN_BARS = 8
spb = sr * 60.0 / a.bpm
win0 = max(0, int((BASS_SOLO_BAR - 2) * 4 * spb))
win1 = min(len(canvas), int((BASS_SOLO_BAR + 6) * 4 * spb))
tmp = OUTDIR / '_canvas_win.wav'
sf.write(str(tmp), canvas[win0:win1].astype(np.float32), sr)
print('separating %.1fs window around bar %.0f (demucs)...'
      % ((win1 - win0) / sr, BASS_SOLO_BAR))
try:
    separate_bass_vocals(tmp)
    bw, _ = sf.read(str(tmp) + '.bass.wav', dtype='float32', always_2d=True)
    vw, _ = sf.read(str(tmp) + '.vocals.wav', dtype='float32', always_2d=True)
    bass = np.zeros_like(canvas); vocals = np.zeros_like(canvas)
    L = min(win1 - win0, len(bw), len(vw))
    bass[win0:win0 + L] = bw[:L]; vocals[win0:win0 + L] = vw[:L]
    stems = {'bass': bass, 'vocals': vocals}
    print('stems ok (window only)')
except Exception as e:
    print('stem separation failed (%s) -> bass_solo will no-op' % e)
    stems = None

# --- recipe ---
from src.hypermix.dna.recipe import ProducerRecipe, RecipeStep, OperatorCall
from src.hypermix.dna.engine import apply_recipe

r = ProducerRecipe(name='malugi_mixshow_v1', phrase_bars=80, bpm_ref=a.bpm,
                   note='work-in-progress producer DNA: malugi mix-show',
                   description=[
                       'Upstream implementation description:',
                       'First select the phrase with the highest deterministic',
                       'suitability score, then express every producer action relative',
                       'to that phrase rather than as absolute wall-clock time.',
                       'The phrase analyzer evaluated drop/hook entry candidates at',
                       'bars 103, 135, 56, and 8; bar 103 ranked highest.',
                       'This v1 recipe is the materialized result of that analysis:',
                       'START_BAR 103 is the selected source anchor, and the canvas is',
                       'indexed from it rather than from an arbitrary wall-clock position.',
                       'Korg MS-20 filter automation is applied to the selected musical',
                       'phrase as a two-bar REV1 Korg-35 low-pass sweep from 300 Hz to',
                       '16 kHz with the high-pass stage bypassed.',
                       'The rewind tail lands at relative bar 16 beat 0.5, then the jumpstyle',
                       'vocal announces the change at relative bar 17 beat 0.',
                       'The Q&A answer is the bomb FX at relative bar 18 beat 3,',
                       'high-passed at 150 Hz and driving smooth group ducking.',
                       'The Korg MS-20 filter automation is the question and the bomb',
                       'answer occupies the opposite frequency pole.',
                       'Bass solo would normally be applied to the same selected musical',
                       'phrase/loop. In this DNA, however, a relative recipe offset moves',
                       'it to the following musical phrase, which has no additional Korg',
                       'MS-20 filter automation. This prevents the bass solo from masking',
                       'the single filter movement and keeps the bass solo audible.',
                       'The current instance realizes that offset at relative bar 18 beat 3,',
                       'rather than using an independent absolute time.',
                       'The intended musical criterion is a short bass-forward peak suitable',
                       'for a breakdown, represented by the bass_solo_malugi profile.',
                       'To keep the expensive operation local, the renderer writes only the',
                       '8-bar window covering the selected bass-solo phrase and its offset',
                       'context (relative bars 16 through 24) to the stem-separation',
                       'environment and runs Demucs on that window.',
                       'It reads the Demucs bass and vocals outputs, places them into',
                       'zero-filled full-canvas buffers at the original window offset,',
                       'and passes those timeline-aligned stems to the DNA engine.',
                       'The bass_solo operator starts 0.3 seconds before the relative anchor,',
                       'runs for 0.5 bar, and splits the bass with Linkwitz-Riley filters',
                       'at 300 Hz. It boosts the upper bass band 4x, normalizes the solo',
                       'peak to 0.88, keeps the vocal stem at 1.5x, and crossfades into',
                       'and back out of the original mix.',
                       'A second bass solo reuses the same relative profile at bar 22 beat 3;',
                       'signature_juggle follows at bar 30.',
                   ],
                   principles={
                       'phrase_selection': {
                           'strategy': 'deterministic highest suitability score',
                           'candidate_type': 'drop/hook entry candidate',
                           'candidate_bars': [103, 135, 56, 8],
                           'selected_candidate_rank': 1,
                           'selection_result': 'bar 103 had the highest score',
                           'reference_frame': 'selected phrase and its relative bars/beats',
                           'materialized_source_anchor_bar': START_BAR,
                       },
                       'relative_offsets': {
                           'bass_solo': {
                               'default': 'same selected phrase/loop',
                               'v1_override': 'following musical phrase without another Korg MS-20 filter automation',
                               'reason': 'avoid masking the single MS-20 movement and keep the bass solo audible',
                           },
                       },
                       'q_and_a': {
                           'name': 'Q&A',
                           'meaning': 'question & answer',
                           'question_step_id': 'ms20_question',
                           'answer_step_id': 'bomb_answer',
                           'frequency_relationship': 'opposite frequency poles',
                       },
                   })
r.add(RecipeStep(id='rewind_intro', bar=16.0, beat=0.5, call=OperatorCall('voice_tag', {
    'path': 'samples/stabs/rewind.mp3', 'align': 'end', 'gain': 1.0,
    'echo_times': 4, 'echo_s': 60.0 / a.bpm, 'echo_decay': 0.6,
    'echo_pingpong': True,
    'echo_wet_ramp_last_s': 4.0 * 60.0 / a.bpm,
    'echo_wet_ramp_to': 0.5}),
    note='rewind tail ends 1/2 beat after bar 16; no cut; same stereo delay as jumpstyle, dry first then 50% wet over final bar'))
r.add(RecipeStep(id='ms20_question', bar=16.0, span_bars=2.0, call=OperatorCall('filter_sweep', {
    'slow_bars': 2, 'fast_reps': 0, 'lp_from_hz': 300.0,
    'lp_to_hz': 16000.0, 'hpf_from_hz': 20.0, 'hpf_to_hz': 20.0,
    'bypass_hpf': True,
    'warmup_s': 0.5,
    'revision': 'rev1',
    'res': 0.6, 'drive': 1.0}),
    note='Q&A question: MS-20 LP opens 300Hz->16k; HP bypassed'))
r.add(RecipeStep(id='jumpstyle_announcement', bar=17.0, beat=0.0, call=OperatorCall('voice_tag', {
    'path': 'samples/stabs/what-energetic-jumpstyle-vocal.wav',
    'gain': 1.0, 'echo_times': 4, 'echo_s': 60.0 / a.bpm, 'echo_decay': 0.6,
    'echo_pingpong': True,
    'sample_tail_cut_s': 2 * 60.0 / a.bpm}),
    note='jumpstyle sample tail cut after 2 beats; master untouched'))
r.add(RecipeStep(id='bomb_answer', bar=BASS_SOLO_BAR, beat=3.0, call=OperatorCall('voice_tag', {
    'path': 'samples/stabs/bomb_sfx.mp3', 'gain': 5.0, 'hipass_hz': 150,
    'duck_depth': 0.45, 'duck_attack_ms': 35.0, 'duck_release_ms': 280.0}),
    note='Q&A answer: bomb FX at the opposite frequency pole, with smooth floating duck'))
r.add(RecipeStep(id='cyberluke2_voice_tag', bar=28.0, beat=1.0, call=OperatorCall('voice_tag', {
    'path': 'samples/voice_tags/Cyberluke2.wav', 'gain': 3.0,
    'phaser_wet': 0.42, 'phaser_rate_hz': 0.22,
    'phaser_depth': 0.7, 'phaser_feedback': 0.32,
    'flanger_wet': 0.38, 'flanger_rate_hz': 0.35,
    'flanger_depth_ms': 5.0, 'flanger_base_ms': 0.7,
    'flanger_feedback': 0.45,
    'post_mix': True}),
    note='Cyberluke2 voice tag at approximately 00:47; post-mix phaser/flanger polish, 3x gain'))
r.add(RecipeStep(id='bass_solo_first', bar=BASS_SOLO_BAR, beat=3.0, call=OperatorCall('bass_solo', {
    'profile': 'bass_solo_malugi'}), note='bass solo #1 at END of bar-18 loop (beat 3)'))
r.add(RecipeStep(id='bass_solo_second', bar=BASS_SOLO_BAR + 4.0, beat=3.0, call=OperatorCall('bass_solo', {
    'profile': 'bass_solo_malugi'}), note='bass solo #2, 18+4 bars = bar 22 beat 3'))
r.add(RecipeStep(id='signature_juggle', bar=30.0, call=OperatorCall('juggle', {
    'preset': 'signature_dj'}), note='juggle signature_dj next loop (bar 30)'))
FINAL_GLITCH_END_S = (37.0 * 4.0 + 1.0385 + 4.0) * 60.0 / a.bpm
HORN_DURATION_S = 3.168
FINAL_GLITCH_START_S = FINAL_GLITCH_END_S - HORN_DURATION_S
FINAL_GLITCH_START_BEATS = FINAL_GLITCH_START_S * a.bpm / 60.0
FINAL_GLITCH_BAR = int(FINAL_GLITCH_START_BEATS // 4.0)
FINAL_GLITCH_BEAT = FINAL_GLITCH_START_BEATS - FINAL_GLITCH_BAR * 4.0
FINAL_GLITCH_BARS = HORN_DURATION_S / (4.0 * 60.0 / a.bpm)
r.add(RecipeStep(id='v1_final_horn', bar=FINAL_GLITCH_BAR, beat=FINAL_GLITCH_BEAT,
    call=OperatorCall('voice_tag', {
        'path': 'samples/stabs/horns.mp3', 'gain': 1.0,
        'align_end_s': FINAL_GLITCH_END_S,
        'hipass_hz': 140.0, 'echo_times': 2, 'echo_decay': 0.35,
        'echo_pingpong': False, 'echo_s': 60.0 / a.bpm,
        'effect_cut_s': HORN_DURATION_S,
    }), note='Horn tail aligned exactly with the end of the final GlitchBitch bar'))
r.add(RecipeStep(id='v1_final_glitch', bar=FINAL_GLITCH_BAR, beat=FINAL_GLITCH_BEAT,
    call=OperatorCall('micro_edit', {
        'length_bars': FINAL_GLITCH_BARS, 'seed': 106, 'overlay_input': 'v1_final_horn',
        'program': {
            'engine': 'glitch', 'sync': '1/8', 'steps': 16,
            'buffer': {
                'ramp': ['1/4', '1/4', '1/8', '1/8', '1/16', '1/16', '1/32', '1/32'],
                'reversePattern': [0, 0, 0, 1, 0, 0, 1, 1],
            },
            'pitch': {'values': [0, 0, 0, 3, 0, 3, 7, 12]},
            'gate': {'values': [1.0, 0.8, 0.6, 0.5]},
            'rate': {'values': [1.0, 1.0, 1.0, 0.5]},
            'pan': {'wiggle': 0.4},
            'filter': {'type': 'bandpass', 'fromHz': 120.0,
                       'toHz': 2400.0, 'upperHz': 6500.0},
            'mix': {'from': 0.65, 'to': 1.0},
            'ms20': {'on': False},
        },
    }), note='GlitchBitch spectral stutter at 01:02, modulating the horn and music'))

from src.hypermix.dna.recipe import save_recipe
save_recipe(r)

print('applying recipe...')
out = apply_recipe(r, canvas, sr, bpm=a.bpm, stems=stems)
final_end_s = 66.5  # keep the snare build, exclude the following melody-only phrase
out = out[:min(len(out), int(round(final_end_s * sr)))]
pk = np.abs(out).max()
if pk > 0.98:
    out = out * 0.98 / pk
outp = OUTDIR / 'malugi.dna.mixshow_v1.wav'
sf.write(str(outp), out.astype(np.float32), sr)
print('peak %.2f  dur %.1fs  -> %s' % (np.abs(out).max(), len(out) / sr, outp.resolve()))
