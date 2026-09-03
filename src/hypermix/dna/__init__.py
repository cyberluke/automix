"""Producer DNA — a deterministic 'recipe / cookbook' for how to treat a phrase.

The idea (user, 2026-08-12): the user teaches his PRODUCER DNA — how to boost a
track (e.g. the malugi track) over a 64/128-bar phrase. That knowledge is
recorded as a deterministic, BAR/BEAT-indexed recipe (a 'state machine') that
can then be applied MODULARLY to ANY phrase.

A recipe is a list of steps; each step fires at a bar/beat position (or a bar
range) and calls an operator (bass-solo, cyber-bass, juggle preset, filter move,
drum fill, mute/duck, ...). Because everything is indexed to bars/beats, the same
recipe applies to any phrase of a given length regardless of the source tempo —
the engine resolves bar/beat → seconds via the phrase BPM.
"""

from .recipe import (ProducerRecipe, RecipeStep, OperatorCall,
                     list_recipes, save_recipe, load_recipe)
from .engine import apply_recipe
from .designer import design_phrase_dna, analyze_canvas, choose_edits, build_recipe
from .effect_vocabulary import EFFECT_VOCABULARY, EFFECT_BY_ID

__all__ = ["ProducerRecipe", "RecipeStep", "OperatorCall",
           "list_recipes", "save_recipe", "load_recipe",
           "apply_recipe", "design_phrase_dna", "analyze_canvas",
           "choose_edits", "build_recipe", "EFFECT_VOCABULARY", "EFFECT_BY_ID"]
