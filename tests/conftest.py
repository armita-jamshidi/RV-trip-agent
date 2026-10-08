"""Shared test helpers."""

import math
import re

# A stand-in for the real embedding model: one dimension per concept, synonyms share it.
# Enough to check the index and filters; the real model's quality is checked live (see PR).
CONCEPTS = [
    {"lake", "lakeside", "reservoir", "lakefront"},
    {"mountain", "mountains", "peaks", "alpine"},
    {"desert", "canyon", "red", "rock", "arches"},
    {"quiet", "peaceful", "secluded", "remote"},
    {"river", "creek", "riverside"},
    {"forest", "pines", "trees", "shade", "shady"},
    {"city", "downtown", "museums", "museum"},
    {"family", "kids", "playground", "pool"},
    {"ocean", "oceanfront", "beach", "coast"},
]


class ConceptEmbedder:
    def embed(self, texts):
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text):
        words = set(re.findall(r"[a-z]+", text.lower()))
        v = [float(len(words & c)) for c in CONCEPTS] + [0.01]
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v]
