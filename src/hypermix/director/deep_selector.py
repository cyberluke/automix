"""DeepMixDirector — Deep Dance / megamix sequencing policy (§16 variant).

Philosophy: a Deep Dance megamix is a STUDIO-CUT hook relay, not a realtime
two-deck blend. It optimizes *time-to-next-recognition*, not graceful mixing.

Policy differences vs. the club `Director`:
  * prefer SHORT, high-hook segments (2/4/8 bars) — never long blends;
  * recognition/hook density is the dominant score (rating ≈ hook proxy);
  * bias strongly toward RESET transitions (rewind/slam/backspin/echo/stutter/
    drum_roll/power) over CONTINUITY transitions (phrase_match/bass_swap/...);
  * fresh-first crate digging: never revisit a track until the crate is spent;
  * novelty pressure: the longer the current track has been playing, the more
    the selector is pushed to cut to something new.

Deterministic given (pack, seed) — same engine, different policy.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..model import Segment
from .graph import MixGraph
from .seeded_rng import SeededRNG

# Phrase roles that carry a strong vocal (used for vocal-family priority +
# vocal-clash penalty). A phrase is "vocal" if any of these roles is present
# with confidence >= threshold.
_VOCAL_ROLES = {"VOCAL_DOMINANT", "VOCAL_LIGHT"}
_VOCAL_CONF = 0.5


def _top_role(roles: Sequence[Dict[str, float]]) -> Optional[str]:
    if not roles:
        return None
    return max(roles, key=lambda r: r.get("confidence", 0.0)).get("role")


def _role_conf(roles: Sequence[Dict[str, float]], role: str) -> float:
    for r in roles:
        if r.get("role") == role:
            return float(r.get("confidence", 0.0))
    return 0.0


def _is_vocal(roles: Sequence[Dict[str, float]], feats: Optional[Dict] = None) -> bool:
    """True when a phrase reads as vocal.

    The role-list alone is NOT enough: in bass-heavy EDM the BASS_DOMINANT
    role usually out-scores VOCAL_DOMINANT even on a clearly-vocal phrase
    (kick+bass dominates low-freq share; vocals ride above it at 0.9+). So we
    ALSO accept a phrase as vocal when the phrase-native detector reports a
    high vocal probability / formant-band energy, regardless of top role.
    """
    # Role-based vocal (fast path): any of the explicit VOCAL_* roles cleared.
    role_vocal = any(_role_conf(roles, r) >= _VOCAL_CONF for r in _VOCAL_ROLES)
    if role_vocal:
        return True
    # Heuristic vocal path: phrase-native content features. A phrase whose
    # formant-band share reads strongly vocal is treated as vocal even when a
    # BASS_DOMINANT / DROP_HOOK structural role out-scores VOCAL_DOMINANT.
    if feats is None:
        return False
    co = feats.get("content", {}) if isinstance(feats, dict) else {}
    vp = float(co.get("vocal_probability", 0.0))
    ver = float(co.get("vocal_energy_ratio", 0.0))
    return vp >= 0.5 and ver > 0.15


def _energy_shape(slopes: Dict[str, float], pe: float) -> str:
    """Classify the phrase's internal energy trajectory from slopes."""
    rms = float(slopes.get("rms", 0.0))
    cent = float(slopes.get("centroid", 0.0))
    if rms > 0.2 or (cent > 0.2 and rms > 0.05):
        return "rising"
    if rms < -0.2:
        return "falling"
    return "plateau"

# Reset transitions: perceptual "tempo/identity reset" tokens (Deep grammar).
RESET_TECHNIQUES = {
    "rewind", "slam", "drop_on_the_one", "backspin", "echo_cut", "stutter",
    "drum_roll", "power_down", "power_up", "transformer_cuts", "back_and_forth",
}
# Continuity transitions: keep the beat/phrase alive across the boundary.
CONTINUITY_TECHNIQUES = {
    "phrase_match", "double_drop", "triple_drop", "loop_transition",
    "melodic_mix", "modulation", "thematic_handoff", "acapella_overlay",
}


class DeepMixDirector:
    def __init__(self, graph: MixGraph, seed: int = 0,
                 mode: str = "weighted-random",
                 target_bars: int = 4,
                 reset_bias: float = 0.8,
                 energy_min: float = 0.0, energy_max: float = 1.0,
                 seg_keys: Optional[Dict[str, str]] = None,
                 seg_energy: Optional[Dict[str, float]] = None,
                 seg_level: Optional[Dict[str, float]] = None,
                 seg_spec: Optional[Dict[str, Dict[str, float]]] = None,
                 harmonic_arc: bool = False,
                 arc_weight: float = 1.0,
                 energy_gradient_weight: float = 1.5,
                 continuity_weight: float = 6.0,
                 spectral_weight: float = 5.0,
                 vocal_family_weight: float = 4.0,
                 vocal_bias_weight: float = 8.0,
                 trajectory_weight: float = 4.5) -> None:
        self.graph = graph
        self.rng = SeededRNG(seed)
        self.mode = mode
        self.target_bars = max(1, int(target_bars))
        self.reset_bias = float(reset_bias)
        self.energy_min = energy_min
        self.energy_max = energy_max
        # ASCENDING_ENERGY_ARC: Camelot key + phrase energy per segment, used to
        # keep a monotonic perceived-energy gradient. Key is one control axis;
        # phrase energy (bar-energy delta across the segment) is the other.
        self.seg_keys = seg_keys or {}
        self.seg_energy = seg_energy or {}
        self.seg_level = seg_level or {}
        self.seg_spec = seg_spec or {}
        self.harmonic_arc = bool(harmonic_arc)
        self.arc_weight = float(arc_weight)
        self.energy_gradient_weight = float(energy_gradient_weight)
        # PRIMARY continuity: match the outgoing phrase's LEVEL and SPECTRAL
        # signature, so a climax flows into a climax and a breakdown into a
        # breakdown. Camelot becomes a tiebreak, not the driver.
        self.continuity_weight = float(continuity_weight)
        self.spectral_weight = float(spectral_weight)
        # PHRASE-NATIVE DRIVER: vocal-family + energy-trajectory are what the
        # user hears as "the vocal phrases should follow each other" and "the
        # energy arc is too naive". These must OUTWEIGH the raw level/spectral
        # continuity above, otherwise the naive terms win and nothing changes.
        self.vocal_family_weight = float(vocal_family_weight)
        self.vocal_bias_weight = float(vocal_bias_weight)
        self.trajectory_weight = float(trajectory_weight)
        self.history: List[str] = []

    # --------------------------------------------------- harmonic helpers #
    @staticmethod
    def _camelot_num(code: str) -> Optional[int]:
        try:
            return int(code[:-1])
        except Exception:
            return None

    def _harmonic_arc_bonus(self, from_id: Optional[str], seg: Segment) -> float:
        """ASCENDING_ENERGY_ARC harmonic term.

        Mixed In Key Energy Boost: +2 Camelot numbers (same letter) = +2
        semitone whole-tone lift. We reward upward modulation and smooth
        (compatible) movement, and penalize downward/clashing movement.
        """
        if not self.harmonic_arc or from_id is None:
            return 0.0
        a = self.seg_keys.get(from_id)
        b = self.seg_keys.get(seg.id)
        if not a or not b:
            return 0.0
        na, nb = self._camelot_num(a), self._camelot_num(b)
        if na is None or nb is None:
            return 0.0
        la, lb = a[-1], b[-1]
        # Wrap-aware Camelot number delta in [-6, +6].
        d = ((nb - na + 6) % 12) - 6
        bonus = 0.0
        if d == 2 and la == lb:
            bonus += 1.0          # Energy Boost: whole-tone lift (preferred)
        elif d == 1 and la == lb:
            bonus += 0.5          # gentle lift
        elif d == 0 and la == lb:
            bonus += 0.3          # same key (power block, when available)
        elif d == 0 and la != lb:
            bonus += 0.2          # relative major<->minor
        elif abs(d) == 1:
            bonus += 0.15         # adjacent Camelot (compatible)
        elif d < 0:
            bonus -= 0.6          # downward modulation: avoid in an ascent
        return self.arc_weight * bonus

    def _energy_gradient_bonus(self, seg: Segment) -> float:
        """Prefer phrases whose internal energy is climbing (rising into a
        drop) over phrases that are already peaked or decaying. seg_energy is
        the normalized bar-energy delta across the phrase (-1..+1-ish)."""
        if not self.harmonic_arc:
            return 0.0
        e = self.seg_energy.get(seg.id)
        if e is None:
            return 0.0
        return self.energy_gradient_weight * max(-1.0, min(1.0, e))

    def _energy_continuity_bonus(self, from_id: Optional[str], seg: Segment) -> float:
        """Match the OUTGOING phrase's absolute level to the incoming phrase's
        level. Penalize a big drop (climax -> bare beat) or a big jump; reward
        a smooth hand-off. This is the anti-'cut the climax into a low-energy
        beat' term. Range ~[-w, +w]."""
        if from_id is None:
            return 0.0
        # Prefer phrase-native globally-normalized perceived energy; fall back
        # to the RMS level when features are unavailable.
        fa, fb = self._get_feats(from_id), self._get_feats(seg.id)
        if fa and fb and "energy_global" in fa and "energy_global" in fb:
            a = float(fa["energy_global"]); b = float(fb["energy_global"])
        else:
            a = self.seg_level.get(from_id)
            b = self.seg_level.get(seg.id)
        if a is None or b is None:
            return 0.0
        d = abs(a - b)
        # 0 gap -> +w; 1.0 gap -> -w (linear, centered at 0.35 as neutral).
        return self.continuity_weight * (1.0 - 2.0 * min(1.0, d / 0.7))

    def _get_feats(self, sid: Optional[str]) -> Optional[Dict]:
        """Phrase-native feature dict for a segment (or legacy flat spec)."""
        if sid is None:
            return None
        return self.seg_spec.get(sid)

    def _spectral_similarity_bonus(self, from_id: Optional[str], seg: Segment) -> float:
        """Phrase-native spectral compatibility.

        New feature vectors expose a rich spectral dict + roles. We match:
          - brightness (centroid_median), bandwidth, HF ratio;
          - low-end occupancy (sub+bass) so two huge-bass phrases don't stack;
          - centroid DELTA (a jump in brightness reads as a jarring cut).
        Legacy flat specs (brightness/low/mid/high) still score via the old
        4-dim distance."""
        a = self._get_feats(from_id)
        b = self._get_feats(seg.id)
        if not a or not b:
            return 0.0
        sa, sb = a.get("spectral"), b.get("spectral")
        if sa and sb:  # phrase-native path
            dims = ("centroid_median", "bandwidth_mean", "high_ratio",
                    "bass_ratio", "mid_ratio")
            va = [float(sa.get(k, 0.0)) for k in dims]
            vb = [float(sb.get(k, 0.0)) for k in dims]
            dist = sum((x - y) ** 2 for x, y in zip(va, vb)) ** 0.5
            base = self.spectral_weight * (1.0 - 2.0 * min(1.0, dist / 0.6))
            # Bass-collision penalty: two bass-dominant phrases overlapping is
            # muddy unless the transition is a bass swap (handled elsewhere).
            bass_a = float(sa.get("sub_ratio", 0.0)) + float(sa.get("bass_ratio", 0.0))
            bass_b = float(sb.get("sub_ratio", 0.0)) + float(sb.get("bass_ratio", 0.0))
            if bass_a > 0.35 and bass_b > 0.35:
                base -= self.spectral_weight * 0.5
            return base
        # Legacy flat-spec fallback.
        dims = ("brightness", "low_ratio", "mid_ratio", "high_ratio")
        va = [float(a.get(k, 0.0)) for k in dims]
        vb = [float(b.get(k, 0.0)) for k in dims]
        dist = sum((x - y) ** 2 for x, y in zip(va, vb)) ** 0.5
        return self.spectral_weight * (1.0 - 2.0 * min(1.0, dist / 0.6))

    def _vocal_family_bonus(self, from_id: Optional[str], seg: Segment) -> float:
        """Vocal phrases belong together (§vocal-priority). Reward vocal ->
        vocal continuity; reward instrumental -> instrumental. Penalize a hard
        *clash*: two strong vocals stacked (which is only valid as a clean cut,
        not a blend — for a studio cut relay we still slightly prefer not to
        slam two dominant vocals unless the trajectory is a reset)."""
        a = self._get_feats(from_id)
        b = self._get_feats(seg.id)
        if not a or not b:
            return 0.0
        ra, rb = a.get("roles", []), b.get("roles", [])
        va, vb = _is_vocal(ra, a), _is_vocal(rb, b)
        if va and vb:
            ca = max(_role_conf(ra, r) for r in _VOCAL_ROLES)
            cb = max(_role_conf(rb, r) for r in _VOCAL_ROLES)
            # Two DOMINANT vocals clash; dominant->light flows.
            if ca > 0.7 and cb > 0.7:
                return -1.2  # vocal-overlap penalty
            return 1.0      # vocal-family continuity
        if not va and not vb:
            return 0.5      # instrumental continuity
        return -0.3         # vocal <-> instrumental: mild mismatch

    def _vocal_bias_bonus(self, seg: Segment) -> float:
        """A strong, unconditional preference for VOCAL-first phrases. The
        whole mix should read as a vocal hook relay, so every vocal phrase is
        pushed hard ahead of an instrumental phrase. Range ~[0, +W]."""
        f = self._get_feats(seg.id)
        if f is None:
            return 0.0
        if _is_vocal(f.get("roles", []), f):
            return self.vocal_bias_weight
        return 0.0

    def _trajectory_bonus(self, from_id: Optional[str], seg: Segment) -> float:
        """Energy-trajectory logic (§8): prefer DROP_HOOK -> equal/stronger
        DROP_HOOK, rising after a plateau, and a controlled reset after a peak.
        Discourage an uncontrolled cliff (peak -> collapse) unless it's a reset."""
        a = self._get_feats(from_id)
        b = self._get_feats(seg.id)
        if not a or not b:
            return 0.0
        pe_a = float(a.get("perceived_energy", 0.0))
        pe_b = float(b.get("perceived_energy", 0.0))
        shape_b = _energy_shape(b.get("slopes", {}), pe_b)
        bonus = 0.0
        # Climbing into a drop is good.
        if shape_b == "rising":
            bonus += 0.6
        # Energy hand-off: equal or slightly stronger is ideal.
        d = pe_b - pe_a
        if -0.1 <= d <= 0.25:
            bonus += 0.8
        elif d < -0.45:
            bonus -= 1.0   # uncontrolled energy cliff
        elif d > 0.5:
            bonus -= 0.3   # sudden over-jump is jarring
        return bonus

    # ------------------------------------------------------------ scoring #
    def _score(self, from_id: Optional[str], seg: Segment) -> float:
        # Hook/recognition density: rating is our hook proxy; shorter segments
        # score higher because they reach the payoff faster.
        score = seg.rating / 10.0
        # Section length is the dominant V1 DeepDance constraint: a drop/hook
        # section should hold for its full phrase (e.g. 64 bars). Penalize any
        # segment that is not the target length hard enough to override the
        # fresh-crate and reset biases below (which are <= ~2.0 combined).
        bar_pen = abs(seg.bars - self.target_bars) / max(1, self.target_bars)
        score -= 4.0 * bar_pen
        # Energy gate.
        if self.energy_min <= seg.energy_start <= self.energy_max:
            score += 0.2
        # Reset-transition bias on the arriving edge.
        if from_id is not None:
            edge = self.graph.edge_between(from_id, seg.id)
            if edge is not None:
                if edge.technique in RESET_TECHNIQUES:
                    score += self.reset_bias
                elif edge.technique in CONTINUITY_TECHNIQUES:
                    score -= 0.2  # blends are rare in a megamix
        # Unique-track lock: a track may NOT repeat until every track in the
        # crate has played once. Different PHRASES of the same track are fine
        # (they share track_id but are distinct segments), but the SAME track
        # can't come back until the crate is spent. Hard-block beats the
        # harmonic-arc bonus (<= +4.0) so Camelot Boost optimizes ACROSS
        # distinct tracks instead of bouncing between two adjacent-key ones.
        played = [self.graph.segments[h].track_id for h in self.history
                  if h in self.graph.segments]
        crate_ids = {s.track_id for s in self.graph.segments.values()}
        crate_spent = crate_ids.issubset(set(played))
        plays = played.count(seg.track_id)
        if plays == 0:
            score += 1.0
        elif not crate_spent:
            score -= 100.0  # hard block: pick an unplayed track instead
        else:
            score -= 2.5 * plays  # crate spent -> mild revisit penalty
        # Novelty pressure: the more consecutive steps on the current track,
        # the stronger the push to cut away.
        recent = [self.graph.segments[h].track_id for h in self.history[-2:]
                  if h in self.graph.segments]
        score -= 3.0 * recent.count(seg.track_id)
        # CONTINUITY FIRST (deep dance, not radio chart hits): match the
        # outgoing phrase's energy LEVEL and SPECTRAL signature so a climax
        # flows into a climax, a breakdown into a breakdown. These dominate.
        score += self._energy_continuity_bonus(from_id, seg)
        score += self._spectral_similarity_bonus(from_id, seg)
        # Phrase-native sequencing: vocal-family priority, energy-trajectory
        # shape, and vocal-clash / bass-collision penalties. These are the
        # semantic-mix terms and they DRIVE the ordering (weights set in
        # __init__ so they outweigh raw continuity); Camelot is a tiebreak.
        score += self.vocal_family_weight * self._vocal_family_bonus(from_id, seg)
        score += self.trajectory_weight * self._trajectory_bonus(from_id, seg)
        # VOCAL-FIRST: unconditional pull toward vocal phrases so the mix reads
        # as a vocal hook relay. This is the primary phrase-selection driver.
        score += self._vocal_bias_bonus(seg)
        # ASCENDING_ENERGY_ARC: Camelot lift + climbing phrase energy are now
        # a TIEBREAK / gentle shape, not the driver (arc_weight lowered 4->1).
        score += self._harmonic_arc_bonus(from_id, seg)
        score += self._energy_gradient_bonus(seg)
        return score

    # ------------------------------------------------------------ choices #
    def choose_entry(self) -> Segment:
        entries = [self.graph.segments[i] for i in self.graph.entry_segments
                   if i in self.graph.segments]
        if not entries:
            entries = list(self.graph.segments.values())
        if not entries:
            raise ValueError("mix graph has no segments")
        # Entry: pick the strongest, shortest hook.
        if self.mode == "deterministic":
            return max(entries, key=lambda s: self._score(None, s))
        weights = [max(1e-3, self._score(None, s)) for s in entries]
        return self.rng.weighted_choice(entries, weights)

    def choose_next(self, current_id: str) -> Optional[Segment]:
        options = self.graph.outgoing(current_id)
        if not options:
            return None
        candidates = [self.graph.segments[o] for o in options
                      if o in self.graph.segments]
        if not candidates:
            return None
        # V1 DeepDance section-length lock: every played section should hold
        # for the full target phrase (e.g. 64 bars). Restrict to target-length
        # segments first. If no target-length segment is reachable from the
        # current position, fall back to ANY unplayed target-length segment in
        # the graph (a megamix "studio cut" — a jump cut, not a deck blend).
        target = [c for c in candidates if c.bars == self.target_bars]
        if not target:
            played_ids = {self.graph.segments[h].track_id for h in self.history
                          if h in self.graph.segments}
            jump = [s for s in self.graph.segments.values()
                    if s.bars == self.target_bars
                    and s.id != current_id
                    and s.track_id not in played_ids]
            if not jump:  # crate of target-length segments spent -> allow revisit
                jump = [s for s in self.graph.segments.values()
                        if s.bars == self.target_bars and s.id != current_id]
            if jump:
                candidates = jump
                target = jump
        if target:
            candidates = target
        # Prefer never-played tracks; only revisit once the crate is spent.
        # This is the pool-level mirror of the unique-track lock in _score.
        played = {self.graph.segments[h].track_id for h in self.history
                  if h in self.graph.segments}
        crate_ids = {s.track_id for s in self.graph.segments.values()}
        crate_spent = crate_ids.issubset(played)
        fresh = [c for c in candidates if c.track_id not in played]
        if fresh and not crate_spent:
            pool = fresh
        else:
            pool = candidates
        # Reset-transition grammar: if any reachable candidate is arrived at via
        # a RESET edge, restrict the pool to those (megamixes cut, not blend).
        # Continuity edges are only used when no reset exit exists.
        if self.reset_bias > 0:
            reset_pool = [c for c in pool
                          if (self.graph.edge_between(current_id, c.id) is not None
                              and self.graph.edge_between(current_id, c.id).technique
                              in RESET_TECHNIQUES)]
            if reset_pool:
                pool = reset_pool
        # UNIQUE-TRACK LOCK (pool-level enforcement): the reset filter above can
        # re-admit an already-played track (e.g. the current one) when it's the
        # only reset exit. Re-apply the fresh-crate preference AFTER reset so a
        # track never repeats before the whole crate has played once.
        if not crate_spent:
            fresh_pool = [c for c in pool if c.track_id not in played]
            if fresh_pool:
                pool = fresh_pool
        # VOCAL-CHAIN: when the outgoing phrase is vocal, keep pulling vocal
        # phrases so consecutive vocal hooks connect. Only applied as a soft
        # pool restriction (falls back to the general pool when no vocal
        # candidate remains, e.g. a fresh-crate constraint).
        cur_feats = self._get_feats(current_id)
        if cur_feats is not None and _is_vocal(cur_feats.get("roles", []), cur_feats):
            vocal_pool = [c for c in pool if _is_vocal(
                self._get_feats(c.id).get("roles", []), self._get_feats(c.id))
                if self._get_feats(c.id) is not None]
            if vocal_pool:
                pool = vocal_pool
        if self.mode == "deterministic":
            pick = max(pool, key=lambda s: self._score(current_id, s))
        else:
            weights = [max(1e-3, self._score(current_id, s)) for s in pool]
            pick = self.rng.weighted_choice(pool, weights)
        return pick

    def advance(self, current_id: Optional[str]) -> Optional[Segment]:
        nxt = self.choose_entry() if current_id is None else self.choose_next(current_id)
        if nxt is not None:
            self.history.append(nxt.id)
        return nxt
